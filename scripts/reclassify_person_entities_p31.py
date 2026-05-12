#!/usr/bin/env python3
"""Rétro-nettoyage NER : reclassifie les faux PERSON via Wikidata P31.

Objectif:
- Scanner les fichiers JSON existants (flux + RSS)
- Reclasser les entités PERSON non-humaines (P31 != Q5)
- Proposer un mode dry-run pour mesurer l'impact avant activation en production

Usage:
    # Dry-run (par défaut) sur tout le corpus
    python3 scripts/reclassify_person_entities_p31.py

    # Dry-run ciblé sur un flux
    python3 scripts/reclassify_person_entities_p31.py --flux Intelligence-artificielle

    # Dry-run ciblé sur un mot-clé RSS
    python3 scripts/reclassify_person_entities_p31.py --keyword openai

    # Appliquer les changements sur disque
    python3 scripts/reclassify_person_entities_p31.py --apply

    # Limiter le périmètre (validation rapide)
    python3 scripts/reclassify_person_entities_p31.py --max-files 3
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.article_index import get_article_index
from utils.config import get_config
from utils.entity_index import get_entity_index
from utils.logging import print_console, setup_logger
from utils.ner_guardrails import sanitize_entities

logger = setup_logger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reclassifie les faux PERSON historiques via Wikidata P31 (dry-run par défaut)."
    )
    parser.add_argument(
        "--flux",
        type=str,
        default=None,
        help="Traiter uniquement ce flux (data/articles/<flux>/)",
    )
    parser.add_argument(
        "--keyword",
        type=str,
        default=None,
        help="Traiter uniquement ce mot-clé RSS (data/articles-from-rss/<keyword>.json)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Applique les changements sur disque (sinon dry-run).",
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=0,
        help="Limite le nombre de fichiers traités (0 = pas de limite).",
    )
    parser.add_argument(
        "--from-report",
        type=str,
        default=None,
        help="Réutilise un rapport JSON existant pour ne retraiter que les fichiers concernés.",
    )
    return parser.parse_args()


def collect_files_from_report(report_path: Path) -> list[tuple[Path, str]]:
    if not report_path.is_file():
        print_console(f"Rapport introuvable : {report_path}", level="error")
        sys.exit(1)

    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except Exception as exc:
        print_console(f"Rapport invalide : {exc}", level="error")
        sys.exit(1)

    tagged_files: list[tuple[Path, str]] = []
    seen: set[str] = set()
    for change in payload.get("changes", []):
        rel_path = change.get("file")
        if not isinstance(rel_path, str) or not rel_path or rel_path in seen:
            continue
        seen.add(rel_path)
        abs_path = PROJECT_ROOT / rel_path
        if not abs_path.is_file():
            continue
        label = "rss/rapport" if "/articles-from-rss/" in f"/{rel_path}" else "flux/rapport"
        tagged_files.append((abs_path, label))

    return tagged_files


def collect_flux_files(articles_dir: Path, flux_filter: str | None) -> list[tuple[Path, str]]:
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

    files: list[tuple[Path, str]] = []
    for d in dirs:
        for f in sorted(d.glob("articles_generated_*.json")):
            files.append((f, f"flux/{d.name}"))
    return files


def collect_rss_files(rss_dir: Path, keyword_filter: str | None) -> list[tuple[Path, str]]:
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


def _entity_pairs(entities: dict) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for etype, values in entities.items():
        if not isinstance(etype, str) or not isinstance(values, list):
            continue
        for value in values:
            if isinstance(value, str) and value.strip():
                pairs.add((etype.strip().upper(), value.strip()))
    return pairs


def process_file(json_file: Path, apply_changes: bool) -> tuple[dict, list[dict]]:
    stats = {
        "articles_total": 0,
        "articles_with_entities": 0,
        "articles_with_person": 0,
        "articles_changed": 0,
        "files_changed": 0,
    }
    change_rows: list[dict] = []

    try:
        articles = json.loads(json_file.read_text(encoding="utf-8"))
    except Exception as exc:
        print_console(f"  JSON invalide ({json_file.name}) : {exc}", level="error")
        return stats, change_rows

    if not isinstance(articles, list):
        print_console(f"  Format inattendu (pas une liste) : {json_file.name}", level="warning")
        return stats, change_rows

    modified = False
    for idx, article in enumerate(articles):
        stats["articles_total"] += 1
        entities = article.get("entities")
        if not isinstance(entities, dict) or not entities:
            continue

        stats["articles_with_entities"] += 1
        persons = entities.get("PERSON")
        if not isinstance(persons, list) or not persons:
            continue

        stats["articles_with_person"] += 1

        before_pairs = _entity_pairs(entities)
        after = sanitize_entities(entities, validate_person_p31=True)
        after_pairs = _entity_pairs(after)

        if before_pairs == after_pairs:
            continue

        stats["articles_changed"] += 1
        modified = True

        removed = sorted(list(before_pairs - after_pairs))
        added = sorted(list(after_pairs - before_pairs))
        change_rows.append(
            {
                "file": str(json_file.relative_to(PROJECT_ROOT)).replace("\\", "/"),
                "article_index": idx,
                "url": article.get("URL", ""),
                "source": article.get("Sources", ""),
                "removed": [{"type": t, "value": v} for t, v in removed],
                "added": [{"type": t, "value": v} for t, v in added],
            }
        )

        if apply_changes:
            article["entities"] = after

    if modified and apply_changes:
        tmp = json_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(articles, ensure_ascii=False, indent=4), encoding="utf-8")
        tmp.replace(json_file)
        stats["files_changed"] = 1

        # Mettre à jour les index pour refléter le nettoyage historique.
        rel = str(json_file.relative_to(PROJECT_ROOT)).replace("\\", "/")
        try:
            get_article_index(PROJECT_ROOT).update(articles, rel)
            get_entity_index(PROJECT_ROOT).update(articles, rel)
        except Exception as exc:
            print_console(f"  Avertissement index ({json_file.name}) : {exc}", level="warning")

    return stats, change_rows


def main() -> int:
    args = parse_args()
    apply_changes = args.apply
    dry_run = not apply_changes

    print_console("=" * 70)
    print_console("Rétro-nettoyage NER — garde-fou PERSON P31", level="info")
    if dry_run:
        print_console("[MODE DRY-RUN] aucun fichier ne sera modifié", level="info")
    else:
        print_console("[MODE APPLY] les fichiers seront mis à jour", level="warning")
    print_console("=" * 70)

    try:
        config = get_config()
    except ValueError as exc:
        print_console(f"Erreur de configuration : {exc}", level="error")
        return 1

    articles_dir = config.data_articles_dir
    rss_dir = articles_dir.parent / "articles-from-rss"

    if args.from_report:
        tagged_files = collect_files_from_report(Path(args.from_report))
    else:
        process_flux = args.flux is not None or args.keyword is None
        process_rss = args.keyword is not None or args.flux is None

        tagged_files = []
        if process_flux:
            tagged_files += collect_flux_files(articles_dir, args.flux)
        if process_rss:
            tagged_files += collect_rss_files(rss_dir, args.keyword)

    if args.max_files and args.max_files > 0:
        tagged_files = tagged_files[: args.max_files]

    if not tagged_files:
        print_console("Aucun fichier à traiter", level="warning")
        return 0

    totals = defaultdict(int)
    report_rows: list[dict] = []

    for json_file, label in tagged_files:
        print_console(f"[{label}] {json_file.name}", level="info")
        stats, rows = process_file(json_file, apply_changes=apply_changes)
        report_rows.extend(rows)

        print_console(
            f"  articles={stats['articles_total']}"
            f"  avec_entities={stats['articles_with_entities']}"
            f"  avec_person={stats['articles_with_person']}"
            f"  changés={stats['articles_changed']}",
            level="info",
        )

        for key, value in stats.items():
            totals[key] += value

    transitions = defaultdict(int)
    for row in report_rows:
        removed_map = {(x["value"], x["type"]) for x in row.get("removed", [])}
        for added in row.get("added", []):
            value = added.get("value")
            new_type = added.get("type")
            for old_type in ("PERSON", "NORP", "GPE", "LOC", "FAC", "ORG", "PRODUCT"):
                if (value, old_type) in removed_map and old_type != new_type:
                    transitions[f"{old_type}->{new_type}"] += 1

    print_console("", level="info")
    print_console("Résumé", level="info")
    print_console(f"- fichiers traités: {len(tagged_files)}", level="info")
    print_console(f"- articles scannés: {totals['articles_total']}", level="info")
    print_console(f"- articles avec entities: {totals['articles_with_entities']}", level="info")
    print_console(f"- articles avec PERSON: {totals['articles_with_person']}", level="info")
    print_console(f"- articles impactés P31: {totals['articles_changed']}", level="info")
    if apply_changes:
        print_console(f"- fichiers modifiés: {totals['files_changed']}", level="warning")

    if transitions:
        print_console("- transitions détectées:", level="info")
        for k, v in sorted(transitions.items(), key=lambda kv: kv[1], reverse=True):
            print_console(f"  * {k}: {v}", level="info")

    report = {
        "dry_run": dry_run,
        "files": len(tagged_files),
        "stats": dict(totals),
        "transitions": dict(transitions),
        "changes": report_rows,
    }
    report_dir = PROJECT_ROOT / "rapports" / "markdown" / "_WUDD.AI_"
    report_dir.mkdir(parents=True, exist_ok=True)
    suffix = "dryrun" if dry_run else "applied"
    report_path = report_dir / f"ner_p31_reclass_{suffix}.json"
    if args.from_report:
        suffix = "targeted_dryrun" if dry_run else "targeted_applied"
        report_path = report_dir / f"ner_p31_reclass_{suffix}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print_console(f"Rapport: {report_path}", level="info")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print_console("Interruption utilisateur", level="warning")
        raise SystemExit(130)
