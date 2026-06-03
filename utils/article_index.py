"""utils/article_index.py — Index léger des métadonnées d'articles.

Maintient data/article_index.json : liste de métadonnées minimales pour chaque
article connu, permettant au ScoringEngine et aux rapports de filtrer par date
et de localiser les fichiers sources SANS relire tout data/.

Format de l'index :
    {
        "version": 1,
        "generated_at": "2026-03-14T10:00:00Z",
        "articles": [
            {
                "url": "https://...",
                "source": "Le Monde",
                "date": "2026-03-13",
                "date_iso": "2026-03-13T10:00:00Z",
                "has_entities": true,
                "has_sentiment": true,
                "has_images": true,
                "file": "data/articles-from-rss/_WUDD.AI_/48-heures.json",
                "idx": 0
            }
        ]
    }

Utilisation typique :
    from utils.article_index import ArticleIndex
    idx = ArticleIndex(project_root)
    idx.update(new_articles, source_file="data/articles-from-rss/_WUDD.AI_/48-heures.json")
    recent = idx.get_recent(hours=24)   # liste de métadonnées filtrées
    articles = idx.load_articles(recent) # charge les articles complets depuis le disque
"""

import json
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from .date_utils import parse_article_date
from .logging import default_logger

_INDEX_VERSION = 1
_INDEX_FILENAME = "article_index.json"

def _parse_date_iso(date_str: str) -> Optional[str]:
    """Convertit une date dans n'importe quel format en ISO 8601 UTC.
    Retourne None si non parsable."""
    dt = parse_article_date(date_str, date_only_policy="end")
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _date_iso_to_dt(iso: str) -> Optional[datetime]:
    """Parse une date ISO 8601 UTC en datetime. Retourne None si invalide."""
    if not iso:
        return None
    try:
        return datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


# ── Classe principale ────────────────────────────────────────────────────────

