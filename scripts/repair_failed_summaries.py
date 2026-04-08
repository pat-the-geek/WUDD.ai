"""
Script : repair_failed_summaries.py

Corrige les articles dont le Résumé contient un message d'erreur API.
Pour chaque article affecté :
  1. Récupère le texte de l'article depuis son URL
  2. Régénère le résumé via l'API EurIA
  3. Régénère les entités NER
  4. Sauvegarde le fichier JSON mis à jour

Usage :
    python3 scripts/repair_failed_summaries.py [--dry-run] [--dir data/articles-from-rss]
"""

import argparse
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.api_client import get_ai_client, get_summary_client
from utils.http_utils import fetch_and_extract_text
from utils.logging import print_console

ERROR_PREFIX = "Désolé, je n'ai pas pu obtenir de réponse"


def is_error_summary(resume: str) -> bool:
    return isinstance(resume, str) and resume.startswith(ERROR_PREFIX)


def repair_file(path: Path, client, dry_run: bool, delay: float) -> tuple[int, int]:
    """Répare les résumés en erreur dans un fichier JSON.

    Returns:
        (nb_réparés, nb_échecs)
    """
    with open(path, "r", encoding="utf-8") as f:
        articles = json.load(f)

    if not isinstance(articles, list):
        print_console(f"  Ignoré (format non-liste) : {path.name}", level="warning")
        return 0, 0

    repaired = 0
    failed = 0
    modified = False

    for i, article in enumerate(articles):
        if not isinstance(article, dict):
            continue
        resume = article.get("Résumé", "")
        if not is_error_summary(resume):
            continue

        url = article.get("URL", "")
        titre = article.get("Titre", article.get("Sources", "?"))
        print_console(f"  [{i+1}] Réparation : {titre[:60]}...")

        if dry_run:
            print_console(f"       [DRY-RUN] URL : {url}", level="debug")
            repaired += 1
            continue

        # Récupérer le texte
        text = fetch_and_extract_text(url)

        # Générer le résumé
        try:
            new_resume = client.generate_summary(text, max_lines=20)
        except RuntimeError as e:
            print_console(f"       Echec résumé : {e}", level="error")
            failed += 1
            if delay:
                time.sleep(delay)
            continue

        article["Résumé"] = new_resume
        modified = True

        # Régénérer les entités NER
        new_entities = client.generate_entities(new_resume)
        if new_entities:
            article["entities"] = new_entities
        elif "entities" in article:
            del article["entities"]

        print_console(f"       ✓ Résumé régénéré ({len(new_resume)} car.)")
        repaired += 1

        if delay:
            time.sleep(delay)

    if modified and not dry_run:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(articles, f, ensure_ascii=False, indent=4)
        print_console(f"  ✓ Fichier sauvegardé : {path.name}")

    return repaired, failed


def main():
    parser = argparse.ArgumentParser(description="Répare les résumés en erreur dans les JSON.")
    parser.add_argument(
        "--dir",
        default="data/articles-from-rss",
        help="Répertoire à scanner (défaut: data/articles-from-rss)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Affiche les articles à réparer sans appeler l'API"
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="Délai en secondes entre les appels API (défaut: 1.0)"
    )
    args = parser.parse_args()

    scan_dir = PROJECT_ROOT / args.dir
    if not scan_dir.exists():
        print_console(f"Répertoire introuvable : {scan_dir}", level="error")
        sys.exit(1)

    # Trouver tous les JSON (hors cache)
    json_files = sorted(
        p for p in scan_dir.rglob("*.json")
        if "cache" not in p.parts
    )
    print_console(f"Scan de {len(json_files)} fichier(s) dans {scan_dir}...")

    # Compter les articles à réparer
    total_errors = 0
    affected_files = []
    for path in json_files:
        try:
            with open(path) as f:
                data = json.load(f)
            if not isinstance(data, list):
                continue
            n = sum(1 for a in data if isinstance(a, dict) and is_error_summary(a.get("Résumé", "")))
            if n:
                total_errors += n
                affected_files.append((path, n))
        except Exception as e:
            print_console(f"  ERR lecture {path}: {e}", level="error")

    print_console(f"{total_errors} article(s) à réparer dans {len(affected_files)} fichier(s).")

    if total_errors == 0:
        print_console("Aucun article à réparer. Terminé.")
        return

    if args.dry_run:
        print_console("[DRY-RUN] Aucun appel API, aucune écriture.")
        for path, n in affected_files:
            print_console(f"  {n:3d} erreur(s) : {path.relative_to(PROJECT_ROOT)}")
        return

    # Initialiser le client
    client = get_summary_client()

    total_repaired = 0
    total_failed = 0

    for path, n in affected_files:
        print_console(f"\nFichier : {path.relative_to(PROJECT_ROOT)} ({n} à réparer)")
        r, f = repair_file(path, client, dry_run=False, delay=args.delay)
        total_repaired += r
        total_failed += f

    print_console(f"\n=== Résultat ===")
    print_console(f"  Réparés  : {total_repaired}")
    print_console(f"  Échecs   : {total_failed}")
    print_console(f"  Total    : {total_errors}")


if __name__ == "__main__":
    main()
