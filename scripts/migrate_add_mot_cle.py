#!/usr/bin/env python3
"""
Migration : ajoute rétroactivement `mot_cle` et `fichier_source`
à tous les articles de data/articles-from-rss/ qui en sont dépourvus.

Le mot-clé est déduit du nom de fichier (slug → keyword via config/keyword-to-search.json).
Le fichier source est le chemin relatif du JSON depuis la racine du projet.

Usage:
    python3 scripts/migrate_add_mot_cle.py [--dry-run]
"""

import argparse
import glob
import json
import os
import shutil
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent


def print_console(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"{ts} {msg}")


def build_slug_to_keyword(project_root: Path) -> dict[str, str]:
    kw_file = project_root / "config" / "keyword-to-search.json"
    with open(kw_file, encoding="utf-8") as f:
        keywords = json.load(f)
    return {kw["keyword"].replace(" ", "-").lower(): kw["keyword"] for kw in keywords}


def migrate(dry_run: bool = False) -> None:
    rss_dir = PROJECT_ROOT / "data" / "articles-from-rss"
    slug_to_kw = build_slug_to_keyword(PROJECT_ROOT)

    files = sorted(rss_dir.glob("*.json"))
    # Exclure les fichiers spéciaux (48-heures, etc.)
    files = [f for f in files if not f.name.startswith("_") and f.name != "48-heures.json"]

    total_files = 0
    total_updated = 0
    total_skipped = 0

    for fpath in files:
        slug = fpath.stem  # nom sans extension
        kw = slug_to_kw.get(slug, slug)  # fallback : utiliser le slug tel quel
        fichier_source = str(fpath.relative_to(PROJECT_ROOT)).replace("\\", "/")

        with open(fpath, encoding="utf-8") as f:
            articles = json.load(f)

        if not isinstance(articles, list):
            print_console(f"[SKIP] {fpath.name} : format non-liste, ignoré")
            continue

        updated = 0
        for article in articles:
            if not isinstance(article, dict):
                continue
            changed = False
            if "mot_cle" not in article:
                article["mot_cle"] = kw
                changed = True
            if "fichier_source" not in article:
                article["fichier_source"] = fichier_source
                changed = True
            if changed:
                updated += 1

        total_files += 1
        total_updated += updated
        total_skipped += len(articles) - updated

        if updated == 0:
            print_console(f"[OK]   {fpath.name} : {len(articles)} articles, rien à migrer")
            continue

        print_console(f"[MIGNÉ] {fpath.name} : {updated}/{len(articles)} articles enrichis (kw={kw})")

        if not dry_run:
            # Sauvegarde avant écriture
            backup_path = PROJECT_ROOT / "archives" / f"{fpath.stem}_mot_cle_migration_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            shutil.copy2(fpath, backup_path)
            with open(fpath, "w", encoding="utf-8") as f:
                json.dump(articles, f, ensure_ascii=False, indent=2)

    print_console(
        f"\nMigration {'(dry-run) ' if dry_run else ''}terminée : "
        f"{total_files} fichiers, {total_updated} articles mis à jour, {total_skipped} déjà à jour"
    )
    if dry_run:
        print_console("Mode dry-run : aucun fichier modifié")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migration : ajoute mot_cle + fichier_source aux articles RSS existants")
    parser.add_argument("--dry-run", action="store_true", help="Simulation sans modification")
    args = parser.parse_args()
    migrate(dry_run=args.dry_run)
