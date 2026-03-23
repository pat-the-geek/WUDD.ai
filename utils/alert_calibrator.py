"""
utils/alert_calibrator.py — Auto-calibration des seuils d'alerte

Analyse la qualité des alertes générées par trend_detector.py en mesurant
si elles ont effectivement été suivies de nouveaux articles dans les 48h.
Ajuste automatiquement les seuils dans config/alert_rules.json.

Logique :
  - Une alerte est "creuse" si l'entité n'a pas produit de nouveaux articles
    dans les 48h suivant l'alerte
  - Si taux d'alertes creuses > 30% sur 7 jours → incrémenter le seuil de +0.25
  - Si aucune alerte sur des entités qui ont ensuite explosé → décrémenter de -0.15
  - Les alertes ignorées par l'utilisateur (via engagement_tracker) sont aussi
    comptabilisées comme "faux positifs"

État persistant : data/alert_feedback.json
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_FEEDBACK_PATH = _PROJECT_ROOT / "data" / "alert_feedback.json"
_RULES_PATH    = _PROJECT_ROOT / "config" / "alert_rules.json"

# Bornes des seuils de ratio
_RATIO_MIN = 1.5
_RATIO_MAX = 8.0

# Seuil de taux de faux positifs déclenchant une augmentation du seuil
_FP_RATE_THRESHOLD = 0.30

# Pas d'ajustement
_DELTA_UP   = 0.25
_DELTA_DOWN = 0.15

# Fenêtre d'analyse (jours)
_ANALYSIS_WINDOW_DAYS = 7

# Fenêtre de suivi post-alerte (heures)
_FOLLOW_UP_HOURS = 48


def load_feedback() -> dict:
    """Charge le feedback d'alertes depuis data/alert_feedback.json."""
    if _FEEDBACK_PATH.exists():
        try:
            return json.loads(_FEEDBACK_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "version": 1,
        "alerts": [],  # historique des alertes avec leur résultat
        "calibration_log": [],
    }


def _save_feedback(data: dict) -> None:
    _FEEDBACK_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _FEEDBACK_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(_FEEDBACK_PATH)


def record_alert(
    entity_type: str,
    entity_value: str,
    ratio: float,
    level: str,
    mentions_24h: int,
) -> None:
    """Enregistre une alerte générée pour suivi ultérieur.

    Appelé par trend_detector.py après génération de data/alertes.json.
    """
    data = load_feedback()
    data["alerts"].append({
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "type": entity_type,
        "value": entity_value,
        "ratio": ratio,
        "level": level,
        "mentions_24h": mentions_24h,
        "follow_up_count": None,   # à remplir lors du calibrage
        "dismissed": False,
    })
    # Garder seulement les 500 dernières alertes
    data["alerts"] = data["alerts"][-500:]
    _save_feedback(data)


def mark_dismissed(entity_value: str) -> None:
    """Marque les alertes récentes de cette entité comme ignorées.

    Appelé par l'engagement_tracker quand signal_type='alert_dismissed'.
    """
    data = load_feedback()
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=24)
    for alert in data["alerts"]:
        if alert.get("value") != entity_value:
            continue
        try:
            ts = datetime.strptime(alert["timestamp"], "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=timezone.utc
            )
            if ts >= cutoff:
                alert["dismissed"] = True
        except Exception:
            pass
    _save_feedback(data)


