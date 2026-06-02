#!/usr/bin/env python3
"""
generate_48h_report.py — Rapport quotidien des Top 10 entités des 48 dernières heures

Lit data/articles-from-rss/_WUDD.AI_/48-heures.json, identifie les 10 entités
nommées les plus citées, et génère un rapport analytique via l'API EurIA.

Usage:
    python3 scripts/generate_48h_report.py
    python3 scripts/generate_48h_report.py --dry-run   # Affiche le prompt sans appeler l'API
"""

import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))

from utils.api_client import get_ai_client
from utils.config import get_config
from utils.logging import print_console
from utils.scheduler_toggle import should_run_task
from utils.date_utils import parse_article_date

# Types d'entités pertinentes pour le classement (personnes, orgs, pays, produits, événements)
ENTITY_TYPES_PERTINENTS = {"PERSON", "ORG", "GPE", "PRODUCT", "EVENT", "NORP", "FAC", "LOC"}

# Champ "Date de publication" au format RFC 822 (ex: "Wed, 04 Mar 2026 10:00:00")
DATE_FORMAT_RSS = "%a, %d %b %Y %H:%M:%S"


def _highlight_ner(text: str, entities: dict) -> str:
    """Met en gras les entités NER dans le texte : **Nom** *(TYPE)*.
    Tri par longueur décroissante pour éviter les sous-matches.
    Word-boundary (?<!)\\w)…(?!\\w) pour ne pas toucher les sous-mots.
    """
    pairs = [
        (name, etype)
        for etype, names in entities.items()
        if etype in ENTITY_TYPES_PERTINENTS
        for name in names
        if len(str(name).strip()) >= 3
    ]
    pairs.sort(key=lambda x: len(x[0]), reverse=True)
    seen: set = set()
    for name_clean, etype in pairs:
        key = name_clean.lower()
        if key in seen:
            continue
        seen.add(key)
        pattern = re.compile(
            r'(?<!\w)' + re.escape(name_clean) + r'(?!\w)',
            re.IGNORECASE | re.UNICODE,
        )
        text = pattern.sub(f"**{name_clean}** *({etype})*", text, count=1)
    return text


def compute_top_entities(
    articles: list,
    top_n: int = 10,
    input_file: "Path | None" = None,
) -> list:
    """
    Compte les entités nommées dans les articles et retourne les top N.

    Si `input_file` est fourni et que DuckDB est disponible, lit le fichier
    directement via DuckDB (IO plus rapide pour les grands fichiers, sans
    charger tout le JSON en mémoire Python).

    Returns:
        Liste de tuples (nom_original, type_entité, nb_occurrences)
    """
    # ── Chemin DuckDB (lecture directe du fichier, évite json.load Python) ───
    if input_file is not None:
        try:
            from utils.db import get_db
            db = get_db()
            if db.available:
                rows = db.entity_json_from_file(input_file)
                if rows:
                    counter: Counter = Counter()
                    type_map: dict = {}
                    for row in rows:
                        ents_json = row.get("entities_json")
                        if not ents_json:
                            continue
                        try:
                            ents = json.loads(ents_json)
                        except (ValueError, TypeError):
                            continue
                        if not isinstance(ents, dict):
                            continue
                        for entity_type, names in ents.items():
                            if entity_type not in ENTITY_TYPES_PERTINENTS:
                                continue
                            if not isinstance(names, list):
                                continue
                            for name in names:
                                name_clean = str(name).strip()
                                if len(name_clean) < 3:
                                    continue
                                key = name_clean.lower()
                                counter[key] += 1
                                if key not in type_map:
                                    type_map[key] = (name_clean, entity_type)
                    top = []
                    for key, count in counter.most_common(top_n):
                        name_original, entity_type = type_map[key]
                        top.append((name_original, entity_type, count))
                    return top
        except Exception:
            pass  # bascule sur la méthode Python classique

    counter: Counter = Counter()
    # key = nom normalisé → (nom original, type)
    type_map: dict = {}

    for article in articles:
        entities = article.get("entities", {})
        if not isinstance(entities, dict):
            continue
        for entity_type, names in entities.items():
            if entity_type not in ENTITY_TYPES_PERTINENTS:
                continue
            if not isinstance(names, list):
                continue
            for name in names:
                name_clean = str(name).strip()
                if len(name_clean) < 3:
                    continue
                key = name_clean.lower()
                counter[key] += 1
                if key not in type_map:
                    type_map[key] = (name_clean, entity_type)

    top = []
    for key, count in counter.most_common(top_n):
        name_original, entity_type = type_map[key]
        top.append((name_original, entity_type, count))

    return top


def build_slim_articles(articles: list, top_entities: list, max_per_entity: int = 5) -> list:
    """
    Filtre les articles pour ne garder que ceux qui mentionnent au moins une entité
    du Top 10, à raison de max_per_entity articles par entité.
    Résumé tronqué à 400 chars pour limiter la taille du payload.
    Retourne une liste dédupliquée (par URL), triée par date décroissante.
    """
    # Index entités → clés normalisées
    entity_keys = {name.lower() for name, _, _ in top_entities}

    selected_urls: set = set()
    # Pour chaque entité, on compte combien d'articles on a déjà sélectionnés
    entity_quota: dict = {name.lower(): 0 for name, _, _ in top_entities}

    # Trier les articles par date (les plus récents d'abord)
    # Supporte les formats RFC 822 (flux_watcher) et DD/MM/YYYY (web_watcher)
    def _safe_date(a: dict):
        # Corpus mixte ISO 8601 (avec/sans Z) / DD/MM/YYYY / RFC 2822.
        return parse_article_date(a.get("Date de publication", "")) or datetime.min

    sorted_articles = sorted(articles, key=_safe_date, reverse=True)

    slim = []
    for art in sorted_articles:
        url = art.get("URL", "")
        if not url or url in selected_urls:
            continue
        entities = art.get("entities", {})
        if not isinstance(entities, dict):
            continue

        # Vérifier si cet article mentionne au moins une entité du Top 10
        # et si on a encore du quota pour cette entité
        matched_entity = None
        for etype_list in entities.values():
            if not isinstance(etype_list, list):
                continue
            for name in etype_list:
                key = str(name).strip().lower()
                if key in entity_keys and entity_quota.get(key, 0) < max_per_entity:
                    matched_entity = key
                    break
            if matched_entity:
                break

        if not matched_entity:
            continue

        entity_quota[matched_entity] += 1
        selected_urls.add(url)

        resume = art.get("Résumé", "")[:400]  # 400 chars max par résumé
        resume_highlighted = _highlight_ner(resume, entities)
        entry = {
            "Date de publication": art.get("Date de publication", ""),
            "Sources": art.get("Sources", ""),
            "URL": url,
            "Résumé": resume_highlighted,
            "entities": {
                k: v for k, v in entities.items()
                if k in ENTITY_TYPES_PERTINENTS
            },
        }
        # Inclure au plus une image
        images = art.get("Images", [])
        if images and isinstance(images, list) and len(images) > 0:
            first_img = images[0]
            if isinstance(first_img, dict):
                img_url = first_img.get("URL") or first_img.get("url", "")
                if img_url and img_url.startswith("http"):
                    entry["Image"] = img_url
        slim.append(entry)

    return slim


