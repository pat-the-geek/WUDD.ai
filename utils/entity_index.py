"""utils/entity_index.py — Index inversé entités → articles.

Maintient data/entity_index.json : pour chaque entité connue, la liste des
références (fichier source + indice dans la liste) des articles qui la mentionnent.

Format de l'index :
    {
        "version": 1,
        "generated_at": "2026-03-14T10:00:00Z",
        "index": {
            "PERSON:Emmanuel Macron": [
                {"file": "data/articles-from-rss/_WUDD.AI_/48-heures.json",
                 "idx": 12, "date": "2026-03-13"}
            ],
            "ORG:OpenAI": [ ... ]
        }
    }

Utilisation typique :
    from utils.entity_index import EntityIndex
    eidx = EntityIndex(project_root)
    eidx.update(new_articles, source_file="data/articles-from-rss/_WUDD.AI_/48-heures.json")

    refs = eidx.get_refs("PERSON", "Emmanuel Macron")  # liste de {file, idx, date}
    articles = eidx.load_articles("PERSON", "Emmanuel Macron", project_root)
"""

import json
import threading
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .logging import default_logger

_INDEX_VERSION = 2
_INDEX_FILENAME = "entity_index.json"

# Types d'entités indexés (filtrage des types peu utiles pour la recherche)
_INDEXED_ENTITY_TYPES = {
    "PERSON", "ORG", "GPE", "LOC", "PRODUCT", "EVENT", "NORP", "FAC",
}


def _cap_score(s: str) -> int:
    """Score de capitalisation : préfère les formes avec des majuscules initiales.

    Retourne -1 pour les formes entièrement en majuscules (ALL_CAPS),
    sinon le nombre de caractères alphabétiques en majuscule.

    Exemples :
        "emmanuel macron" → 0
        "Emmanuel Macron" → 2   ← préféré
        "EMMANUEL MACRON" → -1  (pénalisé)
        "OpenAI"          → 2   ← préféré
    """
    if not s:
        return 0
    alpha_chars = [c for c in s if c.isalpha()]
    if not alpha_chars:
        return 0
    upper_count = sum(1 for c in alpha_chars if c.isupper())
    if upper_count == len(alpha_chars):
        return -1  # Tout en majuscules → pénalisé
    return upper_count


def _normalize_entity_key(etype: str, name: str) -> str:
    """Retourne la clé d'index normalisée (valeur en minuscules)."""
    return f"{etype}:{name.strip().lower()}"


def _update_caps(caps: dict, key: str, name: str) -> None:
    """Met à jour le dict caps avec la forme de capitalisation préférée.

    Conserve la forme ayant le meilleur _cap_score, ou la forme existante
    en cas d'égalité (stable).
    """
    name = name.strip()
    if not name:
        return
    existing = caps.get(key)
    if existing is None or _cap_score(name) > _cap_score(existing):
        caps[key] = name


