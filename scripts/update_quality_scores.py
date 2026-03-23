#!/usr/bin/env python3
"""Mise à jour des scores de qualité dans l'article_index.

Recalcule le champ quality_score pour tous les articles indexés.
Génère un rapport rapide des articles à réparer en priorité.

Usage :
    python3 scripts/update_quality_scores.py [--dry-run] [--stats-only]
"""

import argparse
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from utils.logging import default_logger
from utils.quality_monitor import update_quality_scores, get_quality_stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Met à jour les scores de qualité des articles.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--stats-only", action="store_true", help="Affiche les stats sans recalculer")
    args = parser.parse_args()

    if args.stats_only:
        stats = get_quality_stats()
        default_logger.info(f"[quality] {stats['total']} articles indexés")
        default_logger.info(f"[quality] Score moyen : {stats['avg_score']}")
        default_logger.info(f"[quality] Articles complets : {stats['pct_complete']}%")
        default_logger.info(f"[quality] Répartition : {stats['by_level']}")
        default_logger.info(f"[quality] Articles critiques à réparer : {stats['repair_needed']}")
        return

    default_logger.info("[quality] Calcul des scores de qualité…")
    result = update_quality_scores(dry_run=args.dry_run)

    default_logger.info(f"[quality] {result.get('updated', 0)}/{result.get('total', 0)} articles traités")
    by_level = result.get("by_level", {})
    for level, count in sorted(by_level.items(), key=lambda x: x[1], reverse=True):
        default_logger.info(f"[quality]   {level:10s}: {count}")

    if args.dry_run:
        default_logger.info("[quality] (dry-run) Aucune écriture.")
    elif result.get("applied"):
        default_logger.info("[quality] article_index.json mis à jour.")


if __name__ == "__main__":
    main()
