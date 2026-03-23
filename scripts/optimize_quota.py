#!/usr/bin/env python3
"""Optimisation hebdomadaire des quotas journaliers.

Analyse les 7 derniers jours d'historique et ajuste config/quota.json
si des keywords sont systématiquement saturés ou sous-utilisés.

Usage :
    python3 scripts/optimize_quota.py [--dry-run]
"""

import argparse
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from utils.logging import default_logger
from utils.quota_optimizer import optimize


def main() -> None:
    parser = argparse.ArgumentParser(description="Optimise les quotas selon l'historique.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    default_logger.info("[optimize_quota] Analyse de l'historique des quotas…")
    result = optimize(dry_run=args.dry_run)

    default_logger.info(
        f"[optimize_quota] {result.get('history_days', 0)} jours analysés — "
        f"{result.get('reason', '')}"
    )

    for adj in result.get("adjustments", []):
        default_logger.info(f"[optimize_quota] {adj}")

    if result.get("applied"):
        default_logger.info("[optimize_quota] config/quota.json mis à jour.")
    elif args.dry_run:
        default_logger.info("[optimize_quota] (dry-run) Aucune écriture.")


if __name__ == "__main__":
    main()