def build_prompt(slim_articles: list, top_entities: list, today_str: str) -> str:
    """
    Construit le prompt enrichi avec les entités pré-calculées et les articles allégés.
    Le pré-calcul des entités dans le prompt oriente l'IA vers ce qui est demandé
    et réduit le hallucination sur le comptage.
    """
    # Formatage du classement des Top 10 entités
    if top_entities:
        entities_block = "\n".join(
            f"  {i + 1:2d}. **{name}** ({etype}) — cité dans {count} article(s)"
            for i, (name, etype, count) in enumerate(top_entities)
        )
    else:
        entities_block = "  (Aucune entité détectée — les articles sont peut-être non enrichis)"

    # Sérialisation allégée du JSON
    json_str = json.dumps(slim_articles, ensure_ascii=False, indent=2)

    prompt = f"""Tu es un analyste média expert. Tu vas rédiger un rapport de veille d'actualité basé sur les articles des 48 dernières heures (rapport du {today_str}).

---
## TOP 10 ENTITÉS PRÉ-CALCULÉES

Ces entités ont été extraites et comptabilisées automatiquement depuis le champ "entities" de chaque article (types pris en compte : personnes, organisations, pays/villes, produits, événements) :

{entities_block}

---
## INSTRUCTIONS

### SECTION 1 — Analyse par entité (une section H2 par entité du Top 10)

Pour **chacune** des 10 entités listées ci-dessus, rédige une section avec la structure suivante :

**## [Rang]. [Nom de l'entité]** *(type — X article(s))*

**Contexte :** Qui ou qu'est-ce que c'est ? (1-2 phrases encyclopédiques concises)

**Actualité des 48h :** Synthèse factuelle et précise de ce qui s'est passé concernant cette entité durant les 48 dernières heures. Cite chaque article avec *(Source, date)* inline. Si plusieurs articles traitent du même sujet, donne une vue unifiée et cohérente.

**Analyse :** Ce que ces événements révèlent. Tendances à l'œuvre, implications potentielles, signaux faibles à surveiller, contexte plus large. Sois analytique, pas descriptif.

---

### SECTION 2 — Corrélations inter-entités

Identifie 3 à 5 liens significatifs entre entités du Top 10 :
- entités impliquées dans les mêmes événements
- organisations liées à la même personne
- pays concernés par les mêmes tensions ou dynamiques
Formule ces liens comme des insights utiles pour la veille stratégique.

---

### SECTION 3 — Constatations générales

Tire des conclusions sur les 48 dernières heures :
- Quels sujets dominent l'actualité et pourquoi ?
- Quelles dynamiques ou ruptures sont en cours ?
- Quels signaux faibles méritent une attention particulière dans les prochains jours ?
- Y a-t-il des absences notables (sujets attendus peu couverts) ?

---

### SECTION 4 — Tableau de références

En fin de rapport, insère un tableau Markdown complet de tous les articles cités :

| Date | Source | URL |
|------|--------|-----|
(une ligne par article)

---

## CONTRAINTES DE FORMAT

- Langue : **français**, ton journalistique analytique, registre professionnel
- Format : Markdown brut, compatible iA Writer — PAS de balises HTML, PAS de blocs de code (pas de ```) dans ta réponse
- Commence OBLIGATOIREMENT ton rapport par ces lignes exactes (frontmatter YAML, sans aucun bloc de code autour) :
---
title: "Rapport de veille — Top 10 entités · {today_str}"
date: {today_str}
période: 48 dernières heures
articles_analysés: {len(slim_articles)}
---
- Inclure les images disponibles dans les articles au format Markdown standard : `![](URL)` sur une nouvelle ligne, une seule image par section entité, pas de doublon d'URL dans tout le rapport
- Ne mentionne pas que tu as reçu un JSON — rédige directement le rapport

---

## DONNÉES JSON

----- BEGIN FILE CONTENTS -----
{json_str}
----- END FILE CONTENTS -----
"""
    return prompt


