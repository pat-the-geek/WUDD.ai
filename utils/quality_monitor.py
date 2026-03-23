"""
utils/quality_monitor.py — Monitoring continu de la qualité des articles

Calcule un score de qualité (0–100) pour chaque article et met à jour
le champ `quality_score` dans data/article_index.json.

Niveaux de qualité :
  critique  (0–30)  : résumé manquant ou en erreur, pas d'enrichissement
  dégradé   (31–60) : enrichissements partiels (entities OU sentiment manquant)
  bon       (61–80) : résumé + 1 enrichissement présent
  complet   (81–100): résumé + entities + sentiment + images

Composantes du score (total 100) :
  - Résumé valide        : 40 pts
  - Entities présentes   : 20 pts
  - Sentiment présent    : 15 pts
  - Images présentes     : 10 pts
  - Temps de lecture     : 5 pts
  - Score source (bonus) : 10 pts max

Intégration :
  - article_index.py : champ quality_score ajouté lors de l'update()
  - repair_failed_enrichments.py : piloté par le score pour prioriser
  - viewer/routes/self_learning.py : endpoint GET /api/quality/stats
"""

from pathlib import Path
from typing import Optional

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Préfixes de résumés en erreur (cohérent avec scoring.py)
_ERROR_PREFIXES = (
    "désolé",
    "je n'ai pas pu",
    "erreur",
    "échec",
    "aucune information",
)


def compute_quality_score(article: dict) -> int:
    """Calcule le score de qualité d'un article (0–100).

    Args:
        article : dict article au format WUDD.ai

    Returns:
        Score entier entre 0 et 100.
    """
    score = 0

    # Résumé valide (40 pts)
    resume = article.get("Résumé", "")
    if isinstance(resume, str) and len(resume) > 100:
        if not any(resume.lower().startswith(p) for p in _ERROR_PREFIXES):
            score += 40

    # Entities présentes (20 pts)
    entities = article.get("entities", {})
    if isinstance(entities, dict) and entities:
        # Bonus partiel si au moins 2 types d'entités
        n_types = len(entities)
        score += min(20, 10 + n_types * 2)

    # Sentiment présent (15 pts)
    if article.get("sentiment") and article.get("score_sentiment") is not None:
        score += 15

    # Images présentes (10 pts)
    images = article.get("Images", [])
    if isinstance(images, list) and images:
        score += 10

    # Temps de lecture calculé (5 pts)
    if article.get("temps_lecture_minutes") is not None:
        score += 5

    # Score source (0–10 pts bonus)
    source_score = article.get("score_source", 50)
    if isinstance(source_score, (int, float)):
        score += int(source_score / 10)

    return min(100, max(0, score))


def quality_level(score: int) -> str:
    """Retourne le niveau de qualité correspondant au score."""
    if score <= 30:
        return "critique"
    if score <= 60:
        return "dégradé"
    if score <= 80:
        return "bon"
    return "complet"


def compute_repair_priority(article: dict) -> int:
    """Retourne une priorité de réparation (0 = pas besoin, 10 = urgent).

    Utilisé par repair_failed_enrichments.py pour prioriser les articles.
    """
    resume = article.get("Résumé", "")
    has_error_resume = isinstance(resume, str) and any(
        resume.lower().startswith(p) for p in _ERROR_PREFIXES
    )
    has_short_resume = not isinstance(resume, str) or len(resume) < 100
    missing_entities  = not isinstance(article.get("entities"), dict) or not article["entities"]
    missing_sentiment = not article.get("sentiment")

    priority = 0
    if has_error_resume:
        priority += 5
    if has_short_resume and not has_error_resume:
        priority += 3
    if missing_entities:
        priority += 2
    if missing_sentiment:
        priority += 1

    return min(10, priority)


def update_quality_scores(
    project_root: Optional[Path] = None,
    dry_run: bool = False,
) -> dict:
    """Recalcule les scores de qualité pour tous les articles dans l'index.

    Met à jour le champ quality_score dans data/article_index.json.

    Returns:
        dict avec total, updated, by_level, applied
    """
    import json
    if project_root is None:
        project_root = _PROJECT_ROOT

    from .article_index import get_article_index

    idx = get_article_index(project_root)
    all_entries = idx.get_articles()

    if not all_entries:
        return {"applied": False, "reason": "Index article vide", "total": 0}

    level_counts: dict[str, int] = {
        "critique": 0, "dégradé": 0, "bon": 0, "complet": 0
    }
    updated = 0

    # Grouper les entrées par fichier pour charger les articles en batch
    files: dict[str, list] = {}
    for entry in all_entries:
        file_key = entry.get("file", "")
        files.setdefault(file_key, []).append(entry)

    for file_rel, entries in files.items():
        file_path = project_root / file_rel
        if not file_path.exists():
            continue
        try:
            data = json.loads(file_path.read_text(encoding="utf-8", errors="replace"))
            if not isinstance(data, list):
                continue
        except Exception:
            continue

        for entry in entries:
            idx_pos = entry.get("idx", 0)
            if idx_pos >= len(data):
                continue
            article = data[idx_pos]
            q_score = compute_quality_score(article)
            level = quality_level(q_score)
            level_counts[level] += 1

            if not dry_run:
                entry["quality_score"] = q_score
                entry["quality_level"] = level
            updated += 1

    if not dry_run and updated > 0:
        idx.save()

    return {
        "applied": not dry_run,
        "total": len(all_entries),
        "updated": updated,
        "by_level": level_counts,
    }


def get_quality_stats(project_root: Optional[Path] = None) -> dict:
    """Retourne les statistiques de qualité depuis l'index (lecture seule).

    Returns:
        dict avec distribution par niveau, score moyen, articles à réparer
    """
    if project_root is None:
        project_root = _PROJECT_ROOT

    from .article_index import get_article_index
    idx = get_article_index(project_root)
    all_entries = idx.get_articles()

    level_counts: dict[str, int] = {
        "critique": 0, "dégradé": 0, "bon": 0, "complet": 0, "inconnu": 0
    }
    scores = []
    repair_needed = 0

    for entry in all_entries:
        q = entry.get("quality_score")
        if q is None:
            level_counts["inconnu"] += 1
            continue
        scores.append(q)
        level = quality_level(int(q))
        level_counts[level] = level_counts.get(level, 0) + 1
        if level == "critique":
            repair_needed += 1

    return {
        "total": len(all_entries),
        "by_level": level_counts,
        "avg_score": round(sum(scores) / len(scores), 1) if scores else 0,
        "repair_needed": repair_needed,
        "pct_complete": round(
            level_counts["complet"] / len(all_entries) * 100, 1
        ) if all_entries else 0,
    }
