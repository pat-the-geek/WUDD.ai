"""
utils/quota_optimizer.py — Optimisation automatique des quotas journaliers

Analyse l'historique des quotas (data/quota_history/) pour détecter les
keywords toujours saturés ou sous-utilisés, puis ajuste les limites dans
config/quota.json.

Règles d'ajustement :
  - Keyword saturé ≥ 5 jours sur 7  → augmenter per_keyword_daily_limit de 20%
  - Keyword utilisé < 30% sur 7 jours → réduire de 15% (libérer du budget)
  - Entité monopolisant le quota    → réduire per_entity_daily_limit de 1
  - Global toujours saturé           → augmenter global_daily_limit de 10%

Historisation :
  Appelé par scripts/archive_quota_state.py (cron quotidien 00:05)
  pour archiver data/quota_state.json dans data/quota_history/YYYY-MM-DD.json

Appelé par : scripts/optimize_quota.py (cron hebdo lundi 05:45)
"""

import json
import shutil
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_QUOTA_CONFIG_PATH  = _PROJECT_ROOT / "config" / "quota.json"
_QUOTA_STATE_PATH   = _PROJECT_ROOT / "data" / "quota_state.json"
_QUOTA_HISTORY_DIR  = _PROJECT_ROOT / "data" / "quota_history"

# Bornes des limites
_GLOBAL_MIN  = 50
_GLOBAL_MAX  = 500
_KW_MIN      = 10
_KW_MAX      = 100
_ENTITY_MIN  = 3
_ENTITY_MAX  = 30

# Paramètres d'analyse
_ANALYSIS_DAYS = 7
_SATURATION_DAYS_THRESHOLD = 5   # saturé ≥ 5j/7j → augmenter
_UNDERUSE_RATIO_THRESHOLD  = 0.30  # < 30% utilisé → diminuer


