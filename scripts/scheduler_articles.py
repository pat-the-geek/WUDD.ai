#!/usr/bin/env python3
"""
Scheduler intelligent pour l'exécution automatique de Get_data_from_JSONFile_AskSummary_v2.py

- Planifie au moins une exécution mensuelle (1er au dernier jour du mois)
- Analyse le nombre de nouveaux articles chaque semaine
- Utilise l'IA EurIA pour recommander des fréquences supplémentaires si besoin
- Lance des éditions intermédiaires si >10 nouveaux articles détectés

Usage :
    python scheduler_articles.py
"""

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
import json
import subprocess
import calendar
import time

# Ajouter le répertoire parent au PYTHONPATH pour importer utils
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))

from utils.logging import print_console, setup_logger, default_logger

from utils.config import get_config
from utils.api_client import get_ai_client
from utils.scheduler_toggle import should_run_task

def charger_flux_config(flux_config_path: Path) -> list:
    with open(flux_config_path, 'r', encoding='utf-8') as f:
        return json.load(f)

def normaliser_nom_flux(title: str) -> str:
    return title.strip().replace(' ', '-').replace('\u00a0', '-')

logger = setup_logger(__name__)

# Chemin du script principal
SCRIPT_PATH = SCRIPT_DIR / "Get_data_from_JSONFile_AskSummary_v2.py"

# Fréquence minimale : 1 fois par mois
MIN_FREQ_DAYS = 28


def get_last_day_of_month(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


def get_new_articles_count(json_path: Path, last_run_date: str) -> int:
    """Compte le nombre d'articles publiés après la dernière exécution."""
    if not json_path.exists():
        return 0
    with open(json_path, 'r', encoding='utf-8') as f:
        articles = json.load(f)
    count = 0
    for art in articles:
        date_pub = art.get("Date de publication", "")
        if date_pub > last_run_date:
            count += 1
    return count


def ask_euria_for_schedule(nb_new_articles: int, freq_history: list) -> dict:
    """Demande à l'IA EurIA une recommandation de fréquence."""
    prompt = (
        f"Il y a eu {nb_new_articles} nouveaux articles cette semaine. "
        f"Historique des fréquences d'exécution: {freq_history}. "
        "Propose une fréquence optimale (en jours) pour lancer la génération de résumés, "
        "en tenant compte du volume d'actualités. Si le volume est faible, recommande 1 fois par mois. "
        "Si le volume est élevé, propose plusieurs exécutions par mois. Donne la fréquence en jours et justifie brièvement."
    )
    client = get_ai_client()
    try:
        result = client.generate_summary(prompt, max_lines=5, timeout=60)
        return {"recommendation": result}
    except Exception as e:
        logger.error(f"Erreur IA EurIA pour la planification: {e}")
        return {"recommendation": "30 (défaut)"}



def run_main_script(flux_nom: str, date_debut: str, date_fin: str):
    cmd = [sys.executable, str(SCRIPT_PATH), '--flux', flux_nom, '--date_debut', date_debut, '--date_fin', date_fin]
    print_console(f"Lancement: {' '.join(cmd)}", level="info")
    subprocess.run(cmd, check=True)


def main():
    if not should_run_task("reports.collecte_multi_flux"):
        return

    print_console("=" * 80, level="info")
    print_console("Démarrage du scheduler intelligent d'articles", level="info")
    print_console("=" * 80, level="info")

    config = get_config()
    now = datetime.now()
    year, month = now.year, now.month
    last_day = get_last_day_of_month(year, month)
    date_debut = f"{year}-{month:02d}-01"
    date_fin = f"{year}-{month:02d}-{last_day:02d}"

    # Charger la config multi-flux
    flux_config_path = config.config_dir / "flux_json_sources.json"
    flux_list = charger_flux_config(flux_config_path)

    for flux in flux_list:
        flux_nom = normaliser_nom_flux(flux["title"])
        print_console(f"\n--- Planification pour le flux : {flux_nom} ---", level="info")
        data_dir = config.data_articles_dir / flux_nom
        data_dir.mkdir(parents=True, exist_ok=True)
        json_path = data_dir / f"articles_generated_{date_debut}_{date_fin}.json"

        # Historique des fréquences (à améliorer: stocker dans un fichier)
        freq_history = [30]

        # 1. Exécution mensuelle obligatoire si pas déjà fait
        if not json_path.exists():
            print_console(f"Aucune édition mensuelle trouvée pour {date_debut} à {date_fin}. Lancement...", level="info")
            run_main_script(flux_nom, date_debut, date_fin)
            last_run_date = date_fin
        else:
            print_console(f"Édition mensuelle déjà générée pour {date_debut} à {date_fin}", level="info")
            last_run_date = date_fin

        # 2. Chaque semaine: vérifier le nombre de nouveaux articles
        semaine_debut = (now - timedelta(days=now.weekday())).strftime("%Y-%m-%d")
        semaine_fin = now.strftime("%Y-%m-%d")
        nb_new = get_new_articles_count(json_path, semaine_debut)
        print_console(f"Nouveaux articles depuis {semaine_debut}: {nb_new}", level="info")

        # 3. Si >10 nouveaux articles, lancer une édition intermédiaire
        if nb_new >= 10:
            print_console(f"Plus de 10 nouveaux articles cette semaine, lancement d'une édition intermédiaire...", level="info")
            run_main_script(flux_nom, semaine_debut, semaine_fin)
            freq_history.append(7)
        else:
            print_console(f"Moins de 10 nouveaux articles cette semaine, pas d'édition intermédiaire.", level="info")
            freq_history.append(30)

        # 4. Demander à l'IA une recommandation de fréquence
        ia_result = ask_euria_for_schedule(nb_new, freq_history)
        print_console(f"Recommandation IA pour la fréquence: {ia_result['recommendation']}", level="info")

    print_console("=" * 80)
    print_console("Scheduler terminé.")
    print_console("=" * 80)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print_console("\nInterruption par l'utilisateur")
        sys.exit(130)
    except Exception as e:
        logger.exception(f"Erreur fatale : {e}")
        sys.exit(1)
