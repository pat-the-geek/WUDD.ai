#!/usr/bin/env python3
"""
import_articles.py — Importe des articles depuis un fichier JSON externe.

Permet d'injecter des articles provenant d'une autre instance WUDD.ai, d'un
backup, ou d'une source tiers dans la structure de données locale.

Fonctionnalités :
  - Validation du format article (champs obligatoires)
  - Déduplication contre les articles existants du flux cible
  - Normalisation des champs (dates, sources)
  - Sauvegarde dans data/articles/<flux>/ ou data/articles-from-rss/
  - Mise à jour des index (article_index, entity_index)

Usage :
    # Importer dans un flux nommé
    python3 scripts/import_articles.py --file export.json --flux Intelligence-artificielle

    # Importer dans articles-from-rss sous un keyword
    python3 scripts/import_articles.py --file export.json --keyword ia --rss

    # Dry-run (validation seulement, aucune écriture)
    python3 scripts/import_articles.py --file export.json --flux IA --dry-run

    # Forcer l'import même si des doublons sont détectés
    python3 scripts/import_articles.py --file export.json --flux IA --force

    # Afficher le rapport de validation uniquement
    python3 scripts/import_articles.py --file export.json --validate-only
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))

from utils.logging import print_console
from utils.config import get_config
from utils.deduplication import Deduplicator
from utils.article_index import get_article_index
from utils.entity_index import get_entity_index


# ── Champs obligatoires d'un article valide ────────────────────────────────

REQUIRED_FIELDS = ["Date de publication", "Sources", "URL", "Résumé"]
OPTIONAL_FIELDS = [
    "Images", "entities", "sentiment", "score_sentiment",
    "ton_editorial", "score_ton", "temps_lecture_minutes",
    "temps_lecture_label", "score_source",
]


# ── Validation ─────────────────────────────────────────────────────────────

def validate_article(article: dict) -> list[str]:
    """Valide un article et retourne la liste des anomalies (vide si OK)."""
    issues = []

    if not isinstance(article, dict):
        return ["n'est pas un dictionnaire"]

    for field in REQUIRED_FIELDS:
        if field not in article or not article[field]:
            issues.append(f"champ obligatoire manquant : '{field}'")

    url = article.get("URL", "")
    if url and not str(url).startswith("http"):
        issues.append(f"URL invalide : {url[:80]}")

    resume = article.get("Résumé", "")
    if resume and len(str(resume)) < 20:
        issues.append(f"Résumé trop court ({len(str(resume))} chars)")

    return issues


def validate_file(articles: list) -> dict:
    """Valide tous les articles d'un fichier et retourne un rapport."""
    stats = {
        "total": len(articles),
        "valid": 0,
        "invalid": 0,
        "errors": [],
    }
    for i, article in enumerate(articles):
        issues = validate_article(article)
        if issues:
            stats["invalid"] += 1
            stats["errors"].append({
                "index": i,
                "url": article.get("URL", "(sans URL)") if isinstance(article, dict) else "(non-dict)",
                "issues": issues,
            })
        else:
            stats["valid"] += 1
    return stats


# ── Chargement des articles existants ──────────────────────────────────────

def _load_existing_articles(target_dir: Path) -> list[dict]:
    """Charge tous les articles existants dans un répertoire cible."""
    existing = []
    if not target_dir.exists():
        return existing
    for json_file in sorted(target_dir.glob("*.json")):
        if "cache" in str(json_file):
            continue
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
            if isinstance(data, list):
                existing.extend(data)
        except (json.JSONDecodeError, OSError):
            continue
    return existing


# ── Import principal ───────────────────────────────────────────────────────

