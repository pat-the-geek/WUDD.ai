"""
viewer/routes/entities.py — Blueprint Flask pour les entités nommées (NER).

Routes :
  GET  /api/search/entity
  GET  /api/entities/dashboard
  GET  /api/entities/articles
  GET  /api/entity-context
  GET  /api/entities/cooccurrences
  POST /api/entities/geocode
  POST /api/entities/images
  GET  /api/entities/info
  GET  /api/entities/timeline
  GET  /api/entities/export         ← export consolidé NER + images + synthèses (app tierces)
  GET/POST/DELETE /api/annotations
  GET/POST/DELETE /api/watched-entities
"""
import datetime
import json
import os
import sys
import threading
import time

from flask import Blueprint, jsonify, request, Response, stream_with_context
from pathlib import Path

from viewer.helpers import PROJECT_ROOT, _call_ai_blocking, require_json_body
from viewer.state import _annotations_lock
from utils.article_index import get_article_index
from utils.entity_canonicalization import get_entity_canonicalizer
from utils.date_utils import parse_article_date
from utils.entity_index import STRUCTURAL_ENTITY_TYPES, get_entity_index
from utils.entity_matching import (
    allowed_match_modes,
    default_timeline_match_mode,
    load_match_refs,
    normalize_match_mode,
    resolve_entity_matches,
)

entities_bp = Blueprint("entities", __name__)

# ── Cache TTL pour le dashboard (stats globales — rafraîchi toutes les 5 min) ─
_DASHBOARD_CACHE_TTL = 300  # secondes
_dashboard_cache: dict = {}           # {"default": {"result": ..., "ts": float}, "structural": {...}}
_dashboard_cache_lock = threading.Lock()
_ENTITY_DASHBOARD_SCHEMA_VERSION = 2

# ── Cache TTL pour la liste d'articles d'une entité (ouverture de panel) ───
_ENTITY_ARTICLES_CACHE_TTL = 90  # secondes
_entity_articles_cache: dict = {}  # {(type, value, max, compact): {"result": ..., "ts": float}}
_entity_articles_cache_lock = threading.Lock()

# ── Cache TTL pour les entités surveillées (refresh toutes les 60s) ────────
_WATCHED_CACHE_TTL = 60  # secondes
_watched_cache: dict = {}  # {"result": ..., "ts": float}
_watched_cache_lock = threading.Lock()

# ── Cache TTL pour les co-occurrences (graphe de relations) ────────────────
_COOC_CACHE_TTL = 600  # secondes (10 min)
_cooc_cache: dict = {}  # {cache_key: {"result": ..., "ts": float}}
_cooc_cache_lock = threading.Lock()

# ── Cache TTL pour la recherche d'entités (autocomplete / MCP) ─────────────
_ENTITY_SEARCH_CACHE_TTL = 120  # secondes
_entity_search_cache: dict = {}  # {(query, type): {"result": ..., "ts": float}}
_entity_search_cache_lock = threading.Lock()

_ENTITY_ARTICLE_SORT_FIELDS = ("date", "score_source", "score_ton", "relevance")

# ── Cache mémoire pour images Wikimedia (chargé une seule fois depuis le disque) ─
_images_cache_mem: dict | None = None   # None = pas encore chargé
_images_cache_mem_lock = threading.Lock()

# ── Annotations manuelles ─────────────────────────────────────────────────────
# Stockées dans data/annotations.json (dict keyed par URL d'article)
# Jamais dans les fichiers articles — données sources préservées.

_ANNOTATIONS_FILE = PROJECT_ROOT / "data" / "annotations.json"