class ArticleIndex:
    """Index léger des métadonnées d'articles pour accès rapide sans scan complet.

    Thread-safe via threading.Lock.
    """

    def __init__(self, project_root: Optional[Path] = None):
        if project_root is None:
            project_root = Path(__file__).parent.parent
        self.project_root = project_root
        self._index_path = project_root / "data" / _INDEX_FILENAME
        self._lock = threading.Lock()
        self._data: dict = {"version": _INDEX_VERSION, "articles": []}
        self._loaded = False
        # Carte URL normalisée → position dans self._data["articles"] pour get_by_url() O(1)
        self._url_map: dict[str, int] = {}

    # ── Chargement / sauvegarde ─────────────────────────────────────────────

    def _load(self) -> None:
        """Charge l'index depuis le disque (paresseux, une seule fois)."""
        if self._loaded:
            return
        if self._index_path.exists():
            try:
                raw = json.loads(self._index_path.read_text(encoding="utf-8"))
                if isinstance(raw, dict) and raw.get("version") == _INDEX_VERSION:
                    self._data = raw
                else:
                    default_logger.warning(
                        f"article_index.json : version incompatible, reconstruction nécessaire."
                    )
            except (json.JSONDecodeError, OSError) as e:
                default_logger.warning(f"Impossible de charger article_index.json : {e}")
        self._url_map = {
            (e.get("url") or "").strip().rstrip("/").lower(): i
            for i, e in enumerate(self._data["articles"])
            if e.get("url")
        }
        self._loaded = True

    def _save(self) -> None:
        """Sauvegarde atomique de l'index."""
        self._data["generated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        tmp = self._index_path.with_suffix(".tmp")
        try:
            tmp.write_text(
                json.dumps(self._data, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
            tmp.replace(self._index_path)
        except OSError as e:
            default_logger.error(f"Impossible de sauvegarder article_index.json : {e}")

    # ── Mise à jour incrémentale ─────────────────────────────────────────────

    def update(self, articles: list[dict], source_file: str) -> int:
        """Ajoute ou met à jour les entrées d'index pour les articles donnés.

        Args:
            articles    : liste d'articles au format interne WUDD.ai
            source_file : chemin relatif à project_root du fichier source
                          (ex: "data/articles-from-rss/_WUDD.AI_/48-heures.json")

        Returns:
            Nombre de nouvelles entrées ajoutées.
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

            # Construire un set des URLs déjà indexées pour ce fichier source
            existing: dict[str, int] = {
                entry["url"]: i
                for i, entry in enumerate(self._data["articles"])
                if entry.get("file") == source_file and entry.get("url")
            }

            added = 0
            for idx_in_file, article in enumerate(articles):
                url = (article.get("URL") or article.get("url") or "").strip()
                if not url:
                    continue

                date_raw = article.get("Date de publication", "")
                date_iso = _parse_date_iso(date_raw)
                date_short = date_iso[:10] if date_iso else ""

                entry = {
                    "url": url,
                    "source": str(article.get("Sources") or article.get("source") or ""),
                    "date": date_short,
                    "date_iso": date_iso or "",
                    "has_entities": bool(article.get("entities")),
                    "has_sentiment": bool(article.get("sentiment")),
                    "has_images": bool(article.get("Images")),
                    "file": source_file,
                    "idx": idx_in_file,
                }

                if url in existing:
                    # Mise à jour de l'entrée existante (les champs d'enrichissement peuvent avoir changé)
                    pos = existing[url]
                    self._data["articles"][pos] = entry
                else:
                    pos = len(self._data["articles"])
                    self._data["articles"].append(entry)
                    existing[url] = pos
                    added += 1
                # Maintenir la carte URL → position pour get_by_url() O(1)
                self._url_map[url.strip().rstrip("/").lower()] = pos

            self._save()
            return added

    def rebuild(self) -> int:
        """Reconstruit l'index complet en scannant tout data/.

        À utiliser lors de la migration initiale ou après corruption.
        Retourne le nombre total d'entrées indexées.
        """
        scan_dirs = [
            self.project_root / "data" / "articles",
            self.project_root / "data" / "articles-from-rss",
        ]

        # Charger l'index existant : sert de filet pour les fichiers illisibles
        # (écriture concurrente) et de référence pour le garde-fou anti-rétrécissement.
        with self._lock:
            self._load()
            existing_articles = list(self._data.get("articles", []))
        existing_count = len(existing_articles)

        new_articles: list[dict] = []
        failed_files: set[str] = set()
        for scan_dir in scan_dirs:
            if not scan_dir.exists():
                continue
            for json_file in sorted(scan_dir.rglob("*.json")):
                if "cache" in json_file.relative_to(scan_dir).parts:
                    continue
                rel = str(json_file.relative_to(self.project_root)).replace("\\", "/")
                try:
                    data = json.loads(json_file.read_text(encoding="utf-8", errors="replace"))
                    if not isinstance(data, list):
                        continue
                except (json.JSONDecodeError, OSError):
                    # Lecture échouée — typiquement un fichier en cours de
                    # réécriture par un watcher. Ne PAS perdre ses entrées :
                    # on les reportera depuis l'index existant.
                    failed_files.add(rel)
                    continue
                for i, article in enumerate(data):
                    url = (article.get("URL") or article.get("url") or "").strip()
                    if not url:
                        continue
                    date_raw = article.get("Date de publication", "")
                    date_iso = _parse_date_iso(date_raw)
                    new_articles.append({
                        "url": url,
                        "source": str(article.get("Sources") or article.get("source") or ""),
                        "date": date_iso[:10] if date_iso else "",
                        "date_iso": date_iso or "",
                        "has_entities": bool(article.get("entities")),
                        "has_sentiment": bool(article.get("sentiment")),
                        "has_images": bool(article.get("Images")),
                        "file": rel,
                        "idx": i,
                    })

        # Reporter les entrées des fichiers dont la lecture a échoué (préserve
        # le corpus malgré une écriture concurrente transitoire).
        if failed_files:
            carried = [e for e in existing_articles if e.get("file") in failed_files]
            if carried:
                default_logger.warning(
                    f"[article_index] rebuild : {len(failed_files)} fichier(s) illisible(s), "
                    f"{len(carried)} entrée(s) conservée(s) depuis l'index existant."
                )
                new_articles.extend(carried)

        # Déduplication par URL (garder la plus récente)
        seen: dict[str, dict] = {}
        for entry in new_articles:
            url = entry["url"]
            if url not in seen or entry["date_iso"] > seen[url]["date_iso"]:
                seen[url] = entry

        # Garde-fou anti-rétrécissement : ne jamais écraser un index volumineux
        # par un index brutalement plus petit (corpus à moitié réécrit / course
        # avec les watchers). On conserve l'index existant et on journalise.
        if existing_count and len(seen) < existing_count * 0.5:
            default_logger.warning(
                f"[article_index] rebuild ABANDONNÉ : scan = {len(seen)} entrées "
                f"(< 50% de l'index existant = {existing_count}). Index conservé intact."
            )
            return existing_count

        with self._lock:
            self._data = {
                "version": _INDEX_VERSION,
                "articles": list(seen.values()),
            }
            self._url_map = {
                (e.get("url") or "").strip().rstrip("/").lower(): i
                for i, e in enumerate(self._data["articles"])
                if e.get("url")
            }
            self._save()
            self._loaded = True
            return len(self._data["articles"])

    # ── Requêtes ────────────────────────────────────────────────────────────

    def get_recent(self, hours: int = 48) -> list[dict]:
        """Retourne les métadonnées des articles publiés dans les dernières `hours` heures.

        Ne lit pas les fichiers source — utilise uniquement l'index en mémoire.
        """
        with self._lock:
            self._load()

        if hours <= 0:
            return list(self._data["articles"])

        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=hours)
        result = []
        for entry in self._data["articles"]:
            dt = _date_iso_to_dt(entry.get("date_iso", ""))
            if dt and dt >= cutoff:
                result.append(entry)
        return result

    def load_articles(self, entries: list[dict]) -> list[dict]:
        """Charge les articles complets depuis le disque à partir d'une liste de métadonnées.

        Groupe les lectures par fichier pour minimiser les I/O.

        Args:
            entries : liste de métadonnées (format retourné par get_recent())

        Returns:
            Liste d'articles complets, dans le même ordre que entries.
        """
        # Regrouper par fichier
        by_file: dict[str, list[tuple[int, int]]] = {}
        for pos, entry in enumerate(entries):
            f = entry.get("file", "")
            if f:
                by_file.setdefault(f, []).append((pos, entry.get("idx", -1)))

        result: list[Optional[dict]] = [None] * len(entries)
        for rel_path, positions in by_file.items():
            full_path = self.project_root / rel_path
            try:
                data = json.loads(full_path.read_text(encoding="utf-8", errors="replace"))
                if not isinstance(data, list):
                    continue
                for pos, file_idx in positions:
                    if 0 <= file_idx < len(data):
                        article = data[file_idx]
                        article.setdefault("_source_file", rel_path)
                        result[pos] = article
            except (json.JSONDecodeError, OSError):
                continue

        return [a for a in result if a is not None]

    def get_articles(self) -> list[dict]:
        """Retourne toutes les entrées de métadonnées indexées (référence directe).

        Utilisé par quality_monitor.py et source_performance.py pour itérer
        sur l'ensemble de l'index sans copie intermédiaire.

        .. note::
            Retourne une **référence directe** à la liste interne, hors verrou.
            Les modifications de champs sur les dicts individuels (ex. ajout de
            ``quality_score``) sont intentionnelles et permettent une mise à
            jour en place suivie d'un appel à ``save()``.  En revanche, modifier
            la structure de la liste (ajout/suppression d'éléments) doit être
            évité sans synchronisation externe.

        Returns:
            Liste de dicts de métadonnées (url, source, date, has_entities, …).
            Appeler ``save()`` pour persister les changements de champs.
        """
        with self._lock:
            self._load()
        return self._data["articles"]

    def get_by_url(self, url: str) -> Optional[dict]:
        """Retourne l'entrée de métadonnées correspondant à une URL — O(1).

        Utilisé par scoring_optimizer.py pour retrouver rapidement un article
        par son URL sans scanner l'ensemble de l'index.

        Args:
            url : URL complète de l'article (insensible au slash de fin).

        Returns:
            Dict de métadonnées ou None si l'URL est inconnue.
        """
        if not url:
            return None
        url_clean = url.strip().rstrip("/").lower()
        with self._lock:
            self._load()
            pos = self._url_map.get(url_clean)
        if pos is None:
            return None
        articles = self._data["articles"]
        return articles[pos] if 0 <= pos < len(articles) else None

    def save(self) -> None:
        """Persiste l'index sur disque (écriture atomique).

        Méthode publique appelée par quality_monitor.py après mise à jour
        des champs quality_score / quality_level sur les entrées existantes.
        """
        with self._lock:
            self._save()

    def count(self) -> int:
        """Retourne le nombre total d'articles indexés."""
        with self._lock:
            self._load()
        return len(self._data["articles"])

    def stats(self) -> dict:
        """Retourne des statistiques sur l'index."""
        with self._lock:
            self._load()
        articles = self._data["articles"]
        total_files = len({
            a.get("file", "")
            for a in articles
            if a.get("file") and "_WUDD.AI_" not in a.get("file", "")
        })
        return {
            "total": len(articles),
            "total_files": total_files,
            "with_entities": sum(1 for a in articles if a.get("has_entities")),
            "with_sentiment": sum(1 for a in articles if a.get("has_sentiment")),
            "with_images": sum(1 for a in articles if a.get("has_images")),
            "generated_at": self._data.get("generated_at", ""),
        }


# ── Singleton ────────────────────────────────────────────────────────────────

_instances: dict[Path, ArticleIndex] = {}
_instances_lock = threading.Lock()


def get_article_index(project_root: Optional[Path] = None) -> ArticleIndex:
    """Retourne l'instance singleton de l'ArticleIndex pour project_root."""
    if project_root is None:
        project_root = Path(__file__).parent.parent
    project_root = project_root.resolve()
    with _instances_lock:
        if project_root not in _instances:
            _instances[project_root] = ArticleIndex(project_root)
        return _instances[project_root]