def archive_today(dry_run: bool = False) -> bool:
    """Archive data/quota_state.json dans data/quota_history/YYYY-MM-DD.json.

    Appelé chaque nuit à 00:05 (après le reset des quotas à 00:01).
    Archive la journée qui vient de se terminer.

    Returns:
        True si l'archivage a été effectué, False sinon.
    """
    yesterday = str(date.today() - timedelta(days=1))

    if not _QUOTA_STATE_PATH.exists():
        return False

    try:
        state = json.loads(_QUOTA_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return False

    # Vérifier que c'est bien la date d'hier (le reset vient de tourner)
    state_date = state.get("date", "")
    # On archive l'état de la veille (avant le reset)
    if state_date != yesterday and state_date != str(date.today()):
        return False

    _QUOTA_HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    archive_path = _QUOTA_HISTORY_DIR / f"{state_date}.json"

    if archive_path.exists():
        return True  # Déjà archivé

    if not dry_run:
        archive_path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return True


def _load_history(days: int = _ANALYSIS_DAYS) -> list[dict]:
    """Charge les N derniers jours d'historique depuis data/quota_history/."""
    if not _QUOTA_HISTORY_DIR.exists():
        return []

    history = []
    today = date.today()
    for i in range(1, days + 1):
        d = str(today - timedelta(days=i))
        path = _QUOTA_HISTORY_DIR / f"{d}.json"
        if path.exists():
            try:
                history.append(json.loads(path.read_text(encoding="utf-8")))
            except Exception:
                pass
    return history


def _load_config() -> dict:
    from utils.quota import DEFAULT_CONFIG
    if _QUOTA_CONFIG_PATH.exists():
        try:
            return json.loads(_QUOTA_CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return dict(DEFAULT_CONFIG)


def _save_config(config: dict) -> None:
    _QUOTA_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _QUOTA_CONFIG_PATH.write_text(
        json.dumps(config, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def optimize(dry_run: bool = False) -> dict:
    """Analyse l'historique et ajuste les quotas si nécessaire.

    Returns:
        dict avec old_config, new_config, adjustments, applied
    """
    history = _load_history()
    if len(history) < 3:
        return {
            "applied": False,
            "reason": f"Historique insuffisant ({len(history)} jours < 3)",
            "adjustments": {},
        }

    old_config = _load_config()
    new_config = dict(old_config)
    adjustments: list[str] = []

    kw_limit    = int(old_config.get("per_keyword_daily_limit", 30))
    global_limit = int(old_config.get("global_daily_limit", 150))
    entity_limit = int(old_config.get("per_entity_daily_limit", 10))

    # ── Analyse par keyword ────────────────────────────────────────────────

    # Compter le nombre de jours de saturation et le ratio moyen par keyword
    keyword_days: dict[str, list[float]] = {}   # keyword → [ratio_j1, ratio_j2, ...]
    for day_state in history:
        for kw, data in day_state.get("keywords", {}).items():
            total = data.get("total", 0)
            ratio = total / kw_limit if kw_limit > 0 else 0
            keyword_days.setdefault(kw, []).append(ratio)

    new_kw_limit = kw_limit
    for kw, ratios in keyword_days.items():
        if len(ratios) < 3:
            continue
        avg_ratio = sum(ratios) / len(ratios)
        saturated_days = sum(1 for r in ratios if r >= 0.95)

        if saturated_days >= _SATURATION_DAYS_THRESHOLD:
            # Ce keyword est presque toujours saturé → augmenter le budget global
            # (on agit sur la limite globale car per_keyword est partagée)
            suggestion = f"Keyword '{kw}' saturé {saturated_days}/{len(ratios)} jours"
            if suggestion not in adjustments:
                adjustments.append(suggestion)
                new_kw_limit = min(_KW_MAX, int(new_kw_limit * 1.20))
        elif avg_ratio < _UNDERUSE_RATIO_THRESHOLD:
            suggestion = f"Keyword '{kw}' sous-utilisé (ratio moyen {avg_ratio:.0%})"
            adjustments.append(suggestion)

    if new_kw_limit != kw_limit:
        new_config["per_keyword_daily_limit"] = new_kw_limit
        adjustments.append(
            f"per_keyword_daily_limit : {kw_limit} → {new_kw_limit}"
        )

    # ── Analyse globale ───────────────────────────────────────────────────

    global_ratios = [
        day.get("global_count", 0) / global_limit
        for day in history
        if global_limit > 0
    ]
    global_saturated = sum(1 for r in global_ratios if r >= 0.95)
    if global_saturated >= _SATURATION_DAYS_THRESHOLD:
        new_global = min(_GLOBAL_MAX, int(global_limit * 1.10))
        new_config["global_daily_limit"] = new_global
        adjustments.append(
            f"global_daily_limit : {global_limit} → {new_global} (saturé {global_saturated}/{len(history)} jours)"
        )

    # ── Analyse par entité ────────────────────────────────────────────────

    # Détecter si une entité monopolise le budget global
    entity_totals: dict[str, int] = {}
    for day_state in history:
        for ent, cnt in day_state.get("entities", {}).items():
            entity_totals[ent] = entity_totals.get(ent, 0) + cnt

    if entity_totals:
        total_entity_refs = sum(entity_totals.values())
        top_entity, top_count = max(entity_totals.items(), key=lambda x: x[1])
        monopoly_ratio = top_count / total_entity_refs if total_entity_refs > 0 else 0
        if monopoly_ratio > 0.30 and entity_limit > _ENTITY_MIN:
            new_entity = max(_ENTITY_MIN, entity_limit - 1)
            new_config["per_entity_daily_limit"] = new_entity
            adjustments.append(
                f"per_entity_daily_limit : {entity_limit} → {new_entity} "
                f"('{top_entity}' monopolise {monopoly_ratio:.0%} du budget entités)"
            )

    result = {
        "applied": not dry_run and bool(adjustments),
        "reason": "OK" if adjustments else "Pas d'ajustement nécessaire",
        "adjustments": adjustments,
        "old_config": old_config,
        "new_config": new_config,
        "history_days": len(history),
    }

    if not dry_run and adjustments:
        _save_config(new_config)

    return result