def calibrate(dry_run: bool = False) -> dict:
    """Analyse les alertes passées et ajuste les seuils si nécessaire.

    Returns:
        dict avec old_thresholds, new_thresholds, stats, applied
    """
    data = load_feedback()
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=_ANALYSIS_WINDOW_DAYS)

    # Filtrer les alertes avec suivi disponible (>= 48h d'ancienneté)
    analyzable = []
    for alert in data["alerts"]:
        try:
            ts = datetime.strptime(alert["timestamp"], "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=timezone.utc
            )
        except Exception:
            continue
        if ts < cutoff:
            continue
        age_h = (now - ts).total_seconds() / 3600
        if age_h < _FOLLOW_UP_HOURS:
            continue  # Pas encore possible de mesurer le suivi
        analyzable.append(alert)

    if not analyzable:
        return {
            "applied": False,
            "reason": "Pas assez d'alertes analysables",
            "stats": {},
            "old_thresholds": _load_thresholds(),
            "new_thresholds": _load_thresholds(),
        }

    # Compter les faux positifs (alertes creuses ou ignorées)
    # On considère "creuse" une alerte où follow_up_count == 0 ou dismissed == True
    false_positives = sum(
        1 for a in analyzable
        if a.get("dismissed") or a.get("follow_up_count") == 0
    )
    fp_rate = false_positives / len(analyzable)

    old_thresholds = _load_thresholds()
    new_thresholds = dict(old_thresholds)

    adjustment = 0.0
    reason = "Pas d'ajustement nécessaire"

    if fp_rate > _FP_RATE_THRESHOLD:
        adjustment = _DELTA_UP
        reason = f"Taux faux positifs élevé ({fp_rate:.0%} > {_FP_RATE_THRESHOLD:.0%}) → seuil augmenté"
    elif fp_rate < 0.10 and len(analyzable) >= 5:
        adjustment = -_DELTA_DOWN
        reason = f"Taux faux positifs faible ({fp_rate:.0%}) → seuil diminué"

    if adjustment != 0.0:
        for key in ("global_threshold_ratio", "threshold_ratio"):
            if key in new_thresholds:
                new_val = max(_RATIO_MIN, min(_RATIO_MAX, new_thresholds[key] + adjustment))
                new_thresholds[key] = round(new_val, 2)

    stats = {
        "alerts_analyzed": len(analyzable),
        "false_positives": false_positives,
        "fp_rate": round(fp_rate, 3),
        "adjustment": adjustment,
    }

    # Journaliser
    data["calibration_log"].append({
        "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "dry_run": dry_run,
        **stats,
        "old_thresholds": old_thresholds,
        "new_thresholds": new_thresholds,
    })
    data["calibration_log"] = data["calibration_log"][-50:]

    if not dry_run:
        _save_feedback(data)
        if adjustment != 0.0:
            _save_thresholds(new_thresholds)

    return {
        "applied": not dry_run and adjustment != 0.0,
        "reason": reason,
        "stats": stats,
        "old_thresholds": old_thresholds,
        "new_thresholds": new_thresholds,
    }


def update_follow_up_counts() -> int:
    """Met à jour les compteurs de suivi pour les alertes de plus de 48h.

    Compte les nouveaux articles mentionnant l'entité dans les 48h post-alerte.
    Appelé en début de calibration ou en cron quotidien.

    Returns:
        Nombre d'alertes mises à jour.
    """
    from .entity_index import get_entity_index

    data = load_feedback()
    entity_idx = get_entity_index(_PROJECT_ROOT)
    now = datetime.now(timezone.utc)
    updated = 0

    for alert in data["alerts"]:
        if alert.get("follow_up_count") is not None:
            continue
        try:
            ts = datetime.strptime(alert["timestamp"], "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=timezone.utc
            )
        except Exception:
            continue
        age_h = (now - ts).total_seconds() / 3600
        if age_h < _FOLLOW_UP_HOURS:
            continue

        # Compter les articles publiés dans les 48h après l'alerte
        etype = alert.get("type", "")
        value = alert.get("value", "")
        key = f"{etype}:{value.lower()}"
        refs = entity_idx.get_refs(key)

        follow_up_cutoff = ts + timedelta(hours=_FOLLOW_UP_HOURS)
        count = sum(
            1 for ref in refs
            if _ref_date_in_window(ref.get("date", ""), ts, follow_up_cutoff)
        )
        alert["follow_up_count"] = count
        updated += 1

    if updated:
        _save_feedback(data)
    return updated


def _ref_date_in_window(date_str: str, start: datetime, end: datetime) -> bool:
    """Vérifie si une date est dans la fenêtre [start, end]."""
    if not date_str:
        return False
    from .date_utils import parse_article_date
    dt = parse_article_date(date_str)
    if dt is None:
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return start <= dt <= end


def _load_thresholds() -> dict:
    """Charge les seuils actuels depuis config/alert_rules.json."""
    if not _RULES_PATH.exists():
        return {"global_threshold_ratio": 2.0}
    try:
        rules = json.loads(_RULES_PATH.read_text(encoding="utf-8"))
        global_cfg = rules.get("global", {})
        return {
            "global_threshold_ratio": global_cfg.get("threshold_ratio", 2.0),
        }
    except Exception:
        return {"global_threshold_ratio": 2.0}


def _save_thresholds(new_thresholds: dict) -> None:
    """Applique les nouveaux seuils dans config/alert_rules.json."""
    if not _RULES_PATH.exists():
        return
    try:
        rules = json.loads(_RULES_PATH.read_text(encoding="utf-8"))
        if "global" in rules and "threshold_ratio" in new_thresholds:
            rules["global"]["threshold_ratio"] = new_thresholds["global_threshold_ratio"]
        _RULES_PATH.write_text(
            json.dumps(rules, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass
