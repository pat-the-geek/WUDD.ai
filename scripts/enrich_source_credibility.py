#!/usr/bin/env python3
"""Enrichissement automatique de la crédibilité des sources — WUDD.ai v2.3.

Ce script enrichit les entrées de config/sources_credibility.json avec trois
signaux automatisés :
  - Âge du domaine      (WHOIS)
  - Transparence éditoriale (scraping HTTP)
  - Rating MBFC          (mediabiasfactcheck.com)

Il peut également synchroniser automatiquement les nouvelles sources depuis
les configurations surveillées (OPML, web_sources.json, articles existants)
avant de lancer l'enrichissement.

Modes de fonctionnement :
  1. Mode sync + incrémental (recommandé) — ajoute les nouvelles sources puis
     enrichit celles qui manquent de données v2
  2. Mode incrémental seul (défaut sans --sync) — enrichit uniquement les
     sources manquantes dans la base actuelle
  3. Mode force (--force) — ré-enrichit toutes les sources
  4. Mode sync seul (--sync --dry-run) — affiche les nouvelles sources sans
     rien écrire ni appeler d'API externe

Migration initiale :
  Lors du premier déploiement, lancez avec --sync --force pour synchroniser
  les sources et enrichir toutes les entrées en une seule passe.

Usage :
  # Synchroniser les nouvelles sources puis enrichir les manquantes
  python3 scripts/enrich_source_credibility.py --sync

  # Synchronisation seule (pas d'appel HTTP externe)
  python3 scripts/enrich_source_credibility.py --sync --dry-run

  # Toutes les sources (re-calcul complet) avec synchronisation préalable
  python3 scripts/enrich_source_credibility.py --sync --force

  # Sources non encore enrichies uniquement (sans synchronisation)
  python3 scripts/enrich_source_credibility.py

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
from utils.source_enricher import run_enrichment, sync_new_sources


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Enrichit sources_credibility.json avec âge domaine, transparence et MBFC. "
            "Avec --sync, synchronise d'abord les nouvelles sources depuis OPML et web_sources.json."
        )
    )
    parser.add_argument(
        "--sync",
        action="store_true",
        help=(
            "Synchroniser d'abord les nouvelles sources depuis OPML, web_sources.json "
            "et les articles existants (sans appel API externe)"
        ),
    )
    parser.add_argument(
        "--sync-only",
        action="store_true",
        dest="sync_only",
        help=(
            "Synchroniser le registre uniquement, sans lancer l'enrichissement "
            "WHOIS/transparence/MBFC. Rapide, aucun appel HTTP externe."
        ),
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
        help="Simuler sans écrire dans sources_credibility.json",
    )
    args = parser.parse_args()

    default_logger.info("═" * 60)
    default_logger.info("Enrichissement crédibilité sources — WUDD.ai v2.3")
    if args.dry_run:
        default_logger.info("MODE DRY-RUN — aucune écriture")
    if args.sync_only:
        default_logger.info("MODE SYNC-ONLY — registre uniquement, pas d'enrichissement HTTP")
    if args.sync:
        default_logger.info("MODE SYNC — synchronisation du registre activée")
    if args.force:
        default_logger.info("MODE FORCE — toutes les sources seront ré-enrichies")
    if args.source:
        default_logger.info(f"Source ciblée : {args.source}")
    default_logger.info("═" * 60)

    # ── Mode sync-only : synchroniser sans enrichir ───────────────────────────
    if args.sync_only:
        default_logger.info("─" * 60)
        default_logger.info("Synchronisation du registre des sources")
        sync_stats = sync_new_sources(project_root=PROJECT_ROOT, dry_run=args.dry_run)
        default_logger.info(
            f"Sync terminée : {sync_stats['added']} ajoutées, "
            f"{sync_stats['already_known']} déjà connues "
            f"(registre total : {sync_stats['total_registry']})"
        )
        sys.exit(0)

    # ── Étape 1 : synchronisation du registre (optionnelle) ───────────────────
    if args.sync:
        default_logger.info("─" * 60)
        default_logger.info("Étape 1/2 — Synchronisation du registre des sources")
        sync_stats = sync_new_sources(project_root=PROJECT_ROOT, dry_run=args.dry_run)
        default_logger.info(
            f"Sync terminée : {sync_stats['added']} ajoutées, "
            f"{sync_stats['already_known']} déjà connues "
            f"(registre total : {sync_stats['total_registry']})"
        )
        default_logger.info("─" * 60)
        default_logger.info("Étape 2/2 — Enrichissement WHOIS / transparence / MBFC")
    else:
        default_logger.info("Enrichissement WHOIS / transparence / MBFC")

    # ── Étape 2 : enrichissement des données v2 ───────────────────────────────
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
