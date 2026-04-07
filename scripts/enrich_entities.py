#!/usr/bin/env python3
"""Script d'enrichissement des articles existants avec les entités nommées.

Parcourt les fichiers JSON dans data/articles/ et data/articles-from-rss/
et ajoute le champ "entities" (entités nommées NER) aux articles qui n'en
ont pas, en interrogeant l'API EurIA sur la base du champ "Résumé" existant.

Usage:
    # Tout traiter (dry-run : aucun appel API, aucune sauvegarde)
    python3 scripts/enrich_entities.py --dry-run

    # Tout traiter pour de vrai (flux + rss)
    python3 scripts/enrich_entities.py

    # Un flux spécifique (data/articles/<flux>/)
    python3 scripts/enrich_entities.py --flux Intelligence-artificielle

    # Un mot-clé spécifique (data/articles-from-rss/<keyword>.json)
    python3 scripts/enrich_entities.py --keyword anthropic

    # Délai entre appels API (secondes, défaut 1.0)
    python3 scripts/enrich_entities.py --delay 2.0

    # Re-forcer même les articles déjà enrichis
    python3 scripts/enrich_entities.py --force
"""

import json
import sys
import time
import argparse
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))

from utils.logging import print_console, setup_logger
from utils.config import get_config
from utils.api_client import get_ai_client, get_ner_client
from utils.article_index import get_article_index
from utils.entity_index import get_entity_index

logger = setup_logger(__name__)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Enrichit les articles JSON existants avec les entités nommées."
    )
    parser.add_argument(
        "--flux",
        type=str,
        default=None,
        help="Traiter uniquement ce flux (sous-répertoire de data/articles/). "
             "Si absent et --keyword absent : tous les flux sont traités.",
    )
    parser.add_argument(
        "--keyword",
        type=str,
        default=None,
        help="Traiter uniquement ce mot-clé (fichier dans data/articles-from-rss/). "
             "Si absent et --flux absent : tous les mots-clés sont traités.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Affiche ce qui serait traité sans appeler l'API ni sauvegarder.",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="Délai en secondes entre chaque appel API (défaut : 1.0).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-extraire les entités même si le champ 'entities' existe déjà.",
    )
    return parser.parse_args()



def collect_flux_files(articles_dir: Path, flux_filter: str | None) -> list[tuple[Path, str]]:
    """Retourne les fichiers de data/articles/ avec leur label d'affichage.

    Chaque élément est un tuple (chemin, label) où label = "flux/<nom_flux>".
    """
    if not articles_dir.is_dir():
        return []

    if flux_filter:
        flux_dir = articles_dir / flux_filter
        if not flux_dir.is_dir():
            print_console(f"Flux introuvable : {flux_dir}", level="error")
            sys.exit(1)
        dirs = [flux_dir]
    else:
        dirs = sorted([d for d in articles_dir.iterdir() if d.is_dir() and d.name != "cache"])

    result = []
    for d in dirs:
        for f in sorted(d.glob("articles_generated_*.json")):
            result.append((f, f"flux/{d.name}"))
    return result


def collect_rss_files(rss_dir: Path, keyword_filter: str | None) -> list[tuple[Path, str]]:
    """Retourne les fichiers de data/articles-from-rss/ avec leur label d'affichage.

    Chaque élément est un tuple (chemin, label) où label = "rss/<mot-clé>".
    """
    if not rss_dir.is_dir():
        return []

    if keyword_filter:
        candidate = rss_dir / f"{keyword_filter}.json"
        if not candidate.is_file():
            print_console(f"Mot-clé introuvable : {candidate}", level="error")
            sys.exit(1)
        return [(candidate, f"rss/{keyword_filter}")]

    return [
        (f, f"rss/{f.stem}")
        for f in sorted(rss_dir.glob("*.json"))
        if f.is_file()
    ]


