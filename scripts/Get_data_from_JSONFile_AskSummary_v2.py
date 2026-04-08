#!/usr/bin/env python3
"""Script optimisé de génération de résumés d'articles d'actualité.

Version améliorée avec:
- Traitement parallèle pour extraction de texte
- Cache pour éviter requêtes redondantes
- Gestion d'erreurs robuste
- Logging centralisé
- Configuration centralisée

Usage:
    python Get_data_from_JSONFile_AskSummary_v2.py [date_debut] [date_fin]
    
Exemple:
    python Get_data_from_JSONFile_AskSummary_v2.py 2026-01-01 2026-01-31
"""

import json
import os
import sys
import argparse
from pathlib import Path

# Ajouter le répertoire parent au PYTHONPATH pour importer utils
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))

import requests
from datetime import datetime

# Import des modules utilitaires
from utils.logging import print_console, setup_logger, default_logger
from utils.config import get_config
from utils.api_client import get_ai_client, get_summary_client
from utils.http_utils import fetch_and_extract_text, extract_top_n_largest_images
from utils.date_utils import (
    parse_iso_date,
    verifier_date_entre,
    get_default_date_range,
    validate_date_range
)
from utils.parallel import fetch_articles_parallel
from utils.cache import get_cache


# Configuration du logger
logger = setup_logger(__name__)


def demander_dates() -> tuple[str, str]:
    """Détermine les dates de début et de fin pour le traitement.
    
    Récupère les dates depuis les arguments de ligne de commande (sys.argv[1] et sys.argv[2])
    ou utilise des valeurs par défaut (du 1er jour du mois courant à aujourd'hui).
    
    Returns:
        Un tuple (date_debut, date_fin) au format "YYYY-MM-DD".
    
    Raises:
        ValueError: Si le format de date est invalide ou si date_debut >= date_fin.
    """
    # Les dates sont désormais gérées via argparse
    # Cette fonction n'est plus utilisée directement
    raise NotImplementedError("Utilisez parse_args() pour gérer les dates et le flux.")
def charger_flux_config(flux_config_path: Path) -> list:
    """Charge la liste des flux JSON depuis le fichier de config."""
    with open(flux_config_path, 'r', encoding='utf-8') as f:
        return json.load(f)

def normaliser_nom_flux(title: str) -> str:
    """Normalise le nom du flux (espaces -> tirets)."""
    return title.strip().replace(' ', '-').replace('\u00a0', '-')

def parse_args():
    parser = argparse.ArgumentParser(description="Génération de résumés d'articles multi-flux.")
    parser.add_argument('--flux', type=str, required=True, help="Nom logique du flux à traiter (ex: Intelligence-artificielle)")
    parser.add_argument('--date_debut', type=str, help="Date de début (YYYY-MM-DD)")
    parser.add_argument('--date_fin', type=str, help="Date de fin (YYYY-MM-DD)")
    args = parser.parse_args()
    return args


