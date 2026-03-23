#!/usr/bin/env python3
"""Auto-calibration quotidienne des seuils d'alerte.

Met à jour les compteurs de suivi post-alerte, puis ajuste les seuils
dans config/alert_rules.json si le taux de faux positifs le justifie.

Usage :
    python3 scripts/calibrate_alerts.py [--dry-run]
"""

import argparse
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from utils.logging import default_logger
from utils.alert_calibrator import update_follow_up_counts, calibrate


def main() -> None:
    parser = argparse.ArgumentParser(description="Calibre les seuils d'alerte.")
    parser.add_argument("--dry-run", action="store_true", help="Simulation sans écriture")
    args = parser.parse_args()

    default_logger.info("[calibrate_alerts] Mise à jour des compteurs de suivi…")
    n_updated = update_follow_up_counts()
    default_logger.info(f"[calibrate_alerts] {n_updated} alertes mises à jour.")

    default_logger.info("[calibrate_alerts] Calibration des seuils…")
    result = calibrate(dry_run=args.dry_run)

    stats = result.get("stats", {})
    default_logger.info(
        f"[calibrate_alerts] {stats.get('alerts_analyzed', 0)} alertes analysées, "
        f"taux FP = {stats.get('fp_rate', 0):.0%}"
    )
    default_logger.info(f"[calibrate_alerts] {result.get('reason', '')}")

    if result.get("applied"):
        old = result.get("old_thresholds", {})
        new = result.get("new_thresholds", {})
        for k in old:
            if old.get(k) != new.get(k):
                default_logger.info(
                    f"[calibrate_alerts] Seuil '{k}' : {old.get(k)} → {new.get(k)}"
                )
        default_logger.info("[calibrate_alerts] config/alert_rules.json mis à jour.")
    elif args.dry_run:
        default_logger.info("[calibrate_alerts] (dry-run) Aucune écriture.")


if __name__ == "__main__":
    main()
