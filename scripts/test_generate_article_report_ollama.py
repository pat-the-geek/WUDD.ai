#!/usr/bin/env python3
"""Script de test pour régénérer un rapport d'article avec Ollama.

Ce script est volontairement séparé du code de production.
Il permet de :
  - cibler un article précis depuis un JSON existant
  - récupérer le texte source depuis l'URL (fallback sur le résumé)
  - forcer des chapitres plus développés que le prompt de prod
  - exiger un bloc Mermaid et retenter si nécessaire
  - écraser une note Obsidian existante

Exemple :
  python3 scripts/test_generate_article_report_ollama.py \
    --title "Google unleashes a native Gemini app for the Mac" \
    --json data/articles-from-rss/google.json \
    --output "/Users/.../Rapports-WUDD-ai/2026-04-15_...md"
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import unicodedata
from pathlib import Path

import requests
from bs4 import BeautifulSoup

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Exécution sur l'hôte macOS : on force localhost au lieu de host.docker.internal.
os.environ.setdefault("OLLAMA_HOST", "localhost")

from utils.api_client import OllamaClient
from utils.config import get_config


DEFAULT_TITLE = "Google unleashes a native Gemini app for the Mac"
DEFAULT_URL = "https://www.engadget.com/ai/google-unleashes-a-native-gemini-app-for-the-mac-170500185.html?src=rss"
DEFAULT_JSON = PROJECT_ROOT / "data/articles-from-rss/google.json"
DEFAULT_OUTPUT = Path(
    "/Users/patrickostertag/Library/Mobile Documents/iCloud~md~obsidian/Documents/"
    "Coffre-de-Pat/Rapports-WUDD-ai/2026-04-15_engadget-is-a-w_"
    "google-unleashes-a-native-gemini-app-for.md"
)


def remove_accents(value: str) -> str:
    return "".join(
        ch for ch in unicodedata.normalize("NFD", str(value or ""))
        if unicodedata.category(ch) != "Mn"
    )


def yaml_quote(value: str) -> str:
    return '"' + str(value or "").replace('"', "'") + '"'


def slug_tag(value: str) -> str:
    slug = remove_accents(value)
    slug = re.sub(r"\s+", "-", slug)
    slug = re.sub(r"[^a-zA-Z0-9\-_\/]", "-", slug)
    slug = re.sub(r"-{2,}", "-", slug)
    return slug.strip("-")[:50]


def load_article(json_path: Path, title: str, url: str | None) -> dict:
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise RuntimeError(f"Le fichier {json_path} ne contient pas une liste d'articles.")

    for item in payload:
        if not isinstance(item, dict):
            continue
        if item.get("Titre") != title:
            continue
        if url and item.get("URL") != url:
            continue
        return item

    raise RuntimeError("Article introuvable dans le fichier JSON fourni.")


def fetch_source_text(url: str, resume: str) -> tuple[str, str]:
    try:
        resp = requests.get(
            url,
            timeout=20,
            headers={"User-Agent": "Mozilla/5.0 (compatible; WUDD-bot/1.0)"},
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        text = " ".join(soup.get_text(separator=" ").split())[:20000].strip()
        if text:
            return text, "url"
    except Exception:
        pass

    fallback = (resume or "").strip()
    if not fallback:
        raise RuntimeError("Aucun texte source disponible : URL inaccessible et résumé vide.")
    return fallback, "resume"


def build_frontmatter(article: dict) -> str:
    entities = article.get("entities") or {}
    entity_tags = []
    for vals in entities.values():
        if isinstance(vals, list):
            entity_tags.extend(v for v in vals if isinstance(v, str) and v.strip())

    source = str(article.get("Sources") or "")
    all_tags = []
    for candidate in [source, *entity_tags]:
        if candidate and candidate not in all_tags:
            all_tags.append(candidate)

    tag_lines = "\n".join(f"  - {yaml_quote(slug_tag(tag))}" for tag in all_tags[:30])
    if not tag_lines:
        tag_lines = '  - "rapport"'

    type_map = {
        "PERSON": "personnes",
        "ORG": "organisations",
        "GPE": "lieux",
        "LOC": "lieux_geographiques",
        "PRODUCT": "produits",
        "EVENT": "evenements",
        "WORK_OF_ART": "oeuvres",
    }
    entity_sections = []
    for entity_type, key in type_map.items():
        values = entities.get(entity_type) if isinstance(entities.get(entity_type), list) else []
        if values:
            entity_sections.append(key + ":\n" + "\n".join(f"  - {yaml_quote(v)}" for v in values))

    parts = [
        "---",
        f"title: {yaml_quote(article.get('Titre') or article.get('Sources') or 'Rapport')}",
        f"date: {dt.date.today().isoformat()}",
        f"date_publication: {yaml_quote(article.get('Date de publication') or '')}",
        f"source: {yaml_quote(source)}",
        f"url: {yaml_quote(article.get('URL') or '')}",
        'version: "1.0"',
    ]
    if article.get("temps_lecture_label"):
        parts.append(f"temps_lecture: {yaml_quote(article['temps_lecture_label'])}")
    parts.append("tags:")
    parts.append(tag_lines)
    parts.extend(entity_sections)
    parts.append("type: Rapport-WUDD-ai")
    parts.append("statut: generated")
    parts.append("---\n")
    return "\n".join(parts) + "\n"


def build_note_body(article: dict) -> str:
    entities = article.get("entities") or {}
    body = []

    for img in (article.get("Images") or [])[:1]:
        img_url = img.get("URL") or img.get("url") or ""
        if img_url:
            body.append(f"![]({img_url})\n")

    if article.get("Résumé"):
        body.append(f"## Résumé\n\n{article['Résumé']}\n")

    type_labels = {
        "ORG": "Organisations",
        "PRODUCT": "Produits",
        "WORK_OF_ART": "Oeuvres / concepts",
    }
    sections = []
    for entity_type, label in type_labels.items():
        values = entities.get(entity_type) if isinstance(entities.get(entity_type), list) else []
        if values:
            sections.append(f"### {label}\n\n" + "\n".join(f"- [[{v}]]" for v in values))
    if sections:
        body.append("## Entités\n\n" + "\n\n".join(sections) + "\n")

    source_lines = [
        "## Source\n",
        "| Champ | Valeur |",
        "|---|---|",
        f"| Source | **{article.get('Sources') or ''}** |",
        f"| Date | {article.get('Date de publication') or ''} |",
        f"| URL | [↗ Lire l'article]({article.get('URL') or ''}) |",
        f"| Temps de lecture | {article.get('temps_lecture_label') or ''} |",
        "\n---\n",
    ]
    body.append("\n".join(source_lines))
    return "\n".join(body).strip() + "\n\n"


def build_prompt(article: dict, source_text: str, source_kind: str, chapter_level: str) -> str:
    entities = article.get("entities") or {}
    entity_lines = []
    for entity_type, vals in entities.items():
        if isinstance(vals, list) and vals:
            entity_lines.append(f"  - {entity_type} : " + ", ".join(str(v) for v in vals[:10]))
    entity_context = "\n".join(entity_lines) if entity_lines else "  Aucune entité extraite."

    meta_parts = []
    if article.get("Titre"):
        meta_parts.append(f"Titre : {article['Titre']}")
    if article.get("Sources"):
        meta_parts.append(f"Source : {article['Sources']}")
    if article.get("Date de publication"):
        meta_parts.append(f"Date : {article['Date de publication']}")
    meta_str = "\n".join(meta_parts) or "(non renseigné)"

    if chapter_level == "long":
        length_rules = (
            "2. ## Contexte et enjeux — minimum 4 paragraphes développés\n"
            "3. ## Analyse détaillée — minimum 3 sous-sections en ###, chacune avec au moins 2 paragraphes développés\n"
            "6. ## Points clés — 6 à 8 bullets argumentés puis une conclusion de 2 paragraphes\n"
        )
    else:
        length_rules = (
            "2. ## Contexte et enjeux — 2 à 3 paragraphes\n"
            "3. ## Analyse détaillée — 2 ou 3 sous-sections en ###\n"
            "6. ## Points clés — 4 à 6 bullets puis une conclusion courte\n"
        )

    source_label = "texte complet de l'article" if source_kind == "url" else "résumé de l'article"
    source_link = f"[{article.get('URL')}]({article.get('URL')})"
    return (
        "Tu es un analyste en intelligence médiatique. Génère un rapport approfondi en Markdown en français.\n\n"
        f"## Métadonnées\n{meta_str}\n\n"
        f"## Entités nommées détectées\n{entity_context}\n\n"
        f"## {source_label.capitalize()}\n{source_text}\n\n"
        "---\n\n"
        "Génère un rapport complet en Markdown français avec ces sections dans cet ordre :\n"
        "1. Titre H1 + métadonnées (source · date) + accroche\n"
        f"{length_rules}"
        "4. ## Acteurs impliqués — tableau | Entité | Type | Rôle |\n"
        "5. ## Diagramme Mermaid — inclure OBLIGATOIREMENT un et un seul bloc ```mermaid valide. "
        "Ne saute jamais cette section. Choisis flowchart TD, timeline ou xychart-beta selon le cas. "
        "Le bloc doit commencer directement par le mot-clé du type de diagramme sur la première ligne du bloc. "
        "N'ajoute aucun texte avant le diagramme dans cette section. "
        "Labels sans accents ni caractères spéciaux ; si espaces ou ponctuation, utilise [\"label\"]. "
        "Si les données sont limitées, produis un flowchart TD minimal mais valide à partir des acteurs, du produit et des effets mentionnés.\n"
        f"7. ## Source — {source_link}\n\n"
        "Règles : Markdown uniquement, pas de balises <think>, pas de YAML frontmatter."
    )


def generate_report_with_retry(client: OllamaClient, prompt: str, retries: int, max_tokens: int) -> tuple[str, list[dict]]:
    attempts = []
    for attempt in range(1, retries + 1):
        effective_prompt = prompt
        if attempt > 1:
            effective_prompt += (
                "\n\nIMPORTANT SUPPLEMENTAIRE : le précédent essai ne contenait pas de diagramme Mermaid exploitable. "
                "Cette fois, la section 5 doit contenir un bloc ```mermaid complet et valide."
            )
        candidate = client.ask(effective_prompt, timeout=300, max_tokens=max_tokens)
        candidate = re.sub(r"<think>[\s\S]*?</think>", "", candidate, flags=re.IGNORECASE).strip()
        candidate = re.sub(r"^---[\s\S]*?---\n\n?", "", candidate)
        has_mermaid = "```mermaid" in candidate
        attempts.append({"attempt": attempt, "has_mermaid": has_mermaid, "size": len(candidate)})
        if has_mermaid:
            return candidate, attempts
    raise RuntimeError(
        "Le modèle n'a pas produit de bloc Mermaid après plusieurs tentatives : "
        + json.dumps(attempts, ensure_ascii=False)
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Régénère un rapport d'article avec Ollama hors production.")
    parser.add_argument("--json", type=Path, default=DEFAULT_JSON, help="Fichier JSON source contenant l'article.")
    parser.add_argument("--title", default=DEFAULT_TITLE, help="Titre exact de l'article ciblé.")
    parser.add_argument("--url", default=DEFAULT_URL, help="URL exacte de l'article ciblé.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Fichier Markdown Obsidian à écraser.")
    parser.add_argument("--model", default="qwen2.5:7b", help="Modèle Ollama à utiliser.")
    parser.add_argument("--chapter-level", choices=["normal", "long"], default="long", help="Niveau de développement des chapitres.")
    parser.add_argument("--retries", type=int, default=3, help="Nombre de tentatives si Mermaid absent.")
    parser.add_argument("--max-tokens", type=int, default=3200, help="Nombre max de tokens de sortie.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    get_config()

    article = load_article(args.json, args.title, args.url)
    source_text, source_kind = fetch_source_text(article.get("URL") or "", article.get("Résumé") or "")
    client = OllamaClient(model=args.model)

    prompt = build_prompt(article, source_text, source_kind, args.chapter_level)
    report_md, attempts = generate_report_with_retry(client, prompt, retries=args.retries, max_tokens=args.max_tokens)

    final_markdown = build_frontmatter(article) + build_note_body(article) + "## Rapport IA\n\n" + report_md.strip() + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(final_markdown, encoding="utf-8")

    print(json.dumps({
        "written": True,
        "output": str(args.output),
        "model": args.model,
        "source_kind": source_kind,
        "attempts": attempts,
        "chapter_level": args.chapter_level,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()