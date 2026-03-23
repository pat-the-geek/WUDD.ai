#!/usr/bin/env python3
"""Mise à jour mensuelle des scores empiriques de performance des sources.

Calcule des métriques empiriques (enrichissement, diversité, engagement)
pour chaque source et met à jour config/sources_credibility.json.

Usage :
    python3 scripts/update_source_performance.py [--dry-run]
"""

import argparse
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from utils.logging import default_logger
from utils.source_performance import run_update, compute_source_metrics


def main() -> None:
    parser = argparse.ArgumentParser(description="Met à jour les scores empiriques des sources.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--stats-only", action="store_true", help="Affiche les métriques sans mettre à jour")
    args = parser.parse_args()

    if args.stats_only:
        default_logger.info("[source_performance] Calcul des métriques sources…")
        metrics = compute_source_metrics()
        default_logger.info(f"[source_performance] {len(metrics)} sources analysées :")
        for source, m in sorted(metrics.items(), key=lambda x: -x[1]["empirical_score"])[:20]:
            default_logger.info(
                f"  {source[:40]:40s} score={m['empirical_score']:5.1f} "
                f"enrichi={m['enrichment_rate']:.0%} "
                f"diversité={m['diversity_score']:.0f} "
                f"engagement={m['engagement_score']:.0f}"
            )
        return

    default_logger.info("[source_performance] Calcul et mise à jour des scores empiriques…")
    result = run_update(dry_run=args.dry_run)

    default_logger.info(
        f"[source_performance] {result.get('metrics_computed', 0)} sources analysées — "
        f"{result.get('sources_updated', 0)} mises à jour, "
        f"{result.get('sources_skipped', 0)} ignorées"
    )
    if args.dry_run:
        default_logger.info("[source_performance] (dry-run) Aucune écriture.")
    elif result.get("applied"):
        default_logger.info("[source_performance] sources_credibility.json mis à jour.")


if __name__ == "__main__":
    main()
