#!/usr/bin/env python3
"""Export des articles et entités WUDD.ai vers un vault Obsidian.

Ce script génère des notes Markdown enrichies (frontmatter YAML, liens internes,
graphes Mermaid, géolocalisation) dans la structure Veille/ du vault Obsidian.

Usage:
    python3 scripts/export_obsidian.py [--flux FLUX] [--keyword KW] [--days N]
                                        [--dry-run] [--force] [--no-entities]
                                        [--no-synthesis]

Exemples:
    # Exporter les 7 derniers jours de tous les flux
    python3 scripts/export_obsidian.py --days 7

    # Exporter un flux spécifique, forcer la réécriture
    python3 scripts/export_obsidian.py --flux Intelligence-artificielle --force

    # Simulation sans écriture
    python3 scripts/export_obsidian.py --dry-run --days 30
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

# ── Résolution du projet ──────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent.resolve()
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))

from utils.config import get_config
from utils.logging import default_logger as LOG

# ── Constantes ────────────────────────────────────────────────────────────────
VEILLE_ROOT = "Veille"          # Dossier racine dans le vault
SUBDIR_ARTICLES = "articles"
SUBDIR_ENTITIES = "entités"
SUBDIR_RAPPORTS = "rapports"
SUBDIR_SYNTHESES = "synthèses"

# Seuil minimum de mentions pour générer une note entité
MIN_ENTITY_MENTIONS = 5

# Longueur max du slug de titre dans le nom de fichier
SLUG_MAX_LEN = 40

# Types NER à afficher dans les notes articles
NER_DISPLAY_TYPES = ("PERSON", "ORG", "GPE", "LOC", "PRODUCT", "EVENT")

# Emojis par type NER pour la lisibilité dans Obsidian
NER_EMOJIS = {
    "PERSON": "👤",
    "ORG": "🏢",
    "GPE": "🌍",
    "LOC": "📍",
    "PRODUCT": "📦",
    "EVENT": "📅",
    "MONEY": "💰",
    "DATE": "📆",
    "WORK_OF_ART": "🎨",
    "NORP": "🏳",
}

# Emojis sentiment
SENTIMENT_EMOJIS = {
    "positif": "😊",
    "négatif": "😟",
    "neutre": "😐",
    "mixte": "🤔",
}


# ══════════════════════════════════════════════════════════════════════════════
# Helpers de texte
# ══════════════════════════════════════════════════════════════════════════════

def _slugify(text: str, max_len: int = SLUG_MAX_LEN) -> str:
    """Convertit un texte en slug Obsidian-safe (ASCII, tirets, sans accents)."""
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text.strip())
    text = re.sub(r"-+", "-", text).strip("-")
    return text[:max_len].rstrip("-")


def _print(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"{ts} {msg}")
    LOG.info(msg)


def _md5(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def _parse_date(date_str: str) -> Optional[datetime]:
    """Tente de parser une date depuis les formats courants WUDD.ai."""
    if not date_str:
        return None
    formats = [
        "%Y-%m-%dT%H:%M:%SZ",
        "%d/%m/%Y",
        "%Y-%m-%d",
        "%d/%m/%Y %H:%M:%S",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(date_str.strip(), fmt)
        except ValueError:
            continue
    return None


def _date_iso(d: datetime) -> str:
    return d.strftime("%Y-%m-%d")


def _yaml_str(value: Any) -> str:
    """Échappe une valeur pour un champ YAML inline (string)."""
    if value is None:
        return '""'
    s = str(value).replace('"', '\\"').replace("\n", " ")
    return f'"{s}"'


def _yaml_list(values: list[str]) -> str:
    """Génère une liste YAML inline."""
    if not values:
        return "[]"
    items = ", ".join(f'"{v.replace(chr(34), chr(39))}"' for v in values[:20])
    return f"[{items}]"


# ══════════════════════════════════════════════════════════════════════════════
# Structure du vault
# ══════════════════════════════════════════════════════════════════════════════

def ensure_vault_structure(vault_dir: Path, dry_run: bool = False) -> dict[str, Path]:
    """Crée la structure de dossiers Veille/ dans le vault.

    Retourne un dict des chemins créés.
    """
    dirs = {
        "root": vault_dir / VEILLE_ROOT,
        "articles": vault_dir / VEILLE_ROOT / SUBDIR_ARTICLES,
        "entities": vault_dir / VEILLE_ROOT / SUBDIR_ENTITIES,
        "rapports": vault_dir / VEILLE_ROOT / SUBDIR_RAPPORTS,
        "syntheses": vault_dir / VEILLE_ROOT / SUBDIR_SYNTHESES,
    }
    for name, path in dirs.items():
        if not dry_run:
            path.mkdir(parents=True, exist_ok=True)
        _print(f"[vault] {'(dry) ' if dry_run else ''}Dossier: {path.relative_to(vault_dir)}")
    return dirs


# ══════════════════════════════════════════════════════════════════════════════
# Collecte des articles
# ══════════════════════════════════════════════════════════════════════════════

def _collect_articles(
    project_root: Path,
    flux: Optional[str] = None,
    keyword: Optional[str] = None,
    days: Optional[int] = None,
) -> list[tuple[dict, str]]:
    """Collecte les articles des sources configurées.

    Retourne une liste de (article_dict, source_label).
    """
    cutoff = None
    if days:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    articles: list[tuple[dict, str]] = []

    # Articles flux (data/articles/<flux>/...)
    articles_dir = project_root / "data" / "articles"
    flux_dirs = [articles_dir / flux] if flux else [
        d for d in articles_dir.iterdir() if d.is_dir() and d.name != "cache"
    ]
    for flux_dir in flux_dirs:
        if not flux_dir.is_dir():
            continue
        for json_file in sorted(flux_dir.glob("articles_generated_*.json")):
            try:
                data = json.loads(json_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            for art in data:
                art.setdefault("_flux", flux_dir.name)
                art.setdefault("_type", "flux")
                if cutoff:
                    pub_date = _parse_date(art.get("Date de publication", ""))
                    if pub_date and pub_date.replace(tzinfo=timezone.utc) < cutoff:
                        continue
                articles.append((art, flux_dir.name))

    # Articles RSS/keyword (data/articles-from-rss/...)
    rss_dir = project_root / "data" / "articles-from-rss"
    if rss_dir.exists():
        if keyword:
            rss_files = [rss_dir / f"{keyword}.json"] if (rss_dir / f"{keyword}.json").exists() else []
        else:
            rss_files = sorted(rss_dir.glob("*.json"))
        for json_file in rss_files:
            try:
                data = json.loads(json_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            kw_label = json_file.stem
            for art in data:
                art.setdefault("_flux", kw_label)
                art.setdefault("_type", "rss")
                if cutoff:
                    pub_date = _parse_date(art.get("Date de publication", ""))
                    if pub_date and pub_date.replace(tzinfo=timezone.utc) < cutoff:
                        continue
                articles.append((art, kw_label))

    _print(f"[collecte] {len(articles)} articles collectés")
    return articles


# ══════════════════════════════════════════════════════════════════════════════
# Génération notes articles (3.2)
# ══════════════════════════════════════════════════════════════════════════════

def _article_filename(article: dict) -> str:
    """Génère le nom de fichier pour un article.

    Format: YYYY-MM-DD_source_slug-titre.md
    """
    pub_date = _parse_date(article.get("Date de publication", ""))
    date_part = _date_iso(pub_date) if pub_date else "0000-00-00"
    source = article.get("Sources", "source-inconnue")
    # Garder un court identifiant de la source
    source_slug = _slugify(source.split(".")[0].split(" ")[0], 15)
    title = article.get("Résumé", "")[:80]
    title_slug = _slugify(title, SLUG_MAX_LEN)
    return f"{date_part}_{source_slug}_{title_slug}.md"


def _entity_wikilinks(entities: dict, entity_index_keys: set[str]) -> str:
    """Génère les liens internes Obsidian pour les entités détectées."""
    lines = []
    for ner_type in NER_DISPLAY_TYPES:
        values = entities.get(ner_type, [])
        if not values:
            continue
        emoji = NER_EMOJIS.get(ner_type, "")
        linked = []
        for val in values[:10]:
            key = f"{ner_type}:{val.lower()}"
            if key in entity_index_keys:
                linked.append(f"[[{val}]]")
            else:
                linked.append(val)
        lines.append(f"- **{emoji} {ner_type}**: {', '.join(linked)}")
    return "\n".join(lines)


def _build_article_note(
    article: dict,
    entity_index_keys: set[str],
    geocode: dict,
    geocode_cache_path: Optional[Path] = None,
) -> str:
    """Construit le contenu Markdown complet d'une note article."""
    pub_date = _parse_date(article.get("Date de publication", ""))
    date_str = _date_iso(pub_date) if pub_date else ""
    source = article.get("Sources", "")
    url = article.get("URL", "")
    resume = article.get("Résumé", "")
    entities = article.get("entities", {})
    sentiment = article.get("sentiment", "")
    score_sentiment = article.get("score_sentiment", "")
    ton = article.get("ton_editorial", "")
    score_ton = article.get("score_ton", "")
    score_source = article.get("score_source", "")
    temps_lecture = article.get("temps_lecture_label", "")
    flux = article.get("_flux", "")
    mot_cle = article.get("mot_cle", "")

    # Tags automatiques
    tags: list[str] = ["wudd-ai"]
    if flux:
        tags.append(_slugify(flux, 30))
    if mot_cle:
        tags.append(_slugify(mot_cle, 30))
    if sentiment:
        tags.append(f"sentiment-{_slugify(sentiment, 15)}")
    if ton:
        tags.append(f"ton-{_slugify(ton, 15)}")
    # Tags entités principales
    for ner_type in ("ORG", "PERSON"):
        for val in entities.get(ner_type, [])[:3]:
            tags.append(_slugify(val, 25))

    # Géolocalisation — injecter si GPE/LOC trouvé dans geocode (avec Nominatim fallback)
    location_yaml = ""
    entities_geo_yaml = ""
    all_gpe = entities.get("GPE", []) + entities.get("LOC", [])
    resolved_geo: list[str] = []
    for gpe in all_gpe:
        geo = _resolve_gpe(gpe, geocode, geocode_cache_path)
        if geo and geo.get("lat") and geo.get("lon"):
            resolved_geo.append(f"{gpe}:{geo['lat']},{geo['lon']}")
            if not location_yaml:
                location_yaml = f"\nlocation: [{geo['lat']}, {geo['lon']}]"
    if resolved_geo:
        # Format YAML liste inline pour Dataview
        geo_values = ", ".join(f'"{v}"' for v in resolved_geo)
        entities_geo_yaml = f"\nentités_geo: [{geo_values}]"

    # Images
    images = article.get("Images", [])
    img_block = ""
    if images:
        img_lines = []
        for img in images[:3]:
            img_url = img.get("url") or img.get("URL", "")
            if img_url and img_url.startswith("http"):
                alt = img.get("alt") or img.get("title") or "Image"
                img_lines.append(f"![{alt}]({img_url})")
        if img_lines:
            img_block = "\n\n" + "\n\n".join(img_lines)

    # Entités bloc
    entity_block = ""
    if entities:
        entity_block = "\n\n## Entités détectées\n\n" + _entity_wikilinks(entities, entity_index_keys)

    # Score source
    score_block = ""
    if score_source:
        score_block = f"\n\n## Crédibilité de la source\n\n- Score : **{score_source}/100**"

    # Sentiment emoji
    sent_emoji = SENTIMENT_EMOJIS.get(sentiment, "")

    # Frontmatter YAML
    # Lister les entités importantes dans le frontmatter (pour Dataview)
    all_entities_flat = []
    for ner_type in NER_DISPLAY_TYPES:
        all_entities_flat.extend(entities.get(ner_type, [])[:5])

    frontmatter = f"""---
title: {_yaml_str(resume[:120])}
date: {date_str}
source: {_yaml_str(source)}
url: {_yaml_str(url)}
flux: {_yaml_str(flux)}
sentiment: {_yaml_str(sentiment)}
score_sentiment: {score_sentiment}
ton_editorial: {_yaml_str(ton)}
score_ton: {score_ton}
score_source: {score_source}
temps_lecture: {_yaml_str(temps_lecture)}
tags: {_yaml_list(tags)}
entites: {_yaml_list(all_entities_flat[:15])}{location_yaml}{entities_geo_yaml}
---"""

    # Corps de la note
    title_display = resume[:120] + ("…" if len(resume) > 120 else "")
    sentiment_display = f" {sent_emoji} *{sentiment}*" if sentiment else ""
    body = f"""# {title_display}

> **Source** : [{source}]({url}){sentiment_display}  
> **Publié** : {date_str}  
> **Lecture** : {temps_lecture}

## Résumé

{resume}
{img_block}{entity_block}{score_block}

---
*Note générée automatiquement par WUDD.ai*
"""

    return frontmatter + "\n" + body


