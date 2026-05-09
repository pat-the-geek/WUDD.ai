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
import re
import threading
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .logging import default_logger

# v3 : force une reconstruction quand l'index existant a été généré avant
# l'indexation de WORK_OF_ART et des types structurels.
_INDEX_VERSION = 3
_INDEX_FILENAME = "entity_index.json"

# Types structurels : utiles pour l'analyse ponctuelle, mais masqués par défaut
# dans les vues de découverte pour éviter de noyer le signal principal.
STRUCTURAL_ENTITY_TYPES: frozenset[str] = frozenset(
    {"DATE", "TIME", "CARDINAL", "ORDINAL", "PERCENT", "MONEY", "QUANTITY"}
)

# Types d'entités indexés.
# WORK_OF_ART est indexé par défaut ; les types structurels sont indexés pour
# permettre une exposition opt-in côté API (`include_structural=1`).
_INDEXED_ENTITY_TYPES = {
    "PERSON", "ORG", "GPE", "LOC", "PRODUCT", "EVENT", "NORP", "FAC", "LAW",
    "WORK_OF_ART",
} | STRUCTURAL_ENTITY_TYPES


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


def _display_rank(name: str, *, ref_count: int, explicit: bool) -> tuple[int, int, int, int]:
    """Classe les variantes d'affichage candidates d'un bucket canonique."""
    cleaned = name.strip()
    return (
        1 if explicit else 0,
        int(ref_count),
        _cap_score(cleaned),
        -len(cleaned),
    )


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
        self._search_entries: list[dict] | None = None
        self._canonical_entries: dict[bool, dict[str, list[dict]]] = {}
        self._canonical_lookup: dict[bool, dict[str, str]] = {}
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
                    self._search_entries = None
                    self._canonical_entries = {}
                    self._canonical_lookup = {}
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
                    self._search_entries = None
                    self._canonical_entries = {}
                    self._canonical_lookup = {}
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

            self._search_entries = None
            self._canonical_entries = {}
            self._canonical_lookup = {}
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
            self._search_entries = None
            self._canonical_entries = {}
            self._canonical_lookup = {}
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

    def get_canonical_refs(self, entity_type: str, entity_value: str) -> list[dict]:
        """Retourne les refs de toutes les variantes aliasées d'une entité."""
        include_structural = entity_type in STRUCTURAL_ENTITY_TYPES
        entries = self.get_all_entries(
            canonicalize=True,
            include_structural=include_structural,
        )
        with self._lock:
            lookup = dict(self._canonical_lookup.get(include_structural, {}))
        display_key = lookup.get(self._canonical_key(entity_type, entity_value), "")
        refs = entries.get(display_key, [])
        return sorted(refs, key=lambda r: r.get("date", ""), reverse=True)

    def get_canonical_ref_count(self, entity_type: str, entity_value: str) -> int:
        """Retourne le nombre de refs canoniques pour une entité.

        Utilise d'abord le bucket canonique pré-agrégé, puis retombe sur un
        balayage direct de l'index brut si le lookup d'affichage n'est pas
        encore disponible pour cette variante.
        """
        include_structural = entity_type in STRUCTURAL_ENTITY_TYPES
        entries = self.get_all_entries(
            canonicalize=True,
            include_structural=include_structural,
        )
        bucket_key = self._canonical_key(entity_type, entity_value)
        with self._lock:
            lookup = dict(self._canonical_lookup.get(include_structural, {}))
            raw_index = dict(self._data.get("index", {}))
            caps = dict(self._data.get("caps", {}))
        display_key = lookup.get(bucket_key, "")
        if display_key:
            refs = entries.get(display_key, [])
            if refs:
                return len(refs)

        seen: set[tuple[str, int]] = set()
        for key, refs in raw_index.items():
            if ":" not in key or not isinstance(refs, list):
                continue
            etype, _, name_lower = key.partition(":")
            display = caps.get(key, name_lower)
            if not display:
                continue
            canonical_type, _ = self._canonicalize_entity(etype, display)
            if not include_structural and canonical_type in STRUCTURAL_ENTITY_TYPES:
                continue
            if self._canonical_key(etype, display) != bucket_key:
                continue
            for ref in refs:
                seen.add((ref.get("file", ""), ref.get("idx", -1)))
        return len(seen)

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
        canonicalize: bool = False,
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
        refs = (
            self.get_canonical_refs(entity_type, entity_value)
            if canonicalize
            else self.get_refs(entity_type, entity_value)
        )
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
        counter = Counter(
            {
                k: len(v)
                for k, v in self.get_all_entries(
                    canonicalize=True,
                    include_structural=False,
                ).items()
            }
        )
        results = []
        for key, count in counter.most_common(top_n):
            if ":" in key:
                etype, _, evalue = key.partition(":")
                results.append({"type": etype, "value": evalue, "count": count})
        return results

    def get_cooccurrences(
        self,
        entity_type: str,
        entity_value: str,
        top_n: int = 20,
        canonicalize: bool = True,
    ) -> list[dict]:
        """Calcule les co-occurrences de l'entité à partir de l'index.

        Plus efficace que le scan complet O(F×A×E²) : utilise uniquement les
        articles référencés dans l'index pour l'entité cible.

        Returns:
            Liste de dict {type, value, count} triée par count décroissant.
        """
        target_key = self._canonical_key(entity_type, entity_value)
        articles = self.load_articles(entity_type, entity_value, canonicalize=canonicalize)
        cooc: dict[str, dict[str, object]] = {}
        for article in articles:
            ents = article.get("entities", {})
            if not isinstance(ents, dict):
                continue
            for etype, evals in ents.items():
                if not isinstance(evals, list):
                    continue
                for ev in evals:
                    if not isinstance(ev, str) or not ev.strip():
                        continue
                    if self._is_noise_entity(etype, ev):
                        continue
                    canonical_type, _ = self._canonicalize_entity(etype, ev)
                    bucket_key = self._canonical_key(etype, ev)
                    if bucket_key == target_key:
                        continue
                    candidate_value = self._canonical_display_value(etype, ev)
                    explicit = self._has_explicit_canonical(etype, ev)
                    rank = _display_rank(candidate_value, ref_count=1, explicit=explicit)
                    bucket = cooc.setdefault(
                        bucket_key,
                        {
                            "type": canonical_type,
                            "value": candidate_value,
                            "count": 0,
                            "rank": rank,
                        },
                    )
                    bucket["count"] = int(bucket["count"]) + 1
                    if rank > bucket["rank"]:
                        bucket["value"] = candidate_value
                        bucket["rank"] = rank
        return [
            {
                "type": str(item["type"]),
                "value": str(item["value"]),
                "count": int(item["count"]),
            }
            for item in sorted(
                cooc.values(),
                key=lambda item: (-int(item["count"]), str(item["type"]), str(item["value"])),
            )[:top_n]
        ]

    def get_all_entries(
        self,
        canonicalize: bool = False,
        *,
        include_structural: bool = False,
    ) -> dict[str, list[dict]]:
        """Retourne une copie de l'index complet {entity_key: [{file, idx, date}]}.

        Les clés utilisent la forme d'affichage canonique (caps) pour la valeur,
        afin que les appelants obtiennent "ORG:OpenAI" et non "ORG:openai".

        Args:
            canonicalize: Fusionne les alias via la canonicalisation si activé.
            include_structural: Inclut les types structurels (DATE, MONEY, ...)
                quand True. Les surfaces de découverte peuvent les masquer par
                défaut pour garder un signal lisible.

        Utilisé par entity_timeline.py, cross_flux_analysis.py et le viewer
        pour construire leurs agrégats sans scan rglob.
        """
        with self._lock:
            self._load()
            if canonicalize and include_structural in self._canonical_entries:
                return {
                    key: list(refs)
                    for key, refs in self._canonical_entries[include_structural].items()
                }
        caps = self._data.get("caps", {})
        result: dict[str, list[dict]] = {}
        lookup: dict[str, str] = {}
        bucket_meta: dict[str, dict[str, object]] = {}
        seen_by_key: dict[str, set[tuple[str, int]]] = {}
        for k, refs in self._data.get("index", {}).items():
            if ":" in k:
                etype, _, name_lower = k.partition(":")
                display = caps.get(k, name_lower)
                if canonicalize:
                    if self._is_noise_entity(etype, display):
                        continue
                    canonical_type, _ = self._canonicalize_entity(etype, display)
                    if not include_structural and canonical_type in STRUCTURAL_ENTITY_TYPES:
                        continue
                    bucket_key = self._canonical_key(etype, display)
                    candidate_display = self._canonical_display_value(etype, display)
                    explicit = self._has_explicit_canonical(etype, display)
                    rank = _display_rank(
                        candidate_display,
                        ref_count=len(refs),
                        explicit=explicit,
                    )
                    current = bucket_meta.get(bucket_key)
                    if current is None or rank > current["rank"]:
                        display_key = f"{canonical_type}:{candidate_display}"
                        bucket_meta[bucket_key] = {"display_key": display_key, "rank": rank}
                        lookup[bucket_key] = display_key
                    else:
                        display_key = str(current["display_key"])
                else:
                    if not include_structural and etype in STRUCTURAL_ENTITY_TYPES:
                        continue
                    display_key = f"{etype}:{display}"
            else:
                display_key = k
            bucket = result.setdefault(display_key, [])
            seen = seen_by_key.setdefault(display_key, set())
            for ref in refs:
                sig = (ref.get("file", ""), ref.get("idx", -1))
                if sig in seen:
                    continue
                seen.add(sig)
                bucket.append(ref)
        for refs in result.values():
            refs.sort(key=lambda r: r.get("date", ""), reverse=True)
        if canonicalize:
            with self._lock:
                self._canonical_entries[include_structural] = {
                    key: list(refs)
                    for key, refs in result.items()
                }
                self._canonical_lookup[include_structural] = dict(lookup)
        return result

    def search_values(
        self,
        query: str,
        entity_type: Optional[str] = None,
        *,
        limit_per_type: int = 100,
        include_structural: bool = False,
    ) -> list[dict]:
        """Recherche des entités par sous-chaîne sans copier tout l'index.

        Retourne le même format groupé que le dashboard Viewer:
        [
            {
                "type": "ORG",
                "unique_count": 12,
                "mention_count": 184,
                "top": [{"value": "OpenAI", "count": 120}, ...]
            }
        ]
        """
        canonicalizer = self._get_canonicalizer()
        query_terms = canonicalizer.expand_search_terms(query)
        if not query_terms:
            return []
        query_norm = canonicalizer.normalize_for_matching(query)
        if len(query_norm) < 2:
            return []
        match_terms = [
            {
                "norm": canonicalizer.normalize_for_matching(term),
                "short": canonicalizer.is_short_query(term),
            }
            for term in query_terms
            if canonicalizer.normalize_for_matching(term)
        ]
        if not match_terms:
            return []

        normalized_type = (entity_type or "").strip().upper()
        include_structural = include_structural or normalized_type in STRUCTURAL_ENTITY_TYPES
        capped_limit = max(1, min(int(limit_per_type), 500))

        with self._lock:
            self._load()
            index = self._data.get("index", {})
            caps = self._data.get("caps", {})
            search_entries = self._search_entries
            if search_entries is None:
                search_entries = []
                for key, refs in index.items():
                    if ":" not in key or not isinstance(refs, list):
                        continue
                    etype, _, value_lower = key.partition(":")
                    display_value = caps.get(key, value_lower)
                    if not display_value or self._is_noise_entity(etype, display_value):
                        continue
                    canonical_type, canonical_value = self._canonicalize_entity(etype, display_value)
                    explicit = self._has_explicit_canonical(etype, display_value)
                    search_entries.append(
                        {
                            "etype": etype,
                            "canonical_type": canonical_type,
                            "canonical_value": canonical_value,
                            "canonical_key": self._canonical_key(etype, display_value),
                            "display_value": self._canonical_display_value(etype, display_value),
                            "explicit": explicit,
                            "norm_value": canonicalizer.normalize_for_matching(canonical_value),
                            "ref_count": len(refs),
                        }
                    )
                self._search_entries = search_entries

            by_type: dict[str, dict[str, dict[str, object]]] = {}
            for entry_data in search_entries:
                etype = str(entry_data["etype"])
                canonical_type = str(entry_data["canonical_type"])
                canonical_key = str(entry_data["canonical_key"])
                candidate_value = str(entry_data["display_value"])
                explicit = bool(entry_data["explicit"])
                if normalized_type and etype != normalized_type and canonical_type != normalized_type:
                    continue
                if not include_structural and canonical_type in STRUCTURAL_ENTITY_TYPES:
                    continue
                score = self._search_match_score_from_norm(str(entry_data["norm_value"]), match_terms)
                if score <= 0:
                    continue
                if canonical_type not in by_type:
                    by_type[canonical_type] = {}
                rank = _display_rank(
                    candidate_value,
                    ref_count=int(entry_data["ref_count"]),
                    explicit=explicit,
                )
                entry = by_type[canonical_type].setdefault(
                    canonical_key,
                    {"count": 0, "score": score, "value": candidate_value, "rank": rank},
                )
                entry["count"] = int(entry["count"]) + int(entry_data["ref_count"])
                entry["score"] = max(int(entry["score"]), score)
                if rank > entry["rank"]:
                    entry["value"] = candidate_value
                    entry["rank"] = rank

        result_types = []
        for etype, value_counts in by_type.items():
            sorted_values = sorted(
                value_counts.values(),
                key=lambda item: (-int(item["score"]), -int(item["count"]), str(item["value"])),
            )
            result_types.append(
                {
                    "type": etype,
                    "unique_count": len(sorted_values),
                    "mention_count": sum(int(item["count"]) for item in sorted_values),
                    "top": [
                        {"value": str(item["value"]), "count": int(item["count"])}
                        for item in sorted_values[:capped_limit]
                    ],
                }
            )
        result_types.sort(key=lambda item: item["mention_count"], reverse=True)
        return result_types

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

    def _canonicalize_entity(self, entity_type: str, entity_value: str) -> tuple[str, str]:
        canonicalizer = self._get_canonicalizer()
        return canonicalizer.canonicalize(entity_type, entity_value)

    def _canonical_key(self, entity_type: str, entity_value: str) -> str:
        canonicalizer = self._get_canonicalizer()
        canonical_type, canonical_value = canonicalizer.canonicalize(entity_type, entity_value)
        return f"{canonical_type}:{canonicalizer.normalize_for_matching(canonical_value)}"

    def _canonical_display_value(self, entity_type: str, entity_value: str) -> str:
        canonicalizer = self._get_canonicalizer()
        explicit = canonicalizer.get_explicit_canonical(entity_type, entity_value)
        if explicit is not None:
            return explicit[1]
        return entity_value.strip()

    def _has_explicit_canonical(self, entity_type: str, entity_value: str) -> bool:
        canonicalizer = self._get_canonicalizer()
        return canonicalizer.get_explicit_canonical(entity_type, entity_value) is not None

    def _is_noise_entity(self, entity_type: str, entity_value: str) -> bool:
        canonicalizer = self._get_canonicalizer()
        return canonicalizer.is_noise(entity_type, entity_value)

    def _get_canonicalizer(self):
        from .entity_canonicalization import get_entity_canonicalizer

        return get_entity_canonicalizer(self.project_root)

    def _search_match_score(self, value: str, match_terms: list[dict[str, str | bool]]) -> int:
        normalized_value = self._get_canonicalizer().normalize_for_matching(value)
        return self._search_match_score_from_norm(normalized_value, match_terms)

    def _search_match_score_from_norm(
        self,
        normalized_value: str,
        match_terms: list[dict[str, str | bool]],
    ) -> int:
        if not normalized_value:
            return 0
        best_score = 0
        for term in match_terms:
            term_norm = str(term["norm"])
            if normalized_value == term_norm:
                best_score = max(best_score, 400)
                continue
            if self._has_word_boundary_match(normalized_value, term_norm):
                best_score = max(best_score, 320)
                continue
            if bool(term["short"]):
                continue
            if normalized_value.startswith(f"{term_norm} "):
                best_score = max(best_score, 260)
                continue
            if term_norm in normalized_value:
                best_score = max(best_score, 180)
        return best_score

    @staticmethod
    def _has_word_boundary_match(text: str, query: str) -> bool:
        pattern = rf"(?<![a-z0-9]){re.escape(query)}(?![a-z0-9])"
        return re.search(pattern, text) is not None


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
