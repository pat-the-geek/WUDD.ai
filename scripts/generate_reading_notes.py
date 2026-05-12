#!/usr/bin/env python3
"""
generate_reading_notes.py — Notes de lecture personnelles par tag (08h00)

Lit data/annotations.json et génère un rapport Markdown de toutes les
annotations saisies manuellement (note et/ou tags).
Groupées par tag ; articles sans tag regroupés sous « Sans tag ».

Le fichier de sortie est TOUJOURS le même (écrasé à chaque exécution) :
  rapports/markdown/_WUDD.AI_/notes_lecture.md

Usage :
    python3 scripts/generate_reading_notes.py
    python3 scripts/generate_reading_notes.py --dry-run   # affiche sans sauvegarder
"""

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))

from utils.article_index import get_article_index
from utils.config import get_config
from utils.logging import print_console
from utils.scheduler_toggle import should_run_task

ANNOTATIONS_FILE = PROJECT_ROOT / "data" / "annotations.json"
OUTPUT_FILE = PROJECT_ROOT / "rapports" / "markdown" / "_WUDD.AI_" / "notes_lecture.md"


# ── Chargement ────────────────────────────────────────────────────────────────

def load_annotations() -> dict:
    if not ANNOTATIONS_FILE.exists():
        return {}
    try:
        return json.loads(ANNOTATIONS_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        print_console(f"Erreur lecture annotations.json : {e}", level="error")
        return {}


def build_article_index(project_root: Path) -> dict:
    """Construit un index {url: article_dict} depuis l'article_index (sans scan rglob)."""
    aidx = get_article_index(project_root)
    entries = aidx.get_recent(hours=0)  # heures=0 → tous les articles
    return {
        e["url"]: {
            "Sources": e.get("source", ""),
            "Date de publication": e.get("date_iso", ""),
        }
        for e in entries
        if e.get("url")
    }


# ── Helpers ───────────────────────────────────────────────────────────────────

def parse_date(date_str: str) -> datetime | None:
    if not date_str:
        return None
    try:
        dt = parsedate_to_datetime(date_str)
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
    except Exception:
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(date_str[:19], fmt)
            return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
        except Exception:
            continue
    return None


def format_datetime(date_str: str) -> str:
    dt = parse_date(date_str)
    if dt:
        return dt.strftime("%d/%m/%Y · %H:%M")
    return date_str[:10] if date_str else ""


def extract_title(article: dict, url: str = "") -> str:
    titre = (article.get("Titre") or "").strip()
    if titre:
        return titre[:150]
    for line in (article.get("Résumé") or "").split("\n"):
        line = line.strip().lstrip("*_#").strip()
        if len(line) > 10:
            return line[:150]
    # Fallback : dernier segment de l'URL
    return url.rstrip("/").split("/")[-1][:100] if url else "Sans titre"


# ── Construction du Markdown ──────────────────────────────────────────────────

def build_reading_notes_markdown(
    annotated: list,
    today_str: str,
    today_iso: str,
) -> str:
    # Grouper par tag (un article avec N tags apparaît dans N sections)
    by_tag: dict[str, list] = defaultdict(list)
    for entry in annotated:
        tags = entry["tags"]
        if tags:
            for tag in tags:
                by_tag[tag].append(entry)
        else:
            by_tag["Sans tag"].append(entry)

    sorted_tags = sorted([t for t in by_tag if t != "Sans tag"], key=str.lower)
    if "Sans tag" in by_tag:
        sorted_tags.append("Sans tag")

    total = len(annotated)
    nb_tags = len(by_tag)

    lines = [
        "---",
        'title: "Notes de lecture WUDD.ai"',
        f"date: {today_iso}",
        f"mis_à_jour: {today_str}",
        f"annotations: {total}",
        f"tags: {nb_tags}",
        "---",
        "",
        "# Notes de lecture",
        "",
        f"> {total} article(s) annotés · {nb_tags} tag(s) · mis à jour le {today_str}",
        "",
        "## Sommaire",
        "",
    ]

    for tag in sorted_tags:
        anchor = tag.lower().replace(" ", "-").replace("_", "-")
        lines.append(f"- [{tag}](#{anchor}) ({len(by_tag[tag])})")
    lines.append("")

    for tag in sorted_tags:
        lines.append(f"## {tag}")
        lines.append("")
        entries = sorted(by_tag[tag], key=lambda e: e.get("updated_at", ""), reverse=True)
        for entry in entries:
            url = entry["url"]
            notes = entry["notes"]
            is_important = entry.get("is_important", False)
            article = entry.get("article") or {}
            source = article.get("Sources", "")
            date_label = format_datetime(article.get("Date de publication", ""))
            titre = extract_title(article, url)

            meta_parts = []
            if date_label:
                meta_parts.append(date_label)
            if source:
                meta_parts.append(f"*{source}*")
            meta = " · ".join(meta_parts)

            star = "⭐ " if is_important else ""
            lines.append(f"- {meta + ' — ' if meta else ''}{star}[{titre}]({url})")
            if notes:
                lines.append(f"  > {notes}")

        lines.append("")

    return "\n".join(lines)


# ── Point d'entrée ────────────────────────────────────────────────────────────

def generate_reading_notes(dry_run: bool = False) -> None:
    config = get_config()
    config.setup_directories()

    now = datetime.now(timezone.utc)
    today_iso = now.strftime("%Y-%m-%d")
    today_str = now.strftime("%-d %B %Y")

    print_console("=== Notes de lecture ===")

    # 1. Charger les annotations
    annotations = load_annotations()
    print_console(f"{len(annotations)} annotations chargées")

    # 2. Garder uniquement celles avec note OU tags saisis
    selected = {
        url: ann for url, ann in annotations.items()
        if ann.get("notes", "").strip() or [t for t in (ann.get("tags") or []) if t]
    }
    print_console(f"{len(selected)} annotations avec note ou tag")

    if not selected:
        print_console("Aucune annotation à exporter — rapport annulé", level="warning")
        sys.exit(0)

    # 3. Index URL → métadonnées article
    print_console("Construction de l'index articles…")
    article_index = build_article_index(PROJECT_ROOT)
    print_console(f"{len(article_index)} articles indexés")

    # 4. Assembler les entrées, triées par date de mise à jour décroissante
    annotated = sorted(
        [
            {
                "url": url,
                "tags": [t for t in (ann.get("tags") or []) if t],
                "notes": ann.get("notes", "").strip(),
                "is_important": bool(ann.get("is_important", False)),
                "updated_at": ann.get("updated_at", ""),
                "article": article_index.get(url, {}),
            }
            for url, ann in selected.items()
        ],
        key=lambda e: e["updated_at"],
        reverse=True,
    )

    # 5. Construire le Markdown
    notes_md = build_reading_notes_markdown(
        annotated=annotated,
        today_str=today_str,
        today_iso=today_iso,
    )

    if dry_run:
        print_console("=== MODE DRY-RUN — aperçu ===")
        print(notes_md[:4000])
        if len(notes_md) > 4000:
            print(f"\n[...tronqué — {len(notes_md)} caractères au total]")
        return

    # 6. Sauvegarder — fichier fixe, toujours écrasé
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(notes_md, encoding="utf-8")
    print_console(f"✓ Notes sauvegardées : {OUTPUT_FILE}")


def main() -> None:
    if not should_run_task("reports.reading_notes"):
        return

    parser = argparse.ArgumentParser(description="Génère les notes de lecture personnelles WUDD.ai")
    parser.add_argument("--dry-run", action="store_true", help="Affiche sans sauvegarder")
    args = parser.parse_args()

    generate_reading_notes(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
