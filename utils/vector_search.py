"""Recherche sémantique sur les résumés d'articles.

Stratégie :
  - Option A (complète)   : lancedb + embeddings via EurIA API
  - Option B (fallback)   : TF-IDF cosine similarity (aucune dépendance externe)

L'option A est activée si lancedb est installé ET si VECTOR_SEARCH=true dans .env.
Dans tous les cas, l'API publique est identique : ``search(query, top_k)`` → list[dict].

Usage :
    from utils.vector_search import get_vector_search
    vs = get_vector_search()
    results = vs.search("intelligence artificielle régulation", top_k=5)

Architecture des données :
    data/vector_index/   — répertoire de l'index lancedb (si disponible)
    data/tfidf_cache.json — cache TF-IDF sérialisé (fallback)
"""

from __future__ import annotations

import json
import math
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_DEFAULT_PROJECT_ROOT = Path(__file__).parent.parent.resolve()


def _tokenize(text: str) -> list[str]:
    """Tokenisation simple — supprime ponctuations et met en minuscules."""
    return re.findall(r"[a-záàâäéèêëîïôùûüçœæ0-9]+", text.lower())


def _compute_tf(tokens: list[str]) -> dict[str, float]:
    tf: dict[str, float] = {}
    for t in tokens:
        tf[t] = tf.get(t, 0) + 1
    n = max(len(tokens), 1)
    return {k: v / n for k, v in tf.items()}


def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
    """Similarité cosine entre deux vecteurs TF (dicts)."""
    common = set(a.keys()) & set(b.keys())
    if not common:
        return 0.0
    dot = sum(a[k] * b[k] for k in common)
    norm_a = math.sqrt(sum(v * v for v in a.values()))
    norm_b = math.sqrt(sum(v * v for v in b.values()))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class TFIDFSearch:
    """Recherche par similarité TF-IDF — aucune dépendance externe."""

    def __init__(self, project_root: Path) -> None:
        self._project_root = project_root
        self._documents: list[dict] = []   # [{"article": {...}, "tf": {...}}]
        self._idf: dict[str, float] = {}
        self._built = False

    def build(self, articles: list[dict]) -> None:
        """Indexe les articles."""
        self._documents = []
        df: dict[str, int] = {}

        for art in articles:
            text = str(art.get("Résumé", "") or "")
            tokens = _tokenize(text)
            tf = _compute_tf(tokens)
            self._documents.append({"article": art, "tf": tf})
            for term in set(tokens):
                df[term] = df.get(term, 0) + 1

        n = max(len(self._documents), 1)
        self._idf = {term: math.log(n / (1 + count)) for term, count in df.items()}
        self._built = True

    def _tfidf(self, tf: dict[str, float]) -> dict[str, float]:
        return {k: v * self._idf.get(k, 0.0) for k, v in tf.items()}

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        if not self._built or not self._documents:
            return []
        q_tokens = _tokenize(query)
        q_tf = _compute_tf(q_tokens)
        q_tfidf = self._tfidf(q_tf)

        scored = []
        for doc in self._documents:
            doc_tfidf = self._tfidf(doc["tf"])
            score = _cosine(q_tfidf, doc_tfidf)
            if score > 0:
                scored.append((score, doc["article"]))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [
            {**art, "_similarity": round(score, 4)}
            for score, art in scored[:top_k]
        ]


class VectorSearch:
    """Façade unifiée pour la recherche sémantique.

    Essaie lancedb + EurIA embeddings si disponible,
    sinon repasse sur TFIDFSearch.
    """

    def __init__(self, project_root: Path) -> None:
        self._project_root = project_root
        self._tfidf = TFIDFSearch(project_root)
        self._use_lancedb = False
        self._lancedb_table = None

        # Tentative d'activation lancedb
        if os.getenv("VECTOR_SEARCH", "false").lower() == "true":
            try:
                import lancedb  # noqa: F401
                self._use_lancedb = True
            except ImportError:
                pass

    def build_index(self, articles: list[dict]) -> None:
        """Construit (ou recharge) l'index depuis une liste d'articles."""
        # Toujours construire l'index TF-IDF (fallback rapide)
        self._tfidf.build(articles)

        if self._use_lancedb:
            self._build_lancedb_index(articles)

    def _build_lancedb_index(self, articles: list[dict]) -> None:
        """Construit l'index lancedb avec embeddings EurIA."""
        try:
            import lancedb
            from .api_client import get_ai_client

            db_path = str(self._project_root / "data" / "vector_index")
            db = lancedb.connect(db_path)

            client = get_ai_client()
            rows = []
            for art in articles[:500]:  # limite pour éviter les coûts API
                text = str(art.get("Résumé", "") or "")[:512]
                if not text.strip():
                    continue
                try:
                    emb = client.get_embedding(text)
                    if emb:
                        rows.append({
                            "vector": emb,
                            "url": art.get("URL", ""),
                            "source": art.get("Sources", ""),
                            "date": art.get("Date de publication", ""),
                            "resume": text,
                        })
                except Exception:
                    continue

            if rows:
                import pyarrow as pa
                schema = pa.schema([
                    pa.field("vector", pa.list_(pa.float32(), len(rows[0]["vector"]))),
                    pa.field("url", pa.string()),
                    pa.field("source", pa.string()),
                    pa.field("date", pa.string()),
                    pa.field("resume", pa.string()),
                ])
                table_name = "articles"
                try:
                    db.drop_table(table_name)
                except Exception:
                    pass
                self._lancedb_table = db.create_table(table_name, data=rows, schema=schema)
        except Exception:
            self._use_lancedb = False

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        """Recherche sémantique sur les articles indexés."""
        if self._use_lancedb and self._lancedb_table is not None:
            return self._search_lancedb(query, top_k)
        return self._tfidf.search(query, top_k)

    def _search_lancedb(self, query: str, top_k: int) -> list[dict]:
        """Recherche via lancedb + embeddings."""
        try:
            from .api_client import get_ai_client
            client = get_ai_client()
            emb = client.get_embedding(query[:512])
            if not emb:
                return self._tfidf.search(query, top_k)
            results = self._lancedb_table.search(emb).limit(top_k).to_list()
            return [
                {
                    "URL": r.get("url", ""),
                    "Sources": r.get("source", ""),
                    "Date de publication": r.get("date", ""),
                    "Résumé": r.get("resume", ""),
                    "_similarity": float(r.get("_distance", 0)),
                    "_engine": "lancedb",
                }
                for r in results
            ]
        except Exception:
            return self._tfidf.search(query, top_k)

    @property
    def engine(self) -> str:
        return "lancedb" if self._use_lancedb else "tfidf"


# ── Singleton ─────────────────────────────────────────────────────────────────

_instance: Optional[VectorSearch] = None
_instance_built = False


def get_vector_search(project_root: Optional[Path] = None) -> VectorSearch:
    """Retourne le singleton VectorSearch (lazy-init)."""
    global _instance, _instance_built
    if _instance is None:
        pr = project_root or _DEFAULT_PROJECT_ROOT
        _instance = VectorSearch(pr)
    return _instance


def build_search_index(articles: list[dict], project_root: Optional[Path] = None) -> VectorSearch:
    """Construit l'index et retourne le singleton."""
    global _instance_built
    vs = get_vector_search(project_root)
    vs.build_index(articles)
    _instance_built = True
    return vs