def import_articles(
    source_file: Path,
    flux: str | None = None,
    keyword: str | None = None,
    rss_mode: bool = False,
    dry_run: bool = False,
    force: bool = False,
    validate_only: bool = False,
) -> dict:
    """
    Importe les articles du fichier source dans la structure WUDD.ai.

    Args:
        source_file   : Fichier JSON source (liste d'articles)
        flux          : Nom du flux cible (data/articles/<flux>/)
        keyword       : Mot-clé cible (data/articles-from-rss/<keyword>.json)
        rss_mode      : Si True, sauvegarde dans articles-from-rss/
        dry_run       : Validation + rapport sans écriture
        force         : Importer même les doublons détectés
        validate_only : Afficher le rapport de validation sans importer

    Returns:
        Rapport d'import : {imported, skipped, invalid, output_file}
    """
    config = get_config()
    config.setup_directories()

    # ── Lecture du fichier source ──────────────────────────────────────────
    print_console(f"Lecture de {source_file}")
    try:
        articles = json.loads(source_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print_console(f"Fichier JSON invalide : {e}", level="error")
        sys.exit(1)
    except OSError as e:
        print_console(f"Impossible de lire le fichier : {e}", level="error")
        sys.exit(1)

    if not isinstance(articles, list):
        print_console("Le fichier doit contenir une liste JSON d'articles", level="error")
        sys.exit(1)

    print_console(f"{len(articles)} articles lus")

    # ── Validation ─────────────────────────────────────────────────────────
    validation = validate_file(articles)
    print_console(
        f"Validation : {validation['valid']} valides, "
        f"{validation['invalid']} invalides"
    )
    if validation["errors"]:
        print_console("Anomalies détectées :")
        for err in validation["errors"][:10]:
            print_console(
                f"  [index {err['index']}] {err['url'][:60]} — "
                + "; ".join(err["issues"])
            )
        if len(validation["errors"]) > 10:
            print_console(f"  … {len(validation['errors']) - 10} autres anomalies")

    if validate_only:
        print_console("Mode --validate-only : import annulé")
        return validation

    # ── Détermination du répertoire/fichier de destination ────────────────
    if rss_mode and keyword:
        output_file = config.project_root / "data" / "articles-from-rss" / f"{keyword}.json"
        target_dir = output_file.parent
        merge_mode = True  # fusionner avec l'existant pour rss
    elif flux:
        target_dir = config.project_root / "data" / "articles" / flux
        date_str = datetime.now().strftime("%Y-%m-%d")
        output_file = target_dir / f"articles_imported_{date_str}.json"
        merge_mode = False
    else:
        print_console("Spécifier --flux <nom> ou --keyword <mot-clé> --rss", level="error")
        sys.exit(1)

    # ── Déduplication ──────────────────────────────────────────────────────
    existing = _load_existing_articles(target_dir if not merge_mode else output_file.parent)
    if merge_mode and output_file.exists():
        try:
            merge_existing = json.loads(output_file.read_text(encoding="utf-8"))
            if isinstance(merge_existing, list):
                existing = merge_existing
        except Exception:
            existing = []

    dedup = Deduplicator()
    to_import = []
    skipped_dedup = 0

    for article in articles:
        issues = validate_article(article)
        if issues and not force:
            continue  # ignorer les articles invalides
        if not force and dedup.is_duplicate(article, existing):
            skipped_dedup += 1
            continue
        to_import.append(article)

    print_console(
        f"Après déduplication : {len(to_import)} à importer, "
        f"{skipped_dedup} doublons ignorés"
    )

    if dry_run:
        print_console("Mode --dry-run : aucune écriture effectuée")
        return {
            "imported": len(to_import),
            "skipped": skipped_dedup,
            "invalid": validation["invalid"],
            "output_file": str(output_file),
            "dry_run": True,
        }

    if not to_import:
        print_console("Aucun article à importer")
        return {
            "imported": 0,
            "skipped": skipped_dedup,
            "invalid": validation["invalid"],
            "output_file": str(output_file),
        }

    # ── Écriture ───────────────────────────────────────────────────────────
    target_dir.mkdir(parents=True, exist_ok=True)

    if merge_mode and output_file.exists():
        final_articles = existing + to_import
    else:
        final_articles = to_import

    tmp = output_file.with_suffix(".json.tmp")
    try:
        tmp.write_text(
            json.dumps(final_articles, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(output_file)
        print_console(f"✓ {len(to_import)} articles importés → {output_file}")
    except OSError as e:
        print_console(f"Erreur d'écriture : {e}", level="error")
        sys.exit(1)

    # ── Mise à jour des index ──────────────────────────────────────────────
    try:
        aidx = get_article_index(config.project_root)
        aidx.update([output_file])
        print_console("Index articles mis à jour")
    except Exception as e:
        print_console(f"Index articles : {e}", level="warning")

    has_entities = any(a.get("entities") for a in to_import)
    if has_entities:
        try:
            eidx = get_entity_index(config.project_root)
            rel = str(output_file.relative_to(config.project_root))
            eidx.update(to_import, rel)
            print_console("Index entités mis à jour")
        except Exception as e:
            print_console(f"Index entités : {e}", level="warning")

    return {
        "imported": len(to_import),
        "skipped": skipped_dedup,
        "invalid": validation["invalid"],
        "output_file": str(output_file),
    }


# ── CLI ────────────────────────────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(
        description="Importe des articles JSON dans la structure de données WUDD.ai."
    )
    parser.add_argument(
        "--file", required=True,
        help="Chemin vers le fichier JSON source (liste d'articles)"
    )
    parser.add_argument(
        "--flux",
        help="Flux cible (data/articles/<flux>/). Mutuel. exclusif avec --keyword."
    )
    parser.add_argument(
        "--keyword",
        help="Mot-clé cible pour articles-from-rss (requiert --rss)."
    )
    parser.add_argument(
        "--rss", action="store_true",
        help="Importer dans data/articles-from-rss/ (fusion avec l'existant)."
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Valide et simule l'import sans écrire aucun fichier."
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Importer même les articles identifiés comme doublons."
    )
    parser.add_argument(
        "--validate-only", action="store_true",
        help="Affiche uniquement le rapport de validation, sans importer."
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    source = Path(args.file)
    if not source.exists():
        print_console(f"Fichier source introuvable : {source}", level="error")
        sys.exit(1)

    if args.flux and args.keyword:
        print_console("--flux et --keyword sont mutuellement exclusifs", level="error")
        sys.exit(1)

    if not args.flux and not args.keyword and not args.validate_only:
        print_console("Spécifier --flux <nom> ou --keyword <mot-clé> --rss", level="error")
        sys.exit(1)

    result = import_articles(
        source_file=source,
        flux=args.flux,
        keyword=args.keyword,
        rss_mode=args.rss,
        dry_run=args.dry_run,
        force=args.force,
        validate_only=args.validate_only,
    )

    print_console(
        f"\nRésumé : {result.get('imported', 0)} importés, "
        f"{result.get('skipped', 0)} doublons, "
        f"{result.get('invalid', 0)} invalides"
    )