def export_articles(
    articles: list[tuple[dict, str]],
    articles_dir: Path,
    entity_index_keys: set[str],
    geocode: dict,
    geocode_cache_path: Optional[Path] = None,
    dry_run: bool = False,
    force: bool = False,
) -> tuple[int, int]:
    """Exporte les articles vers Obsidian.

    Retourne (nombre créés, nombre ignorés).
    """
    created = 0
    skipped = 0

    seen_hashes: set[str] = set()

    for article, _ in articles:
        resume = article.get("Résumé", "")
        if not resume:
            skipped += 1
            continue

        # Déduplication par MD5 du résumé
        h = _md5(resume)
        if h in seen_hashes:
            skipped += 1
            continue
        seen_hashes.add(h)

        filename = _article_filename(article)
        dest = articles_dir / filename

        if dest.exists() and not force:
            skipped += 1
            continue

        content = _build_article_note(article, entity_index_keys, geocode, geocode_cache_path)

        if not dry_run:
            dest.write_text(content, encoding="utf-8")
        created += 1

    _print(f"[articles] {created} notes créées, {skipped} ignorées")
    return created, skipped


# ══════════════════════════════════════════════════════════════════════════════
# Génération notes entités + Mermaid (3.3)
# ══════════════════════════════════════════════════════════════════════════════