def enrich_file(
    json_file: Path,
    api_client,
    dry_run: bool,
    delay: float,
    force: bool,
) -> dict:
    """Enrichit un fichier JSON avec les entités. Retourne les stats du fichier."""
    stats = {"total": 0, "enrichis": 0, "deja_presents": 0, "erreurs": 0, "ignores": 0}

    with open(json_file, "r", encoding="utf-8") as f:
        try:
            articles = json.load(f)
        except json.JSONDecodeError as e:
            print_console(f"  JSON invalide ({json_file.name}) : {e}", level="error")
            return stats

    if not isinstance(articles, list):
        print_console(f"  Format inattendu (pas une liste) : {json_file.name}", level="warning")
        return stats

    modified = False

    for i, article in enumerate(articles):
        stats["total"] += 1

        resume = article.get("Résumé", "").strip()
        if not resume:
            stats["ignores"] += 1
            continue

        if article.get("entities") and not force:
            stats["deja_presents"] += 1
            continue

        if dry_run:
            print_console(
                f"    [DRY-RUN] Article {i+1} — {article.get('Sources', '?')} "
                f"({len(resume)} car.) → serait enrichi",
                level="info",
            )
            stats["enrichis"] += 1
            continue

        # Appel API via generate_entities() (parsing inclus)
        entities = api_client.generate_entities(resume, timeout=60)
        if entities is None:
            # echec_parse : réponse reçue mais JSON non extractible
            article["enrichissement_statut"] = "echec_parse"
            modified = True
            stats["erreurs"] += 1
            print_console(
                f"    Article {i+1}/{len(articles)} — {article.get('Sources', '?')} "
                f"→ réponse non parseable (echec_parse)",
                level="error",
            )
        elif entities:
            article["entities"] = entities
            article["enrichissement_statut"] = "ok"
            modified = True
            stats["enrichis"] += 1
            nb_entites = sum(len(v) for v in entities.values())
            print_console(
                f"    Article {i+1}/{len(articles)} — {article.get('Sources', '?')} "
                f"→ {nb_entites} entités ({len(entities)} types)",
                level="debug",
            )
        else:
            # {} : echec_api (exception réseau) ou aucune entité trouvée
            article["enrichissement_statut"] = "echec_api"
            modified = True
            stats["erreurs"] += 1
            print_console(
                f"    Article {i+1}/{len(articles)} — {article.get('Sources', '?')} "
                f"→ réponse vide ou erreur API",
                level="error",
            )

        if delay > 0:
            time.sleep(delay)

    # Sauvegarder uniquement si le fichier a été modifié
    if modified and not dry_run:
        tmp = json_file.with_suffix(".tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(articles, f, ensure_ascii=False, indent=4)
            tmp.replace(json_file)
            # Mise à jour des indexes après sauvegarde (proposition 1)
            rel = str(json_file.relative_to(PROJECT_ROOT)).replace("\\", "/")
            try:
                get_article_index(PROJECT_ROOT).update(articles, rel)
                if any("entities" in a for a in articles):
                    get_entity_index(PROJECT_ROOT).update(articles, rel)
            except Exception as _idx_e:
                print_console(f"  Avertissement : index non mis à jour ({_idx_e})", level="warning")
        except Exception as e:
            print_console(f"  Erreur de sauvegarde : {e}", level="error")
            if tmp.exists():
                tmp.unlink()

    return stats


def main():
    print_console("=" * 70, level="info")
    print_console("Enrichissement des articles avec les entités nommées (NER)", level="info")
    print_console("=" * 70, level="info")

    args = parse_args()

    try:
        config = get_config()
    except ValueError as e:
        logger.error(f"Erreur de configuration : {e}")
        sys.exit(1)

    articles_dir = config.data_articles_dir
    rss_dir = articles_dir.parent / "articles-from-rss"

    # Construire la liste des fichiers à traiter selon les filtres
    # - --flux seul  → uniquement data/articles/<flux>/
    # - --keyword seul → uniquement data/articles-from-rss/<keyword>.json
    # - les deux     → les deux sources filtrées
    # - aucun filtre → toutes les sources
    process_flux = args.flux is not None or args.keyword is None
    process_rss = args.keyword is not None or args.flux is None

    tagged_files: list[tuple[Path, str]] = []
    if process_flux:
        tagged_files += collect_flux_files(articles_dir, args.flux)
    if process_rss:
        tagged_files += collect_rss_files(rss_dir, args.keyword)

    if not tagged_files:
        print_console("Aucun fichier JSON trouvé.", level="warning")
        sys.exit(0)

    nb_flux = sum(1 for _, lbl in tagged_files if lbl.startswith("flux/"))
    nb_rss = sum(1 for _, lbl in tagged_files if lbl.startswith("rss/"))
    print_console(
        f"{len(tagged_files)} fichier(s) à traiter "
        f"({nb_flux} flux, {nb_rss} rss)",
        level="info",
    )
    if args.dry_run:
        print_console("[MODE DRY-RUN — aucun appel API, aucune sauvegarde]", level="info")
    print_console("", level="info")

    api_client = None if args.dry_run else get_ner_client()

    totaux = {"total": 0, "enrichis": 0, "deja_presents": 0, "erreurs": 0, "ignores": 0}

    for json_file, label in tagged_files:
        print_console(f"[{label}] {json_file.name}", level="info")

        stats = enrich_file(json_file, api_client, args.dry_run, args.delay, args.force)

        print_console(
            f"  total={stats['total']}  enrichis={stats['enrichis']}  "
            f"existants={stats['deja_presents']}  erreurs={stats['erreurs']}  "
            f"ignorés={stats['ignores']}",
            level="info",
        )
        for k in totaux:
            totaux[k] += stats[k]

    print_console("", level="info")
    print_console("=" * 70, level="info")
    print_console(
        f"Terminé — {totaux['enrichis']} article(s) enrichi(s) sur {totaux['total']} "
        f"({totaux['erreurs']} erreur(s), {totaux['deja_presents']} déjà présent(s))",
        level="info",
    )
    print_console("=" * 70, level="info")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print_console("\nInterruption par l'utilisateur", level="warning")
        sys.exit(130)
    except Exception as e:
        logger.exception(f"Erreur fatale : {e}")
        sys.exit(1)
