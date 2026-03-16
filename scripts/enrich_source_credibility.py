#!/usr/bin/env python3
"""Enrichissement automatique de la crédibilité des sources — WUDD.ai v2.3.

Ce script enrichit les entrées de config/sources_credibility.json avec trois
signaux automatisés :
  - Âge du domaine      (WHOIS)
  - Transparence éditoriale (scraping HTTP)
  - Rating MBFC          (mediabiasfactcheck.com)

Il est conçu pour fonctionner en deux modes :
  1. Mode incrémental (défaut) — enrichit uniquement les sources manquantes
  2. Mode force (--force)     — ré-enrichit toutes les sources

Migration initiale :
  Lors du premier déploiement, lancez avec --force pour enrichir les 40 sources
  existantes en une seule passe.

Usage :
  # Sources non encore enrichies uniquement
  python3 scripts/enrich_source_credibility.py

  # Toutes les sources (re-calcul complet)
  python3 scripts/enrich_source_credibility.py --force

  # Une source spécifique
  python3 scripts/enrich_source_credibility.py --source "Le Monde"

  # Simuler sans écrire
  python3 scripts/enrich_source_credibility.py --dry-run

  # Réduire les pauses inter-requêtes (attention au rate-limiting)
  python3 scripts/enrich_source_credibility.py --delay 1.0
"""

import argparse
import sys
from pathlib import Path

# Résolution du project root depuis n'importe quel répertoire de travail
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from utils.logging import default_logger
from utils.source_enricher import run_enrichment


def main():
    parser = argparse.ArgumentParser(
        description="Enrichit sources_credibility.json avec âge domaine, transparence et MBFC."
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Ré-enrichir toutes les sources (y compris déjà enrichies)",
    )
    parser.add_argument(
        "--source",
        metavar="NOM",
        default=None,
        help="Enrichir uniquement cette source (ex: 'Le Monde')",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=2.0,
        metavar="SEC",
        help="Pause entre requêtes HTTP en secondes (défaut: 2.0)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simuler l'enrichissement sans écrire dans sources_credibility.json",
    )
    args = parser.parse_args()

    default_logger.info("═" * 60)
    default_logger.info("Enrichissement crédibilité sources — WUDD.ai v2.3")
    if args.dry_run:
        default_logger.info("MODE DRY-RUN — aucune écriture")
    if args.force:
        default_logger.info("MODE FORCE — toutes les sources seront ré-enrichies")
    if args.source:
        default_logger.info(f"Source ciblée : {args.source}")
    default_logger.info("═" * 60)

    stats = run_enrichment(
        project_root=PROJECT_ROOT,
        force=args.force,
        source_filter=args.source,
        delay=args.delay,
        dry_run=args.dry_run,
    )

    default_logger.info("─" * 60)
    default_logger.info(
        f"Terminé : {stats['enriched']} enrichies, "
        f"{stats['skipped']} ignorées, "
        f"{stats['failed']} en échec"
    )

    sys.exit(1 if stats["failed"] > 0 and stats["enriched"] == 0 else 0)


if __name__ == "__main__":
    main()
