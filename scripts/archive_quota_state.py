#!/usr/bin/env python3
"""Archive l'état des quotas du jour précédent dans data/quota_history/.

Doit s'exécuter après le reset des quotas (00:01) pour capturer la journée
qui vient de se terminer.

Usage :
    python3 scripts/archive_quota_state.py [--dry-run]
"""

import argparse
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from utils.logging import default_logger
from utils.quota_optimizer import archive_today


def main() -> None:
    parser = argparse.ArgumentParser(description="Archive quota_state.json quotidiennement.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    ok = archive_today(dry_run=args.dry_run)
    if ok:
        default_logger.info("[archive_quota] État des quotas archivé avec succès.")
    else:
        default_logger.info("[archive_quota] Rien à archiver (état absent ou date incorrecte).")


if __name__ == "__main__":
    main()