def fetch_json_feed(url: str, timeout: int = 10) -> dict:
    """Récupère et parse le flux JSON depuis une URL.
    
    Args:
        url: URL du flux JSON
        timeout: Timeout en secondes
    
    Returns:
        Données JSON parsées
    
    Raises:
        SystemExit: En cas d'erreur réseau ou de parsing
    """
    print_console(f"Chargement du flux JSON depuis : {url}", level="info")
    
    try:
        response = requests.get(url, timeout=timeout)
        response.raise_for_status()
        data = response.json()
        print_console(f"Flux JSON chargé avec succès ({len(data.get('items', []))} articles)", level="info")
        return data
        
    except requests.exceptions.HTTPError as e:
        logger.error(f"Erreur HTTP : {e}")
        sys.exit(1)
    except requests.exceptions.ConnectionError:
        logger.error("Erreur de connexion au serveur")
        sys.exit(1)
    except requests.exceptions.Timeout:
        logger.error("La requête a expiré")
        sys.exit(1)
    except requests.exceptions.RequestException as e:
        logger.error(f"Erreur générale de requête : {e}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        logger.error(f"Erreur de parsing JSON : {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Erreur inattendue : {e}")
        sys.exit(1)


def create_report(file_output: Path, api_client) -> None:
    """Génère un rapport synthétique Markdown à partir des articles.
    
    Args:
        file_output: Chemin du fichier JSON source contenant les articles
        api_client: Client API pour générer le rapport
    """
    print_console("Génération du rapport en cours...", level="info")
    
    try:
        with open(file_output, 'r', encoding='utf-8') as jsonfile:
            data = json.load(jsonfile)

        json_str = json.dumps(data, indent=2, ensure_ascii=False)

        # Générer le rapport via l'API
        config = get_config()
        report = api_client.generate_report(
            json_str,
            file_output.name,
            timeout=config.timeout_rapport
        )

        # Déterminer le nom du flux à partir du chemin du fichier output
        flux_title = file_output.parent.name
        rapport_dir = config.rapports_markdown_dir / flux_title
        rapport_dir.mkdir(parents=True, exist_ok=True)
        report_file = rapport_dir / f"rapport_sommaire_{file_output.stem}.md"

        with open(report_file, 'w', encoding='utf-8') as txtfile:
            txtfile.write(report)

        print_console(f"Le rapport a été sauvegardé dans le fichier {report_file}", level="info")

    except Exception as e:
        logger.error(f"Erreur lors de la génération du rapport : {e}")


def main():
    """Fonction principale du script."""
    print_console("=" * 80, level="info")
    print_console("Démarrage du script de génération de résumés d'articles", level="info")
    print_console("Version 2.0 - Optimisée avec traitement parallèle et cache", level="info")
    print_console("=" * 80, level="info")
    
    # Charger la configuration générale
    try:
        config = get_config()
        logger.info("Configuration chargée avec succès")
    except ValueError as e:
        logger.error(f"Erreur de configuration : {e}")
        sys.exit(1)

    # Charger la config multi-flux
    flux_config_path = config.config_dir / "flux_json_sources.json"
    flux_list = charger_flux_config(flux_config_path)

    # Parser les arguments
    args = parse_args()
    flux_nom = args.flux
    date_debut = args.date_debut
    date_fin = args.date_fin

    # Chercher le flux demandé
    flux = None
    for f in flux_list:
        if normaliser_nom_flux(f["title"]) == flux_nom:
            flux = f
            break
    if not flux:
        print_console(f"Flux '{flux_nom}' introuvable. Flux disponibles : " + ", ".join([normaliser_nom_flux(f["title"]) for f in flux_list]), level="error")
        sys.exit(1)

    flux_url = flux["url"]
    flux_title = normaliser_nom_flux(flux["title"])

    # Initialiser le cache
    cache = get_cache(namespace=flux_title)
    stats = cache.get_stats()
    logger.info(f"Cache ({flux_title}) : {stats['entries']} entrées, {stats['total_size_mb']:.2f} MB")

    # Déterminer les dates
    if not date_debut or not date_fin:
        d1, d2 = get_default_date_range()
        date_debut = date_debut or d1
        date_fin = date_fin or d2
    validate_date_range(date_debut, date_fin)

    # Créer le sous-répertoire de sortie pour ce flux
    output_dir = config.data_articles_dir / flux_title
    output_dir.mkdir(parents=True, exist_ok=True)

    # Chargement du flux JSON
    data = fetch_json_feed(flux_url)
    items = data.get('items', [])
    
    if not items:
        logger.warning("Aucun article trouvé dans le flux JSON")
        sys.exit(0)
    
    # Filtrer les articles par date d'abord pour optimiser
    print_console(f"Filtrage des articles entre {date_debut} et {date_fin}...", level="info")
    filtered_items = []
    
    for item in items:
        date_published = item.get('date_published', 'Unknown Date')
        date_obj = parse_iso_date(date_published)
        
        if date_obj:
            date_formatee = date_obj.strftime("%Y-%m-%d")
            if verifier_date_entre(date_formatee, date_debut, date_fin):
                filtered_items.append(item)
    
    print_console(f"{len(filtered_items)} articles correspondent aux dates spécifiées", level="info")
    
    if not filtered_items:
        logger.warning("Aucun article ne correspond aux dates spécifiées")
        sys.exit(0)
    
    # Extraction des textes en parallèle avec cache
    print_console("Extraction des textes en parallèle...", level="info")
    
    def fetch_with_cache(url: str) -> str:
        """Fonction wrapper pour fetch avec cache."""
        # Vérifier le cache d'abord
        cached_text = cache.get(f"text:{url}", ttl=86400)  # 24h
        if cached_text:
            return cached_text
        
        # Sinon extraire et cacher
        text = fetch_and_extract_text(url, timeout=10, max_retries=3)
        cache.set(f"text:{url}", text)
        return text
    
    texts = fetch_articles_parallel(
        filtered_items,
        fetch_with_cache,
        max_workers=5  # 5 requêtes en parallèle
    )
    
    # Initialiser le client API
    api_client = get_summary_client()
    
    # Traitement de chaque article : résumé IA et extraction d'images
    print_console("Génération des résumés...", level="info")
    articles_data = []
    
    for i, item in enumerate(filtered_items, 1):
        url = item.get('url')
        date_published = item.get('date_published', 'Unknown Date')
        
        # Récupérer le texte extrait
        text = texts.get(url, "Failed to retrieve text.")

        # Ignorer les articles inaccessibles (erreur HTTP, timeout, connexion, etc.)
        if text.startswith("Erreur") or text == "Failed to retrieve text.":
            logger.warning(f"Article inaccessible ignoré : {url} — {text[:70]}")
            continue

        # Cache résumé + sentiment combinés (TTL 7 jours)
        resume_sent_cache_key = f"resume_sentiment:{url}:{date_published}"
        cached_combined = cache.get(resume_sent_cache_key, ttl=604800)

        if cached_combined and isinstance(cached_combined, dict):
            # Résultat combiné en cache : résumé + sentiment déjà disponibles
            resume = cached_combined.get("resume", "")
            _sentiment_data = cached_combined
        else:
            # Compatibilité avec l'ancien cache résumé seul (clé "resume:")
            old_cache_key = f"resume:{url}:{date_published}"
            old_resume = cache.get(old_cache_key, ttl=604800)
            if old_resume and isinstance(old_resume, str):
                resume = old_resume
                _sentiment_data = {}  # sera enrichi par le cron enrich_sentiment
            else:
                try:
                    cached_combined = api_client.generate_summary_with_sentiment(
                        text, max_lines=20, timeout=config.timeout_resume
                    )
                    resume = cached_combined.get("resume", "")
                    _sentiment_data = cached_combined
                    cache.set(resume_sent_cache_key, cached_combined)
                except RuntimeError as e:
                    logger.warning(f"Résumé impossible pour '{url}' : {e}")
                    resume = ""
                    _sentiment_data = {}

        # Extraire les entités nommées (avec cache)
        entities_cache_key = f"entities:{url}:{date_published}"
        entities = cache.get(entities_cache_key, ttl=604800)  # 7 jours
        if not entities:
            entities = api_client.generate_entities(resume, timeout=60)
            if entities:
                cache.set(entities_cache_key, entities)

        # Extraire la source
        authors = item.get('authors', [])
        if authors and isinstance(authors, list) and len(authors) > 0:
            source = authors[0].get('name', 'Unknown Source')
        else:
            source = 'Unknown Source'
        
        # Extraire les images (pas de cache car rapide)
        images = extract_top_n_largest_images(url, n=3, min_width=500, timeout=10)
        
        print_console(f"[{i}/{len(filtered_items)}] {source}: {len(resume)} car. | {len(images) if isinstance(images, list) else 0} images", level="debug")
        
        article = {
            "Titre": item.get('title', ''),
            "Date de publication": date_published,
            "Sources": source,
            "URL": url,
            "Résumé": resume,
            "Images": images,
        }
        if entities:
            article["entities"] = entities
        # Sentiment + ton éditorial depuis l'appel combiné (sans coût supplémentaire)
        for _field in ("sentiment", "score_sentiment", "ton_editorial", "score_ton"):
            if _field in _sentiment_data:
                article[_field] = _sentiment_data[_field]
        articles_data.append(article)
    
    # Sauvegarde des résultats dans un fichier JSON (dans le sous-répertoire du flux)
    file_output = output_dir / f"articles_generated_{date_debut}_{date_fin}.json"

    with open(file_output, 'w', encoding='utf-8') as jsonfile:
        json.dump(articles_data, jsonfile, ensure_ascii=False, indent=4)

    print_console("", level="info")
    print_console(f"✓ Les textes de tous les articles ont été sauvés dans {file_output}", level="info")

    # Générer le rapport
    create_report(file_output, api_client)
    
    print_console("=" * 80)
    print_console("Traitement terminé avec succès!")
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
