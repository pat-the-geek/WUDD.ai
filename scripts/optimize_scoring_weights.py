#!/usr/bin/env python3
"""Optimisation hebdomadaire des poids de scoring.

Analyse les signaux d'engagement collectés par l'EngagementTracker et ajuste
les poids dans config/scoring_weights.json.

Usage :
    python3 scripts/optimize_scoring_weights.py [--dry-run]

Options :
    --dry-run   Affiche les ajustements sans les appliquer
"""

import argparse
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from utils.logging import default_logger
from utils.scoring_optimizer import optimize


def main() -> None:
    parser = argparse.ArgumentParser(description="Optimise les poids de scoring selon l'engagement.")
    parser.add_argument("--dry-run", action="store_true", help="Simulation sans écriture")
    args = parser.parse_args()

    default_logger.info("[scoring_optimizer] Démarrage de l'optimisation des poids…")

    result = optimize(dry_run=args.dry_run)

    if not result.get("applied") and not args.dry_run:
        default_logger.info(f"[scoring_optimizer] Pas d'ajustement : {result.get('reason')}")
        return

    old = result.get("old_weights", {})
    new = result.get("new_weights", {})
    adj = result.get("adjustments", {})
    n   = result.get("signals_count", 0)

    default_logger.info(f"[scoring_optimizer] {n} signaux analysés")
    default_logger.info("[scoring_optimizer] Poids anciens → nouveaux :")
    for k in ("freshness", "entities", "keywords", "completeness"):
        delta = adj.get(k, 0)
        sign = "+" if delta >= 0 else ""
        default_logger.info(
            f"  {k:15s}: {old.get(k, '?'):.4f} → {new.get(k, '?'):.4f}  ({sign}{delta:.4f})"
        )

    if args.dry_run:
        default_logger.info("[scoring_optimizer] (dry-run) Aucune écriture effectuée.")
    else:
        default_logger.info("[scoring_optimizer] config/scoring_weights.json mis à jour.")


if __name__ == "__main__":
    main()
