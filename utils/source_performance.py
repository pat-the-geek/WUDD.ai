"""
utils/source_performance.py — Score empirique des sources basé sur les données réelles

Calcule mensuellement des métriques empiriques par source à partir du corpus
d'articles, puis met à jour config/sources_credibility.json avec un champ
`empirical_score` (0–100) et `empirical_score_updated`.

Métriques calculées :
  - Taux de duplication     : articles dédoublonnés / total → malus si > 20%
  - Taux d'enrichissement   : articles avec entities+sentiment / total → bonus
  - Engagement relatif      : score engagement moyen vs médiane globale
  - Diversité des entités   : entropie des types d'entités produites

Formule finale :
  score_empirique = base_score × 0.70 + empirical_score × 0.30

Singleton via get_source_performance()
"""

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_CREDIBILITY_FILE = _PROJECT_ROOT / "config" / "sources_credibility.json"

# Pondérations des métriques empiriques
_W_ENRICHMENT  = 0.35
_W_DIVERSITY   = 0.25
_W_ENGAGEMENT  = 0.25
_W_DUPLICATION = 0.15  # pénalité


def compute_source_metrics(project_root: Optional[Path] = None) -> dict[str, dict]:
    """Calcule les métriques empiriques pour toutes les sources.

    Returns:
        dict source_name → {
            enrichment_rate, diversity_score, engagement_score,
            duplication_rate, empirical_score, article_count
        }
    """
    if project_root is None:
        project_root = _PROJECT_ROOT

    from .engagement_tracker import get_engagement_tracker
    from .article_index import get_article_index

    tracker = get_engagement_tracker()
    article_idx = get_article_index(project_root)
    engagement_sources = tracker.get_source_scores()

    # Agréger les métriques par source depuis l'article_index
    source_stats: dict[str, dict] = {}

    all_entries = article_idx.get_articles()
    for entry in all_entries:
        source = entry.get("source", "")
        if not source:
            continue

        stats = source_stats.setdefault(source, {
            "total": 0,
            "with_entities": 0,
            "with_sentiment": 0,
            "entity_types": {},
        })
        stats["total"] += 1
        if entry.get("has_entities"):
            stats["with_entities"] += 1
        if entry.get("has_sentiment"):
            stats["with_sentiment"] += 1

    # Charger les articles complets pour la diversité des entités
    _enrich_entity_diversity(project_root, source_stats)

    # Calculer les métriques finales
    results: dict[str, dict] = {}

    # Médiane du score d'engagement (pour normalisation relative)
    eng_scores = [v for v in engagement_sources.values() if v > 0]
    eng_median = _median(eng_scores) if eng_scores else 1.0

    for source, stats in source_stats.items():
        total = stats["total"]
        if total == 0:
            continue

        # Taux d'enrichissement (NER + sentiment)
        enriched = (stats["with_entities"] + stats["with_sentiment"]) / (total * 2)
        enrichment_score = min(100.0, enriched * 100)

        # Diversité des entités (entropie de Shannon normalisée)
        entity_types = stats.get("entity_types", {})
        diversity_score = _entropy_score(entity_types)

        # Score d'engagement relatif (normalisé sur la médiane)
        eng_raw = engagement_sources.get(source, 0.0)
        if eng_median > 0:
            engagement_score = min(100.0, max(0.0, (eng_raw / eng_median) * 50 + 50))
        else:
            engagement_score = 50.0

        # Taux de duplication (approximé si l'index contient les doublons)
        # On utilise 0 par défaut (non calculé ici, mise à jour via deduplication)
        duplication_rate = stats.get("duplication_rate", 0.0)
        duplication_penalty = min(40.0, duplication_rate * 200)  # 20% → -40 pts

        # Score empirique composite
        empirical = (
            enrichment_score  * _W_ENRICHMENT
            + diversity_score * _W_DIVERSITY
            + engagement_score * _W_ENGAGEMENT
            - duplication_penalty * _W_DUPLICATION
        )
        empirical = max(0.0, min(100.0, empirical))

        results[source] = {
            "article_count":    total,
            "enrichment_rate":  round(enriched, 3),
            "enrichment_score": round(enrichment_score, 1),
            "diversity_score":  round(diversity_score, 1),
            "engagement_score": round(engagement_score, 1),
            "duplication_rate": round(duplication_rate, 3),
            "empirical_score":  round(empirical, 1),
        }

    return results