def generate_48h_report(dry_run: bool = False) -> None:
    """Point d'entrée principal."""
    config = get_config()
    config.setup_directories()

    input_file = PROJECT_ROOT / "data" / "articles-from-rss" / "_WUDD.AI_" / "48-heures.json"

    if not input_file.exists():
        print_console(f"Fichier 48-heures non trouvé : {input_file}", level="error")
        sys.exit(1)

    print_console(f"Lecture de {input_file}")
    with open(input_file, "r", encoding="utf-8") as f:
        articles = json.load(f)

    if not articles:
        print_console("Aucun article dans 48-heures.json — rapport annulé")
        sys.exit(0)

    print_console(f"{len(articles)} articles chargés")

    # Calcul des top 10 entités (DuckDB si disponible, sinon Python in-memory)
    top_entities = compute_top_entities(articles, top_n=10, input_file=input_file)
    if top_entities:
        print_console("Top 10 entités :")
        for i, (name, etype, count) in enumerate(top_entities, 1):
            print_console(f"  {i:2d}. {name} ({etype}) — {count} article(s)")
    else:
        print_console(
            "Aucune entité détectée — pensez à exécuter enrich_entities.py",
            level="warning"
        )

    # Réduction du JSON : uniquement les articles pertinents pour le Top 10
    slim_articles = build_slim_articles(articles, top_entities, max_per_entity=5)
    print_console(f"{len(slim_articles)} articles sélectionnés pour le rapport ({len(top_entities)} entités × max 5)")

    # Fallback : si aucune entité détectée ou aucun article sélectionné,
    # inclure les 50 articles les plus récents pour que l'IA puisse quand même générer un rapport
    if not slim_articles:
        print_console(
            "Aucun article sélectionné via entités — utilisation des 50 articles les plus récents comme fallback",
            level="warning"
        )

        def _safe_date_fallback(a: dict):
            # Corpus mixte ISO 8601 (avec/sans Z) / DD/MM/YYYY / RFC 2822.
            return parse_article_date(a.get("Date de publication", "")) or datetime.min

        slim_articles = sorted(articles, key=_safe_date_fallback, reverse=True)[:50]
        slim_articles = [
            {
                "Date de publication": a.get("Date de publication", ""),
                "Sources": a.get("Sources", ""),
                "URL": a.get("URL", ""),
                "Résumé": a.get("Résumé", "")[:400],
            }
            for a in slim_articles
        ]
        print_console(f"{len(slim_articles)} articles inclus (mode fallback sans entités)")

    today_str = datetime.now().strftime("%d/%m/%Y")
    prompt = build_prompt(slim_articles, top_entities, today_str)

    if dry_run:
        print_console("=== MODE DRY-RUN : prompt généré (non envoyé à l'API) ===")
        print(prompt[:3000])
        print(f"\n[...prompt tronqué — {len(prompt)} caractères au total]")
        return

    # Appel API avec timeout étendu (rapport complexe)
    api_client = get_ai_client()
    print_console("Génération du rapport IA (timeout 300s)...")

    try:
        report_content = api_client.ask(prompt, max_attempts=3, timeout=300, max_tokens=16000)
    except RuntimeError as e:
        print_console(f"Échec de la génération du rapport : {e}", level="error")
        sys.exit(1)

    if not report_content:
        print_console("Rapport vide reçu — abandon", level="error")
        sys.exit(1)

    # Nettoyage : supprimer les blocs de code parasites que le LLM peut générer
    # autour du frontmatter (```yaml\n---...---\n```) et en fin de fichier
    report_content = re.sub(r'^```(?:yaml|markdown)?\s*\n', '', report_content, flags=re.IGNORECASE)
    report_content = re.sub(r'\n```\s*$', '', report_content)

    # Sauvegarde — fichier fixe remplacé chaque jour dans rapports/markdown/_WUDD.AI_/
    output_dir = PROJECT_ROOT / "rapports" / "markdown" / "_WUDD.AI_"
    output_dir.mkdir(parents=True, exist_ok=True)

    output_file = output_dir / "rapport_48h.md"
    output_file.write_text(report_content, encoding="utf-8")
    print_console(f"✓ Rapport sauvegardé : {output_file}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Génère un rapport quotidien Top 10 entités depuis 48-heures.json"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Affiche le prompt sans appeler l'API EurIA"
    )
    args = parser.parse_args()
    if not should_run_task("reports.top_entities_48h"):
        sys.exit(0)
    generate_48h_report(dry_run=args.dry_run)
