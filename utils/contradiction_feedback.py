"""
utils/contradiction_feedback.py — Feedback sur les contradictions détectées

Accumule les validations utilisateur (confirmer / rejeter) sur les contradictions
détectées par utils/contradiction_engine.py, puis ajuste automatiquement les
seuils de confiance dans config/alert_rules.json ou directement dans le moteur.

État persistant : data/contradiction_feedback.json
Singleton via get_contradiction_feedback()
"""

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_FEEDBACK_PATH = _PROJECT_ROOT / "data" / "contradiction_feedback.json"

# Seuil de confiance par type de contradiction (cohérent avec contradiction_engine.py)
_DEFAULT_THRESHOLDS: dict[str, float] = {
    "CHIFFRE":      0.55,
    "DATE":         0.55,
    "FAIT_BINAIRE": 0.55,
    "ATTRIBUTION":  0.55,
    "AUTRE":        0.60,
}
_THRESHOLDS_FILE = _PROJECT_ROOT / "config" / "contradiction_thresholds.json"

# Bornes des seuils
_THRESHOLD_MIN = 0.30
_THRESHOLD_MAX = 0.90

# Pas d'ajustement
_DELTA_UP   = 0.05   # Si precision faible → augmenter le seuil
_DELTA_DOWN = 0.03   # Si precision élevée → diminuer le seuil

# Nombre minimal de retours pour déclencher un ajustement
_MIN_FEEDBACK = 10


