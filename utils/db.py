"""utils/db.py — Couche analytique DuckDB pour WUDD.ai.

Optimisation 2.1 : fournit des requêtes analytiques rapides sur le corpus
d'articles JSON, sans migration destructive du stockage existant.

DuckDB lit les fichiers JSON natifs via `read_json_auto()` — aucune copie,
aucun schéma à définir. Les fichiers JSON restent la source de vérité.

Dépendance optionnelle :
    pip install duckdb>=0.10.0

Usage :
    from utils.db import get_db

    db = get_db()
    if db.available:
        rows = db.query_articles_by_entity("OpenAI", days=7)
        stats = db.article_stats_by_source(days=30)
"""

import json
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from .logging import default_logger

# ── Import optionnel DuckDB ───────────────────────────────────────────────────

try:
    import duckdb as _duckdb
    _DUCKDB_AVAILABLE = True
except ImportError:
    _duckdb = None  # type: ignore
    _DUCKDB_AVAILABLE = False


def _duckdb_available() -> bool:
    """Retourne True si DuckDB est installé."""
    return _DUCKDB_AVAILABLE


# ── Classe principale ─────────────────────────────────────────────────────────

class ArticleDB:
    """Interface analytique DuckDB sur le corpus JSON WUDD.ai.

    Toutes les méthodes retournent des listes de dict Python sérialisables.
    En cas d'indisponibilité de DuckDB, les méthodes retournent une liste vide
    et logguent un avertissement — le pipeline continue sans interruption.

    Thread-safe : utilise un verrou pour les connexions DuckDB en mémoire.
    """

    def __init__(self, project_root: Optional[Path] = None):
        if project_root is None:
            project_root = Path(__file__).parent.parent
        self.project_root = project_root.resolve()
        self.available = _duckdb_available()
        self._lock = threading.Lock()
        self._conn = None

        if self.available:
            self._conn = _duckdb.connect(database=":memory:")
            default_logger.info("[ArticleDB] DuckDB disponible — couche analytique initialisée.")
        else:
            default_logger.warning(
                "[ArticleDB] DuckDB non installé — requêtes analytiques indisponibles. "
                "Installez avec : pip install duckdb>=0.10.0"
            )

    def _exec(self, sql: str, params: Optional[list] = None) -> list[dict]:
        """Exécute une requête SQL et retourne les résultats en liste de dict."""
        if not self.available or self._conn is None:
            return []
        with self._lock:
            try:
                rel = self._conn.execute(sql, params or [])
                cols = [d[0] for d in rel.description]
                return [dict(zip(cols, row)) for row in rel.fetchall()]
            except Exception as e:
                default_logger.error(f"[ArticleDB] Erreur SQL : {e}\nRequête : {sql[:200]}")
                return []

    def _glob_pattern(self, subdir: str = "**/*.json") -> str:
        """Retourne le glob absolu vers les fichiers d'articles."""
        return str(self.project_root / "data" / subdir)

    # ── Requêtes articles ────────────────────────────────────────────────────

    def query_articles_by_entity(
        self,
        entity_name: str,
        days: int = 7,
        entity_type: Optional[str] = None,
    ) -> list[dict]:
        """Retourne les articles mentionnant une entité dans une fenêtre temporelle.

        Args:
            entity_name  : Nom de l'entité (insensible à la casse)
            days         : Fenêtre temporelle en jours (défaut : 7)
            entity_type  : Type NER optionnel ('PERSON', 'ORG', etc.)

        Returns:
            Liste de dicts article avec les champs disponibles.
        """
        cutoff = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
        # DuckDB peut lire les JSON imbriqués avec json_extract
        glob = self._glob_pattern("articles-from-rss/*.json")
        sql = f"""
            SELECT
                "Sources",
                "URL",
                "Date de publication",
                "Résumé",
                "sentiment",
                "score_sentiment",
                "temps_lecture_label"
            FROM read_json_auto('{glob}', ignore_errors=true)
            WHERE
                "Date de publication" >= '{cutoff}'
                AND (
                    json_extract_string(entities, '$.PERSON') LIKE '%{entity_name}%'
                    OR json_extract_string(entities, '$.ORG') LIKE '%{entity_name}%'
                    OR json_extract_string(entities, '$.GPE') LIKE '%{entity_name}%'
                    OR json_extract_string(entities, '$.PRODUCT') LIKE '%{entity_name}%'
                    OR json_extract_string(entities, '$.EVENT') LIKE '%{entity_name}%'
                )
            ORDER BY "Date de publication" DESC
            LIMIT 100
        """
        return self._exec(sql)

    def article_stats_by_source(self, days: int = 30) -> list[dict]:
        """Statistiques d'articles par source sur une fenêtre temporelle.

        Returns:
            Liste de {source, article_count, avg_score_sentiment, last_article}
            triée par volume décroissant.
        """
        cutoff = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
        glob = self._glob_pattern("articles-from-rss/*.json")
        sql = f"""
            SELECT
                "Sources" AS source,
                COUNT(*) AS article_count,
                ROUND(AVG(TRY_CAST("score_sentiment" AS DOUBLE)), 2) AS avg_score_sentiment,
                MAX("Date de publication") AS last_article
            FROM read_json_auto('{glob}', ignore_errors=true)
            WHERE "Date de publication" >= '{cutoff}'
            GROUP BY "Sources"
            ORDER BY article_count DESC
            LIMIT 50
        """
        return self._exec(sql)

    def article_stats_by_day(self, days: int = 30) -> list[dict]:
        """Volume quotidien d'articles sur une fenêtre temporelle.

        Returns:
            Liste de {date, article_count} triée par date croissante.
        """
        cutoff = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
        glob = self._glob_pattern("articles-from-rss/*.json")
        sql = f"""
            SELECT
                LEFT("Date de publication", 10) AS date,
                COUNT(*) AS article_count
            FROM read_json_auto('{glob}', ignore_errors=true)
            WHERE "Date de publication" >= '{cutoff}'
            GROUP BY LEFT("Date de publication", 10)
            ORDER BY date ASC
        """
        return self._exec(sql)

    def sentiment_distribution(self, days: int = 7) -> list[dict]:
        """Distribution des sentiments sur une fenêtre temporelle.

        Returns:
            Liste de {sentiment, count, pct} triée par count décroissant.
        """
        cutoff = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
        glob = self._glob_pattern("articles-from-rss/*.json")
        sql = f"""
            WITH base AS (
                SELECT "sentiment"
                FROM read_json_auto('{glob}', ignore_errors=true)
                WHERE "Date de publication" >= '{cutoff}'
                    AND "sentiment" IS NOT NULL
                    AND "sentiment" != ''
            )
            SELECT
                "sentiment",
                COUNT(*) AS count,
                ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) AS pct
            FROM base
            GROUP BY "sentiment"
            ORDER BY count DESC
        """
        return self._exec(sql)

    def top_sources_by_credibility(self) -> list[dict]:
        """Sources triées par score de crédibilité et volume d'articles (30j).

        Returns:
            Liste de {source, article_count, avg_score_source}
        """
        cutoff = (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%d")
        glob = self._glob_pattern("articles-from-rss/*.json")
        sql = f"""
            SELECT
                "Sources" AS source,
                COUNT(*) AS article_count,
                ROUND(AVG(TRY_CAST("score_source" AS DOUBLE)), 1) AS avg_score_source
            FROM read_json_auto('{glob}', ignore_errors=true)
            WHERE "Date de publication" >= '{cutoff}'
                AND "score_source" IS NOT NULL
            GROUP BY "Sources"
            HAVING COUNT(*) >= 3
            ORDER BY avg_score_source DESC NULLS LAST, article_count DESC
            LIMIT 30
        """
        return self._exec(sql)

    def reading_time_stats(self, days: int = 7) -> dict:
        """Statistiques de temps de lecture sur une fenêtre temporelle.

        Returns:
            Dict {avg_minutes, median_minutes, total_articles}
        """
        cutoff = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
        glob = self._glob_pattern("articles-from-rss/*.json")
        sql = f"""
            SELECT
                ROUND(AVG(TRY_CAST("temps_lecture_minutes" AS DOUBLE)), 1) AS avg_minutes,
                ROUND(MEDIAN(TRY_CAST("temps_lecture_minutes" AS DOUBLE)), 1) AS median_minutes,
                COUNT(*) AS total_articles
            FROM read_json_auto('{glob}', ignore_errors=true)
            WHERE "Date de publication" >= '{cutoff}'
                AND "temps_lecture_minutes" IS NOT NULL
        """
        rows = self._exec(sql)
        return rows[0] if rows else {"avg_minutes": None, "median_minutes": None, "total_articles": 0}

    def full_text_search(self, query: str, days: int = 7, limit: int = 20) -> list[dict]:
        """Recherche plein texte dans les résumés via LIKE (insensible à la casse).

        Pour une recherche sémantique avancée, voir utils/embeddings.py (à venir).

        Args:
            query : Terme(s) à rechercher (insensible à la casse)
            days  : Fenêtre temporelle en jours
            limit : Nombre maximal de résultats

        Returns:
            Liste d'articles avec "Sources", "URL", "Date de publication", "Résumé".
        """
        cutoff = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
        glob = self._glob_pattern("articles-from-rss/*.json")
        # Échapper les apostrophes dans la requête
        safe_query = query.replace("'", "''")
        sql = f"""
            SELECT
                "Sources",
                "URL",
                "Date de publication",
                "Résumé",
                "sentiment",
                "temps_lecture_label"
            FROM read_json_auto('{glob}', ignore_errors=true)
            WHERE
                "Date de publication" >= '{cutoff}'
                AND LOWER("Résumé") LIKE LOWER('%{safe_query}%')
            ORDER BY "Date de publication" DESC
            LIMIT {int(limit)}
        """
        return self._exec(sql)


# ── Singleton ─────────────────────────────────────────────────────────────────

_instance: Optional[ArticleDB] = None
_instance_lock = threading.Lock()


def get_db(project_root: Optional[Path] = None) -> ArticleDB:
    """Retourne le singleton ArticleDB.

    Si DuckDB n'est pas installé, retourne une instance dont `available=False`
    et toutes les méthodes retournent [].
    """
    global _instance
    if project_root is None:
        project_root = Path(__file__).parent.parent
    with _instance_lock:
        if _instance is None:
            _instance = ArticleDB(project_root)
        return _instance
