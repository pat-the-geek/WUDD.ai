"""
Script : generate_keyword_reports.py

Pour chaque fichier JSON du répertoire data/articles-from-rss/
- Détecte le mot-clé à partir du nom du fichier (ex : intelligence-artificielle.json)
- Sélectionne la période :
    - Date de début = 1er jour du mois courant
    - Date de fin = dernier jour du mois courant
- Génère un rapport Markdown pour ce mot-clé et cette période
- Le rapport est sauvegardé dans rapports/Markdown/keyword sous le nom :
    <keyword>_rapport_<date_debut>_<date_fin>.md
- Utilise la méthode de génération de rapport IA (API EurIA) déjà utilisée dans le projet
"""

import os
import sys
import json
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ARTICLES_DIR = PROJECT_ROOT / "data/articles-from-rss"

RAPPORTS_BASE_DIR = PROJECT_ROOT / "rapports/markdown/keyword"
RAPPORTS_BASE_DIR.mkdir(parents=True, exist_ok=True)

# Ajout du dossier racine au sys.path pour les imports relatifs (utils.*)
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.api_client import get_ai_client
from utils.logging import print_console
from utils.date_utils import parse_article_date
from utils.report_cleanup import cleanup_old_dated_reports

def get_month_period():
    now = datetime.now()
    date_debut = now.replace(day=1).strftime("%Y-%m-%d")
    # Dernier jour du mois
    next_month = now.replace(day=28) + timedelta(days=4)
    last_day = (next_month - timedelta(days=next_month.day)).day
    date_fin = now.replace(day=last_day).strftime("%Y-%m-%d")
    return date_debut, date_fin

def main():
    date_debut, date_fin = get_month_period()
    api_client = get_ai_client()
    json_files = list(ARTICLES_DIR.glob("*.json"))
    total_files = len(json_files)
    print_console(f"Début génération des rapports par mot-clé ({total_files} fichiers à traiter)")
    for idx, json_file in enumerate(json_files, 1):
        keyword = json_file.stem.replace("-", " ").title()
        print_console(f"[{idx}/{total_files}] Traitement du mot-clé : {keyword} ({json_file.name})")
        try:
            with open(json_file, "r", encoding="utf-8") as f:
                articles = json.load(f)
        except Exception as e:
            print_console(f"Erreur lecture fichier {json_file.name} : {e}", level="error")
            continue
        # Filtrer les articles par période
        filtered = []
        for article in articles:
            pub_date = article.get("Date de publication", "")
            # Corpus mixte ISO 8601 (avec/sans Z) / DD/MM/YYYY / RFC 2822.
            pub_dt = parse_article_date(pub_date)
            if not pub_dt:
                print_console(f"  Article ignoré (date non reconnue) : {pub_date}", level="warning")
                continue
            if date_debut <= pub_dt.strftime("%Y-%m-%d") <= date_fin:
                filtered.append(article)
        print_console(f"  {len(filtered)} articles retenus pour {keyword} sur la période {date_debut} à {date_fin}")
        if not filtered:
            print_console(f"Aucun article pour {keyword} sur la période {date_debut} à {date_fin}")
            continue
        # Générer le rapport Markdown via IA
        json_content = json.dumps(filtered, ensure_ascii=False, indent=2)
        filename = f"{keyword}_rapport_{date_debut}_{date_fin}.md"
        rapport_dir = RAPPORTS_BASE_DIR / keyword.replace(" ", "").replace("-", "").lower()
        rapport_dir.mkdir(parents=True, exist_ok=True)
        rapport_path = rapport_dir / filename
        print_console(f"Génération du rapport IA pour {keyword}...")
        try:
            rapport_md = api_client.generate_report(json_content, filename)
            with open(rapport_path, "w", encoding="utf-8") as f:
                f.write(rapport_md)
            print_console(f"✓ Rapport généré : {rapport_path}")
            cleanup_old_dated_reports(rapport_path)
        except Exception as e:
            print_console(f"Erreur génération rapport pour {keyword} : {e}", level="error")

if __name__ == "__main__":
    main()