def update_credibility_file(
    metrics: dict[str, dict],
    dry_run: bool = False,
) -> dict:
    """Met à jour sources_credibility.json avec les scores empiriques.

    Returns:
        dict avec sources_updated, sources_skipped, applied
    """
    if not _CREDIBILITY_FILE.exists():
        return {"applied": False, "reason": "sources_credibility.json introuvable"}

    try:
        credibility = json.loads(_CREDIBILITY_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        return {"applied": False, "reason": str(e)}

    if not isinstance(credibility, list):
        return {"applied": False, "reason": "Format inattendu (pas une liste)"}

    updated = 0
    skipped = 0
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    for entry in credibility:
        source_name = entry.get("source") or entry.get("name") or ""
        if not source_name:
            skipped += 1
            continue

        # Chercher par correspondance partielle
        matched_key = _match_source(source_name, metrics)
        if not matched_key:
            skipped += 1
            continue

        m = metrics[matched_key]
        entry["empirical_score"] = m["empirical_score"]
        entry["empirical_score_updated"] = timestamp
        entry["empirical_details"] = {
            "article_count":    m["article_count"],
            "enrichment_score": m["enrichment_score"],
            "diversity_score":  m["diversity_score"],
            "engagement_score": m["engagement_score"],
        }
        updated += 1

    if not dry_run and updated > 0:
        _CREDIBILITY_FILE.write_text(
            json.dumps(credibility, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    return {
        "applied": not dry_run,
        "sources_updated": updated,
        "sources_skipped": skipped,
    }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _enrich_entity_diversity(project_root: Path, source_stats: dict) -> None:
    """Enrichit source_stats avec la distribution des types d'entités."""
    data_dir = project_root / "data"
    for json_file in list((data_dir / "articles").rglob("*.json"))[:200]:
        if "cache" in json_file.parts:
            continue
        try:
            articles = json.loads(json_file.read_text(encoding="utf-8", errors="replace"))
            if not isinstance(articles, list):
                continue
            for art in articles:
                source = art.get("Sources") or art.get("source", "")
                if not source or source not in source_stats:
                    continue
                entities = art.get("entities", {})
                if not isinstance(entities, dict):
                    continue
                for etype, vals in entities.items():
                    if isinstance(vals, list) and vals:
                        source_stats[source]["entity_types"][etype] = (
                            source_stats[source]["entity_types"].get(etype, 0) + len(vals)
                        )
        except Exception:
            continue


def _entropy_score(type_counts: dict) -> float:
    """Calcule un score de diversité (0–100) basé sur l'entropie de Shannon."""
    total = sum(type_counts.values())
    if total == 0:
        return 0.0
    n_types = len(type_counts)
    if n_types <= 1:
        return 0.0
    entropy = -sum(
        (c / total) * math.log2(c / total)
        for c in type_counts.values()
        if c > 0
    )
    max_entropy = math.log2(n_types)
    return min(100.0, (entropy / max_entropy) * 100) if max_entropy > 0 else 0.0


def _median(values: list) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    return (s[n // 2] + s[(n - 1) // 2]) / 2


def _match_source(name: str, metrics: dict) -> Optional[str]:
    """Trouve la clé correspondante dans metrics (correspondance insensible à la casse)."""
    name_lower = name.lower()
    # Correspondance exacte
    if name in metrics:
        return name
    # Correspondance insensible à la casse
    for key in metrics:
        if key.lower() == name_lower:
            return key
    # Correspondance partielle
    for key in metrics:
        if name_lower in key.lower() or key.lower() in name_lower:
            return key
    return None


# ── Singleton ─────────────────────────────────────────────────────────────────

def run_update(dry_run: bool = False) -> dict:
    """Point d'entrée principal : calcule les métriques et met à jour le fichier."""
    metrics = compute_source_metrics()
    result = update_credibility_file(metrics, dry_run=dry_run)
    result["metrics_computed"] = len(metrics)
    return result