class EntityIndex:
    """Index inversé entités → articles pour accès rapide sans scan de data/.

    Thread-safe via threading.Lock.
    """

    def __init__(self, project_root: Optional[Path] = None):
        if project_root is None:
            project_root = Path(__file__).parent.parent
        self.project_root = project_root
        self._index_path = project_root / "data" / _INDEX_FILENAME
        self._lock = threading.Lock()
        self._data: dict = {"version": _INDEX_VERSION, "index": {}, "caps": {}}
        self._loaded = False

    # ── Chargement / sauvegarde ─────────────────────────────────────────────

    def _load(self) -> None:
        if self._loaded:
            return
        if self._index_path.exists():
            try:
                raw = json.loads(self._index_path.read_text(encoding="utf-8"))
                if isinstance(raw, dict) and raw.get("version") == _INDEX_VERSION:
                    # S'assurer que le champ caps existe (migration partielle)
                    if "caps" not in raw:
                        raw["caps"] = {}
                    self._data = raw
                elif isinstance(raw, dict) and raw.get("version") in (1, None):
                    # Migration automatique v1 → v2 : normaliser les clés en minuscules
                    # et construire le dict caps pour conserver la forme canonique.
                    version_found = raw.get("version")
                    if version_found == 1:
                        default_logger.warning(
                            "entity_index.json : version v1 détectée, migration automatique v1→v2."
                        )
                    else:
                        default_logger.warning(
                            "entity_index.json : version absente (format hérité), migration automatique vers v2."
                        )
                    old_index = raw.get("index", {})
                    new_index: dict[str, list[dict]] = {}
                    new_caps: dict[str, str] = {}
                    for key, refs in old_index.items():
                        if ":" not in key or not isinstance(refs, list):
                            continue
                        etype, _, name = key.partition(":")
                        if not name:
                            continue
                        norm_key = _normalize_entity_key(etype, name)
                        _update_caps(new_caps, norm_key, name)
                        # Dédupliquer les références (file, idx)
                        seen_sigs: set = set()
                        for ref in refs:
                            sig = (ref.get("file", ""), ref.get("idx", -1))
                            if sig not in seen_sigs:
                                seen_sigs.add(sig)
                                new_index.setdefault(norm_key, []).append(ref)
                    self._data = {
                        "version": _INDEX_VERSION,
                        "index": new_index,
                        "caps": new_caps,
                    }
                    # Persister la version migrée pour éviter de remigrer à chaque démarrage
                    try:
                        self._save()
                    except OSError as e:
                        default_logger.warning(
                            f"entity_index.json : impossible de persister la migration v2 : {e}"
                        )
                else:
                    default_logger.warning(
                        "entity_index.json : version incompatible, "
                        "reconstruction nécessaire. Lancez normalize_entity_index.py."
                    )
            except (json.JSONDecodeError, OSError) as e:
                default_logger.warning(f"Impossible de charger entity_index.json : {e}")
        self._loaded = True

    def _save(self) -> None:
        self._data["generated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        tmp = self._index_path.with_suffix(".tmp")
        try:
            tmp.write_text(
                json.dumps(self._data, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
            tmp.replace(self._index_path)
        except OSError as e:
            default_logger.error(f"Impossible de sauvegarder entity_index.json : {e}")

    # ── Mise à jour incrémentale ─────────────────────────────────────────────

    def update(self, articles: list[dict], source_file: str) -> int:
        """Met à jour l'index pour les articles donnés.

        Ajoute les nouvelles références entité → article.
        Les références existantes pour ce fichier source sont remplacées en bloc
        (pour gérer la mise à jour d'un fichier comme 48-heures.json).

        Args:
            articles    : liste d'articles au format interne WUDD.ai
            source_file : chemin relatif à project_root

        Returns:
            Nombre de références entité-article ajoutées.
        """
        if not articles:
            return 0

        # Normaliser le chemin source
        try:
            src_path = Path(source_file)
            if src_path.is_absolute():
                source_file = str(src_path.relative_to(self.project_root)).replace("\\", "/")
        except ValueError:
            pass

        with self._lock:
            self._load()
            index = self._data.setdefault("index", {})
            caps = self._data.setdefault("caps", {})

            # Retirer toutes les références existantes pour ce fichier source
            # (nécessaire pour 48-heures.json qui est réécrit intégralement)
            for key in list(index.keys()):
                index[key] = [r for r in index[key] if r.get("file") != source_file]
                if not index[key]:
                    del index[key]

            # Ajouter les nouvelles références
            added = 0
            for file_idx, article in enumerate(articles):
                entities = article.get("entities", {})
                if not isinstance(entities, dict):
                    continue
                date_raw = article.get("Date de publication", "")
                date_short = date_raw[:10] if date_raw else ""
                # Normaliser le format de date court (DD/MM/YYYY → YYYY-MM-DD)
                if date_short and "/" in date_short:
                    parts = date_short.split("/")
                    if len(parts) == 3:
                        date_short = f"{parts[2]}-{parts[1]}-{parts[0]}"

                for etype, names in entities.items():
                    if etype not in _INDEXED_ENTITY_TYPES:
                        continue
                    if not isinstance(names, list):
                        continue
                    for name in names:
                        if not isinstance(name, str) or not name.strip():
                            continue
                        key = _normalize_entity_key(etype, name)
                        _update_caps(caps, key, name)
                        ref = {"file": source_file, "idx": file_idx, "date": date_short}
                        index.setdefault(key, []).append(ref)
                        added += 1

            self._save()
            return added

    def rebuild(self) -> int:
        """Reconstruit l'index complet en scannant tout data/.

        À utiliser lors de la migration initiale ou après corruption.
        """
        scan_dirs = [
            self.project_root / "data" / "articles",
            self.project_root / "data" / "articles-from-rss",
        ]
        new_index: dict[str, list[dict]] = {}
        new_caps: dict[str, str] = {}
        total_refs = 0

        for scan_dir in scan_dirs:
            if not scan_dir.exists():
                continue
            for json_file in sorted(scan_dir.rglob("*.json")):
                if "cache" in json_file.relative_to(scan_dir).parts:
                    continue
                try:
                    data = json.loads(json_file.read_text(encoding="utf-8", errors="replace"))
                    if not isinstance(data, list):
                        continue
                    rel = str(json_file.relative_to(self.project_root)).replace("\\", "/")
                    for file_idx, article in enumerate(data):
                        entities = article.get("entities", {})
                        if not isinstance(entities, dict):
                            continue
                        date_raw = article.get("Date de publication", "")
                        date_short = date_raw[:10] if date_raw else ""
                        if date_short and "/" in date_short:
                            parts = date_short.split("/")
                            if len(parts) == 3:
                                date_short = f"{parts[2]}-{parts[1]}-{parts[0]}"
                        for etype, names in entities.items():
                            if etype not in _INDEXED_ENTITY_TYPES:
                                continue
                            if not isinstance(names, list):
                                continue
                            for name in names:
                                if not isinstance(name, str) or not name.strip():
                                    continue
                                key = _normalize_entity_key(etype, name)
                                _update_caps(new_caps, key, name)
                                ref = {"file": rel, "idx": file_idx, "date": date_short}
                                new_index.setdefault(key, []).append(ref)
                                total_refs += 1
                except (json.JSONDecodeError, OSError):
                    continue

        with self._lock:
            self._data = {"version": _INDEX_VERSION, "index": new_index, "caps": new_caps}
            self._save()
            self._loaded = True
            return total_refs

    # ── Requêtes ────────────────────────────────────────────────────────────

    def get_refs(self, entity_type: str, entity_value: str) -> list[dict]:
        """Retourne les références (file, idx, date) des articles mentionnant l'entité.

        Args:
            entity_type  : ex. "PERSON", "ORG", "GPE"
            entity_value : ex. "Emmanuel Macron" (insensible à la casse)

        Returns:
            Liste de dict {file, idx, date}, triée par date décroissante.
        """
        with self._lock:
            self._load()
        key = _normalize_entity_key(entity_type, entity_value)
        refs = self._data.get("index", {}).get(key, [])
        return sorted(refs, key=lambda r: r.get("date", ""), reverse=True)

    def get_display_name(self, entity_type: str, entity_value: str) -> str:
        """Retourne la forme canonique d'affichage de l'entité (caps).

        Fallback : retourne entity_value tel quel si aucune forme capitalisée connue.
        """
        with self._lock:
            self._load()
        key = _normalize_entity_key(entity_type, entity_value)
        return self._data.get("caps", {}).get(key, entity_value.strip())

    def load_articles(
        self,
        entity_type: str,
        entity_value: str,
        max_articles: int = 0,
        cutoff_date: str = "",
    ) -> list[dict]:
        """Charge et retourne les articles complets mentionnant l'entité.

        Groupe les lectures par fichier pour minimiser les I/O.

        Args:
            entity_type  : type NER
            entity_value : valeur de l'entité
            max_articles : limite optionnelle (0 = pas de limite)
            cutoff_date  : date ISO minimum "YYYY-MM-DD" — filtre les refs avant
                           de lire les fichiers JSON (évite les I/O inutiles)

        Returns:
            Articles complets triés par date décroissante.
        """
        refs = self.get_refs(entity_type, entity_value)
        if cutoff_date:
            # refs triées par date décroissante : dès qu'une ref est < cutoff, on coupe
            refs = [r for r in refs if r.get("date", "") >= cutoff_date]
        if max_articles > 0:
            refs = refs[:max_articles]
        if not refs:
            return []

        # Grouper par fichier
        by_file: dict[str, list[tuple[int, int]]] = {}
        for pos, ref in enumerate(refs):
            f = ref.get("file", "")
            if f:
                by_file.setdefault(f, []).append((pos, ref.get("idx", -1)))

        result: list[Optional[dict]] = [None] * len(refs)
        seen_urls: set[str] = set()

        for rel_path, positions in by_file.items():
            full_path = self.project_root / rel_path
            try:
                data = json.loads(full_path.read_text(encoding="utf-8", errors="replace"))
                if not isinstance(data, list):
                    continue
                for pos, file_idx in positions:
                    if 0 <= file_idx < len(data):
                        article = data[file_idx]
                        url = (article.get("URL") or "").strip()
                        if url and url in seen_urls:
                            continue
                        if url:
                            seen_urls.add(url)
                        article.setdefault("_source_file", rel_path)
                        result[pos] = article
            except (json.JSONDecodeError, OSError):
                continue

        return [a for a in result if a is not None]

    def get_top_entities(self, top_n: int = 50) -> list[dict]:
        """Retourne les entités les plus référencées dans l'index.

        Returns:
            Liste de dict {type, value, count} triée par count décroissant.
            Le champ "value" contient la forme d'affichage capitalisée (caps).
        """
        with self._lock:
            self._load()
        caps = self._data.get("caps", {})
        counter = Counter({k: len(v) for k, v in self._data.get("index", {}).items()})
        results = []
        for key, count in counter.most_common(top_n):
            if ":" in key:
                etype, _, evalue_lower = key.partition(":")
                display = caps.get(key, evalue_lower)
                results.append({"type": etype, "value": display, "count": count})
        return results

    def get_cooccurrences(
        self,
        entity_type: str,
        entity_value: str,
        top_n: int = 20,
    ) -> list[dict]:
        """Calcule les co-occurrences de l'entité à partir de l'index.

        Plus efficace que le scan complet O(F×A×E²) : utilise uniquement les
        articles référencés dans l'index pour l'entité cible.

        Returns:
            Liste de dict {type, value, count} triée par count décroissant.
        """
        articles = self.load_articles(entity_type, entity_value)
        cooc: Counter = Counter()
        for article in articles:
            ents = article.get("entities", {})
            if not isinstance(ents, dict):
                continue
            for etype, evals in ents.items():
                if not isinstance(evals, list):
                    continue
                for ev in evals:
                    # Exclure l'entité cible (comparaison insensible à la casse)
                    if not (etype == entity_type and ev.strip().lower() == entity_value.strip().lower()):
                        cooc[(etype, ev)] += 1
        caps = self._data.get("caps", {})
        return [
            {
                "type": etype,
                "value": caps.get(_normalize_entity_key(etype, ev), ev),
                "count": cnt,
            }
            for (etype, ev), cnt in cooc.most_common(top_n)
        ]

    def get_all_entries(self) -> dict[str, list[dict]]:
        """Retourne une copie de l'index complet {entity_key: [{file, idx, date}]}.

        Les clés utilisent la forme d'affichage canonique (caps) pour la valeur,
        afin que les appelants obtiennent "ORG:OpenAI" et non "ORG:openai".

        Utilisé par entity_timeline.py, cross_flux_analysis.py et le viewer
        pour construire leurs agrégats sans scan rglob.
        """
        with self._lock:
            self._load()
        caps = self._data.get("caps", {})
        result = {}
        for k, v in self._data.get("index", {}).items():
            if ":" in k:
                etype, _, name_lower = k.partition(":")
                display = caps.get(k, name_lower)
                display_key = f"{etype}:{display}"
            else:
                display_key = k
            result[display_key] = list(v)
        return result

    def count_entities(self) -> int:
        """Retourne le nombre d'entités distinctes indexées."""
        with self._lock:
            self._load()
        return len(self._data.get("index", {}))

    def stats(self) -> dict:
        """Retourne des statistiques sur l'index."""
        with self._lock:
            self._load()
        index = self._data.get("index", {})
        total_refs = sum(len(v) for v in index.values())
        by_type: Counter = Counter()
        for key in index:
            if ":" in key:
                etype = key.split(":")[0]
                by_type[etype] += 1
        return {
            "entities": len(index),
            "references": total_refs,
            "by_type": dict(by_type),
            "generated_at": self._data.get("generated_at", ""),
        }


# ── Singleton ────────────────────────────────────────────────────────────────

_instances: dict[Path, EntityIndex] = {}
_instances_lock = threading.Lock()


def get_entity_index(project_root: Optional[Path] = None) -> EntityIndex:
    """Retourne l'instance singleton de l'EntityIndex pour project_root."""
    if project_root is None:
        project_root = Path(__file__).parent.parent
    project_root = project_root.resolve()
    with _instances_lock:
        if project_root not in _instances:
            _instances[project_root] = EntityIndex(project_root)
        return _instances[project_root]