class ContradictionFeedback:
    """Collecte et analyse les retours utilisateur sur les contradictions."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._data = self._load()

    def _load(self) -> dict:
        if _FEEDBACK_PATH.exists():
            try:
                return json.loads(_FEEDBACK_PATH.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {
            "version": 1,
            "total_confirmed": 0,
            "total_rejected": 0,
            "by_type": {},
            "entries": [],
            "thresholds": dict(_DEFAULT_THRESHOLDS),
            "calibration_log": [],
        }

    def _persist(self) -> None:
        _FEEDBACK_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _FEEDBACK_PATH.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(_FEEDBACK_PATH)

    # ── API publique ──────────────────────────────────────────────────────────

    def record(
        self,
        contradiction_type: str,
        action: str,  # "confirmed" ou "rejected"
        description: Optional[str] = None,
        confidence: Optional[float] = None,
        article_url: Optional[str] = None,
    ) -> None:
        """Enregistre un retour utilisateur sur une contradiction.

        Args:
            contradiction_type : CHIFFRE, DATE, FAIT_BINAIRE, ATTRIBUTION, AUTRE
            action             : "confirmed" (vraie contradiction) ou "rejected" (faux positif)
            description        : description de la contradiction (optionnel)
            confidence         : score de confiance assigné par le moteur (optionnel)
            article_url        : URL de l'article source (optionnel)
        """
        if action not in ("confirmed", "rejected"):
            return

        with self._lock:
            # Compteurs globaux
            if action == "confirmed":
                self._data["total_confirmed"] += 1
            else:
                self._data["total_rejected"] += 1

            # Compteurs par type
            type_data = self._data["by_type"].setdefault(contradiction_type, {
                "confirmed": 0, "rejected": 0
            })
            type_data[action] += 1

            # Historique (500 dernières entrées)
            self._data["entries"].append({
                "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "type":        contradiction_type,
                "action":      action,
                "description": description,
                "confidence":  confidence,
                "article_url": article_url,
            })
            self._data["entries"] = self._data["entries"][-500:]

            self._persist()

    def get_thresholds(self) -> dict[str, float]:
        """Retourne les seuils de confiance actuels par type."""
        with self._lock:
            return self._get_thresholds_nolock()

    def _get_thresholds_nolock(self) -> dict[str, float]:
        """Retourne les seuils sans acquérir le lock (appelé depuis méthodes déjà lockées)."""
        stored = self._data.get("thresholds", {})
        return {
            k: stored.get(k, v)
            for k, v in _DEFAULT_THRESHOLDS.items()
        }

    def calibrate(self, dry_run: bool = False) -> dict:
        """Ajuste les seuils de confiance en fonction du feedback accumulé.

        Returns:
            dict avec old_thresholds, new_thresholds, stats, applied
        """
        with self._lock:
            old_thresholds = self._get_thresholds_nolock()
            new_thresholds = dict(old_thresholds)
            adjustments: dict[str, str] = {}
            stats: dict[str, dict] = {}

            for ctype, type_data in self._data.get("by_type", {}).items():
                confirmed = type_data.get("confirmed", 0)
                rejected  = type_data.get("rejected", 0)
                total = confirmed + rejected

                if total < _MIN_FEEDBACK:
                    continue

                precision = confirmed / total
                stats[ctype] = {
                    "confirmed": confirmed,
                    "rejected": rejected,
                    "precision": round(precision, 3),
                }

                old_t = old_thresholds.get(ctype, 0.55)
                if precision < 0.60:
                    # Trop de faux positifs → augmenter le seuil
                    new_t = min(_THRESHOLD_MAX, old_t + _DELTA_UP)
                    adjustments[ctype] = f"{old_t:.2f} → {new_t:.2f} (precision {precision:.0%})"
                    new_thresholds[ctype] = round(new_t, 3)
                elif precision > 0.85:
                    # Bonne précision → peut abaisser le seuil pour détecter plus
                    new_t = max(_THRESHOLD_MIN, old_t - _DELTA_DOWN)
                    adjustments[ctype] = f"{old_t:.2f} → {new_t:.2f} (precision {precision:.0%})"
                    new_thresholds[ctype] = round(new_t, 3)

            # Journaliser
            self._data["calibration_log"].append({
                "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "dry_run": dry_run,
                "stats": stats,
                "adjustments": adjustments,
                "old_thresholds": old_thresholds,
                "new_thresholds": new_thresholds,
            })
            self._data["calibration_log"] = self._data["calibration_log"][-30:]

            if not dry_run and adjustments:
                self._data["thresholds"] = new_thresholds
                self._persist()
                _save_thresholds_file(new_thresholds)

            return {
                "applied": not dry_run and bool(adjustments),
                "adjustments": adjustments,
                "stats": stats,
                "old_thresholds": old_thresholds,
                "new_thresholds": new_thresholds,
            }

    def get_stats(self) -> dict:
        """Retourne les statistiques de feedback."""
        with self._lock:
            total = self._data["total_confirmed"] + self._data["total_rejected"]
            precision = (
                self._data["total_confirmed"] / total if total > 0 else None
            )
            return {
                "total_feedback": total,
                "total_confirmed": self._data["total_confirmed"],
                "total_rejected": self._data["total_rejected"],
                "global_precision": round(precision, 3) if precision is not None else None,
                "by_type": dict(self._data.get("by_type", {})),
                "thresholds": self._get_thresholds_nolock(),
            }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _save_thresholds_file(thresholds: dict) -> None:
    """Persiste les seuils dans config/contradiction_thresholds.json."""
    _THRESHOLDS_FILE.parent.mkdir(parents=True, exist_ok=True)
    _THRESHOLDS_FILE.write_text(
        json.dumps(thresholds, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_thresholds() -> dict[str, float]:
    """Charge les seuils de confiance depuis le fichier de config ou les défauts."""
    if _THRESHOLDS_FILE.exists():
        try:
            data = json.loads(_THRESHOLDS_FILE.read_text(encoding="utf-8"))
            return {k: float(data.get(k, v)) for k, v in _DEFAULT_THRESHOLDS.items()}
        except Exception:
            pass
    return dict(_DEFAULT_THRESHOLDS)


# ── Singleton ─────────────────────────────────────────────────────────────────

_feedback_instance: Optional["ContradictionFeedback"] = None
_feedback_lock = threading.Lock()


def get_contradiction_feedback() -> "ContradictionFeedback":
    """Retourne l'instance singleton de ContradictionFeedback."""
    global _feedback_instance
    if _feedback_instance is None:
        with _feedback_lock:
            if _feedback_instance is None:
                _feedback_instance = ContradictionFeedback()
    return _feedback_instance
