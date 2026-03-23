"""
utils/scoring_optimizer.py — Optimisation automatique des poids de scoring

Ajuste hebdomadairement les poids de scoring (freshness, entities, keywords,
completeness) en comparant les scores prédits aux signaux d'engagement réels
collectés par utils/engagement_tracker.py.

Principe : gradient descent simplifié avec contrainte sum(weights) == 1.0
  - Si les articles à fort score_entities ont un engagement moyen élevé
    → augmenter w_entities
  - Si les articles récents (fort score_freshness) ont un faible engagement
    → diminuer w_freshness

Config persistante : config/scoring_weights.json
Appelé par        : scripts/optimize_scoring_weights.py (cron hebdo lundi 05:30)
"""

import json
import threading
from pathlib import Path
from typing import Optional

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_WEIGHTS_FILE = _PROJECT_ROOT / "config" / "scoring_weights.json"

# Bornes des poids (évite les dérives extrêmes)
_WEIGHT_MIN = 0.05
_WEIGHT_MAX = 0.55

# Pas d'ajustement maximal par cycle
_DELTA_MAX = 0.03

# Poids initiaux (cohérents avec scoring.py)
_DEFAULT_WEIGHTS: dict[str, float] = {
    "freshness":    0.35,
    "entities":     0.25,
    "keywords":     0.25,
    "completeness": 0.15,
}

# Nombre minimal de signaux d'engagement pour déclencher un ajustement
_MIN_SIGNALS = 20


def load_weights() -> dict[str, float]:
    """Charge les poids depuis config/scoring_weights.json.

    Si le fichier n'existe pas, retourne les poids par défaut et le crée.
    """
    if _WEIGHTS_FILE.exists():
        try:
            data = json.loads(_WEIGHTS_FILE.read_text(encoding="utf-8"))
            w = {k: float(data.get(k, v)) for k, v in _DEFAULT_WEIGHTS.items()}
            return _normalize_weights(w)
        except Exception:
            pass
    # Créer le fichier avec les valeurs par défaut
    save_weights(_DEFAULT_WEIGHTS)
    return dict(_DEFAULT_WEIGHTS)


def save_weights(weights: dict[str, float]) -> None:
    """Persiste les poids dans config/scoring_weights.json."""
    _WEIGHTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    _WEIGHTS_FILE.write_text(
        json.dumps(weights, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _normalize_weights(weights: dict[str, float]) -> dict[str, float]:
    """Normalise les poids pour que leur somme soit exactement 1.0."""
    total = sum(weights.values())
    if total <= 0:
        return dict(_DEFAULT_WEIGHTS)
    return {k: round(v / total, 4) for k, v in weights.items()}


def _clamp(value: float, min_val: float, max_val: float) -> float:
    return max(min_val, min(max_val, value))


def optimize(dry_run: bool = False) -> dict:
    """Calcule et applique les nouveaux poids de scoring.

    Analyse la corrélation entre les composantes de scoring et l'engagement
    réel mesuré sur les 30 derniers jours.

    Returns:
        dict avec old_weights, new_weights, adjustments, signals_count, applied
    """
    from .engagement_tracker import get_engagement_tracker
    from .article_index import get_article_index
    from .scoring import (
        _freshness_score, _entity_score, _keyword_score, _completeness_score,
        _extract_keywords_flat,
    )
    import json as _json
    from datetime import datetime, timezone, timedelta

    tracker = get_engagement_tracker()
    article_idx = get_article_index(_PROJECT_ROOT)

    old_weights = load_weights()

    # Récupérer les scores d'engagement par URL
    eng_state = tracker._state.get("articles", {})
    if len(eng_state) < _MIN_SIGNALS:
        return {
            "applied": False,
            "reason": f"Pas assez de signaux ({len(eng_state)} < {_MIN_SIGNALS})",
            "old_weights": old_weights,
            "new_weights": old_weights,
            "adjustments": {},
            "signals_count": len(eng_state),
        }

    # Charger les mots-clés
    kw_file = _PROJECT_ROOT / "config" / "keyword-to-search.json"
    keywords: list[str] = []
    if kw_file.exists():
        try:
            keywords = _extract_keywords_flat(
                _json.loads(kw_file.read_text(encoding="utf-8"))
            )
        except Exception:
            pass

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=30)

    # Collecter les articles avec leur score d'engagement et leurs composantes
    samples: list[dict] = []
    for url_key, eng_data in eng_state.items():
        url = eng_data.get("url", "")
        engagement = eng_data.get("score", 0.0)
        if engagement == 0.0:
            continue

        # Trouver l'article dans l'index
        art = article_idx.get_by_url(url)
        if not art:
            continue

        # Charger l'article complet pour calculer ses composantes
        file_path = _PROJECT_ROOT / art.get("file", "")
        idx_pos = art.get("idx", 0)
        if not file_path.exists():
            continue
        try:
            data = _json.loads(file_path.read_text(encoding="utf-8", errors="replace"))
            if not isinstance(data, list) or idx_pos >= len(data):
                continue
            article = data[idx_pos]
        except Exception:
            continue

        # Calculer les composantes de scoring
        f_score = _freshness_score(article.get("Date de publication", ""), now) / 100.0
        e_score = _entity_score(article.get("entities", {})) / 100.0
        k_score = _keyword_score(article.get("Résumé", ""), keywords) / 100.0
        c_score = _completeness_score(article) / 100.0

        samples.append({
            "freshness":    f_score,
            "entities":     e_score,
            "keywords":     k_score,
            "completeness": c_score,
            "engagement":   engagement,
        })

    if len(samples) < _MIN_SIGNALS:
        return {
            "applied": False,
            "reason": f"Articles trouvés insuffisants ({len(samples)} < {_MIN_SIGNALS})",
            "old_weights": old_weights,
            "new_weights": old_weights,
            "adjustments": {},
            "signals_count": len(samples),
        }

    # Calculer la corrélation engagement ~ composante pour chaque dimension
    # Méthode : covariance normalisée
    n = len(samples)
    mean_eng = sum(s["engagement"] for s in samples) / n

    adjustments: dict[str, float] = {}
    new_weights = dict(old_weights)

    for dim in ("freshness", "entities", "keywords", "completeness"):
        mean_dim = sum(s[dim] for s in samples) / n
        cov = sum((s[dim] - mean_dim) * (s["engagement"] - mean_eng) for s in samples) / n
        std_dim = (sum((s[dim] - mean_dim) ** 2 for s in samples) / n) ** 0.5
        std_eng = (sum((s["engagement"] - mean_eng) ** 2 for s in samples) / n) ** 0.5

        if std_dim > 0 and std_eng > 0:
            correlation = cov / (std_dim * std_eng)
        else:
            correlation = 0.0

        # Ajuster le poids proportionnellement à la corrélation
        # corrélation positive → augmenter le poids
        # corrélation négative → diminuer le poids
        delta = _clamp(correlation * _DELTA_MAX, -_DELTA_MAX, _DELTA_MAX)
        adjustments[dim] = round(delta, 4)
        new_weights[dim] = _clamp(
            old_weights[dim] + delta, _WEIGHT_MIN, _WEIGHT_MAX
        )

    # Normaliser pour que la somme == 1.0
    new_weights = _normalize_weights(new_weights)

    result = {
        "applied": not dry_run,
        "reason": "OK",
        "old_weights": old_weights,
        "new_weights": new_weights,
        "adjustments": adjustments,
        "signals_count": len(samples),
    }

    if not dry_run:
        save_weights(new_weights)

    return result