def _load_annotations() -> dict:
    """Charge le fichier annotations.json (crée s'il n'existe pas)."""
    if not _ANNOTATIONS_FILE.exists():
        return {}
    try:
        return json.loads(_ANNOTATIONS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_annotations(data: dict) -> None:
    """Sauvegarde atomique du fichier annotations.json."""
    _ANNOTATIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = _ANNOTATIONS_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(_ANNOTATIONS_FILE)


def _parse_entity_article_sort(sort_by: str | None) -> str:
    value = (sort_by or "date").strip().lower()
    if value not in _ENTITY_ARTICLE_SORT_FIELDS:
        raise ValueError(
            "sort_by invalide (valeurs: "
            + ", ".join(_ENTITY_ARTICLE_SORT_FIELDS)
            + ")"
        )
    return value


def _article_sort_timestamp(article: dict) -> float:
    dt = parse_article_date(
        str(article.get("Date de publication", "")),
        date_only_policy="end",
    )
    if dt is None:
        return 0.0
    return dt.timestamp()


def _numeric_article_field(article: dict, field: str) -> float | None:
    raw = article.get(field)
    if raw in (None, ""):
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _sort_entity_articles(results: list[dict], sort_by: str) -> list[dict]:
    if sort_by == "relevance":
        results.sort(
            key=lambda a: (
                int(a.get("_sort_relevance_rank", 10**9)),
                -float(a.get("_sort_date_ts", 0.0)),
            )
        )
        return results

    if sort_by == "date":
        results.sort(
            key=lambda a: (
                float(a.get("_sort_date_ts", 0.0)),
                -int(a.get("_sort_relevance_rank", 10**9)),
            ),
            reverse=True,
        )
        return results

    results.sort(
        key=lambda a: (
            _numeric_article_field(a, sort_by) is not None,
            _numeric_article_field(a, sort_by) or float("-inf"),
            float(a.get("_sort_date_ts", 0.0)),
            -int(a.get("_sort_relevance_rank", 10**9)),
        ),
        reverse=True,
    )
    return results


# ── Entités surveillées ───────────────────────────────────────────────────────
# Stockées dans data/watched_entities.json
# [{type, value, added_at, notes}]

_WATCHED_FILE = PROJECT_ROOT / "data" / "watched_entities.json"
_watched_lock = threading.Lock()
_LEGACY_TIMELINE_FILE = PROJECT_ROOT / "data" / "entity_timeline.json"
_TIMELINE_CACHE_DIR = PROJECT_ROOT / "data" / "entity_timeline_cache"


def _load_watched() -> list:
    if not _WATCHED_FILE.exists():
        return []
    try:
        return json.loads(_WATCHED_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_watched(data: list) -> None:
    _WATCHED_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = _WATCHED_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(_WATCHED_FILE)


def _canonicalize_watched_entity(entity_type: str, entity_value: str) -> tuple[str, str]:
    canonicalizer = get_entity_canonicalizer(PROJECT_ROOT)
    return canonicalizer.canonicalize(entity_type, entity_value)


def _build_entity_query_info(
    *,
    entity: str | None,
    entity_type: str | None,
    match_mode: str,
    all_types: bool,
    include_structural: bool = False,
    matched_entities: list[dict] | None = None,
) -> dict:
    return {
        "entity": (entity or "").strip(),
        "type": (entity_type or "").strip().upper(),
        "match_mode": match_mode,
        "all_types": bool(all_types),
        "include_structural": bool(include_structural),
        "matched_entities": matched_entities or [],
    }


def _timeline_cache_file(days: int, top_n: int, *, include_structural: bool = False) -> Path:
    """Retourne le fichier de cache de timeline associé aux paramètres."""
    if days == 30 and top_n == 30 and not include_structural:
        return _LEGACY_TIMELINE_FILE
    safe_days = max(0, days)
    safe_top = max(1, top_n)
    suffix = "_struct" if include_structural else ""
    return _TIMELINE_CACHE_DIR / f"entity_timeline_{safe_days}d_top{safe_top}{suffix}.json"


def _build_search_query_info(query: str, *, include_structural: bool = False) -> dict:
    canonicalizer = get_entity_canonicalizer(PROJECT_ROOT)
    expanded_terms = canonicalizer.expand_search_terms(query)
    return {
        "original": query,
        "expanded_terms": expanded_terms,
        "short_query": canonicalizer.is_short_query(query),
        "include_structural": bool(include_structural),
    }


@entities_bp.route("/api/search/entity")
def api_search_entity():
    """Recherche cross-fichiers d'une valeur d'entité nommée (via entity_index)."""
    q = request.args.get("q", "").strip()
    entity_type = request.args.get("type", "").strip()
    if len(q) < 2:
        return jsonify([])

    q_lower = q.lower()
    results = []

    try:
        eidx = get_entity_index(PROJECT_ROOT)
        all_entries = eidx.get_all_entries(canonicalize=True)  # { "TYPE:value": [{file, idx, date}, ...] }

        # Filtrer les clés qui contiennent q_lower (correspondance partielle)
        matching_keys = [
            k for k in all_entries
            if q_lower in k.split(":", 1)[-1].lower()
            and (not entity_type or k.startswith(entity_type + ":"))
        ]

        # Regrouper refs par fichier pour charger chaque fichier une seule fois
        files_to_idxs: dict[str, set[int]] = {}
        key_by_file_idx: dict[tuple, list[str]] = {}  # (file, idx) → matched types
        for k in matching_keys:
            etype = k.split(":", 1)[0]
            for ref in all_entries[k]:
                fpath = ref.get("file", "")
                idx = ref.get("idx", -1)
                if not fpath:
                    continue
                files_to_idxs.setdefault(fpath, set()).add(idx)
                key_by_file_idx.setdefault((fpath, idx), []).append(etype)

        seen_results: set[str] = set()
        for rel_path, idxs in files_to_idxs.items():
            try:
                articles = json.loads(
                    (PROJECT_ROOT / rel_path).read_text(encoding="utf-8", errors="replace")
                )
                if not isinstance(articles, list):
                    continue
            except (json.JSONDecodeError, OSError):
                continue
            for i, article in enumerate(articles):
                if i not in idxs:
                    continue
                url = article.get("URL", "")
                if url and url in seen_results:
                    continue
                if url:
                    seen_results.add(url)
                matched_types = key_by_file_idx.get((rel_path, i), [])
                resume = article.get("Résumé", "")
                idx_in_resume = resume.lower().find(q_lower)
                if idx_in_resume >= 0:
                    start = max(0, idx_in_resume - 80)
                    end = min(len(resume), idx_in_resume + len(q) + 80)
                    excerpt = (
                        ("…" if start > 0 else "")
                        + resume[start:end]
                        + ("…" if end < len(resume) else "")
                    )
                else:
                    excerpt = resume[:160] + ("…" if len(resume) > 160 else "")
                results.append({
                    "path": rel_path,
                    "name": Path(rel_path).name,
                    "source": article.get("Sources", ""),
                    "date": article.get("Date de publication", ""),
                    "url": url,
                    "excerpt": excerpt,
                    "types": matched_types,
                })
    except Exception:
        # Fallback rglob si l'index est indisponible
        data_dirs = [
            PROJECT_ROOT / "data" / "articles",
            PROJECT_ROOT / "data" / "articles-from-rss",
        ]
        canonicalizer = get_entity_canonicalizer(PROJECT_ROOT)
        for data_dir in data_dirs:
            if not data_dir.exists():
                continue
            for json_file in sorted(data_dir.rglob("*.json")):
                if "cache" in json_file.relative_to(data_dir).parts:
                    continue
                try:
                    articles = json.loads(json_file.read_text(encoding="utf-8", errors="replace"))
                    if not isinstance(articles, list):
                        continue
                except (json.JSONDecodeError, OSError):
                    continue
                for article in articles:
                    ents = article.get("entities")
                    if not ents or not isinstance(ents, dict):
                        continue
                    matched_types = []
                    for etype, values in ents.items():
                        if entity_type and etype != entity_type:
                            continue
                        if not isinstance(values, list):
                            continue
                        if any(q_lower in str(v).lower() for v in values):
                            matched_types.append(etype)
                    if not matched_types:
                        continue
                    resume = article.get("Résumé", "")
                    idx = resume.lower().find(q_lower)
                    if idx >= 0:
                        start = max(0, idx - 80)
                        end = min(len(resume), idx + len(q) + 80)
                        excerpt = (
                            ("…" if start > 0 else "")
                            + resume[start:end]
                            + ("…" if end < len(resume) else "")
                        )
                    else:
                        excerpt = resume[:160] + ("…" if len(resume) > 160 else "")
                    rel = json_file.relative_to(PROJECT_ROOT)
                    results.append({
                        "path": str(rel).replace("\\", "/"),
                        "name": json_file.name,
                        "source": article.get("Sources", ""),
                        "date": article.get("Date de publication", ""),
                        "url": article.get("URL", ""),
                        "excerpt": excerpt,
                        "types": matched_types,
                    })

    results.sort(key=lambda r: r["date"], reverse=True)
    return jsonify(results[:100])


@entities_bp.route("/api/entities/search")
def api_entities_search():
    """Recherche d'entités par nom (plein texte) dans l'entity_index.

    Retourne le même format que /api/entities/dashboard (by_type) mais filtré
    sur toutes les entrées de l'index (pas seulement le top 50 par type).
    """
    q = request.args.get("q", "").strip()
    include_structural = request.args.get("include_structural", "0").strip().lower() in {
        "1", "true", "yes", "on"
    }
    if len(q) < 2:
        return jsonify({
            "by_type": [],
            "query": _build_search_query_info(q, include_structural=include_structural),
            "advanced_options": {
                "include_structural": {
                    "default": False,
                    "description": "Inclut DATE, MONEY et autres types structurels dans la recherche."
                }
            },
        })

    q_lower = q.lower()
    cache_key = (q_lower, "", include_structural)
    canonicalizer = get_entity_canonicalizer(PROJECT_ROOT)

    with _entity_search_cache_lock:
        cached = _entity_search_cache.get(cache_key)
        cached_ts = 0.0 if cached is None else cached.get("ts", 0.0)
        if cached is not None and (time.monotonic() - cached_ts) < _ENTITY_SEARCH_CACHE_TTL:
            return jsonify(cached["result"])

    try:
        eidx = get_entity_index(PROJECT_ROOT)
        if hasattr(eidx, "search_values"):
            result = {
                "by_type": eidx.search_values(q, include_structural=include_structural),
                "query": _build_search_query_info(q, include_structural=include_structural),
                "advanced_options": {
                    "include_structural": {
                        "default": False,
                        "description": "Inclut DATE, MONEY et autres types structurels dans la recherche."
                    }
                },
            }
            with _entity_search_cache_lock:
                _entity_search_cache[cache_key] = {"result": result, "ts": time.monotonic()}
            return jsonify(result)

        by_type: dict[str, dict[str, int]] = {}
        all_entries = eidx.get_all_entries(
            canonicalize=True,
            include_structural=include_structural,
        )  # Compatibilité vieux mocks/tests
        for key, refs in all_entries.items():
            parts = key.split(":", 1)
            if len(parts) != 2:
                continue
            etype, value = parts[0], parts[1].strip()
            if not value or q_lower not in value.lower():
                continue
            if etype not in by_type:
                by_type[etype] = {}
            by_type[etype][value] = by_type[etype].get(value, 0) + len(refs)

    except Exception:
        # Fallback rglob si l'index est indisponible
        by_type: dict[str, dict[str, int]] = {}
        data_dirs = [
            PROJECT_ROOT / "data" / "articles",
            PROJECT_ROOT / "data" / "articles-from-rss",
        ]
        for data_dir in data_dirs:
            if not data_dir.exists():
                continue
            for json_file in sorted(data_dir.rglob("*.json")):
                rel_parts = json_file.relative_to(data_dir).parts
                if "cache" in rel_parts or "_WUDD.AI_" in rel_parts:
                    continue
                try:
                    articles = json.loads(json_file.read_text(encoding="utf-8", errors="replace"))
                    if not isinstance(articles, list):
                        continue
                except (json.JSONDecodeError, OSError):
                    continue
                for article in articles:
                    ents = article.get("entities")
                    if not ents or not isinstance(ents, dict):
                        continue
                    for etype, values in ents.items():
                        if not include_structural and etype in STRUCTURAL_ENTITY_TYPES:
                            continue
                        if not isinstance(values, list):
                            continue
                        for v in values:
                            if isinstance(v, str) and q_lower in v.lower():
                                if canonicalizer.is_noise(etype, v):
                                    continue
                                canonical_type, canonical_value = canonicalizer.canonicalize(etype, v)
                                if canonical_type not in by_type:
                                    by_type[canonical_type] = {}
                                by_type[canonical_type][canonical_value] = (
                                    by_type[canonical_type].get(canonical_value, 0) + 1
                                )

    result_types = []
    for etype, value_counts in by_type.items():
        sorted_values = sorted(value_counts.items(), key=lambda x: x[1], reverse=True)
        result_types.append({
            "type": etype,
            "unique_count": len(sorted_values),
            "mention_count": sum(c for _, c in sorted_values),
            "top": [{"value": v, "count": c} for v, c in sorted_values[:100]],
        })
    result_types.sort(key=lambda x: x["mention_count"], reverse=True)
    result = {
        "by_type": result_types,
        "query": _build_search_query_info(q, include_structural=include_structural),
        "advanced_options": {
            "include_structural": {
                "default": False,
                "description": "Inclut DATE, MONEY et autres types structurels dans la recherche."
            }
        },
    }
    with _entity_search_cache_lock:
        _entity_search_cache[cache_key] = {"result": result, "ts": time.monotonic()}
    return jsonify(result)


@entities_bp.route("/api/entities/dashboard")
def api_entities_dashboard():
    """Agrège les entités de tous les fichiers JSON et retourne des stats globales (via entity_index).

    Ordre de priorité du cache :
      1. Cache TTL mémoire (5 min) — le plus rapide
      2. entity_stats.json pré-calculé nightly par precompute_entity_stats.py
      3. Calcul live via entity_index (O(index_keys), pas de I/O fichier)
      4. Fallback rglob Python si entity_index indisponible
    """
    include_structural = request.args.get("include_structural", "0").strip().lower() in {
        "1", "true", "yes", "on"
    }
    cache_bucket = "structural" if include_structural else "default"

    def _build_duckdb_stats_payload(db) -> dict:
        reading_time_7j = db.reading_time_stats(days=7)
        sentiment_7j = db.sentiment_distribution(days=7)
        enrichment_7j = db.enrichment_coverage(days=7)
        sample_size = sum(int(row.get("count", 0)) for row in sentiment_7j if isinstance(row, dict))
        denominator = int((reading_time_7j or {}).get("total_articles") or 0)
        coverage_pct = round((100.0 * sample_size / denominator), 1) if denominator > 0 else None
        enrichment_total = int((enrichment_7j or {}).get("total_articles") or 0)

        def _coverage(field: str) -> float | None:
            value = int((enrichment_7j or {}).get(field) or 0)
            if enrichment_total <= 0:
                return None
            return round((100.0 * value / enrichment_total), 1)

        return {
            "reading_time_7j": reading_time_7j,
            "sentiment_7j": sentiment_7j,
            "sentiment_7j_meta": {
                "sample_size": sample_size,
                "coverage_pct_of_reading_time_7j": coverage_pct,
                "basis": "Articles RSS des 7 derniers jours avec champ sentiment non vide.",
            },
            "enrichment_7j": {
                **(enrichment_7j or {}),
                "enrichissement_pct": _coverage("ok_status"),
                "entities_coverage_pct": _coverage("with_entities"),
                "sentiment_coverage_pct": _coverage("with_sentiment"),
                "score_source_coverage_pct": _coverage("with_score_source"),
                "editorial_ready_pct": _coverage("editorial_ready"),
                "basis": "Articles RSS des 7 derniers jours ; indicateur de complétude du pipeline d'enrichissement.",
            },
            "source_count_30j": len(db.article_stats_by_source(days=30)),
        }

    # ── 1. Cache TTL mémoire ──────────────────────────────────────────────────
    with _dashboard_cache_lock:
        cached_entry = _dashboard_cache.get(cache_bucket, {})
        cached = cached_entry.get("result")
        cached_ts = cached_entry.get("ts", 0.0)
        if cached is not None and (time.monotonic() - cached_ts) < _DASHBOARD_CACHE_TTL:
            return jsonify(cached)

    # ── 2. Fichier entity_stats.json pré-calculé (cache chaud nightly) ────────
    _stats_file = PROJECT_ROOT / "data" / "entity_stats.json"
    if not include_structural and _stats_file.exists():
        try:
            precomp = json.loads(_stats_file.read_text(encoding="utf-8"))
            if precomp.get("schema_version") != _ENTITY_DASHBOARD_SCHEMA_VERSION:
                raise ValueError("precomputed entity_stats schema obsolète")
            # Valide si le fichier a moins de 25 heures (laisser passer la 1re nuit)
            from datetime import timezone as _tz
            from datetime import datetime as _dt
            gen_at = precomp.get("generated_at", "")
            if gen_at:
                age_h = (_dt.now(_tz.utc) - _dt.fromisoformat(gen_at)).total_seconds() / 3600
                if age_h < 25:
                    # Enrichir avec DuckDB temps-réel (rapide) puis mettre en cache
                    duckdb_stats = {}
                    try:
                        from utils.db import get_db as _gdb
                        _db = _gdb(PROJECT_ROOT)
                        if _db.available:
                            duckdb_stats = _build_duckdb_stats_payload(_db)
                    except Exception:
                        pass
                    # total_files depuis le precomputed peut être None si généré par une
                    # ancienne version — fallback sur l'article_index dans ce cas
                    precomp_total_files = precomp.get("total_files") or 0
                    if not precomp_total_files:
                        try:
                            _aidx = get_article_index(PROJECT_ROOT)
                            precomp_total_files = _aidx.stats().get("total_files", 0)
                        except Exception:
                            pass
                    result_payload = {
                        "schema_version":       _ENTITY_DASHBOARD_SCHEMA_VERSION,
                        "total_files":          precomp_total_files,
                        "total_articles":       precomp.get("total_articles", 0),
                        "total_with_entities":  precomp.get("total_with_entities", 0),
                        "by_type":              precomp.get("by_type", []),
                        "duckdb_stats":         duckdb_stats,
                        "include_structural":   False,
                        "_source":              "precomputed",
                        "advanced_options": {
                            "include_structural": {
                                "default": False,
                                "description": "Ajoute DATE, MONEY et autres types structurels au dashboard."
                            }
                        },
                    }
                    with _dashboard_cache_lock:
                        _dashboard_cache[cache_bucket] = {
                            "result": result_payload,
                            "ts": time.monotonic(),
                        }
                    return jsonify(result_payload)
        except Exception:
            pass  # Continuer vers le calcul live

    by_type: dict[str, dict[str, int]] = {}
    total_with_entities = 0
    canonicalizer = get_entity_canonicalizer(PROJECT_ROOT)

    try:
        eidx = get_entity_index(PROJECT_ROOT)
        all_entries = eidx.get_all_entries(
            include_structural=include_structural
        )  # { "TYPE:value": [{file, idx, date}, ...] }

        # Compter les mentions depuis l'index (O(k) sur les clés)
        for key, refs in all_entries.items():
            parts = key.split(":", 1)
            if len(parts) != 2:
                continue
            etype, value = parts[0], parts[1].strip()
            if not value:
                continue
            if etype not in by_type:
                by_type[etype] = {}
            by_type[etype][value] = by_type[etype].get(value, 0) + len(refs)

        # Totaux depuis l'article_index (URL-dédupliqué)
        aidx = get_article_index(PROJECT_ROOT)
        astats = aidx.stats()
        # total_files depuis l'article_index (tous les fichiers, même sans entités)
        total_files = astats.get("total_files", 0)
        total_articles = astats.get("total", 0)
        # Utiliser l'article_index (URL-dédupliqué) pour éviter de compter 2×
        # les articles présents à la fois dans un fichier mot-clé et dans 48-heures.json
        total_with_entities = astats.get("with_entities", 0)

    except Exception:
        # Fallback rglob
        data_dirs = [
            PROJECT_ROOT / "data" / "articles",
            PROJECT_ROOT / "data" / "articles-from-rss",
        ]
        total_files = 0
        total_articles = 0
        total_with_entities = 0
        seen_urls: set[str] = set()
        for data_dir in data_dirs:
            if not data_dir.exists():
                continue
            for json_file in sorted(data_dir.rglob("*.json")):
                rel_parts = json_file.relative_to(data_dir).parts
                if "cache" in rel_parts or "_WUDD.AI_" in rel_parts:
                    continue
                try:
                    articles = json.loads(json_file.read_text(encoding="utf-8", errors="replace"))
                    if not isinstance(articles, list):
                        continue
                except (json.JSONDecodeError, OSError):
                    continue
                total_files += 1
                for article in articles:
                    url = str(article.get("URL") or article.get("url") or "").strip()
                    if not url or url in seen_urls:
                        continue
                    seen_urls.add(url)
                    total_articles += 1
                    ents = article.get("entities")
                    if not ents or not isinstance(ents, dict):
                        continue
                    has_ent = False
                    for etype, values in ents.items():
                        if not include_structural and etype in STRUCTURAL_ENTITY_TYPES:
                            continue
                        if not isinstance(values, list) or not values:
                            continue
                        has_ent = True
                        if etype not in by_type:
                            by_type[etype] = {}
                        for v in values:
                            if isinstance(v, str) and v.strip():
                                if canonicalizer.is_noise(etype, v):
                                    continue
                                canonical_type, canonical_value = canonicalizer.canonicalize(etype, v)
                                if canonical_type not in by_type:
                                    by_type[canonical_type] = {}
                                by_type[canonical_type][canonical_value] = (
                                    by_type[canonical_type].get(canonical_value, 0) + 1
                                )
                    if has_ent:
                        total_with_entities += 1

    result_types = []
    for etype, value_counts in by_type.items():
        sorted_values = sorted(value_counts.items(), key=lambda x: x[1], reverse=True)
        result_types.append({
            "type": etype,
            "unique_count": len(sorted_values),
            "mention_count": sum(c for _, c in sorted_values),
            "top": [{"value": v, "count": c} for v, c in sorted_values[:50]],
        })
    result_types.sort(key=lambda x: x["mention_count"], reverse=True)

    # ── Enrichissement DuckDB (stats articles temps-réel) ─────────────────────
    duckdb_stats = {}
    try:
        from utils.db import get_db
        db = get_db(PROJECT_ROOT)
        if db.available:
            duckdb_stats = _build_duckdb_stats_payload(db)
    except Exception:
        pass

    result_payload = {
        "schema_version": _ENTITY_DASHBOARD_SCHEMA_VERSION,
        "total_files": total_files,
        "total_articles": total_articles,
        "total_with_entities": total_with_entities,
        "by_type": result_types,
        "duckdb_stats": duckdb_stats,
        "include_structural": include_structural,
        "advanced_options": {
            "include_structural": {
                "default": False,
                "description": "Ajoute DATE, MONEY et autres types structurels au dashboard."
            }
        },
    }
    # Stocker dans le cache TTL
    with _dashboard_cache_lock:
        _dashboard_cache[cache_bucket] = {
            "result": result_payload,
            "ts": time.monotonic(),
        }
    return jsonify(result_payload)


@entities_bp.route("/api/entities/articles")
def api_entities_articles():
    """Retourne tous les articles contenant une entité donnée (type + valeur) via entity_index."""
    allowed_params = {
        "type",
        "value",
        "max_articles",
        "limit",
        "compact",
        "sort_by",
        "match_mode",
        "all_types",
    }
    unknown_params = sorted(set(request.args.keys()) - allowed_params)
    if unknown_params:
        return jsonify({
            "error": "Paramètres de requête inconnus",
            "unknown_params": unknown_params,
            "allowed_params": sorted(allowed_params),
        }), 400

    entity_type = request.args.get("type", "").strip()
    entity_value = request.args.get("value", "").strip()
    if "max_articles" in request.args:
        max_articles = request.args.get("max_articles", default=300, type=int)
    elif "limit" in request.args:
        max_articles = request.args.get("limit", default=300, type=int)
    else:
        max_articles = 300

    if max_articles is None:
        return jsonify({"error": "max_articles/limit doit être un entier"}), 400

    max_articles = max(1, min(max_articles or 300, 2000))
    compact = request.args.get("compact", "0").strip().lower() in {"1", "true", "yes", "on"}
    try:
        sort_by = _parse_entity_article_sort(request.args.get("sort_by"))
    except ValueError as exc:
        return jsonify({"error": str(exc), "allowed_sort_by": list(_ENTITY_ARTICLE_SORT_FIELDS)}), 400
    try:
        match_mode = normalize_match_mode(request.args.get("match_mode"), default="canonical")
    except ValueError as exc:
        return jsonify({"error": str(exc), "allowed_match_modes": allowed_match_modes()}), 400
    all_types = request.args.get("all_types", "0").strip().lower() in {"1", "true", "yes", "on"}

    if not entity_value or (not entity_type and not all_types):
        return jsonify({"error": "Paramètre value requis, et type sauf si all_types=1"}), 400

    canonicalizer = get_entity_canonicalizer(PROJECT_ROOT)
    cache_key = (
        entity_type.upper(),
        entity_value.lower(),
        max_articles,
        compact,
        sort_by,
        match_mode,
        all_types,
    )
    with _entity_articles_cache_lock:
        cached = _entity_articles_cache.get(cache_key)
        if cached and (time.monotonic() - cached.get("ts", 0.0)) < _ENTITY_ARTICLES_CACHE_TTL:
            return jsonify(cached.get("result", []))

    compact_fields = {
        "Date de publication",
        "Sources",
        "URL",
        "Résumé",
        "Images",
        "entities",
        "sentiment",
        "score_sentiment",
        "ton_editorial",
        "score_ton",
        "score_source",
        "temps_lecture_minutes",
        "temps_lecture_label",
        "mot_cle",
        "terme_declencheur",
        "terme_and",
        "enrichissement_statut",
        "fichier_source",
        "rapports",
    }

    seen_urls: set = set()
    results = []
    index_found_results = False

    try:
        eidx = get_entity_index(PROJECT_ROOT)
        matches = resolve_entity_matches(
            PROJECT_ROOT,
            entity_value,
            entity_type,
            match_mode=match_mode,
            all_types=all_types,
        )
        refs = load_match_refs(
            PROJECT_ROOT,
            matches,
            canonicalize=(match_mode != "strict"),
        )
        if refs:
            index_found_results = True
            refs_cap = min(len(refs), max(max_articles * 8, 200))
            refs = refs[:refs_cap]

            refs_by_file: dict[str, list[tuple[int, int]]] = {}
            for pos, ref in enumerate(refs):
                rel_path = ref.get("file", "")
                file_idx = ref.get("idx", -1)
                if not rel_path or not isinstance(file_idx, int) or file_idx < 0:
                    continue
                refs_by_file.setdefault(rel_path, []).append((pos, file_idx))

            file_order = sorted(
                refs_by_file.items(),
                key=lambda item: (-len(item[1]), min(p for p, _ in item[1])),
            )

            max_files_to_open = 25 if compact else 60
            for rel_path, positions in file_order[:max_files_to_open]:
                full_path = PROJECT_ROOT / rel_path
                try:
                    data = json.loads(full_path.read_text(encoding="utf-8", errors="replace"))
                    if not isinstance(data, list):
                        continue
                except (json.JSONDecodeError, OSError):
                    continue

                for _, file_idx in sorted(positions, key=lambda p: p[0]):
                    if not (0 <= file_idx < len(data)):
                        continue
                    article = data[file_idx]
                    url = (article.get("URL") or "").strip()
                    resume_key = article.get("Résumé", "")[:150].strip()
                    if (url and url in seen_urls) or (resume_key and resume_key in seen_urls):
                        continue
                    if url:
                        seen_urls.add(url)
                    if resume_key:
                        seen_urls.add(resume_key)
                    payload = (
                        {k: article.get(k) for k in compact_fields if k in article}
                        if compact
                        else dict(article)
                    )
                    payload["_sort_relevance_rank"] = int(len(results))
                    payload["_sort_date_ts"] = _article_sort_timestamp(article)
                    results.append(payload)
                    if len(results) >= max_articles:
                        break
                if len(results) >= max_articles:
                    break
    except Exception:
        pass

    # En mode compact (UI panel), on évite le fallback rglob coûteux pour
    # garantir un premier affichage rapide même si l'index est temporairement
    # indisponible sur un worker.
    if not index_found_results and not compact:
        # Fallback rglob : index indisponible, version incompatible, entité non indexée
        # (types DATE/MONEY/…), ou index non encore reconstruit après ajout d'articles.
        matches = resolve_entity_matches(
            PROJECT_ROOT,
            entity_value,
            entity_type,
            match_mode=match_mode,
            all_types=all_types,
        )
        matched_keys = {
            (
                str(match.get("type") or "").strip().upper(),
                str(match.get("value") or "").strip(),
            )
            for match in matches
        }
        for data_dir in [PROJECT_ROOT / "data" / "articles", PROJECT_ROOT / "data" / "articles-from-rss"]:
            if not data_dir.exists():
                continue
            for json_file in sorted(data_dir.rglob("*.json")):
                if "cache" in json_file.relative_to(data_dir).parts:
                    continue
                try:
                    articles = json.loads(json_file.read_text(encoding="utf-8", errors="replace"))
                    if not isinstance(articles, list):
                        continue
                except (json.JSONDecodeError, OSError):
                    continue
                for article in articles:
                    entities = article.get("entities", {})
                    if not isinstance(entities, dict):
                        continue
                    matched = False
                    for article_type, values in entities.items():
                        if not isinstance(values, list):
                            continue
                        for raw_value in values:
                            if not isinstance(raw_value, str) or not raw_value.strip():
                                continue
                            current_type = article_type.strip().upper()
                            current_value = raw_value.strip()
                            if match_mode != "strict":
                                current_type, current_value = canonicalizer.canonicalize(current_type, current_value)
                            if (current_type, current_value) in matched_keys:
                                matched = True
                                break
                        if matched:
                            break
                    if not matched:
                        continue
                    url = (article.get("URL") or "").strip()
                    resume_key = article.get("Résumé", "")[:150].strip()
                    if (url and url in seen_urls) or (resume_key and resume_key in seen_urls):
                        continue
                    if url:
                        seen_urls.add(url)
                    if resume_key:
                        seen_urls.add(resume_key)
                    payload = (
                        {k: article.get(k) for k in compact_fields if k in article}
                        if compact
                        else dict(article)
                    )
                    payload["_sort_relevance_rank"] = int(len(results))
                    payload["_sort_date_ts"] = _article_sort_timestamp(article)
                    results.append(payload)
                    if len(results) >= max_articles:
                        break
                if len(results) >= max_articles:
                    break
            if len(results) >= max_articles:
                break

    results = _sort_entity_articles(results, sort_by)
    for article in results:
        article.pop("_sort_relevance_rank", None)
        article.pop("_sort_date_ts", None)

    with _entity_articles_cache_lock:
        _entity_articles_cache[cache_key] = {"result": results, "ts": time.monotonic()}

    return jsonify(results)


@entities_bp.route("/api/entity-context")
def api_entity_context():
    """Construit le contexte complet d'une entité pour le Terminal IA.

    Retourne un flux SSE avec des événements de progression, puis un
    événement "done" contenant le contexte assemblé (articles, co-occurrences,
    calendrier, synthèse encyclopédique IA, analyse comparative RAG).

    Query params :
      type  — type NER (ex. "ORG", "PERSON", "GPE")
      value — valeur de l'entité (ex. "OpenAI", "Emmanuel Macron")
      n     — nombre max d'articles dans le contexte (défaut 20, max 50)
    """
    entity_type  = request.args.get("type",  "").strip()
    entity_value = request.args.get("value", "").strip()
    n_articles   = min(int(request.args.get("n", 20)), 50)

    if not entity_type or not entity_value:
        return jsonify({"error": "Paramètres type et value requis"}), 400

    def _evt(payload: dict) -> str:
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    def generate():  # noqa: C901
        from collections import Counter as _Counter, defaultdict as _defaultdict

        # ── Étape 1 : collecte via entity_index (évite le scan rglob) ──────
        yield _evt({"type": "progress", "step": "data",
                    "message": f"Collecte des articles pour « {entity_value} »…"})

        try:
            from utils.entity_index import get_entity_index as _get_eidx
            eidx = _get_eidx(PROJECT_ROOT)
            articles = eidx.load_articles(entity_type, entity_value)
        except Exception:
            # Fallback : scan complet si l'index n'est pas disponible
            articles = []
            seen_urls: set = set()
            for data_dir in [PROJECT_ROOT / "data" / "articles",
                             PROJECT_ROOT / "data" / "articles-from-rss"]:
                if not data_dir.exists():
                    continue
                for json_file in sorted(data_dir.rglob("*.json")):
                    if "cache" in json_file.relative_to(data_dir).parts:
                        continue
                    try:
                        arts = json.loads(json_file.read_text(encoding="utf-8", errors="replace"))
                        if not isinstance(arts, list):
                            continue
                    except (json.JSONDecodeError, OSError):
                        continue
                    for article in arts:
                        ents = article.get("entities", {})
                        if not isinstance(ents, dict):
                            continue
                        values = ents.get(entity_type, [])
                        _ev_lower = entity_value.lower()
                        if not (isinstance(values, list) and any(
                            isinstance(v, str) and v.lower() == _ev_lower for v in values
                        )):
                            continue
                        url = (article.get("URL") or "").strip()
                        if url and url in seen_urls:
                            continue
                        if url:
                            seen_urls.add(url)
                        articles.append(article)

        articles.sort(key=lambda a: a.get("Date de publication", ""), reverse=True)
        top_articles = articles[:n_articles]

        yield _evt({"type": "progress", "step": "data",
                    "message": f"{len(articles)} article(s) trouvé(s). Calcul des relations…"})

        # ── Calcul co-occurrences + calendrier en un seul passage ──────────
        cooc: _Counter = _Counter()
        monthly: dict[str, int] = _defaultdict(int)
        sentiments_tmp: _Counter = _Counter()
        sources_tmp: _Counter = _Counter()

        for article in articles:
            # Co-occurrences L1
            ents = article.get("entities", {})
            if isinstance(ents, dict):
                for etype, evals in ents.items():
                    if isinstance(evals, list):
                        for ev in evals:
                            if not (etype == entity_type and ev == entity_value):
                                cooc[(etype, ev)] += 1
            # Calendrier mensuel
            date_str = article.get("Date de publication", "")
            if date_str and len(date_str) >= 7:
                if "/" in date_str:
                    parts = date_str.split("/")
                    if len(parts) == 3:
                        monthly[f"{parts[2]}-{parts[1]}"] += 1
                elif "-" in date_str:
                    monthly[date_str[:7]] += 1
            # Sentiments & sources (évite un 2e passage plus bas)
            s = article.get("sentiment")
            if s:
                sentiments_tmp[s] += 1
            src = article.get("Sources")
            if src:
                sources_tmp[src] += 1

        top_cooc = cooc.most_common(15)

        # ── Étape 2 : synthèse IA (encyclopédie + RAG) avec cache ─────────
        yield _evt({"type": "progress", "step": "info",
                    "message": "Synthèse encyclopédique IA en cours…"})

        type_labels_fr = {
            "PERSON": "personne physique", "ORG": "organisation ou entreprise",
            "GPE": "lieu géopolitique", "LOC": "lieu géographique",
            "PRODUCT": "produit ou technologie", "EVENT": "événement",
        }
        label_fr = type_labels_fr.get(entity_type, entity_type.lower())

        info_text = ""
        rag_text = ""

        # Vérifier le cache avant tout appel IA
        try:
            from utils.synthesis_cache import get_synthesis_cache as _get_scache
            _scache = _get_scache(PROJECT_ROOT)
            _cached = _scache.get(entity_type, entity_value)
        except Exception:
            _cached = None
            _scache = None

        if _cached:
            info_text = _cached.get("info_text", "")
            rag_text  = _cached.get("rag_text", "")
            yield _evt({"type": "progress", "step": "info",
                        "message": "Synthèse chargée depuis le cache."})
        else:
            # Appel 1 : synthèse encyclopédique
            info_prompt = (
                f"Fournis une synthèse encyclopédique en français sur « {entity_value} » ({label_fr}).\n\n"
                "Structure ta réponse en Markdown avec des sections pertinentes "
                "(présentation, rôle, contexte, actualité récente, chiffres clés, "
                "liens avec d'autres acteurs…).\n"
                "Sois factuel et concis. Génère uniquement le contenu Markdown, "
                "sans balises <think>."
            )
            info_text = _call_ai_blocking(info_prompt, timeout=90, enable_web_search=True)

            # Appel 2 : analyse RAG multi-sources
            yield _evt({"type": "progress", "step": "rag",
                        "message": "Analyse comparative multi-sources (RAG)…"})

            if top_articles:
                sources_block = ""
                for i, a in enumerate(top_articles[:15], 1):
                    src    = a.get("Sources", "Source inconnue")
                    date   = a.get("Date de publication", "")
                    resume = (a.get("Résumé") or "")[:600]
                    sources_block += f"\n--- Article {i} ({src}, {date}) ---\n{resume}\n"

                rag_prompt = (
                    f"Tu es un analyste de presse. Voici {min(len(top_articles), 15)} articles "
                    f"de sources différentes traitant de : **{entity_value}**.\n\n"
                    "Génère une synthèse comparative structurée en Markdown comprenant :\n"
                    "1. **Résumé de la situation** (2-3 phrases)\n"
                    "2. **Points de convergence** entre les sources\n"
                    "3. **Points de divergence ou contradictions**\n"
                    "4. **Positionnement éditorial** : sources favorables, neutres ou critiques\n"
                    "5. **Éléments clés manquants**\n\n"
                    "Cite les sources (nom + date) à chaque point. Sois concis et factuel.\n"
                    "Génère uniquement le contenu Markdown, sans balises <think>.\n\n"
                    f"Articles :\n{sources_block}"
                )
                rag_text = _call_ai_blocking(rag_prompt, timeout=120)

            # Stocker dans le cache pour les prochaines requêtes
            if _scache and (info_text or rag_text):
                try:
                    _scache.set(entity_type, entity_value,
                                info_text=info_text, rag_text=rag_text)
                except Exception:
                    pass

        # ── Étape 4 : assemblage du contexte final ─────────────────────────
        yield _evt({"type": "progress", "step": "build",
                    "message": "Assemblage du contexte…"})

        type_labels = {
            "PERSON": "Personne", "ORG": "Organisation", "GPE": "Pays/Région",
            "LOC": "Lieu", "PRODUCT": "Produit", "EVENT": "Événement",
            "DATE": "Date", "MONEY": "Montant",
        }
        type_label = type_labels.get(entity_type, entity_type)

        ctx_lines: list[str] = [
            f"# Contexte entité : {entity_value} ({type_label})",
            f"Total articles trouvés : {len(articles)}",
            "",
        ]

        # Calendrier
        cal_lines = [f"  {m} : {c} article(s)"
                     for m, c in sorted(monthly.items(), reverse=True)[:12]]
        if cal_lines:
            ctx_lines.append("## Calendrier des mentions (derniers 12 mois)")
            ctx_lines.extend(cal_lines)
            ctx_lines.append("")

        # Co-occurrences
        if top_cooc:
            ctx_lines.append("## Entités co-occurrentes principales")
            for (etype, ev), count in top_cooc:
                lbl = type_labels.get(etype, etype)
                ctx_lines.append(f"  - {ev} ({lbl}) : {count} co-occurrence(s)")
            ctx_lines.append("")

        # Sentiments agrégés (calculés lors du passage co-occurrences)
        sentiments = sentiments_tmp
        sources_ctr = sources_tmp
        if sentiments:
            ctx_lines.append("## Tonalité éditoriale")
            for sent, cnt in sentiments.most_common():
                ctx_lines.append(f"  - {sent} : {cnt} article(s)")
            ctx_lines.append("")
        if sources_ctr:
            ctx_lines.append("## Sources principales")
            for src, cnt in sources_ctr.most_common(8):
                ctx_lines.append(f"  - {src} : {cnt} article(s)")
            ctx_lines.append("")

        # Synthèse encyclopédique IA
        if info_text:
            ctx_lines.append("## Synthèse encyclopédique (IA)")
            ctx_lines.append(info_text)
            ctx_lines.append("")

        # Analyse comparative RAG
        if rag_text:
            ctx_lines.append("## Analyse comparative multi-sources (RAG)")
            ctx_lines.append(rag_text)
            ctx_lines.append("")

        # Articles (résumés tronqués)
        if top_articles:
            ctx_lines.append(f"## Articles récents ({len(top_articles)} sur {len(articles)})")
            for i, art in enumerate(top_articles, 1):
                date   = art.get("Date de publication", "?")
                src    = art.get("Sources", "?")
                url    = art.get("URL", "")
                resume = (art.get("Résumé") or "").strip()
                if len(resume) > 500:
                    resume = resume[:500] + "…"
                header = f"### {i}. [{date}] {src}"
                if url:
                    header += f" — {url}"
                ctx_lines.append(header)
                if resume:
                    ctx_lines.append(resume)
                ctx_lines.append("")

        context_text = "\n".join(ctx_lines)

        yield _evt({
            "type":          "done",
            "entity_type":   entity_type,
            "entity_value":  entity_value,
            "article_count": len(articles),
            "has_info":      bool(info_text),
            "has_rag":       bool(rag_text),
            "context_text":  context_text,
        })

    return Response(
        stream_with_context(generate()),
        content_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@entities_bp.route("/api/entities/cooccurrences")
def api_entities_cooccurrences():
    """Retourne les entités co-occurrentes d'une entité donnée (via articles partagés).

    Utilise entity_index.load_articles() pour ne charger que les articles
    pertinents au lieu de scanner la totalité de data/.
    Fallback rglob si l'index est indisponible.

    Paramètres :
      type, value  — entité centrale
      limit        — max d'entités niveau 1 (défaut 40)
      depth        — profondeur du graphe : 1 ou 2 (défaut 1)
      limit_l2     — max d'entités niveau 2 par nœud L1 (défaut 4)
    """
    entity_type = request.args.get("type", "").strip()
    entity_value = request.args.get("value", "").strip()
    depth = min(int(request.args.get("depth", 1)), 2)
    # Quand depth=2 on réduit L1 pour garder le graphe lisible
    limit_l1 = min(int(request.args.get("limit", 40)), 100)
    if depth >= 2:
        limit_l1 = min(limit_l1, 12)
    limit_l2 = min(int(request.args.get("limit_l2", 4)), 15)
    # Filtre temporel : 0 = tout l'historique, sinon N derniers jours
    days_filter = max(0, int(request.args.get("days", 0)))

    if not entity_type or not entity_value:
        return jsonify({"error": "Paramètres type et value requis"}), 400

    canonicalizer = get_entity_canonicalizer(PROJECT_ROOT)
    entity_type, entity_value = canonicalizer.canonicalize(entity_type, entity_value)

    # ── Calcul de la date de coupure ──────────────────────────────────────────
    from datetime import datetime, timedelta, timezone
    cutoff_date_str = ""
    if days_filter > 0:
        cutoff_dt = datetime.now(timezone.utc) - timedelta(days=days_filter)
        cutoff_date_str = cutoff_dt.strftime("%Y-%m-%d")

    # ── Cache TTL : même requête → réponse instantanée pendant 10 min ─────────
    cache_key = (entity_type, entity_value.lower(), depth, limit_l1, limit_l2, days_filter)
    with _cooc_cache_lock:
        entry = _cooc_cache.get(cache_key)
        if entry is not None and (time.monotonic() - entry["ts"]) < _COOC_CACHE_TTL:
            return jsonify(entry["result"])

    def node_id(t, v):
        return f"{t}:{v}"

    # ── Chargement via entity_index (O(articles de l'entité) au lieu de O(tous les articles)) ──
    index_available = False
    eidx = None
    central_articles: list[dict] = []
    try:
        eidx = get_entity_index(PROJECT_ROOT)
        central_articles = eidx.load_articles(
            entity_type,
            entity_value,
            cutoff_date=cutoff_date_str,
            canonicalize=True,
        )
        index_available = True
    except Exception:
        pass

    if not index_available:
        # ── Fallback rglob si l'index est indisponible ────────────────────────
        target_key = canonicalizer.canonical_key(entity_type, entity_value)
        for data_dir in [PROJECT_ROOT / "data" / "articles",
                         PROJECT_ROOT / "data" / "articles-from-rss"]:
            if not data_dir.exists():
                continue
            for json_file in sorted(data_dir.rglob("*.json")):
                if "cache" in json_file.relative_to(data_dir).parts:
                    continue
                try:
                    arts = json.loads(json_file.read_text(encoding="utf-8", errors="replace"))
                    if not isinstance(arts, list):
                        continue
                    for art in arts:
                        # Filtre date fallback
                        if cutoff_date_str:
                            pub = art.get("Date de publication", "")
                            from utils.date_utils import parse_date
                            dt = parse_date(pub)
                            if dt and dt.strftime("%Y-%m-%d") < cutoff_date_str:
                                continue
                        ents = art.get("entities", {})
                        if not isinstance(ents, dict):
                            continue
                        matched = False
                        for etype, vals in ents.items():
                            if not isinstance(vals, list):
                                continue
                            if any(
                                isinstance(v, str)
                                and canonicalizer.canonical_key(etype, v) == target_key
                                for v in vals
                            ):
                                matched = True
                                break
                        if matched:
                            central_articles.append(art)
                except (json.JSONDecodeError, OSError):
                    continue

    # ── Passe 1 : co-occurrences L1 depuis les articles de l'entité centrale ──
    entity_value_lower = entity_value.lower()
    target_key = canonicalizer.canonical_key(entity_type, entity_value)
    cooc_l1: dict[tuple[str, str], int] = {}
    for article in central_articles:
        entities = article.get("entities", {})
        if not isinstance(entities, dict):
            continue
        for etype, evals in entities.items():
            if not isinstance(evals, list):
                continue
            for ev in evals:
                if not isinstance(ev, str) or not ev.strip():
                    continue
                if canonicalizer.is_noise(etype, ev):
                    continue
                canonical_type, canonical_value = canonicalizer.canonicalize(etype, ev)
                if canonicalizer.canonical_key(etype, ev) == target_key:
                    continue
                key = (canonical_type, canonical_value)
                cooc_l1[key] = cooc_l1.get(key, 0) + 1

    sorted_l1 = sorted(cooc_l1.items(), key=lambda x: x[1], reverse=True)[:limit_l1]
    top_l1_set: set[tuple[str, str]] = {k for k, _ in sorted_l1}

    # ── Batch total_count : une seule passe sur l'index pour tous les nœuds L1 ──
    def resolve_total_count(etype: str, ev: str, fallback: int) -> int:
        if not index_available or eidx is None:
            return fallback
        try:
            count_resolver = getattr(eidx, "get_canonical_ref_count", None)
            if callable(count_resolver):
                total = int(count_resolver(etype, ev))
            else:
                total = len(eidx.get_canonical_refs(etype, ev))
            if total > 0:
                return total
        except Exception:
            pass
        try:
            groups = eidx.search_values(
                ev,
                entity_type=etype,
                include_structural=etype in STRUCTURAL_ENTITY_TYPES,
                limit_per_type=25,
            )
            query_norm = canonicalizer.normalize_for_matching(ev)
            best = 0
            for group in groups:
                if str(group.get("type") or "").strip().upper() != etype:
                    continue
                top_items = group.get("top", [])
                if not isinstance(top_items, list):
                    continue
                for item in top_items:
                    candidate = str(item.get("value") or "").strip()
                    if not candidate:
                        continue
                    if canonicalizer.normalize_for_matching(candidate) != query_norm:
                        continue
                    best = max(best, int(item.get("count", 0)))
            if best > 0:
                return best
        except Exception:
            pass
        return fallback

    def batch_total_counts(keys: list[tuple[str, str]]) -> dict[tuple[str, str], int]:
        """Retourne {(type, value): total_count} pour tous les nœuds en une passe."""
        result: dict[tuple[str, str], int] = {}
        for etype, ev in keys:
            result[(etype, ev)] = resolve_total_count(etype, ev, cooc_l1.get((etype, ev), 0))
        return result

    l1_keys = [(etype, ev) for (etype, ev), _ in sorted_l1]
    total_counts = batch_total_counts(l1_keys)

    # ── Construction des nœuds / arêtes L1 ───────────────────────────────────
    central_total = len(central_articles)
    nodes = [{"type": entity_type, "value": entity_value, "count": 0,
               "central": True, "level": 0, "total_count": central_total}]
    edges = []

    for (etype, ev), count in sorted_l1:
        nodes.append({"type": etype, "value": ev, "count": count,
                       "central": False, "level": 1,
                       "total_count": total_counts.get((etype, ev), count)})
        edges.append({"source": node_id(entity_type, entity_value),
                       "target": node_id(etype, ev), "weight": count})

    # ── Passe 2 : co-occurrences L2 via entity_index ─────────────────────────
    if depth >= 2 and top_l1_set:
        existing: set[tuple[str, str]] = {(entity_type, entity_value)} | top_l1_set
        added_l2: set[tuple[str, str]] = set()

        for (l1_etype, l1_ev), _ in sorted_l1:
            # Charger uniquement les articles du nœud L1 (pas tous les articles)
            if index_available and eidx is not None:
                try:
                    l1_articles = eidx.load_articles(
                        l1_etype,
                        l1_ev,
                        cutoff_date=cutoff_date_str,
                        canonicalize=True,
                    )
                except Exception:
                    l1_articles = []
            else:
                # Fallback : réutiliser les articles déjà chargés (sous-ensemble)
                l1_ev_lower = l1_ev.lower()
                l1_articles = [
                    a for a in central_articles
                    if isinstance(a.get("entities", {}).get(l1_etype, []), list)
                    and any(
                        isinstance(v, str) and v.lower() == l1_ev_lower
                        for v in a["entities"].get(l1_etype, [])
                    )
                ]

            cooc_l2_for_l1: dict[tuple[str, str], int] = {}
            for article in l1_articles:
                entities = article.get("entities", {})
                if not isinstance(entities, dict):
                    continue
                for etype, evals in entities.items():
                    if not isinstance(evals, list):
                        continue
                    for ev in evals:
                        if not isinstance(ev, str) or not ev.strip():
                            continue
                        if canonicalizer.is_noise(etype, ev):
                            continue
                        canonical_type, canonical_value = canonicalizer.canonicalize(etype, ev)
                        co_key = (canonical_type, canonical_value)
                        if co_key == (l1_etype, l1_ev):
                            continue
                        if canonicalizer.canonical_key(etype, ev) == target_key:
                            continue  # évite l'arête de retour vers le centre
                        cooc_l2_for_l1[co_key] = cooc_l2_for_l1.get(co_key, 0) + 1

            top_for_l1 = sorted(
                [(k, c) for k, c in cooc_l2_for_l1.items() if k not in existing],
                key=lambda x: x[1],
                reverse=True,
            )[:limit_l2]

            for (etype, ev), count in top_for_l1:
                l2_key = (etype, ev)
                if l2_key not in added_l2:
                    l2_total = resolve_total_count(etype, ev, count)
                    nodes.append({"type": etype, "value": ev, "count": count,
                                   "central": False, "level": 2,
                                   "total_count": l2_total})
                    added_l2.add(l2_key)
                    existing.add(l2_key)
                edges.append({"source": node_id(l1_etype, l1_ev),
                               "target": node_id(etype, ev),
                               "weight": count})

    result = {
        "nodes": nodes,
        "edges": edges,
        "total_cooc": len(cooc_l1),
        "meta": {
            "days_filter": days_filter,
            "edge_weight_scope": "Poids calculé sur les articles co-occurrents dans la fenêtre courante.",
            "total_count_scope": "Couverture corpus du nœud sur l'index canonique; peut dépasser le poids local des arêtes.",
        },
    }
    with _cooc_cache_lock:
        _cooc_cache[cache_key] = {"result": result, "ts": time.monotonic()}
    return jsonify(result)


@entities_bp.route("/api/entities/dashboard/invalidate", methods=["POST"])
def api_entities_dashboard_invalidate():
    """Invalide les caches TTL du dashboard, co-occurrences et entités surveillées."""
    with _dashboard_cache_lock:
        _dashboard_cache.clear()
    with _cooc_cache_lock:
        _cooc_cache.clear()
    with _watched_cache_lock:
        _watched_cache.clear()
    return jsonify({"status": "ok", "message": "Cache dashboard invalidé"})


@entities_bp.route("/api/entities/geocode", methods=["POST"])
def api_entities_geocode():
    """Géocode une liste d'entités via Wikipedia API + Nominatim (polygons), avec cache JSON local.

    Format cache v2 : {"lat": float, "lon": float, "geojson": dict|null}
    Les entrées au format v1 {lat, lon} sans clé geojson sont remplacées à la prochaine requête.
    """
    import requests as req
    import time

    names = request.get_json(force=True) or []
    if not names or not isinstance(names, list):
        return jsonify({})

    # Limite le nombre de nouvelles entités geocodées par requête (évite les timeouts >30s).
    # Le frontend appelle l'endpoint en séquence jusqu'à ce que tout soit en cache.
    try:
        max_new = min(int(request.args.get("max_new", 25)), 60)
    except (ValueError, TypeError):
        max_new = 25

    # ── Coordonnées manuelles pour régions géopolitiques souvent mal reconnues ──
    def _rect(b):
        """Convertit [[sw_lat, sw_lon], [ne_lat, ne_lon]] en GeoJSON Polygon rectangle."""
        (s, w), (n, e) = b
        return {"type": "Polygon", "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]]}

    GEOCODE_OVERRIDES = {
        "moyen-orient":       {"lat": 29.0,  "lon": 41.0,  "geojson": None},
        "moyen orient":       {"lat": 29.0,  "lon": 41.0,  "geojson": None},
        "middle east":        {"lat": 29.0,  "lon": 41.0,  "geojson": None},
        "proche-orient":      {"lat": 33.5,  "lon": 36.0,  "geojson": None},
        "proche orient":      {"lat": 33.5,  "lon": 36.0,  "geojson": None},
        "golfe persique":     {"lat": 27.0,  "lon": 51.0,  "geojson": None},
        "péninsule arabique": {"lat": 24.0,  "lon": 45.0,  "geojson": None},
        "péninsule ibérique": {"lat": 40.0,  "lon": -4.0,  "geojson": None},
        "balkans":            {"lat": 42.5,  "lon": 21.0,  "geojson": None},
        "levant":             {"lat": 34.0,  "lon": 36.5,  "geojson": None},
        "indochine":          {"lat": 15.0,  "lon": 102.0, "geojson": None},
        "caucase":            {"lat": 42.0,  "lon": 44.0,  "geojson": None},
        # Continents — bounds pour le zoom uniquement (pas de rectangle GeoJSON)
        "europe":             {"lat": 54.5,  "lon": 15.3,  "bounds": [[35.0, -25.0], [72.0, 45.0]],     "geojson": None},
        "asie":               {"lat": 34.0,  "lon": 100.0, "bounds": [[-10.0, 26.0], [78.0, 180.0]],    "geojson": None},
        "asia":               {"lat": 34.0,  "lon": 100.0, "bounds": [[-10.0, 26.0], [78.0, 180.0]],    "geojson": None},
        "afrique":            {"lat": 1.0,   "lon": 17.0,  "bounds": [[-35.0, -20.0], [38.0, 52.0]],    "geojson": None},
        "africa":             {"lat": 1.0,   "lon": 17.0,  "bounds": [[-35.0, -20.0], [38.0, 52.0]],    "geojson": None},
        "amérique du nord":   {"lat": 54.5,  "lon": -105.0,"bounds": [[15.0, -170.0], [72.0, -52.0]],   "geojson": None},
        "amérique du sud":    {"lat": -14.0, "lon": -55.0, "bounds": [[-56.0, -82.0], [13.0, -35.0]],   "geojson": None},
        "amérique latine":    {"lat": -5.0,  "lon": -60.0, "bounds": [[-56.0, -120.0], [33.0, -35.0]],  "geojson": None},
        "océanie":            {"lat": -27.0, "lon": 133.0, "bounds": [[-47.0, 113.0], [-10.0, 180.0]],  "geojson": None},
        # Pays souvent mal résolus par Nominatim
        "royaume-uni":        {"lat": 55.4,  "lon": -3.4,  "geojson": None},
        "royaume uni":        {"lat": 55.4,  "lon": -3.4,  "geojson": None},
        "united kingdom":     {"lat": 55.4,  "lon": -3.4,  "geojson": None},
        "uk":                 {"lat": 55.4,  "lon": -3.4,  "geojson": None},
        "grande-bretagne":    {"lat": 55.4,  "lon": -3.4,  "geojson": None},
        "grande bretagne":    {"lat": 55.4,  "lon": -3.4,  "geojson": None},
        "etats-unis":         {"lat": 39.5,  "lon": -98.4, "geojson": None},
        "états-unis":         {"lat": 39.5,  "lon": -98.4, "geojson": None},
        "etats unis":         {"lat": 39.5,  "lon": -98.4, "geojson": None},
        "états unis":         {"lat": 39.5,  "lon": -98.4, "geojson": None},
        "united states":      {"lat": 39.5,  "lon": -98.4, "geojson": None},
        "usa":                {"lat": 39.5,  "lon": -98.4, "geojson": None},
    }

    cache_path = PROJECT_ROOT / "data" / "geocode_cache.json"
    cache = {}
    if cache_path.exists():
        try:
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            cache = {}

    # Invalider : entrées null + ancien format v1 sans clé 'geojson'
    cache = {k: v for k, v in cache.items() if v is not None and "geojson" in v}

    # Appliquer les overrides manuels (prioritaires sur tout).
    # Si un polygon est déjà en cache pour cet override, on le préserve.
    override_needs_polygon = []  # overrides avec geojson=None → Nominatim sera appelé
    for name in names:
        if name.lower() in GEOCODE_OVERRIDES:
            override = GEOCODE_OVERRIDES[name.lower()].copy()
            existing = cache.get(name, {})
            if override.get("geojson") is None and isinstance(existing, dict) and existing.get("geojson"):
                override["geojson"] = existing["geojson"]
            cache[name] = override
            if cache[name].get("geojson") is None:
                override_needs_polygon.append(name)

    to_fetch = [n for n in names if n not in cache][:max_new]

    WIKIPEDIA_UA = (
        "WUDD.ai/2.1.0 (news monitoring tool; "
        "https://github.com/patrickostertag) python-requests"
    )

    BATCH = 50
    for i in range(0, len(to_fetch), BATCH):
        batch = to_fetch[i : i + BATCH]
        titles_str = "|".join(batch)

        # ── Étape 1 : Wikipedia pour lat/lon ──────────────────────────────────
        wiki_coords: dict[str, dict] = {}
        for lang in ("fr", "en"):
            try:
                r = req.get(
                    f"https://{lang}.wikipedia.org/w/api.php",
                    params={
                        "action": "query",
                        "titles": titles_str,
                        "prop": "coordinates",
                        "format": "json",
                        "origin": "*",
                    },
                    headers={"User-Agent": WIKIPEDIA_UA},
                    timeout=10,
                )
                data = r.json()
                pages = data.get("query", {}).get("pages", {})
                normalized = {
                    n["from"]: n["to"]
                    for n in data.get("query", {}).get("normalized", [])
                }
                for page in pages.values():
                    if "coordinates" not in page:
                        continue
                    title = page.get("title", "")
                    coords = {
                        "lat": page["coordinates"][0]["lat"],
                        "lon": page["coordinates"][0]["lon"],
                    }
                    wiki_coords[title] = coords
                    for orig, norm in normalized.items():
                        if norm == title:
                            wiki_coords[orig] = coords
            except Exception:
                continue

            if lang == "fr" and len(wiki_coords) >= len(batch):
                break

        # ── Étape 2 : Nominatim — polygon + fallback lat/lon ──────────────────
        for name in batch:
            try:
                time.sleep(0.15)  # Respect Nominatim usage policy (max 1 req/s)
                nom_r = req.get(
                    "https://nominatim.openstreetmap.org/search",
                    params={
                        "q": name,
                        "format": "json",
                        "limit": 1,
                        "polygon_geojson": 1,
                        "polygon_threshold": "0.005",
                    },
                    headers={"User-Agent": WIKIPEDIA_UA},
                    timeout=12,
                )
                results = nom_r.json()
                if results:
                    geojson  = results[0].get("geojson")
                    nom_lat  = float(results[0]["lat"])
                    nom_lon  = float(results[0]["lon"])
                    # Ignorer les geojson de type Point (pas un polygone utile)
                    if geojson and geojson.get("type") == "Point":
                        geojson = None
                    # Ignorer les bbox rectangles Nominatim (Polygon 5 pts, 2 lon × 2 lat)
                    if geojson and geojson.get("type") == "Polygon":
                        ring = geojson.get("coordinates", [[]])[0]
                        if len(ring) == 5:
                            lons = {round(p[0], 4) for p in ring}
                            lats = {round(p[1], 4) for p in ring}
                            if len(lons) == 2 and len(lats) == 2:
                                geojson = None
                    # Wikipedia plus précis pour le point central ; Nominatim fournit le polygon
                    if name in wiki_coords:
                        cache[name] = {
                            "lat": wiki_coords[name]["lat"],
                            "lon": wiki_coords[name]["lon"],
                            "geojson": geojson,
                        }
                    else:
                        cache[name] = {"lat": nom_lat, "lon": nom_lon, "geojson": geojson}
                    continue
            except Exception:
                pass

            # Nominatim échoué : utiliser Wikipedia si disponible
            if name in wiki_coords:
                cache[name] = {**wiki_coords[name], "geojson": None}
            # Sinon ne pas stocker → sera retenté à la prochaine requête

    # ── Fetch polygon Nominatim pour les overrides sans geojson ───────────────
    # (continents, grandes régions : bounds définis mais polygon absent)
    for name in override_needs_polygon:
        try:
            time.sleep(0.15)
            nom_r = req.get(
                "https://nominatim.openstreetmap.org/search",
                params={
                    "q": name,
                    "format": "json",
                    "limit": 1,
                    "polygon_geojson": 1,
                    "polygon_threshold": "0.005",
                },
                headers={"User-Agent": WIKIPEDIA_UA},
                timeout=12,
            )
            results = nom_r.json()
            if results:
                geojson = results[0].get("geojson")
                if geojson and geojson.get("type") != "Point":
                    cache[name] = {**cache[name], "geojson": geojson}
        except Exception:
            pass

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    return jsonify({n: cache.get(n) for n in names})


@entities_bp.route("/api/entities/geocode/stream", methods=["POST"])
def api_entities_geocode_stream():
    """Version SSE du géocodage — yield chaque entité dès qu'elle est résolue.

    Le frontend peut afficher les marqueurs au fur et à mesure sans attendre
    la fin du géocodage.
    Format SSE : data: {name, lat, lon, geojson, bounds?}\n\n
    Événement terminal : data: {type: "done", saved: N}\n\n
    """
    import requests as req
    import time

    names = request.get_json(force=True) or []
    if not names or not isinstance(names, list):
        return jsonify({})

    def _is_bbox_rect(geo):
        """Retourne True si geo est un rectangle bbox Nominatim (Polygon 5 pts, 2 lon × 2 lat)."""
        if not geo or geo.get("type") != "Polygon":
            return False
        ring = geo.get("coordinates", [[]])[0]
        if len(ring) != 5:
            return False
        lons = {round(p[0], 4) for p in ring}
        lats = {round(p[1], 4) for p in ring}
        return len(lons) == 2 and len(lats) == 2

    WIKIPEDIA_UA = (
        "WUDD.ai/2.1.0 (news monitoring tool; "
        "https://github.com/patrickostertag) python-requests"
    )

    # Overrides manuels (continents, régions géopolitiques) — identiques à api_entities_geocode
    GEOCODE_OVERRIDES = {
        "moyen-orient":       {"lat": 29.0,  "lon": 41.0,  "geojson": None},
        "moyen orient":       {"lat": 29.0,  "lon": 41.0,  "geojson": None},
        "middle east":        {"lat": 29.0,  "lon": 41.0,  "geojson": None},
        "proche-orient":      {"lat": 33.5,  "lon": 36.0,  "geojson": None},
        "proche orient":      {"lat": 33.5,  "lon": 36.0,  "geojson": None},
        "golfe persique":     {"lat": 27.0,  "lon": 51.0,  "geojson": None},
        "péninsule arabique": {"lat": 24.0,  "lon": 45.0,  "geojson": None},
        "péninsule ibérique": {"lat": 40.0,  "lon": -4.0,  "geojson": None},
        "balkans":            {"lat": 42.5,  "lon": 21.0,  "geojson": None},
        "levant":             {"lat": 34.0,  "lon": 36.5,  "geojson": None},
        "indochine":          {"lat": 15.0,  "lon": 102.0, "geojson": None},
        "caucase":            {"lat": 42.0,  "lon": 44.0,  "geojson": None},
        "europe":             {"lat": 54.5,  "lon": 15.3,  "bounds": [[35.0, -25.0], [72.0, 45.0]],     "geojson": None},
        "asie":               {"lat": 34.0,  "lon": 100.0, "bounds": [[-10.0, 26.0], [78.0, 180.0]],    "geojson": None},
        "asia":               {"lat": 34.0,  "lon": 100.0, "bounds": [[-10.0, 26.0], [78.0, 180.0]],    "geojson": None},
        "afrique":            {"lat": 1.0,   "lon": 17.0,  "bounds": [[-35.0, -20.0], [38.0, 52.0]],    "geojson": None},
        "africa":             {"lat": 1.0,   "lon": 17.0,  "bounds": [[-35.0, -20.0], [38.0, 52.0]],    "geojson": None},
        "amérique du nord":   {"lat": 54.5,  "lon": -105.0,"bounds": [[15.0, -170.0], [72.0, -52.0]],   "geojson": None},
        "amérique du sud":    {"lat": -14.0, "lon": -55.0, "bounds": [[-56.0, -82.0], [13.0, -35.0]],   "geojson": None},
        "amérique latine":    {"lat": -5.0,  "lon": -60.0, "bounds": [[-56.0, -120.0], [33.0, -35.0]],  "geojson": None},
        "océanie":            {"lat": -27.0, "lon": 133.0, "bounds": [[-47.0, 113.0], [-10.0, 180.0]],  "geojson": None},
        "royaume-uni":        {"lat": 55.4,  "lon": -3.4,  "geojson": None},
        "royaume uni":        {"lat": 55.4,  "lon": -3.4,  "geojson": None},
        "united kingdom":     {"lat": 55.4,  "lon": -3.4,  "geojson": None},
        "uk":                 {"lat": 55.4,  "lon": -3.4,  "geojson": None},
        "grande-bretagne":    {"lat": 55.4,  "lon": -3.4,  "geojson": None},
        "grande bretagne":    {"lat": 55.4,  "lon": -3.4,  "geojson": None},
        "etats-unis":         {"lat": 39.5,  "lon": -98.4, "geojson": None},
        "états-unis":         {"lat": 39.5,  "lon": -98.4, "geojson": None},
        "etats unis":         {"lat": 39.5,  "lon": -98.4, "geojson": None},
        "états unis":         {"lat": 39.5,  "lon": -98.4, "geojson": None},
        "united states":      {"lat": 39.5,  "lon": -98.4, "geojson": None},
        "usa":                {"lat": 39.5,  "lon": -98.4, "geojson": None},
    }

    cache_path = PROJECT_ROOT / "data" / "geocode_cache.json"

    def generate():
        # ── Chargement du cache ──────────────────────────────────────────────
        cache = {}
        if cache_path.exists():
            try:
                cache = json.loads(cache_path.read_text(encoding="utf-8"))
            except Exception:
                cache = {}
        cache = {k: v for k, v in cache.items() if v is not None and "geojson" in v}

        # Appliquer les overrides (préserver polygon existant si présent)
        for name in names:
            if name.lower() in GEOCODE_OVERRIDES:
                override = GEOCODE_OVERRIDES[name.lower()].copy()
                existing = cache.get(name, {})
                if override.get("geojson") is None and isinstance(existing, dict) and existing.get("geojson"):
                    override["geojson"] = existing["geojson"]
                cache[name] = override

        # ── Yield immédiat des entrées déjà en cache ─────────────────────────
        to_fetch = []
        for name in names:
            if name in cache and cache[name].get("lat") is not None:
                yield f"data: {json.dumps({'name': name, **cache[name]}, ensure_ascii=False)}\n\n"
            else:
                to_fetch.append(name)

        if not to_fetch:
            yield f'data: {{"type": "done", "saved": 0}}\n\n'
            return

        # ── Wikipedia : coordonnées en lot ───────────────────────────────────
        wiki_coords: dict = {}
        BATCH = 50
        for i in range(0, len(to_fetch), BATCH):
            batch_names = to_fetch[i: i + BATCH]
            titles_str = "|".join(batch_names)
            for lang in ("fr", "en"):
                try:
                    r = req.get(
                        f"https://{lang}.wikipedia.org/w/api.php",
                        params={
                            "action": "query",
                            "titles": titles_str,
                            "prop": "coordinates",
                            "format": "json",
                            "origin": "*",
                        },
                        headers={"User-Agent": WIKIPEDIA_UA},
                        timeout=10,
                    )
                    data = r.json()
                    pages = data.get("query", {}).get("pages", {})
                    normalized = {
                        n["from"]: n["to"]
                        for n in data.get("query", {}).get("normalized", [])
                    }
                    for page in pages.values():
                        if "coordinates" not in page:
                            continue
                        title = page.get("title", "")
                        c = {
                            "lat": page["coordinates"][0]["lat"],
                            "lon": page["coordinates"][0]["lon"],
                        }
                        wiki_coords[title] = c
                        for orig, norm in normalized.items():
                            if norm == title:
                                wiki_coords[orig] = c
                except Exception:
                    continue
                if lang == "fr" and len(wiki_coords) >= len(batch_names):
                    break

        # ── Nominatim : polygon, un par un — yield immédiat à chaque résultat ─
        saved = 0
        for name in to_fetch:
            result = None
            try:
                time.sleep(0.15)  # Respect Nominatim usage policy
                nom_r = req.get(
                    "https://nominatim.openstreetmap.org/search",
                    params={
                        "q": name,
                        "format": "json",
                        "limit": 1,
                        "polygon_geojson": 1,
                        "polygon_threshold": "0.005",
                    },
                    headers={"User-Agent": WIKIPEDIA_UA},
                    timeout=12,
                )
                results = nom_r.json()
                if results:
                    geojson  = results[0].get("geojson")
                    nom_lat  = float(results[0]["lat"])
                    nom_lon  = float(results[0]["lon"])
                    if geojson and geojson.get("type") == "Point":
                        geojson = None
                    if _is_bbox_rect(geojson):
                        geojson = None
                    if name in wiki_coords:
                        result = {"lat": wiki_coords[name]["lat"], "lon": wiki_coords[name]["lon"], "geojson": geojson}
                    else:
                        result = {"lat": nom_lat, "lon": nom_lon, "geojson": geojson}
            except Exception:
                pass

            if result is None and name in wiki_coords:
                result = {**wiki_coords[name], "geojson": None}

            if result:
                cache[name] = result
                saved += 1
                yield f"data: {json.dumps({'name': name, **result}, ensure_ascii=False)}\n\n"

        # ── Sauvegarde du cache ──────────────────────────────────────────────
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(
                json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception:
            pass

        yield f'data: {{"type": "done", "saved": {saved}}}\n\n'

    return Response(
        stream_with_context(generate()),
        content_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@entities_bp.route("/api/entities/images", methods=["POST"])
def api_entities_images():
    """Récupère les images Wikipedia d'une liste d'entités.

    Accepte [{name, type}] ou [str] (compat. ascendante).
    Stratégie :
      - PERSON               → Wikipedia pageimages (portrait)
      - ORG / PRODUCT        → Wikidata P154 (logo officiel) + fallback pageimages
      - autres / inconnus    → Wikipedia pageimages
    """
    import requests as req

    body = request.get_json(force=True) or []
    if not body or not isinstance(body, list):
        return jsonify({})

    # Normalise l'entrée en [{name, type}]
    entities: list[dict] = []
    for item in body:
        if isinstance(item, dict):
            entities.append({"name": item.get("name", "").strip(), "type": item.get("type", "").upper()})
        elif isinstance(item, str):
            entities.append({"name": item.strip(), "type": ""})
    entities = [e for e in entities if e["name"]]

    UA = "WUDD.ai/2.1.0 (news monitoring tool; https://github.com/patrickostertag) python-requests"
    THUMB = 200
    BATCH = 50

    cache_path = PROJECT_ROOT / "data" / "images_cache.json"

    # Chargement unique en mémoire — évite de lire/parser 400 KB à chaque requête
    global _images_cache_mem
    with _images_cache_mem_lock:
        if _images_cache_mem is None:
            _tmp: dict = {}
            if cache_path.exists():
                try:
                    _tmp = json.loads(cache_path.read_text(encoding="utf-8"))
                except Exception:
                    pass
            _images_cache_mem = _tmp
        # Snapshot thread-safe pour cette requête
        cache: dict = dict(_images_cache_mem)

    # Les PRODUCT avec null en cache sont re-tentés (stratégie de fetch modifiée)
    to_fetch = [
        e for e in entities
        if e["name"] not in cache
        or (cache.get(e["name"]) is None and e["type"] == "PRODUCT")
    ]
    if not to_fetch:
        return jsonify({e["name"]: cache.get(e["name"]) for e in entities})

    # ── Séparer PERSON vs ORG vs PRODUCT vs autres ─────────────────────────────
    person_names  = [e["name"] for e in to_fetch if e["type"] == "PERSON"]
    logo_names    = [e["name"] for e in to_fetch if e["type"] == "ORG"]
    product_names = [e["name"] for e in to_fetch if e["type"] == "PRODUCT"]
    other_names   = [e["name"] for e in to_fetch if e["type"] not in ("PERSON", "ORG", "PRODUCT")]

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _pageimages(names_batch: list[str]) -> dict[str, dict]:
        """Retourne {name: {url,width,height}} via Wikipedia pageimages."""
        result: dict[str, dict] = {}
        for i in range(0, len(names_batch), BATCH):
            batch = names_batch[i : i + BATCH]
            titles_str = "|".join(batch)
            for lang in ("fr", "en"):
                try:
                    r = req.get(
                        f"https://{lang}.wikipedia.org/w/api.php",
                        params={"action": "query", "titles": titles_str,
                                "prop": "pageimages", "pithumbsize": THUMB,
                                "pilicense": "any", "format": "json", "origin": "*"},
                        headers={"User-Agent": UA}, timeout=10,
                    )
                    pages = r.json().get("query", {})
                    normalized = {n["from"]: n["to"] for n in pages.get("normalized", [])}
                    for page in pages.get("pages", {}).values():
                        if "thumbnail" not in page:
                            continue
                        title = page["title"]
                        img = {"url": page["thumbnail"]["source"],
                               "width": page["thumbnail"].get("width", THUMB),
                               "height": page["thumbnail"].get("height", THUMB)}
                        result[title] = img
                        for orig, norm in normalized.items():
                            if norm == title:
                                result[orig] = img
                except Exception:
                    continue
                if lang == "fr" and len(result) >= len(batch):
                    break
        return result

    def _wikidata_logos(names_batch: list[str]) -> tuple[dict[str, str], set[str]]:
        """Retourne ({name: image_filename}, rejected) via Wikidata P154 puis P18."""
        logos: dict[str, str] = {}
        rejected: set[str] = set()
        P154 = "P154"
        P18  = "P18"

        HARD_WRONG = {
            "Q5", "Q202444", "Q101352", "Q11266439",
        }
        SOFT_WRONG = {
            "Q4167410", "Q50339617",
        }
        WRONG_TYPES = HARD_WRONG | SOFT_WRONG
        OK_TYPES = {
            "Q4830453", "Q783794", "Q891723", "Q43229", "Q167037",
            "Q7397", "Q166142", "Q9143", "Q9135", "Q7889",
            "Q18127206", "Q18662854", "Q1331793", "Q17155032",
            "Q3220391", "Q122759350", "Q6576792", "Q118140435",
        }

        def _filename(claim_value) -> str:
            if isinstance(claim_value, str):
                return claim_value
            return claim_value.get("value", "") if isinstance(claim_value, dict) else ""

        for i in range(0, len(names_batch), BATCH):
            batch = names_batch[i : i + BATCH]
            titles_str = "|".join(batch)
            for site in ("enwiki", "frwiki"):
                try:
                    r = req.get(
                        "https://www.wikidata.org/w/api.php",
                        params={"action": "wbgetentities", "sites": site,
                                "titles": titles_str, "props": "claims|sitelinks",
                                "format": "json", "origin": "*"},
                        headers={"User-Agent": UA}, timeout=10,
                    )
                    for eid, entity in r.json().get("entities", {}).items():
                        if eid.startswith("-"):
                            continue
                        wiki_title = entity.get("sitelinks", {}).get(site, {}).get("title", "")
                        claims = entity.get("claims", {})
                        p31_ids = {
                            claim["mainsnak"]["datavalue"]["value"]["id"]
                            for claim in claims.get("P31", [])
                            if claim["mainsnak"].get("datavalue")
                        }
                        for orig in batch:
                            if orig.lower() == wiki_title.lower() and orig not in logos and orig not in rejected:
                                if p31_ids & HARD_WRONG:
                                    rejected.add(orig)
                                elif p31_ids & SOFT_WRONG:
                                    break
                                elif P154 in claims:
                                    logos[orig] = _filename(claims[P154][0]["mainsnak"]["datavalue"]["value"])
                                elif P18 in claims and p31_ids & OK_TYPES:
                                    logos[orig] = _filename(claims[P18][0]["mainsnak"]["datavalue"]["value"])
                                elif p31_ids & OK_TYPES:
                                    pass
                                else:
                                    break
                                break
                except Exception:
                    continue
        return logos, rejected

    def _wikidata_p18_persons(names_batch: list[str], require_human: bool = False) -> dict[str, str]:
        """Retourne {name: image_filename} via Wikidata P18 pour les PERSON.

        Si require_human=True, n'accepte que les entités dont P31 contient Q5
        (humain), évitant de retourner des images de plats homonymes (ex. poutine).
        """
        logos: dict[str, str] = {}
        P18 = "P18"
        for i in range(0, len(names_batch), BATCH):
            batch = names_batch[i : i + BATCH]
            titles_str = "|".join(batch)
            for site in ("enwiki", "frwiki"):
                try:
                    r = req.get(
                        "https://www.wikidata.org/w/api.php",
                        params={"action": "wbgetentities", "sites": site,
                                "titles": titles_str, "props": "claims|sitelinks",
                                "format": "json", "origin": "*"},
                        headers={"User-Agent": UA}, timeout=10,
                    )
                    for eid, entity in r.json().get("entities", {}).items():
                        if eid.startswith("-"):
                            continue
                        wiki_title = entity.get("sitelinks", {}).get(site, {}).get("title", "")
                        claims = entity.get("claims", {})
                        if require_human:
                            p31 = {
                                c["mainsnak"]["datavalue"]["value"]["id"]
                                for c in claims.get("P31", [])
                                if c["mainsnak"].get("datavalue")
                            }
                            # Rejeter si P31 est défini mais ne contient pas Q5 (humain)
                            if p31 and "Q5" not in p31:
                                continue
                        if P18 not in claims:
                            continue
                        for orig in batch:
                            if orig.lower() == wiki_title.lower() and orig not in logos:
                                val = claims[P18][0]["mainsnak"]["datavalue"]["value"]
                                fname = val if isinstance(val, str) else val.get("value", "")
                                if fname:
                                    logos[orig] = fname
                                break
                except Exception:
                    continue
        return logos

    def _resolve_logo_urls(filenames: list[str]) -> dict[str, str]:
        """Retourne {filename: url_miniature} depuis Wikimedia Commons."""
        urls: dict[str, str] = {}
        for i in range(0, len(filenames), BATCH):
            batch = filenames[i : i + BATCH]
            titles = "|".join(f"File:{f}" for f in batch)
            try:
                r = req.get(
                    "https://commons.wikimedia.org/w/api.php",
                    params={"action": "query", "titles": titles,
                            "prop": "imageinfo", "iiprop": "url",
                            "iiurlwidth": THUMB, "format": "json", "origin": "*"},
                    headers={"User-Agent": UA}, timeout=10,
                )
                for page in r.json().get("query", {}).get("pages", {}).values():
                    fname = page.get("title", "").removeprefix("File:")
                    info = page.get("imageinfo", [])
                    if info:
                        url = info[0].get("thumburl") or info[0].get("url")
                        if url:
                            urls[fname] = url
            except Exception:
                pass
        return urls

    def _pageimages_persons(names_batch: list[str]) -> dict[str, dict]:
        """Comme _pageimages mais valide que la page Wikipedia est une personne (P31=Q5).

        Effectue un appel Wikidata groupé pour vérifier les instances afin d'éviter
        de retourner l'image d'un plat (ex. poutine) pour une personne homonyme.
        """
        result: dict[str, dict] = {}
        for i in range(0, len(names_batch), BATCH):
            batch = names_batch[i : i + BATCH]
            titles_str = "|".join(batch)
            for lang in ("fr", "en"):
                try:
                    r = req.get(
                        f"https://{lang}.wikipedia.org/w/api.php",
                        params={"action": "query", "titles": titles_str,
                                "prop": "pageimages|pageprops", "pithumbsize": THUMB,
                                "pilicense": "any", "ppprop": "wikibase_item",
                                "format": "json", "origin": "*"},
                        headers={"User-Agent": UA}, timeout=10,
                    )
                    pages_data = r.json().get("query", {})
                    normalized = {n["from"]: n["to"] for n in pages_data.get("normalized", [])}
                    pages_list = list(pages_data.get("pages", {}).values())

                    # Validation Wikidata en batch : accepter seulement les humains (Q5)
                    qids = [p.get("pageprops", {}).get("wikibase_item", "") for p in pages_list]
                    batch_qids = [q for q in qids if q]
                    valid_qids: set[str] = set()
                    if batch_qids:
                        try:
                            r2 = req.get(
                                "https://www.wikidata.org/w/api.php",
                                params={"action": "wbgetentities",
                                        "ids": "|".join(batch_qids),
                                        "props": "claims", "format": "json", "origin": "*"},
                                headers={"User-Agent": UA}, timeout=10,
                            )
                            for qid, entity in r2.json().get("entities", {}).items():
                                if qid.startswith("-"):
                                    continue
                                p31 = {
                                    c["mainsnak"]["datavalue"]["value"]["id"]
                                    for c in entity.get("claims", {}).get("P31", [])
                                    if c["mainsnak"].get("datavalue")
                                }
                                # Accepter : pas de P31 (ambigu) OU P31 contient Q5 (humain)
                                if not p31 or "Q5" in p31:
                                    valid_qids.add(qid)
                        except Exception:
                            valid_qids.update(batch_qids)  # erreur réseau → accepter

                    for page in pages_list:
                        if "thumbnail" not in page:
                            continue
                        qid = page.get("pageprops", {}).get("wikibase_item", "")
                        if qid and qid not in valid_qids:
                            continue  # page n'est pas une personne (P31 ≠ Q5)
                        title = page["title"]
                        img = {"url": page["thumbnail"]["source"],
                               "width": page["thumbnail"].get("width", THUMB),
                               "height": page["thumbnail"].get("height", THUMB)}
                        result[title] = img
                        for orig, norm in normalized.items():
                            if norm == title:
                                result[orig] = img
                except Exception:
                    continue
                if lang == "fr" and len(result) >= len(batch):
                    break
        return result

    SEARCH_WRONG = {
        "Q5", "Q202444", "Q101352", "Q4167410", "Q11266439", "Q50339617",
        "Q4086834", "Q35234", "Q12503", "Q8091", "Q1298765", "Q17451",
        "Q58481926", "Q8171", "Q58778", "Q82042", "Q16521", "Q89", "Q1364",
    }

    def _wikidata_type_ok(qid: str, strict: bool = False) -> bool:
        if not qid:
            return not strict
        try:
            r2 = req.get(
                "https://www.wikidata.org/w/api.php",
                params={"action": "wbgetentities", "ids": qid,
                        "props": "claims", "format": "json", "origin": "*"},
                headers={"User-Agent": UA}, timeout=5,
            )
            claims = r2.json().get("entities", {}).get(qid, {}).get("claims", {})
            p31_ids = {
                c["mainsnak"]["datavalue"]["value"]["id"]
                for c in claims.get("P31", [])
                if c["mainsnak"].get("datavalue")
            }
            if strict and not p31_ids:
                return False
            return not bool(p31_ids & SEARCH_WRONG)
        except Exception:
            return True

    def _search_pageimage_single(name: str, entity_type: str = "") -> tuple[str, dict | None]:
        """Fallback final : recherche Wikipedia generator=search avec validation de type."""
        langs = ("fr", "en")
        validate = entity_type in ("ORG", "PRODUCT")
        require_human = entity_type == "PERSON"
        name_tokens = [token for token in name.strip().split() if token]
        # Pour les PERSON avec un seul token (ex. "Claude"), on évite le fallback
        # search pour ne pas figer des homonymes très ambigus dans le cache.
        if require_human and len(name_tokens) <= 1:
            return name, None
        # Augmenter le nombre de résultats pour les personnes (la 1ère entrée peut être un homonyme)
        gsrlimit = 5 if require_human else 3

        for lang in langs:
            try:
                r = req.get(
                    f"https://{lang}.wikipedia.org/w/api.php",
                    params={
                        "action": "query",
                        "generator": "search",
                        "gsrsearch": name,
                        "gsrlimit": gsrlimit,
                        "prop": "pageimages|pageprops",
                        "pithumbsize": THUMB,
                        "pilicense": "any",
                        "ppprop": "wikibase_item",
                        "format": "json",
                        "origin": "*",
                    },
                    headers={"User-Agent": UA},
                    timeout=8,
                )
                pages = r.json().get("query", {}).get("pages", {})
                for page in sorted(pages.values(), key=lambda p: p.get("index", 0)):
                    qid = page.get("pageprops", {}).get("wikibase_item", "")
                    if validate:
                        if not _wikidata_type_ok(qid, strict=True):
                            continue
                    elif require_human:
                        if not qid:
                            continue
                        try:
                            r2 = req.get(
                                "https://www.wikidata.org/w/api.php",
                                params={"action": "wbgetentities", "ids": qid,
                                        "props": "claims", "format": "json", "origin": "*"},
                                headers={"User-Agent": UA}, timeout=5,
                            )
                            p31 = {
                                c["mainsnak"]["datavalue"]["value"]["id"]
                                for c in r2.json().get("entities", {}).get(qid, {})
                                         .get("claims", {}).get("P31", [])
                                if c["mainsnak"].get("datavalue")
                            }
                            if "Q5" not in p31:
                                continue  # pas une personne (Q5 = humain)
                        except Exception:
                            continue  # erreur réseau → ignorer ce candidat

                    thumb = page.get("thumbnail")
                    if thumb and thumb.get("source"):
                        return name, {
                            "url": thumb["source"],
                            "width": thumb.get("width", THUMB),
                            "height": thumb.get("height", THUMB),
                        }
            except Exception:
                continue
        return name, None

    # ── PERSON : pageimages avec validation P31=Q5 (évite les homonymes type plats) ──
    pageimg_persons = _pageimages_persons(person_names) if person_names else {}
    for name in person_names:
        if name not in cache:
            cache[name] = pageimg_persons.get(name)

    # ── PRODUCT & autres : pageimages standard ──
    pageimg = _pageimages(product_names + other_names) if (product_names or other_names) else {}
    for name in product_names + other_names:
        if name not in cache:
            cache[name] = pageimg.get(name)

    # Fallback Wikidata P18 pour les PERSON sans image Wikipedia (avec validation P31=Q5)
    persons_no_img = [n for n in person_names if not cache.get(n)]
    if persons_no_img:
        p18_files = _wikidata_p18_persons(persons_no_img, require_human=True)
        if p18_files:
            p18_urls = _resolve_logo_urls(list(set(p18_files.values())))
            for name, fname in p18_files.items():
                if name not in cache or not cache[name]:
                    url = p18_urls.get(fname)
                    cache[name] = {"url": url, "width": THUMB, "height": THUMB} if url else None

    # Fallback Wikidata P18 pour les PRODUCT sans image Wikipedia
    products_no_img = [n for n in product_names if not cache.get(n)]
    if products_no_img:
        p18_files = _wikidata_p18_persons(products_no_img)
        if p18_files:
            p18_urls = _resolve_logo_urls(list(set(p18_files.values())))
            for name, fname in p18_files.items():
                if name not in cache or not cache[name]:
                    url = p18_urls.get(fname)
                    cache[name] = {"url": url, "width": THUMB, "height": THUMB} if url else None

    # ── ORG / PRODUCT : Wikidata P154/P18 → sinon _search_pageimage_single ──
    if logo_names:
        wikidata, rejected = _wikidata_logos(logo_names)
        resolved = _resolve_logo_urls(list(set(wikidata.values()))) if wikidata else {}
        for name in logo_names:
            if name not in cache:
                logo_file = wikidata.get(name)
                if logo_file and logo_file in resolved:
                    cache[name] = {"url": resolved[logo_file], "width": THUMB, "height": THUMB}
                elif name in rejected:
                    cache[name] = None

    # ── Fallback final : Wikipedia generator=search pour toutes les entités sans image ──
    SEARCH_LIMIT = 25
    _rejected = rejected if logo_names else set()
    _type_map = {e["name"]: e["type"] for e in to_fetch}
    null_entities = [
        name for name in (person_names + product_names + logo_names + other_names)
        if not cache.get(name) and name not in _rejected
    ][:SEARCH_LIMIT]
    if null_entities:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        with ThreadPoolExecutor(max_workers=6) as pool:
            futures = {
                pool.submit(_search_pageimage_single, name, _type_map.get(name, "")): name
                for name in null_entities
            }
            for future in as_completed(futures):
                try:
                    name, result = future.result()
                    if result and not cache.get(name):
                        cache[name] = result
                except Exception:
                    pass

    # Stocker None pour les entités sans image — évite de les retenter à chaque requête
    for e in to_fetch:
        if e["name"] not in cache:
            cache[e["name"]] = None

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with _images_cache_mem_lock:
        _images_cache_mem.update(cache)
        cache_path.write_text(json.dumps(_images_cache_mem, ensure_ascii=False, indent=2), encoding="utf-8")

    return jsonify({e["name"]: cache.get(e["name"]) for e in entities})


@entities_bp.route("/api/entities/info")
def api_entities_info():
    """Génère en streaming une synthèse encyclopédique sur une entité (EurIA ou Claude)."""
    import requests as req

    entity_type  = request.args.get("type",  "").strip()
    entity_value = request.args.get("value", "").strip()
    if not entity_type or not entity_value:
        return jsonify({"error": "Paramètres type et value requis"}), 400

    provider = os.environ.get("AI_PROVIDER", "euria").strip().lower()

    type_labels = {
        "PERSON":      "personne physique",
        "ORG":         "organisation ou entreprise",
        "GPE":         "lieu géopolitique",
        "LOC":         "lieu géographique",
        "PRODUCT":     "produit ou technologie",
        "EVENT":       "événement",
        "WORK_OF_ART": "œuvre",
        "LAW":         "loi ou règlement",
        "NORP":        "groupe national, religieux ou politique",
        "FAC":         "site ou bâtiment",
    }
    label = type_labels.get(entity_type, entity_type.lower())

    prompt = (
        f"Fournis une synthèse encyclopédique en français sur « {entity_value} » ({label}).\n\n"
        "Structure ta réponse en Markdown avec des sections pertinentes "
        "(présentation, rôle, contexte, actualité récente, chiffres clés, liens avec d'autres acteurs…).\n"
        "Sois factuel et concis. Génère uniquement le contenu Markdown, sans balises <think>."
    )

    if provider == "claude":
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            return jsonify({"error": "ANTHROPIC_API_KEY manquante dans .env (AI_PROVIDER=claude)"}), 503
        from utils.api_client import ClaudeClient as _ClaudeClient
        _claude = _ClaudeClient(api_key=api_key)

        def generate():
            yield from _claude.stream(prompt=prompt, timeout=90)

    else:
        api_url = os.environ.get("URL", "")
        bearer  = os.environ.get("bearer", "")
        if not api_url or not bearer:
            return jsonify({"error": "URL ou bearer manquant dans .env (AI_PROVIDER=euria)"}), 503
        from utils.api_client import EurIAClient as _EC
        _euria = _EC(url=api_url, bearer=bearer)

        def generate():
            yield from _euria.stream(prompt=prompt, timeout=90, enable_web_search=True)

    return Response(
        stream_with_context(generate()),
        content_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@entities_bp.route("/api/entities/timeline")
def api_entities_timeline():
    """Série chronologique des mentions d'entités.

    Query params :
      days       : fenêtre temporelle en jours (défaut 30)
      top        : nombre d'entités (défaut 30)
      entity     : filtrer sur une valeur d'entité
      type       : filtrer sur un type d'entité (PERSON, ORG…)
      regenerate : si "1", force le recalcul (sinon utilise le cache JSON)
    """
    import time as _time
    import sys as _sys
    try:
        days       = int(request.args.get("days", 30))
        top_n      = int(request.args.get("top", 30))
        entity     = request.args.get("entity") or None
        etype      = request.args.get("type")   or None
        include_structural = request.args.get("include_structural", "0").strip().lower() in {"1", "true", "yes", "on"}
        include_structural = include_structural or (etype or "").strip().upper() in STRUCTURAL_ENTITY_TYPES
        match_mode = normalize_match_mode(
            request.args.get("match_mode"),
            default=default_timeline_match_mode(),
        )
        all_types  = request.args.get("all_types", "0").strip().lower() in {"1", "true", "yes", "on"}
        regenerate = request.args.get("regenerate") == "1"

        timeline_file = _timeline_cache_file(days, top_n, include_structural=include_structural)

        # Utiliser le fichier mis en cache si présent et non périmé (< 1h)
        if not regenerate and timeline_file.exists() and not entity and not etype:
            age_s = _time.time() - timeline_file.stat().st_mtime
            if age_s < 3600:
                data = json.loads(timeline_file.read_text(encoding="utf-8"))
                return jsonify(data)

        _sys.path.insert(0, str(PROJECT_ROOT))
        from scripts.entity_timeline import collect_timeline, fill_missing_dates, build_top_entities

        raw = collect_timeline(
            PROJECT_ROOT,
            days=days,
            entity_filter=entity,
            type_filter=etype,
            match_mode=match_mode,
            all_types=all_types,
            include_structural=include_structural,
        )
        preliminary_top = build_top_entities(raw, top_n=top_n)
        top_keys = {e["key"] for e in preliminary_top}
        filled = fill_missing_dates({k: v for k, v in raw.items() if k in top_keys}, days=days)
        top_entities = build_top_entities(filled, top_n=top_n)
        query_info = _build_entity_query_info(
            entity=entity,
            entity_type=etype,
            match_mode=match_mode,
            all_types=all_types,
            include_structural=include_structural,
            matched_entities=resolve_entity_matches(
                PROJECT_ROOT,
                entity,
                etype,
                match_mode=match_mode,
                all_types=all_types,
                include_structural=include_structural,
            ) if entity else [],
        )

        result = {
            "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
            "window_days": days,
            "top_entities": top_entities,
            "timeline": filled,
            "query": query_info,
            "advanced_options": {
                "match_mode": list(allowed_match_modes()),
                "all_types": True,
                "include_structural": {
                    "default": False,
                    "description": "Inclut DATE, MONEY et autres types structurels dans la timeline."
                },
            },
        }

        # Sauvegarder le cache si requête sans filtre
        if not entity and not etype:
            timeline_file.parent.mkdir(parents=True, exist_ok=True)
            timeline_file.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")

        return jsonify(result)
    except ValueError as exc:
        return jsonify({"error": str(exc), "allowed_match_modes": allowed_match_modes()}), 400
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@entities_bp.route("/api/annotations", methods=["GET"])
def api_annotations_get():
    """Retourne toutes les annotations (dict keyed par URL)."""
    with _annotations_lock:
        return jsonify(_load_annotations())


@entities_bp.route("/api/annotations", methods=["POST"])
def api_annotations_post():
    """Crée ou met à jour l'annotation d'un article.

    Body JSON attendu :
        url         (str, obligatoire) — URL de l'article
        is_important (bool, optionnel)
        is_read      (bool, optionnel)
        is_hidden    (bool, optionnel)
        tags         (list[str], optionnel, max 20 items)
        notes        (str, optionnel, max 5000 chars)
    """
    body = require_json_body(required_fields=["url"])
    url = (body.get("url") or "").strip()
    if not url:
        return jsonify({"error": "Le champ 'url' est obligatoire"}), 400

    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")

    with _annotations_lock:
        data = _load_annotations()
        existing = data.get(url, {})

        # Merge : on ne remplace que les champs explicitement fournis
        updated = dict(existing)
        if "is_important" in body:
            updated["is_important"] = bool(body["is_important"])
        if "is_read" in body:
            updated["is_read"] = bool(body["is_read"])
        if "is_hidden" in body:
            updated["is_hidden"] = bool(body["is_hidden"])
        if "tags" in body:
            tags = body["tags"]
            if not isinstance(tags, list):
                return jsonify({"error": "'tags' doit être une liste"}), 400
            tags = [str(t).strip() for t in tags if str(t).strip()][:20]
            updated["tags"] = tags
        if "notes" in body:
            notes = str(body["notes"])[:5000]
            updated["notes"] = notes
        if "wf_status" in body:
            allowed = {"À traiter", "En cours", "Archivé", ""}
            v = str(body["wf_status"]).strip()
            if v not in allowed:
                return jsonify({"error": f"wf_status invalide (valeurs: {sorted(allowed)})"}), 400
            updated["wf_status"] = v

        updated["updated_at"] = now_iso
        if "created_at" not in updated:
            updated["created_at"] = now_iso

        data[url] = updated
        _save_annotations(data)

    return jsonify({"ok": True, "url": url, "annotation": updated})


@entities_bp.route("/api/annotations", methods=["DELETE"])
def api_annotations_delete():
    """Supprime l'annotation d'un article (paramètre ?url=...)."""
    url = (request.args.get("url") or "").strip()
    if not url:
        return jsonify({"error": "Paramètre 'url' obligatoire"}), 400

    with _annotations_lock:
        data = _load_annotations()
        if url not in data:
            return jsonify({"ok": True, "removed": False})
        del data[url]
        _save_annotations(data)

    return jsonify({"ok": True, "removed": True, "url": url})


@entities_bp.route("/api/watched-entities", methods=["GET"])
def api_watched_get():
    """Retourne les entités surveillées avec leur volume de mentions récentes.
    
    Résultat en cache 60s pour éviter les calculs répétés sur l'index.
    """
    # ── Cache TTL : même requête → réponse instantanée pendant 60s ─────────
    with _watched_cache_lock:
        entry = _watched_cache.get("result")
        if entry is not None and (time.monotonic() - entry["ts"]) < _WATCHED_CACHE_TTL:
            return jsonify(entry["result"])

    with _watched_lock:
        watched = _load_watched()

    if not watched:
        result = []
        with _watched_cache_lock:
            _watched_cache["result"] = {"result": result, "ts": time.monotonic()}
        return jsonify(result)

    # Calcul rapide des mentions via entity_index.json (évite le scan rglob).
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    cutoff_7d = now - timedelta(days=7)
    cutoff_24h = now - timedelta(hours=24)

    try:
        eidx = get_entity_index(PROJECT_ROOT)
        result = []
        for w in watched:
            etype = (w.get("type") or "").strip().upper()
            value = (w.get("value") or "").strip()
            if not etype or not value:
                continue
            etype, value = _canonicalize_watched_entity(etype, value)

            refs = eidx.get_canonical_refs(etype, value)
            mentions_7d = 0
            mentions_24h = 0
            for ref in refs:
                dt = parse_article_date(ref.get("date", ""), date_only_policy="end")
                if dt is None:
                    continue
                dt = dt.replace(tzinfo=timezone.utc)
                if dt < cutoff_7d:
                    # refs triées décroissantes : on peut arrêter tôt
                    break
                mentions_7d += 1
                if dt >= cutoff_24h:
                    mentions_24h += 1

            result.append({**w, "mentions_7d": mentions_7d, "mentions_24h": mentions_24h})
        
        # ── Mise en cache du résultat ──
        with _watched_cache_lock:
            _watched_cache["result"] = {"result": result, "ts": time.monotonic()}
        
        return jsonify(result)
    except Exception:
        # Fallback de sécurité : préserver l'API même si l'index est indisponible.
        result = [{**w, "mentions_7d": 0, "mentions_24h": 0} for w in watched]
        with _watched_cache_lock:
            _watched_cache["result"] = {"result": result, "ts": time.monotonic()}
        return jsonify(result)


@entities_bp.route("/api/watched-entities", methods=["POST"])
def api_watched_post():
    """Ajoute ou met à jour une entité surveillée.

    Body JSON : { type: str, value: str, notes?: str }
    """
    body = require_json_body(required_fields=["type", "value"])
    requested_type = (body.get("type") or "").strip().upper()
    requested_value = (body.get("value") or "").strip()
    if not requested_type or not requested_value:
        return jsonify({"error": "Champs type et value requis"}), 400
    etype, value = _canonicalize_watched_entity(requested_type, requested_value)

    with _watched_lock:
        watched = _load_watched()
        # Mise à jour si déjà présent
        for w in watched:
            if w["type"] == etype and w["value"] == value:
                if "notes" in body:
                    w["notes"] = str(body["notes"])[:500]
                _save_watched(watched)
                with _watched_cache_lock:
                    _watched_cache.clear()
                return jsonify(
                    {
                        "ok": True,
                        "action": "updated",
                        "type": etype,
                        "value": value,
                        "requested_type": requested_type,
                        "requested_value": requested_value,
                    }
                )
        # Ajout
        entry = {
            "type": etype,
            "value": value,
            "added_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
            "notes": str(body.get("notes", ""))[:500],
        }
        watched.append(entry)
        _save_watched(watched)
    
    with _watched_cache_lock:
        _watched_cache.clear()
    return jsonify(
        {
            "ok": True,
            "action": "added",
            "type": etype,
            "value": value,
            "requested_type": requested_type,
            "requested_value": requested_value,
        }
    )


@entities_bp.route("/api/watched-entities", methods=["DELETE"])
def api_watched_delete():
    """Retire une entité de la surveillance (paramètres ?type=...&value=...)."""
    requested_type = (request.args.get("type") or "").strip().upper()
    requested_value = (request.args.get("value") or "").strip()
    if not requested_type or not requested_value:
        return jsonify({"error": "Paramètres type et value requis"}), 400
    etype, value = _canonicalize_watched_entity(requested_type, requested_value)

    with _watched_lock:
        watched = _load_watched()
        before = len(watched)
        watched = [w for w in watched if not (w["type"] == etype and w["value"] == value)]
        _save_watched(watched)
    
    with _watched_cache_lock:
        _watched_cache.clear()
    
    return jsonify(
        {
            "ok": True,
            "removed": len(watched) < before,
            "type": etype,
            "value": value,
            "requested_type": requested_type,
            "requested_value": requested_value,
        }
    )


@entities_bp.route("/api/entity-timeline", methods=["GET"])
def api_entity_timeline():
    """Retourne entity_timeline.json pour affichage des courbes dans EntityWatchPanel."""
    tl_path = PROJECT_ROOT / "data" / "entity_timeline.json"
    if not tl_path.exists():
        return jsonify({})
    try:
        return jsonify(json.loads(tl_path.read_text(encoding="utf-8")))
    except Exception:
        return jsonify({})


@entities_bp.route("/api/sources/health", methods=["GET"])
def api_sources_health():
    """Retourne le rapport de santé des sources (data/source_health.json).

    Si le fichier n'existe pas encore, lance une analyse à la volée (rapide).
    Paramètres :
      refresh=1  — force une nouvelle analyse
      days=14    — fenêtre d'analyse en jours
    """
    health_path = PROJECT_ROOT / "data" / "source_health.json"
    days = int(request.args.get("days", 14))
    force_refresh = request.args.get("refresh", "0") == "1"

    if force_refresh or not health_path.exists():
        try:
            sys.path.insert(0, str(PROJECT_ROOT))
            from scripts.check_source_health import run_check
            run_check(PROJECT_ROOT, days=days, dry_run=False)
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    if not health_path.exists():
        return jsonify({"sources": [], "summary": {}})
    try:
        return jsonify(json.loads(health_path.read_text(encoding="utf-8")))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Profils utilisateur ───────────────────────────────────────────────────────

_PROFILES_PATH = PROJECT_ROOT / "config" / "user_profiles.json"
_profiles_lock = threading.Lock()


def _load_profiles() -> list[dict]:
    if not _PROFILES_PATH.exists():
        return []
    try:
        data = json.loads(_PROFILES_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save_profiles(profiles: list[dict]) -> None:
    _PROFILES_PATH.parent.mkdir(parents=True, exist_ok=True)
    _PROFILES_PATH.write_text(json.dumps(profiles, ensure_ascii=False, indent=2), encoding="utf-8")


@entities_bp.route("/api/profiles", methods=["GET"])
def api_profiles_get():
    """Retourne la liste des profils utilisateur."""
    return jsonify(_load_profiles())


@entities_bp.route("/api/profiles", methods=["POST"])
def api_profiles_post():
    """Crée ou met à jour un profil utilisateur.

    Body JSON : id (obligatoire), name, description, entities, themes, sources,
                keywords, exclude_sources, exclude_keywords, top_n
    """
    body = require_json_body(required_fields=["id"])
    pid = str(body.get("id", "")).strip()
    if not pid:
        return jsonify({"error": "L'id est obligatoire"}), 400

    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")

    with _profiles_lock:
        profiles = _load_profiles()
        existing = next((p for p in profiles if p.get("id") == pid), None)
        if existing:
            idx = profiles.index(existing)
            updated = dict(existing)
        else:
            updated = {"id": pid, "created_at": now_iso}
            idx = None

        for field in ("name", "description", "top_n"):
            if field in body:
                updated[field] = body[field]
        for field in ("entities", "themes", "sources", "keywords", "exclude_sources", "exclude_keywords"):
            if field in body:
                v = body[field]
                if not isinstance(v, list):
                    return jsonify({"error": f"'{field}' doit être une liste"}), 400
                updated[field] = [str(x).strip() for x in v if str(x).strip()]

        updated["updated_at"] = now_iso

        if idx is not None:
            profiles[idx] = updated
        else:
            profiles.append(updated)
        _save_profiles(profiles)

    return jsonify({"ok": True, "profile": updated})


@entities_bp.route("/api/profiles/<profile_id>", methods=["DELETE"])
def api_profiles_delete(profile_id: str):
    """Supprime un profil utilisateur."""
    with _profiles_lock:
        profiles = _load_profiles()
        new_profiles = [p for p in profiles if p.get("id") != profile_id]
        if len(new_profiles) == len(profiles):
            return jsonify({"error": "Profil introuvable"}), 404
        _save_profiles(new_profiles)
    return jsonify({"ok": True})


# ── Comparaison couverture sources ────────────────────────────────────────────

@entities_bp.route("/api/sources/coverage", methods=["GET"])
def api_sources_coverage():
    """Compare comment les sources couvrent une entité ou un sujet donné.

    Paramètres :
      entity  — nom de l'entité à analyser (ex: "OpenAI")
      days    — fenêtre en jours (défaut 7)
      type    — type NER optionnel pour filtrer (ex: "ORG")

    Retourne pour chaque source : nb articles, sentiment moyen, ton éditorial
    dominant, liste d'URL avec résumé court.
    """
    entity_query = (request.args.get("entity") or "").strip().lower()
    days = min(int(request.args.get("days", 7)), 90)
    etype_filter = (request.args.get("type") or "").strip().upper()

    if not entity_query:
        return jsonify({"error": "Paramètre 'entity' obligatoire"}), 400

    now = datetime.datetime.now(datetime.timezone.utc)
    cutoff = now - datetime.timedelta(days=days)

    # Agréger les articles par source
    source_data: dict[str, dict] = {}

    for source_dir in [PROJECT_ROOT / "data" / "articles-from-rss",
                        PROJECT_ROOT / "data" / "articles"]:
        if not source_dir.exists():
            continue
        for json_file in sorted(source_dir.rglob("*.json"),
                                key=lambda f: f.stat().st_mtime, reverse=True)[:40]:
            if "cache" in str(json_file) or "index" in json_file.name:
                continue
            try:
                data = json.loads(json_file.read_text(encoding="utf-8"))
                if not isinstance(data, list):
                    continue
            except Exception:
                continue

            for art in data:
                # Filtre date
                d = art.get("Date de publication", "") or ""
                try:
                    dt = datetime.datetime.fromisoformat(d.replace("Z", "+00:00"))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=datetime.timezone.utc)
                    if dt < cutoff:
                        continue
                except Exception:
                    pass

                # Vérifier la présence de l'entité
                resume = str(art.get("Résumé", "") or "").lower()
                art_ents = art.get("entities", {}) or {}
                found = False

                # Chercher dans les entités NER
                for etype, vals in art_ents.items():
                    if etype_filter and etype != etype_filter:
                        continue
                    if isinstance(vals, list):
                        for v in vals:
                            if entity_query in str(v).lower():
                                found = True
                                break
                    if found:
                        break

                # Chercher dans le résumé si pas trouvé dans NER
                if not found and entity_query in resume:
                    found = True

                if not found:
                    continue

                src = str(art.get("Sources", "")) or "Inconnu"
                if src not in source_data:
                    source_data[src] = {
                        "source": src,
                        "count": 0,
                        "sentiments": [],
                        "tons": [],
                        "articles": [],
                    }

                source_data[src]["count"] += 1
                sent = art.get("sentiment", "")
                if sent:
                    source_data[src]["sentiments"].append(sent)
                ton = art.get("ton_editorial", "")
                if ton:
                    source_data[src]["tons"].append(ton)
                source_data[src]["articles"].append({
                    "url": art.get("URL", ""),
                    "date": (art.get("Date de publication") or "")[:10],
                    "resume": str(art.get("Résumé", "") or "")[:200],
                })

    # Calculer les métriques agrégées
    result = []
    for src, sd in sorted(source_data.items(), key=lambda x: -x[1]["count"]):
        sentiments = sd["sentiments"]
        tons = sd["tons"]
        # Mode sentiment
        sent_mode = max(set(sentiments), key=sentiments.count) if sentiments else None
        # Mode ton
        ton_mode = max(set(tons), key=tons.count) if tons else None

        result.append({
            "source": src,
            "count": sd["count"],
            "sentiment_dominant": sent_mode,
            "ton_dominant": ton_mode,
            "articles": sd["articles"][:5],  # Max 5 articles par source
        })

    return jsonify({
        "entity": entity_query,
        "days": days,
        "sources_count": len(result),
        "sources": result,
    })


# ── Veille concurrentielle ────────────────────────────────────────────────────

@entities_bp.route("/api/competitive/targets", methods=["GET"])
def api_competitive_targets_get():
    """Retourne la liste des cibles de veille concurrentielle."""
    rules_path = PROJECT_ROOT / "config" / "alert_rules.json"
    try:
        rules = json.loads(rules_path.read_text(encoding="utf-8"))
        targets = rules.get("veille_concurrentielle", {}).get("targets", [])
        return jsonify({"targets": targets})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@entities_bp.route("/api/competitive/targets", methods=["POST"])
def api_competitive_targets_post():
    """Ajoute ou met à jour une cible de veille concurrentielle.

    Body JSON : name (obligatoire), type (défaut: ORG), aliases (liste optionnelle)
    """
    body = require_json_body(required_fields=["name"])
    name = str(body.get("name", "")).strip()
    if not name:
        return jsonify({"error": "'name' est obligatoire"}), 400
    etype = str(body.get("type", "ORG")).strip().upper()
    aliases = body.get("aliases", [])
    if not isinstance(aliases, list):
        aliases = []
    aliases = [str(a).strip() for a in aliases if str(a).strip()]

    rules_path = PROJECT_ROOT / "config" / "alert_rules.json"
    try:
        rules = json.loads(rules_path.read_text(encoding="utf-8"))
        vc = rules.setdefault("veille_concurrentielle", {"enabled": True, "targets": []})
        targets = vc.setdefault("targets", [])
        existing = next((t for t in targets if t.get("name", "").lower() == name.lower()), None)
        if existing:
            existing["type"] = etype
            existing["aliases"] = aliases
        else:
            targets.append({"name": name, "type": etype, "aliases": aliases})
        rules_path.write_text(json.dumps(rules, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"ok": True, "name": name})


@entities_bp.route("/api/competitive/targets/<target_name>", methods=["DELETE"])
def api_competitive_targets_delete(target_name: str):
    """Supprime une cible de veille concurrentielle."""
    rules_path = PROJECT_ROOT / "config" / "alert_rules.json"
    try:
        rules = json.loads(rules_path.read_text(encoding="utf-8"))
        targets = rules.get("veille_concurrentielle", {}).get("targets", [])
        new_targets = [t for t in targets if t.get("name", "").lower() != target_name.lower()]
        rules["veille_concurrentielle"]["targets"] = new_targets
        rules_path.write_text(json.dumps(rules, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"ok": True})


@entities_bp.route("/api/competitive/report", methods=["GET"])
def api_competitive_report():
    """Rapport de veille concurrentielle : mentions des cibles sur N jours.

    Paramètres : days (défaut 7)
    """
    days = min(int(request.args.get("days", 7)), 90)
    rules_path = PROJECT_ROOT / "config" / "alert_rules.json"

    try:
        rules = json.loads(rules_path.read_text(encoding="utf-8"))
        targets = rules.get("veille_concurrentielle", {}).get("targets", [])
    except Exception:
        targets = []

    if not targets:
        return jsonify({"targets": [], "days": days, "message": "Aucune cible configurée"})

    # Pour chaque cible, compter les mentions via /api/sources/coverage logic
    now = datetime.datetime.now(datetime.timezone.utc)
    cutoff = now - datetime.timedelta(days=days)
    report = []

    for target in targets:
        name = target.get("name", "")
        aliases = target.get("aliases", [])
        search_terms = [name.lower()] + [a.lower() for a in aliases]
        count = 0
        sources: set[str] = set()
        sentiments: list[str] = []
        recent_urls: list[str] = []

        for source_dir in [PROJECT_ROOT / "data" / "articles-from-rss",
                            PROJECT_ROOT / "data" / "articles"]:
            if not source_dir.exists():
                continue
            for json_file in sorted(source_dir.rglob("*.json"),
                                    key=lambda f: f.stat().st_mtime, reverse=True)[:20]:
                if "cache" in str(json_file) or "index" in json_file.name:
                    continue
                try:
                    data = json.loads(json_file.read_text(encoding="utf-8"))
                    if not isinstance(data, list):
                        continue
                except Exception:
                    continue
                for art in data:
                    resume = str(art.get("Résumé", "") or "").lower()
                    if not any(t in resume for t in search_terms):
                        continue
                    d = art.get("Date de publication", "") or ""
                    try:
                        dt = datetime.datetime.fromisoformat(d.replace("Z", "+00:00"))
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=datetime.timezone.utc)
                        if dt < cutoff:
                            continue
                    except Exception:
                        pass
                    count += 1
                    src = str(art.get("Sources", ""))
                    if src:
                        sources.add(src)
                    sent = art.get("sentiment", "")
                    if sent:
                        sentiments.append(sent)
                    url = art.get("URL", "")
                    if url and len(recent_urls) < 5:
                        recent_urls.append(url)

        sent_mode = max(set(sentiments), key=sentiments.count) if sentiments else None
        report.append({
            "name": name,
            "type": target.get("type", "ORG"),
            "aliases": aliases,
            "count": count,
            "sources_count": len(sources),
            "sentiment_dominant": sent_mode,
            "recent_urls": recent_urls,
        })

    report.sort(key=lambda r: -r["count"])
    return jsonify({"targets": report, "days": days})


# ── Recherche sémantique ──────────────────────────────────────────────────────

_semantic_index_built = False
_semantic_index_lock = threading.Lock()


def _ensure_semantic_index(project_root: Path) -> None:
    """Construit l'index TF-IDF sémantique à la demande."""
    global _semantic_index_built
    with _semantic_index_lock:
        if _semantic_index_built:
            return
        articles: list[dict] = []
        for source_dir in [project_root / "data" / "articles-from-rss",
                            project_root / "data" / "articles"]:
            if not source_dir.exists():
                continue
            for json_file in sorted(source_dir.rglob("*.json"),
                                    key=lambda f: f.stat().st_mtime, reverse=True)[:30]:
                if "cache" in str(json_file) or "index" in json_file.name:
                    continue
                try:
                    data = json.loads(json_file.read_text(encoding="utf-8"))
                    if isinstance(data, list):
                        articles.extend(data)
                except Exception:
                    continue
        try:
            from utils.vector_search import build_search_index
            build_search_index(articles, project_root)
            _semantic_index_built = True
        except Exception:
            pass


@entities_bp.route("/api/search/semantic", methods=["GET"])
def api_search_semantic():
    """Recherche sémantique TF-IDF sur les résumés d'articles.

    Paramètres :
      q      — requête de recherche (obligatoire)
      top_k  — nombre de résultats (défaut 10, max 50)

    Retourne les articles les plus similaires avec _similarity score.
    """
    query = (request.args.get("q") or "").strip()
    if not query:
        return jsonify({"error": "Paramètre 'q' obligatoire"}), 400
    top_k = min(int(request.args.get("top_k", 10)), 50)

    _ensure_semantic_index(PROJECT_ROOT)

    try:
        from utils.vector_search import get_vector_search
        vs = get_vector_search(PROJECT_ROOT)
        results = vs.search(query, top_k=top_k)
        return jsonify({
            "query": query,
            "engine": vs.engine,
            "count": len(results),
            "results": results,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─────────────────────────────────────────────────────────────────────────────
# Export consolidé des entités NER (consommable par des applications tierces)
# ─────────────────────────────────────────────────────────────────────────────

@entities_bp.route("/api/entities/export")
def api_entities_export():
    """Exporte toutes les entités NER en JSON consolidé avec images et synthèses.

    Paramètres de requête :
      q          — Filtre textuel partiel sur le nom de l'entité (insensible à la casse)
      type       — Filtre sur le type NER (PERSON, ORG, GPE, LOC, PRODUCT, EVENT, NORP, FAC…)
      limit      — Nombre max d'entités retournées (défaut 200, max 5000)
      sort       — Tri : « mentions » (défaut) ou « value » (ordre alphabétique)
      images     — Inclure les images depuis le cache disque : « true » (défaut) / « false »
      synthesis  — Inclure les synthèses IA depuis synthesis_cache : « true » / « false » (défaut)

    Réponse :
    {
      "generated_at": "<ISO-8601>",
      "total":        <int>,         # nombre d'entités retournées après filtrage
      "params": { ... },             # paramètres effectifs de la requête
      "entities": [
        {
          "type":      "PERSON",
          "value":     "Emmanuel Macron",
          "mentions":  42,
          "image":     { "url": "https://...", "width": 200, "height": 200 } | null,
          "synthesis": "<texte markdown>" | null
        },
        ...
      ]
    }
    """
    # ── Paramètres ─────────────────────────────────────────────────────────
    q_raw         = request.args.get("q", "").strip()
    type_filter   = request.args.get("type", "").strip().upper()
    try:
        match_mode = normalize_match_mode(request.args.get("match_mode"), default="canonical")
    except ValueError as exc:
        return jsonify({"error": str(exc), "allowed_match_modes": allowed_match_modes()}), 400
    try:
        limit = min(max(1, int(request.args.get("limit", 200))), 5000)
    except (ValueError, TypeError):
        limit = 200
    sort_by       = request.args.get("sort", "mentions").lower()
    include_images    = request.args.get("images",    "true").lower()  != "false"
    include_synthesis = request.args.get("synthesis", "false").lower() == "true"
    q_lower = q_raw.lower() if q_raw else ""

    # ── 1. Lecture de l'entity_index ────────────────────────────────────────
    raw_entities: list[dict] = []  # [{type, value, caps, mentions}]
    try:
        eidx = get_entity_index(PROJECT_ROOT)
        all_entries = eidx.get_all_entries(canonicalize=(match_mode != "strict"))
        canonicalizer = get_entity_canonicalizer(PROJECT_ROOT)
        caps_map: dict[str, str] = {}
        try:
            caps_map = eidx.get_caps_map() or {}   # {"TYPE:value (lower)": "Display Form"}
        except AttributeError:
            # Fallback : lire directement le fichier JSON de l'index
            _idx_file = PROJECT_ROOT / "data" / "entity_index.json"
            if _idx_file.exists():
                try:
                    _raw = json.loads(_idx_file.read_text(encoding="utf-8"))
                    caps_map = _raw.get("caps", {})
                except Exception:
                    pass

        grouped_entities: dict[str, dict] = {}
        for key, refs in all_entries.items():
            parts = key.split(":", 1)
            if len(parts) != 2:
                continue
            etype, value = parts[0], parts[1].strip()
            if not value:
                continue
            display_value = caps_map.get(key, value)
            canonical_type = etype
            canonical_value = display_value
            if match_mode != "strict":
                canonical_type, canonical_value = canonicalizer.canonicalize(etype, display_value)

            if type_filter and canonical_type != type_filter:
                continue

            group_key = (
                key
                if match_mode == "strict"
                else canonicalizer.canonical_key(canonical_type, canonical_value)
            )
            entry = grouped_entities.get(group_key)
            if entry is None:
                entry = {
                    "type": canonical_type,
                    "value": canonical_value,
                    "_key": group_key,
                    "mentions": 0,
                    "aliases": set(),
                }
                grouped_entities[group_key] = entry
            entry["mentions"] += len(refs)
            entry["aliases"].add(display_value)

        for entry in grouped_entities.values():
            aliases = sorted(entry.get("aliases", set()))
            searchable_values = [entry["value"], *aliases]
            if q_lower and not any(q_lower in str(candidate).lower() for candidate in searchable_values):
                continue
            raw_entities.append({
                "type": entry["type"],
                "value": entry["value"],
                "_key": entry["_key"],
                "mentions": entry["mentions"],
                "aliases": aliases,
            })

    except Exception:
        # Fallback rglob si l'entity_index est indisponible
        canonicalizer = get_entity_canonicalizer(PROJECT_ROOT)
        counts: dict[str, int] = {}
        type_vals: dict[str, tuple[str, str, set[str]]] = {}   # key → (type, display_value, aliases)
        for data_dir in [
            PROJECT_ROOT / "data" / "articles",
            PROJECT_ROOT / "data" / "articles-from-rss",
        ]:
            if not data_dir.exists():
                continue
            for json_file in sorted(data_dir.rglob("*.json")):
                if "cache" in json_file.relative_to(data_dir).parts:
                    continue
                try:
                    arts = json.loads(json_file.read_text(encoding="utf-8", errors="replace"))
                    if not isinstance(arts, list):
                        continue
                except (json.JSONDecodeError, OSError):
                    continue
                for article in arts:
                    ents = article.get("entities")
                    if not isinstance(ents, dict):
                        continue
                    for etype, values in ents.items():
                        if type_filter and etype != type_filter:
                            continue
                        if not isinstance(values, list):
                            continue
                        for v in values:
                            if not isinstance(v, str) or not v.strip():
                                continue
                            display_value = v.strip()
                            normalized_type = etype
                            normalized_value = display_value
                            if match_mode != "strict":
                                normalized_type, normalized_value = canonicalizer.canonicalize(etype, display_value)
                            if type_filter and normalized_type != type_filter:
                                continue
                            if q_lower and q_lower not in display_value.lower() and q_lower not in normalized_value.lower():
                                continue
                            k = (
                                f"{normalized_type}:{normalized_value.lower()}"
                                if match_mode != "strict"
                                else f"{etype}:{display_value.lower()}"
                            )
                            counts[k] = counts.get(k, 0) + 1
                            if k not in type_vals:
                                type_vals[k] = (normalized_type, normalized_value, set())
                            type_vals[k][2].add(display_value)

        for k, cnt in counts.items():
            etype, value, aliases = type_vals[k]
            raw_entities.append({
                "type":     etype,
                "value":    value,
                "_key":     k,
                "mentions": cnt,
                "aliases": sorted(aliases),
            })

    # ── 2. Tri ──────────────────────────────────────────────────────────────
    if sort_by == "value":
        raw_entities.sort(key=lambda e: e["value"].lower())
    else:
        raw_entities.sort(key=lambda e: e["mentions"], reverse=True)

    # ── 3. Pagination ───────────────────────────────────────────────────────
    total_before_limit = len(raw_entities)
    raw_entities = raw_entities[:limit]

    # ── 4. Images (depuis le cache disque) ──────────────────────────────────
    images_map: dict[str, dict | None] = {}
    if include_images:
        cache_path = PROJECT_ROOT / "data" / "images_cache.json"
        global _images_cache_mem
        with _images_cache_mem_lock:
            if _images_cache_mem is None:
                _tmp: dict = {}
                if cache_path.exists():
                    try:
                        _tmp = json.loads(cache_path.read_text(encoding="utf-8"))
                    except Exception:
                        pass
                _images_cache_mem = _tmp
            images_map = dict(_images_cache_mem)

    # ── 5. Synthèses IA (depuis synthesis_cache) ────────────────────────────
    synthesis_map: dict[str, str] = {}
    if include_synthesis:
        try:
            from utils.synthesis_cache import get_synthesis_cache as _get_scache
            _scache = _get_scache(PROJECT_ROOT)
            for ent in raw_entities:
                etype = ent["type"]
                # La valeur affichable peut différer de la clé originale — essayer les deux
                for candidate in [ent["value"], ent["_key"].split(":", 1)[-1]]:
                    cached = _scache.get(etype, candidate)
                    if cached:
                        text = cached.get("info_text") or cached.get("rag_text") or ""
                        if text:
                            synthesis_map[ent["_key"]] = text
                        break
        except Exception:
            pass

    # ── 6. Assemblage de la réponse ─────────────────────────────────────────
    entities_out = []
    for ent in raw_entities:
        item: dict = {
            "type":     ent["type"],
            "value":    ent["value"],
            "mentions": ent["mentions"],
        }
        if ent.get("aliases"):
            item["aliases"] = ent["aliases"]
        if include_images:
            image_entry = images_map.get(ent["value"])
            if image_entry is None:
                for alias in ent.get("aliases", []):
                    image_entry = images_map.get(alias)
                    if image_entry is not None:
                        break
            item["image"] = image_entry
        if include_synthesis:
            item["synthesis"] = synthesis_map.get(ent["_key"])
        entities_out.append(item)

    response_body = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "total":        total_before_limit,
        "returned":     len(entities_out),
        "params": {
            "q":         q_raw or None,
            "type":      type_filter or None,
            "limit":     limit,
            "sort":      sort_by,
            "match_mode": match_mode,
            "images":    include_images,
            "synthesis": include_synthesis,
        },
        "entities": entities_out,
    }

    resp = jsonify(response_body)
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Cache-Control"] = "no-cache"
    return resp


# ── Propagation narratifs ─────────────────────────────────────────────────────

@entities_bp.route("/api/narrative/propagation", methods=["GET"])
def api_narrative_propagation():
    """Détecte et retourne la propagation des narratifs entre sources.

    Params GET :
      entity  — filtre par entité/mot-clé (optionnel)
      days    — fenêtre temporelle en jours (défaut: 14)
      refresh — 1 pour forcer le recalcul (sinon utilise le cache fichier 1h)
    """
    entity = request.args.get("entity", "").strip() or None
    days = max(1, min(90, int(request.args.get("days", 14))))
    force = request.args.get("refresh", "0") == "1"

    output_path = PROJECT_ROOT / "data" / "narrative_propagation.json"

    # Utiliser le cache fichier si disponible et < 1h
    if not force and output_path.exists():
        try:
            cached = json.loads(output_path.read_text(encoding="utf-8"))
            import datetime as _dt
            generated = _dt.datetime.fromisoformat(cached.get("generated_at", "2000-01-01"))
            if generated.tzinfo is None:
                generated = generated.replace(tzinfo=_dt.timezone.utc)
            age_minutes = (_dt.datetime.now(_dt.timezone.utc) - generated).total_seconds() / 60
            if age_minutes < 60 and cached.get("days_window") == days and cached.get("entity_filter") == entity:
                return jsonify(cached)
        except Exception:
            pass

    try:
        sys.path.insert(0, str(PROJECT_ROOT))
        from scripts.detect_narrative_propagation import detect_narrative_propagation
        results = detect_narrative_propagation(
            project_root=PROJECT_ROOT,
            entity=entity,
            days=days,
            dry_run=False,
        )
        output = {
            "generated_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
            "days_window": days,
            "entity_filter": entity,
            "narratives_count": len(results),
            "narratives": results,
        }
        return jsonify(output)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


# ── Analyse réseau d'influence (Louvain) ──────────────────────────────────────

@entities_bp.route("/api/sources/influence-network", methods=["GET"])
def api_sources_influence_network():
    """Construit et retourne le graphe d'influence des sources.

    Params GET :
      days    — fenêtre temporelle en jours (défaut: 30)
      refresh — 1 pour forcer le recalcul (sinon cache fichier 2h)
    """
    days = max(1, min(90, int(request.args.get("days", 30))))
    force = request.args.get("refresh", "0") == "1"

    cache_path = PROJECT_ROOT / "data" / "influence_network.json"

    if not force and cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            import datetime as _dt
            generated = _dt.datetime.fromisoformat(cached.get("generated_at", "2000-01-01"))
            if generated.tzinfo is None:
                generated = generated.replace(tzinfo=_dt.timezone.utc)
            age_minutes = (_dt.datetime.now(_dt.timezone.utc) - generated).total_seconds() / 60
            if age_minutes < 120 and cached.get("days_window") == days:
                return jsonify(cached)
        except Exception:
            pass

    try:
        from utils.network_analysis import build_influence_report
        report = build_influence_report(PROJECT_ROOT, days=days)
        # Sauvegarder pour le cache
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return jsonify(report)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
