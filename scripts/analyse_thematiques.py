#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Analyse des thématiques sociétales dans les articles collectés.

Lit les mots-clés depuis config/thematiques_societales.json.
Scanne récursivement data/articles/ ET data/articles-from-rss/.
"""


import json
import os
from collections import Counter
from datetime import datetime
import sys

# Import du logger centralisé
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.logging import print_console, setup_logger
logger = setup_logger("AnalyseActualites")

# Définir le répertoire du projet
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
DATA_DIRS = [
    os.path.join(PROJECT_ROOT, "data", "articles"),
    os.path.join(PROJECT_ROOT, "data", "articles-from-rss"),
]
CONFIG_THEMATIQUES = os.path.join(PROJECT_ROOT, "config", "thematiques_societales.json")


def _charger_thematiques() -> dict[str, list[str]]:
    """Charge les mots-clés depuis config/thematiques_societales.json.

    Retourne un dict {nom_thematique: [mots_cles]}.
    Repli sur un dict intégré minimal si le fichier est absent.
    """
    try:
        with open(CONFIG_THEMATIQUES, encoding="utf-8") as f:
            cfg = json.load(f)
        thematiques = {}
        for nom, data in cfg.get("thematiques", {}).items():
            mots = data.get("mots_cles", [])
            if mots:
                thematiques[nom] = [m.lower() for m in mots]
        if thematiques:
            print_console(f"  {len(thematiques)} thématiques chargées depuis config/")
            return thematiques
    except Exception as e:
        print_console(f"  Impossible de lire {CONFIG_THEMATIQUES} : {e}", level="warning")

    # Repli minimal intégré
    print_console("  Utilisation des mots-clés intégrés (repli).", level="warning")
    return {
        "Intelligence Artificielle & Technologie": [
            "ia", "intelligence artificielle", "chatgpt", "gemini", "mistral",
            "openai", "modèle", "algorithme", "llm", "machine learning",
        ],
        "Économie & Entreprises": [
            "économie", "entreprise", "marché", "investissement",
        ],
        "Politique & Géopolitique": [
            "gouvernement", "état", "ministère", "régulation", "loi",
        ],
        "Santé": [
            "santé", "médical", "cancer", "patient", "maladie",
        ],
    }


def charger_articles() -> list[dict]:
    """Charge tous les fichiers JSON de data/articles/ et data/articles-from-rss/ (récursif)."""
    from pathlib import Path

    articles: list[dict] = []
    total_fichiers = 0

    for data_dir in DATA_DIRS:
        dir_path = Path(data_dir)
        if not dir_path.exists():
            continue
        json_files = sorted(dir_path.rglob("*.json"))
        # Exclure les caches et 48-heures.json (agrégat redondant)
        json_files = [
            f for f in json_files
            if "cache" not in f.parts
            and f.name != "48-heures.json"
        ]
        print_console(f"  Scan {dir_path.name}/ : {len(json_files)} fichier(s)")
        for fichier in json_files:
            try:
                data = json.loads(fichier.read_text(encoding="utf-8", errors="replace"))
                if isinstance(data, list):
                    articles.extend(data)
                    total_fichiers += 1
            except Exception as e:
                print_console(f"  ✗ {fichier.name} : {e}", level="error")

    print_console(f"Total : {len(articles)} articles chargés depuis {total_fichiers} fichier(s)")
    return articles


def analyser_thematiques(articles: list[dict], thematiques: dict[str, list[str]]):
    """Analyse les thématiques sociétales présentes dans les articles."""
    compteur_thematiques: Counter = Counter()
    articles_par_thematique: dict[str, list[dict]] = {t: [] for t in thematiques}
    articles_valides = 0

    for article in articles:
        resume = article.get("Résumé", "").lower()
        source = article.get("Sources", "N/A")
        url = article.get("URL", "N/A")
        date = article.get("Date de publication", "N/A")

        if any(kw in resume for kw in (
            "impossible de résumer", "accès refusé", "erreur", "error"
        )):
            continue

        articles_valides += 1

        for theme, mots_cles in thematiques.items():
            for mot in mots_cles:
                if mot in resume:
                    compteur_thematiques[theme] += 1
                    if len(articles_par_thematique[theme]) < 3:
                        articles_par_thematique[theme].append({
                            "date": date,
                            "source": source,
                            "url": url,
                            "extrait": resume[:200] + "…" if len(resume) > 200 else resume,
                        })
                    break

    return compteur_thematiques, articles_par_thematique, articles_valides


def afficher_resultats(compteur, exemples, total, total_valides):
    """Affiche les résultats de l'analyse."""
    print("\n" + "=" * 90)
    print(" " * 20 + "ANALYSE DES THÉMATIQUES SOCIÉTALES")
    print("=" * 90)
    print(f"\n📊 Corpus analysé : {total} articles totaux, {total_valides} avec résumés valides")
    print(f"📅 Date d'analyse : {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print("\n" + "=" * 90)

    for i, (theme, count) in enumerate(compteur.most_common(), 1):
        pourcentage = (count / total_valides * 100) if total_valides > 0 else 0
        print(f"\n{i}. {theme.upper()}")
        print("─" * 90)
        print(f"   Mentions : {count} ({pourcentage:.1f}% des articles)")

        if exemples.get(theme):
            print(f"   Exemples d'articles ({len(exemples[theme])}) :")
            for j, ex in enumerate(exemples[theme], 1):
                date_str = ex["date"][:10] if ex["date"] != "N/A" else "N/A"
                print(f"\n   [{j}] {ex['source']}")
                print(f"       Date : {date_str}")
                print(f"       {ex['extrait']}")

    print("\n" + "=" * 90)
    print("Analyse terminée.")
    print("=" * 90)


def main():
    """Fonction principale."""
    print_console("Démarrage de l'analyse des thématiques sociétales…")

    thematiques = _charger_thematiques()
    articles = charger_articles()

    if not articles:
        print_console("Aucun article à analyser.")
        return

    print_console("Analyse en cours…")
    compteur, exemples, articles_valides = analyser_thematiques(articles, thematiques)

    afficher_resultats(compteur, exemples, len(articles), articles_valides)


if __name__ == "__main__":
    main()
