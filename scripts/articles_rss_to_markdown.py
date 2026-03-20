"""
Script : articles_rss_to_markdown.py

Pour chaque fichier JSON dans data/articles-from-rss/ :
  - Convertit les articles en Markdown avec annotation inline des entités nommées
  - Sauvegarde dans rapports/markdown/keyword/<mot-clé>/<mot-clé>_<YYYY-MM-DD>.md

Usage :
    python3 scripts/articles_rss_to_markdown.py
    python3 scripts/articles_rss_to_markdown.py --keyword anthropic
"""

import argparse
import calendar
import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.articles_json_to_markdown import json_to_markdown
from utils.logging import print_console

ARTICLES_DIR = PROJECT_ROOT / "data" / "articles-from-rss"
RAPPORTS_BASE = PROJECT_ROOT / "rapports" / "markdown" / "keyword"


def _get_month_range():
    """Retourne (premier_jour, dernier_jour) du mois courant."""
    now = datetime.now()
    last_day_num = calendar.monthrange(now.year, now.month)[1]
    first_day = datetime(now.year, now.month, 1)
    last_day = datetime(now.year, now.month, last_day_num, 23, 59, 59)
    return first_day, last_day


def _parse_pub_date(date_str: str):
    """Parse une date dans tous les formats du pipeline (RFC 822, DD/MM/YYYY, ISO 8601)."""
    if not date_str:
        return None
    date_str = date_str.strip()
    # ISO 8601
    for fmt, length in (("%Y-%m-%dT%H:%M:%SZ", 20), ("%Y-%m-%dT%H:%M:%S", 19), ("%Y-%m-%d", 10)):
        try:
            return datetime.strptime(date_str[:length], fmt)
        except (ValueError, TypeError):
            continue
    # DD/MM/YYYY — format web_watcher.py
    try:
        return datetime.strptime(date_str[:10], "%d/%m/%Y")
    except (ValueError, TypeError):
        pass
    # RFC 822 (flux_watcher.py / get-keyword-from-rss.py)
    try:
        return datetime.strptime(date_str[:25], "%a, %d %b %Y %H:%M:%S")
    except (ValueError, TypeError):
        pass
    try:
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(date_str).replace(tzinfo=None)
    except Exception:
        return None


def process_file(json_file: Path) -> None:
    keyword_slug = json_file.stem          # ex: "intelligence-artificielle"
    first_day, last_day = _get_month_range()
    month_start = first_day.strftime("%Y-%m-%d")
    month_end = last_day.strftime("%Y-%m-%d")

    # Charger et filtrer les articles du mois courant
    with open(json_file, "r", encoding="utf-8") as f:
        articles = json.load(f)

    filtered = [
        a for a in articles
        if (dt := _parse_pub_date(a.get("Date de publication", ""))) is not None
        and first_day <= dt <= last_day
    ]

    if not filtered:
        print_console(f"Aucun article pour {month_start}/{month_end} dans {json_file.name}", level="warning")
        return

    rapport_dir = RAPPORTS_BASE / keyword_slug
    rapport_dir.mkdir(parents=True, exist_ok=True)
    output_file = rapport_dir / f"{keyword_slug}_{month_start}_{month_end}.md"

    # Écriture dans un fichier temporaire pour compatibilité avec json_to_markdown()
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as tmp:
        json.dump(filtered, tmp, ensure_ascii=False)
        tmp_path = tmp.name

    try:
        print_console(f"Conversion : {json_file.name} ({len(filtered)} articles du {month_start} au {month_end}) → {output_file.relative_to(PROJECT_ROOT)}")
        json_to_markdown(tmp_path, str(output_file))
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(
        description="Convertit tous les fichiers articles-from-rss en Markdown (nouveau format)"
    )
    parser.add_argument(
        "--keyword",
        help="Traiter uniquement ce mot-clé (slug du nom de fichier, ex: anthropic)",
    )
    args = parser.parse_args()

    if args.keyword:
        target = ARTICLES_DIR / f"{args.keyword}.json"
        if not target.exists():
            print_console(f"Fichier introuvable : {target}", level="error")
            sys.exit(1)
        json_files = [target]
    else:
        json_files = sorted(ARTICLES_DIR.glob("*.json"))

    if not json_files:
        print_console("Aucun fichier JSON trouvé dans data/articles-from-rss/", level="warning")
        sys.exit(0)

    print_console(f"Début conversion RSS→Markdown ({len(json_files)} fichier(s))")
    for json_file in json_files:
        try:
            process_file(json_file)
        except Exception as e:
            print_console(f"Erreur sur {json_file.name} : {e}", level="error")

    print_console(f"Terminé — {len(json_files)} rapport(s) générés dans {RAPPORTS_BASE.relative_to(PROJECT_ROOT)}/")


if __name__ == "__main__":
    main()