def _resolve_gpe(
    name: str,
    geocode_cache: dict,
    geocode_cache_path: Optional[Path] = None,
) -> Optional[dict]:
    """Résout les coordonnées GPS d'une entité GPE/LOC.

    Cherche d'abord dans le cache, puis fait appel à Nominatim (OSM) en fallback.
    Enregistre le résultat dans le cache si une requête a été faite.
    Retourne un dict {lat, lon} ou None.
    """
    # 1. Cache local
    if name in geocode_cache:
        entry = geocode_cache[name]
        if entry and entry.get("lat") and entry.get("lon"):
            return entry
        # Cache négatif (pas de résultat connu) — éviter les re-requêtes
        if entry is None:
            return None

    # 2. Nominatim fallback
    try:
        import urllib.parse
        import urllib.request
        query = urllib.parse.quote(name)
        url = f"https://nominatim.openstreetmap.org/search?q={query}&format=json&limit=1"
        req = urllib.request.Request(url, headers={"User-Agent": "WUDD.ai/2.4 (contact: patrick.ostertag@gmail.com)"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
        if data:
            lat = float(data[0]["lat"])
            lon = float(data[0]["lon"])
            result: dict = {"lat": lat, "lon": lon}
            geocode_cache[name] = result
            # Persister dans le cache
            if geocode_cache_path:
                try:
                    geocode_cache_path.write_text(
                        json.dumps(geocode_cache, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                except OSError:
                    pass
            return result
        else:
            # Marquer comme introuvable pour ne pas re-requêter
            geocode_cache[name] = None
    except Exception:
        pass

    return None


def _load_entity_timeline(project_root: Path) -> dict:
    """Charge entity_timeline.json si disponible."""
    path = project_root / "data" / "entity_timeline.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _build_entity_note(
    entity_key: str,
    caps: str,
    refs: list[dict],
    caps_all: dict[str, str],
    entity_index: dict,
    timeline: dict,
    project_root: Path,
) -> str:
    """Construit une note Obsidian pour une entité importante."""
    ner_type, entity_lower = entity_key.split(":", 1)
    display_name = caps or entity_lower.title()

    # Articles récents (10 max)
    recent_refs = sorted(refs, key=lambda r: r.get("date", ""), reverse=True)[:10]

    # Charger les articles pour obtenir les titres
    article_links: list[str] = []
    sentiment_counts: dict[str, int] = {}
    cooccurrences: dict[str, int] = {}

    seen_files: dict[str, list] = {}
    for ref in recent_refs:
        f = ref.get("file", "")
        if f not in seen_files:
            p = project_root / f
            if p.exists():
                try:
                    seen_files[f] = json.loads(p.read_text(encoding="utf-8"))
                except Exception:
                    seen_files[f] = []
            else:
                seen_files[f] = []
        articles_list = seen_files[f]
        idx = ref.get("idx", 0)
        if 0 <= idx < len(articles_list):
            art = articles_list[idx]
            pub_date = _parse_date(art.get("Date de publication", ""))
            date_str = _date_iso(pub_date) if pub_date else "?"
            # Générer le [[wikilink]] interne vers la note article
            art_filename = _article_filename(art)
            art_slug = art_filename[:-3]  # retirer .md
            resume_short = art.get("Résumé", "")[:80].replace("|", "\\|")
            article_links.append(
                f"- `{date_str}` — [[{art_slug}|{resume_short}…]]"
            )
            # Sentiment
            sent = art.get("sentiment", "")
            if sent:
                sentiment_counts[sent] = sentiment_counts.get(sent, 0) + 1
            # Co-occurrences d'entités
            ents = art.get("entities", {})
            for t in NER_DISPLAY_TYPES:
                for val in ents.get(t, []):
                    other_key = f"{t}:{val.lower()}"
                    if other_key != entity_key:
                        cooccurrences[other_key] = cooccurrences.get(other_key, 0) + 1

    # Mermaid co-occurrences (top 8)
    top_cooc = sorted(cooccurrences.items(), key=lambda x: x[1], reverse=True)[:8]
    mermaid_cooc = ""
    if top_cooc:
        cooc_lines = []
        cooc_lines.append("```mermaid")
        cooc_lines.append("graph TD")
        safe_name = display_name.replace('"', "'").replace(" ", "_")
        cooc_lines.append(f'    A["{display_name}"]')
        for i, (cooc_key, count) in enumerate(top_cooc):
            cooc_caps = caps_all.get(cooc_key, cooc_key.split(":", 1)[-1].title())
            cooc_safe = cooc_caps.replace('"', "'").replace(" ", "_")
            node_id = f"B{i}"
            cooc_lines.append(f'    {node_id}["{cooc_caps}"]')
            label = str(count)
            cooc_lines.append(f"    A -->|{label}| {node_id}")
        cooc_lines.append("```")
        mermaid_cooc = "\n".join(cooc_lines)

    # Mermaid pie (sentiments)
    mermaid_pie = ""
    if sentiment_counts:
        pie_lines = ["```mermaid", 'pie title Répartition éditoriale']
        for sent, cnt in sorted(sentiment_counts.items(), key=lambda x: x[1], reverse=True):
            pie_lines.append(f'    "{sent}" : {cnt}')
        pie_lines.append("```")
        mermaid_pie = "\n".join(pie_lines)

    # Timeline (depuis entity_timeline.json)
    mermaid_timeline = ""
    timeline_data = timeline.get(entity_key, timeline.get(entity_lower, {}))
    if timeline_data and isinstance(timeline_data, dict):
        entries = timeline_data.get("mentions", [])
        if len(entries) >= 2:
            tl_lines = ["```mermaid", "timeline"]
            for entry in entries[-8:]:
                d = entry.get("date", "?")[:10]
                tl_lines.append(f"    {d} : {entry.get('count', 1)} mention(s)")
            tl_lines.append("```")
            mermaid_timeline = "\n".join(tl_lines)

    # Statistiques
    total_mentions = len(refs)
    first_date = min((r.get("date", "9999") for r in refs), default="?")
    last_date = max((r.get("date", "0000") for r in refs), default="?")

    # Frontmatter YAML
    frontmatter = f"""---
title: {_yaml_str(display_name)}
type: entité
ner_type: {ner_type}
mentions: {total_mentions}
premiere_mention: {first_date}
derniere_mention: {last_date}
tags: ["wudd-ai", "entite", "ner-{ner_type.lower()}"]
---"""

    # Corps
    cooc_section = ""
    if mermaid_cooc:
        cooc_section = f"\n\n## Co-occurrences\n\n{mermaid_cooc}"

    pie_section = ""
    if mermaid_pie:
        pie_section = f"\n\n## Répartition éditoriale\n\n{mermaid_pie}"

    timeline_section = ""
    if mermaid_timeline:
        timeline_section = f"\n\n## Timeline de mentions\n\n{mermaid_timeline}"

    articles_section = ""
    if article_links:
        articles_section = "\n\n## Articles récents\n\n" + "\n".join(article_links[:10])

    body = f"""# {display_name}

> **Type NER** : `{ner_type}` | **Mentions** : {total_mentions} | **Période** : {first_date} → {last_date}
{cooc_section}{pie_section}{timeline_section}{articles_section}

---
*Note générée automatiquement par WUDD.ai*
"""

    return frontmatter + "\n" + body


def export_entities(
    entity_index: dict,
    caps: dict,
    timeline: dict,
    entities_dir: Path,
    project_root: Path,
    dry_run: bool = False,
    force: bool = False,
) -> tuple[int, int]:
    """Exporte les notes entités importantes vers Obsidian.

    Retourne (nombre créés, nombre ignorés).
    """
    created = 0
    skipped = 0

    for entity_key, refs in entity_index.items():
        if not isinstance(refs, list) or len(refs) < MIN_ENTITY_MENTIONS:
            skipped += 1
            continue

        _, entity_lower = entity_key.split(":", 1) if ":" in entity_key else ("", entity_key)
        display_name = caps.get(entity_key, entity_lower.title())
        filename = _slugify(display_name, 50) + ".md"
        dest = entities_dir / filename

        if dest.exists() and not force:
            skipped += 1
            continue

        content = _build_entity_note(
            entity_key, display_name, refs, caps, entity_index, timeline, project_root
        )

        if not dry_run:
            dest.write_text(content, encoding="utf-8")
        created += 1

    _print(f"[entités] {created} notes créées, {skipped} ignorées")
    return created, skipped


# ══════════════════════════════════════════════════════════════════════════════
# Notes géographiques GPE/LOC (3.4)
# ══════════════════════════════════════════════════════════════════════════════

def _build_geo_entity_note(
    name: str,
    ner_type: str,
    geo: dict,
    article_refs: list[dict],
    caps_all: dict[str, str],
    project_root: Path,
) -> str:
    """Génère une note Obsidian pour une entité géographique GPE ou LOC."""
    lat = geo.get("lat", 0)
    lon = geo.get("lon", 0)
    total = len(article_refs)

    # 10 articles récents
    recent_refs = sorted(article_refs, key=lambda r: r.get("date", ""), reverse=True)[:10]
    article_links: list[str] = []
    seen_files: dict[str, list] = {}
    for ref in recent_refs:
        f = ref.get("file", "")
        if f not in seen_files:
            p = project_root / f
            if p.exists():
                try:
                    seen_files[f] = json.loads(p.read_text(encoding="utf-8"))
                except Exception:
                    seen_files[f] = []
            else:
                seen_files[f] = []
        articles_list = seen_files[f]
        idx = ref.get("idx", 0)
        if 0 <= idx < len(articles_list):
            art = articles_list[idx]
            pub_date = _parse_date(art.get("Date de publication", ""))
            date_str = _date_iso(pub_date) if pub_date else "?"
            art_filename = _article_filename(art)
            art_slug = art_filename[:-3]
            resume_short = art.get("Résumé", "")[:80].replace("|", "\\|")
            article_links.append(f"- `{date_str}` — [[{art_slug}|{resume_short}…]]")

    articles_section = ""
    if article_links:
        articles_section = "\n\n## Articles mentionnant ce lieu\n\n" + "\n".join(article_links)

    first_date = min((r.get("date", "9999") for r in article_refs), default="?")
    last_date = max((r.get("date", "0000") for r in article_refs), default="?")

    frontmatter = f"""---
title: {_yaml_str(name)}
type: entité-géo
ner_type: {ner_type}
mentions: {total}
location: [{lat}, {lon}]
premiere_mention: {first_date}
derniere_mention: {last_date}
tags: ["wudd-ai", "geo", "entite", "ner-{ner_type.lower()}"]
---"""

    body = f"""# {name}

> **Type** : `{ner_type}` | **Mentions** : {total} | **Coordonnées** : {lat}, {lon}

📍 [Ouvrir sur OpenStreetMap](https://www.openstreetmap.org/?mlat={lat}&mlon={lon}&zoom=10)
{articles_section}

---
*Note générée automatiquement par WUDD.ai*
"""
    return frontmatter + "\n" + body


def export_geo_entities(
    entity_index: dict,
    caps: dict,
    geocode: dict,
    geocode_cache_path: Optional[Path],
    entities_dir: Path,
    project_root: Path,
    dry_run: bool = False,
    force: bool = False,
) -> tuple[int, int]:
    """Exporte des notes Obsidian pour chaque entité GPE/LOC avec coordonnées connues."""
    created = 0
    skipped = 0

    geo_types = {"GPE", "LOC"}
    for entity_key, refs in entity_index.items():
        if ":" not in entity_key:
            skipped += 1
            continue
        ner_type, entity_lower = entity_key.split(":", 1)
        if ner_type not in geo_types:
            continue
        if not isinstance(refs, list) or len(refs) < 2:
            skipped += 1
            continue

        display_name = caps.get(entity_key, entity_lower.title())
        geo = _resolve_gpe(display_name, geocode, geocode_cache_path)
        if not geo:
            # Essayer avec la valeur brute (casse exacte depuis caps)
            geo = _resolve_gpe(entity_lower, geocode, geocode_cache_path)
        if not geo:
            skipped += 1
            continue

        filename = f"geo_{_slugify(display_name, 50)}.md"
        dest = entities_dir / filename
        if dest.exists() and not force:
            skipped += 1
            continue

        content = _build_geo_entity_note(
            display_name, ner_type, geo, refs, caps, project_root
        )
        if not dry_run:
            dest.write_text(content, encoding="utf-8")
        created += 1

    _print(f"[entités-geo] {created} notes géographiques créées, {skipped} ignorées")
    return created, skipped


# ══════════════════════════════════════════════════════════════════════════════
# Copie rapports Markdown (3.5)
# ══════════════════════════════════════════════════════════════════════════════

def export_rapports(
    project_root: Path,
    rapports_obsidian_dir: Path,
    dry_run: bool = False,
    force: bool = False,
) -> tuple[int, int]:
    """Copie les rapports Markdown existants vers Obsidian/Veille/rapports/.

    Injecte un frontmatter YAML si le fichier n'en a pas déjà un.
    """
    created = 0
    skipped = 0

    rapports_dir = project_root / "rapports" / "markdown"
    if not rapports_dir.exists():
        return 0, 0

    for md_file in rapports_dir.rglob("*.md"):
        dest = rapports_obsidian_dir / md_file.name
        if dest.exists() and not force:
            skipped += 1
            continue
        try:
            original = md_file.read_text(encoding="utf-8")
            # Injecter frontmatter si absent
            if original.startswith("---"):
                content = original
            else:
                # Déduire titre et date depuis le nom de fichier
                stem = md_file.stem  # ex: rapport_2026-02-01_mon-flux
                parts = stem.split("_", 1)
                rapport_date = parts[1][:10] if len(parts) > 1 else ""
                rapport_title = stem.replace("_", " ").replace("-", " ").title()
                # Tenter d'extraire la date depuis le nom (format YYYY-MM-DD)
                date_match = re.search(r"(\d{4}-\d{2}-\d{2})", stem)
                rapport_date = date_match.group(1) if date_match else ""
                injected = f"""---
title: {_yaml_str(rapport_title)}
date: {rapport_date}
type: rapport
tags: ["wudd-ai", "rapport"]
---

"""
                content = injected + original
            if not dry_run:
                dest.write_text(content, encoding="utf-8")
            created += 1
        except OSError as exc:
            _print(f"[rapports] Erreur copie {md_file.name}: {exc}")

    _print(f"[rapports] {created} rapports copiés, {skipped} ignorés")
    return created, skipped


# ══════════════════════════════════════════════════════════════════════════════
# Génération INDEX (3.5)
# ══════════════════════════════════════════════════════════════════════════════

def _build_flux_synthesis(flux_name: str, articles: list[dict]) -> str:
    """Génère une note de synthèse pour un flux donné."""
    if not articles:
        return ""
    total = len(articles)
    # Top entités
    ent_counts: dict[str, int] = {}
    sent_counts: dict[str, int] = {}
    for art in articles:
        for t in NER_DISPLAY_TYPES:
            for val in art.get("entities", {}).get(t, []):
                key = val.strip()
                ent_counts[key] = ent_counts.get(key, 0) + 1
        sent = art.get("sentiment", "")
        if sent:
            sent_counts[sent] = sent_counts.get(sent, 0) + 1

    top_ents = sorted(ent_counts.items(), key=lambda x: x[1], reverse=True)[:10]
    dates = []
    for art in articles:
        d = _parse_date(art.get("Date de publication", ""))
        if d:
            dates.append(d)
    date_from = _date_iso(min(dates)) if dates else "?"
    date_to = _date_iso(max(dates)) if dates else "?"

    top_ents_lines = "\n".join(f"- [[{e}]] ({c} mentions)" for e, c in top_ents)

    # Mermaid pie sentiments
    pie_block = ""
    if sent_counts:
        pie_lines = ["```mermaid", 'pie title Sentiments']
        for s, c in sorted(sent_counts.items(), key=lambda x: x[1], reverse=True):
            pie_lines.append(f'    "{s}" : {c}')
        pie_lines.append("```")
        pie_block = "\n\n## Répartition des sentiments\n\n" + "\n".join(pie_lines)

    return f"""---
title: {_yaml_str(f"Synthèse — {flux_name}")}
type: synthèse
flux: {_yaml_str(flux_name)}
articles: {total}
periode: "{date_from} → {date_to}"
tags: ["wudd-ai", "synthese", "{_slugify(flux_name, 30)}"]
---

# Synthèse — {flux_name}

> **{total} articles** analysés | Période : {date_from} → {date_to}

## Entités les plus mentionnées

{top_ents_lines}
{pie_block}

---
*Synthèse générée automatiquement par WUDD.ai*
"""


def export_syntheses(
    articles: list[tuple[dict, str]],
    syntheses_dir: Path,
    dry_run: bool = False,
    force: bool = False,
) -> tuple[int, int]:
    """Exporte une note de synthèse par flux + un index global."""
    created = 0
    skipped = 0

    # Grouper par flux
    flux_map: dict[str, list[dict]] = {}
    for art, label in articles:
        flux_map.setdefault(label, []).append(art)

    # Une note par flux
    for flux_name, flux_articles in sorted(flux_map.items()):
        filename = f"{_slugify(flux_name, 40)}.md"
        dest = syntheses_dir / filename
        if dest.exists() and not force:
            skipped += 1
            continue
        content = _build_flux_synthesis(flux_name, flux_articles)
        if content:
            if not dry_run:
                dest.write_text(content, encoding="utf-8")
            created += 1

    # Index global
    index_dest = syntheses_dir / "_INDEX.md"
    if not index_dest.exists() or force:
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        lines = [
            "---",
            'title: "Index WUDD.ai"',
            'tags: ["wudd-ai", "index"]',
            "---",
            "",
            "# Index WUDD.ai",
            "",
            f"> Dernière mise à jour : {now}",
            "",
            "## Flux disponibles",
            "",
        ]
        for flux_name in sorted(flux_map.keys()):
            filename_no_ext = _slugify(flux_name, 40)
            count = len(flux_map[flux_name])
            lines.append(f"- [[{filename_no_ext}|{flux_name}]] ({count} articles)")
        lines += [
            "",
            "## Navigation",
            "",
            "- [[Veille/articles/|Articles]]",
            "- [[Veille/entités/|Entités]]",
            "- [[Veille/rapports/|Rapports]]",
            "",
            "---",
            "*Index généré automatiquement par WUDD.ai*",
        ]
        if not dry_run:
            index_dest.write_text("\n".join(lines), encoding="utf-8")
        created += 1
        _print("[synthèses] Index global créé")

    _print(f"[synthèses] {created} fichiers créés, {skipped} ignorés")
    return created, skipped


# ══════════════════════════════════════════════════════════════════════════════
# Point d'entrée principal
# ══════════════════════════════════════════════════════════════════════════════

def run_export(
    flux: Optional[str] = None,
    keyword: Optional[str] = None,
    days: Optional[int] = None,
    dry_run: bool = False,
    force: bool = False,
    no_entities: bool = False,
    no_synthesis: bool = False,
) -> dict:
    """Lance l'export complet vers Obsidian.

    Retourne un dict de statistiques.
    """
    # Export Obsidian désactivé — génération dans Veille/articles, Veille/entités, etc. supprimée
    _print("[export] Export Obsidian désactivé.")
    return {"désactivé": True, "total_créés": 0}

    config = get_config()  # noqa: unreachable
    project_root = config.project_root

    vault_dir = config.obsidian_dir
    if not vault_dir:
        _print("[ERREUR] OBSIDIAN_DIR non configurée dans .env — export impossible")
        return {"erreur": "OBSIDIAN_DIR non configurée"}
    if not vault_dir.exists():
        _print(f"[ERREUR] Vault introuvable: {vault_dir}")
        return {"erreur": f"Vault introuvable: {vault_dir}"}

    _print(f"[export] Vault: {vault_dir}")
    _print(f"[export] dry_run={dry_run}, force={force}, days={days}, flux={flux}, keyword={keyword}")

    # 1. Préparer la structure
    dirs = ensure_vault_structure(vault_dir, dry_run=dry_run)

    # 2. Collecter les articles
    articles = _collect_articles(project_root, flux=flux, keyword=keyword, days=days)
    if not articles:
        _print("[export] Aucun article à exporter")
        return {"articles_créés": 0, "articles_ignorés": 0}

    # 3. Charger l'index entités
    entity_index: dict = {}
    entity_caps: dict = {}
    entity_index_path = project_root / "data" / "entity_index.json"
    if entity_index_path.exists():
        try:
            raw = json.loads(entity_index_path.read_text(encoding="utf-8"))
            entity_index = raw.get("index", raw)
            entity_caps = raw.get("caps", {})
        except (json.JSONDecodeError, OSError):
            pass
    entity_index_keys = set(entity_index.keys())

    # 4. Charger le cache de géolocalisation
    geocode: dict = {}
    geocode_path = project_root / "data" / "geocode_cache.json"
    if geocode_path.exists():
        try:
            geocode = json.loads(geocode_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass

    # 5. Exporter les articles (3.2)
    art_created, art_skipped = export_articles(
        articles, dirs["articles"], entity_index_keys, geocode,
        geocode_cache_path=geocode_path if geocode_path.exists() else None,
        dry_run=dry_run, force=force
    )

    # 6. Exporter les entités (3.3)
    ent_created = ent_skipped = 0
    geo_created = geo_skipped = 0
    if not no_entities and entity_index:
        timeline = _load_entity_timeline(project_root)
        ent_created, ent_skipped = export_entities(
            entity_index, entity_caps, timeline, dirs["entities"],
            project_root, dry_run=dry_run, force=force
        )
        # 6b. Notes géographiques GPE/LOC (3.4)
        geo_cache_path = geocode_path if geocode_path.exists() else None
        geo_created, geo_skipped = export_geo_entities(
            entity_index, entity_caps, geocode, geo_cache_path,
            dirs["entities"], project_root, dry_run=dry_run, force=force
        )

    # 7. Copier les rapports (3.5 partiel)
    rap_created, rap_skipped = export_rapports(
        project_root, dirs["rapports"], dry_run=dry_run, force=force
    )

    # 8. Générer les synthèses (3.5)
    syn_created = syn_skipped = 0
    if not no_synthesis:
        syn_created, syn_skipped = export_syntheses(
            articles, dirs["syntheses"], dry_run=dry_run, force=force
        )

    stats = {
        "vault": str(vault_dir),
        "dry_run": dry_run,
        "articles_créés": art_created,
        "articles_ignorés": art_skipped,
        "entités_créées": ent_created + geo_created,
        "entités_ignorées": ent_skipped,
        "rapports_copiés": rap_created,
        "synthèses_créées": syn_created,
        "total_créés": art_created + ent_created + geo_created + rap_created + syn_created,
    }

    _print(
        f"[export] Terminé — {stats['total_créés']} fichiers créés "
        f"({art_created} articles, {ent_created} entités, {rap_created} rapports, "
        f"{syn_created} synthèses)"
    )
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export WUDD.ai → vault Obsidian",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--flux", help="Nom du flux à exporter (all si absent)")
    parser.add_argument("--keyword", help="Mot-clé RSS à exporter")
    parser.add_argument("--days", type=int, default=None,
                        help="Limiter aux N derniers jours")
    parser.add_argument("--dry-run", action="store_true",
                        help="Simulation sans écriture")
    parser.add_argument("--force", action="store_true",
                        help="Écraser les notes existantes")
    parser.add_argument("--no-entities", action="store_true",
                        help="Ne pas exporter les notes entités")
    parser.add_argument("--no-synthesis", action="store_true",
                        help="Ne pas générer les notes de synthèse")
    args = parser.parse_args()

    stats = run_export(
        flux=args.flux,
        keyword=args.keyword,
        days=args.days,
        dry_run=args.dry_run,
        force=args.force,
        no_entities=args.no_entities,
        no_synthesis=args.no_synthesis,
    )
    print(json.dumps(stats, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
