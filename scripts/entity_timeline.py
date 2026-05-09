#!/usr/bin/env python3
"""
entity_timeline.py — Suivi temporel des entités nommées (Priorité 3)

Construit une série chronologique des mentions d'entités en scannant tous les
fichiers d'articles. Le résultat est sauvegardé dans data/entity_timeline.json.

Sortie : data/entity_timeline.json
Format :
  {
    "generated_at": "2026-03-06T22:00:00Z",
    "timeline": {
      "PERSON:Emmanuel Macron": {
        "2026-02-01": 3,
        "2026-02-02": 0,
        ...
      },
      ...
    },
    "top_entities": [
      { "key": "PERSON:Emmanuel Macron", "type": "PERSON", "value": "...", "total": 42 }
    ]
  }

Usage :
    python3 scripts/entity_timeline.py
    python3 scripts/entity_timeline.py --days 30 --top 50 --dry-run
    python3 scripts/entity_timeline.py --entity "OpenAI" --type ORG
"""

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from utils.logging import default_logger
from utils.entity_canonicalization import get_entity_canonicalizer

# ── Constantes ───────────────────────────────────────────────────────────────

_OUTPUT_FILE = _PROJECT_ROOT / "data" / "entity_timeline.json"

_MONITORED_TYPES = {
    "PERSON", "ORG", "GPE", "PRODUCT", "EVENT", "NORP", "LOC", "FAC"
}

_DATE_FMTS = (
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%d",
    "%d/%m/%Y",
)


# ── Parsing de date ───────────────────────────────────────────────────────────

def _parse_date(date_str: str) -> datetime | None:
    """Retourne un datetime UTC ou None."""
    if not date_str:
        return None
    for fmt in _DATE_FMTS:
        try:
            return datetime.strptime(date_str[:len(fmt)], fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    try:
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(date_str).astimezone(timezone.utc)
    except Exception:
        pass
    return None


# ── Collecte ──────────────────────────────────────────────────────────────────

def _collect_timeline_from_index(
    project_root: Path,
    days: int,
    entity_filter: str | None,
    type_filter: str | None,
) -> dict[str, dict[str, int]] | None:
    """Construit la timeline depuis l'entity_index sans scan rglob.

    Retourne None si l'index est absent ou vide (→ fallback rglob).
    """
    try:
        from utils.entity_index import get_entity_index
        eidx = get_entity_index(project_root)
        all_entries = eidx.get_all_entries(canonicalize=True)
    except Exception:
        return None

    if not all_entries:
        return None  # Index vide → fallback rglob

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days) if days > 0 else None

    monitored = _MONITORED_TYPES
    if type_filter and type_filter.upper() in _MONITORED_TYPES:
        monitored = {type_filter.upper()}

    canonicalizer = get_entity_canonicalizer(project_root)
    entity_filter_lower = None
    if entity_filter:
        _, canonical_value = canonicalizer.canonicalize(type_filter or "", entity_filter)
        entity_filter_lower = canonical_value.lower()

    timeline: dict[str, dict[str, int]] = {}

    for key, refs in all_entries.items():
        if ":" not in key:
            continue
        etype, _, value = key.partition(":")
        if etype not in monitored:
            continue
        if entity_filter_lower and entity_filter_lower not in value.lower():
            continue

        date_counts: dict[str, int] = defaultdict(int)
        for ref in refs:
            date_str = ref.get("date", "")
            if not date_str or len(date_str) < 10:
                continue
            date_str = date_str[:10]
            if cutoff:
                try:
                    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                    if dt < cutoff:
                        continue
                except ValueError:
                    continue
            date_counts[date_str] += 1

        if date_counts:
            timeline[key] = dict(date_counts)

    return timeline


def collect_timeline(
    project_root: Path,
    days: int = 30,
    entity_filter: str | None = None,
    type_filter: str | None = None,
) -> dict[str, dict[str, int]]:
    """Construit la série chronologique des mentions d'entités.

    Essaie d'abord l'entity_index (O(1) lecture), puis fallback scan rglob.

    Args:
        project_root  : racine du projet
        days          : fenêtre temporelle en jours (0 = pas de limite)
        entity_filter : filtrer sur une valeur d'entité spécifique (insensible à la casse)
        type_filter   : filtrer sur un type d'entité (ex: "PERSON")

    Returns:
        { "TYPE:valeur" : { "YYYY-MM-DD" : count, ... }, ... }
    """
    # Tentative via entity_index (évite le scan rglob complet)
    result = _collect_timeline_from_index(project_root, days, entity_filter, type_filter)
    if result is not None:
        default_logger.info("  [entity_index] Timeline construite sans scan rglob")
        return result

    default_logger.info("  [rglob] Index absent — scan complet des fichiers")
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days) if days > 0 else None

    # timeline[entity_key][date_str] = count
    timeline: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    scan_dirs = [
        project_root / "data" / "articles",
        project_root / "data" / "articles-from-rss",
    ]

    monitored = _MONITORED_TYPES
    if type_filter and type_filter.upper() in _MONITORED_TYPES:
        monitored = {type_filter.upper()}

    canonicalizer = get_entity_canonicalizer(project_root)
    entity_filter_lower = None
    if entity_filter:
        _, canonical_value = canonicalizer.canonicalize(type_filter or "", entity_filter)
        entity_filter_lower = canonical_value.lower()

    for scan_dir in scan_dirs:
        if not scan_dir.exists():
            continue
        for json_file in scan_dir.rglob("*.json"):
            if "cache" in json_file.relative_to(scan_dir).parts:
                continue
            try:
                data = json.loads(json_file.read_text(encoding="utf-8", errors="replace"))
                if not isinstance(data, list):
                    continue
            except (json.JSONDecodeError, OSError):
                continue

            for article in data:
                dt = _parse_date(article.get("Date de publication", ""))
                if dt is None:
                    continue
                if cutoff and dt < cutoff:
                    continue

                date_str = dt.strftime("%Y-%m-%d")
                entities = article.get("entities")
                if not isinstance(entities, dict):
                    continue

                for etype, values in entities.items():
                    if etype not in monitored:
                        continue
                    if not isinstance(values, list):
                        continue
                    for v in values:
                        if not isinstance(v, str) or not v.strip():
                            continue
                        v = v.strip()
                        if canonicalizer.is_noise(etype, v):
                            continue
                        canonical_type, canonical_value = canonicalizer.canonicalize(etype, v)
                        if canonical_type not in monitored:
                            continue
                        if entity_filter_lower and entity_filter_lower not in canonical_value.lower():
                            continue
                        key = f"{canonical_type}:{canonical_value}"
                        timeline[key][date_str] += 1

    return {k: dict(v) for k, v in timeline.items()}


# ── Post-traitement ──────────────────────────────────────────────────────────

def fill_missing_dates(
    timeline: dict[str, dict[str, int]],
    days: int,
) -> dict[str, dict[str, int]]:
    """Remplit les dates manquantes avec 0 pour produire des séries continues."""
    now = datetime.now(timezone.utc)
    all_dates = [
        (now - timedelta(days=i)).strftime("%Y-%m-%d")
        for i in range(days - 1, -1, -1)
    ]
    filled = {}
    for key, counts in timeline.items():
        filled[key] = {d: counts.get(d, 0) for d in all_dates}
    return filled


def build_top_entities(
    timeline: dict[str, dict[str, int]],
    top_n: int = 30,
) -> list[dict]:
    """Retourne les top_n entités triées par total de mentions décroissant."""
    totals = [
        {"key": key, "total": sum(counts.values()), **_split_key(key)}
        for key, counts in timeline.items()
    ]
    totals.sort(key=lambda x: x["total"], reverse=True)
    return totals[:top_n]


def _split_key(key: str) -> dict:
    """Décompose 'TYPE:valeur' en {'type': ..., 'value': ...}."""
    if ":" in key:
        etype, value = key.split(":", 1)
        return {"type": etype, "value": value}
    return {"type": "UNKNOWN", "value": key}


# ── Point d'entrée ────────────────────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(
        description="Génère la chronologie des entités WUDD.ai"
    )
    parser.add_argument(
        "--days", type=int, default=30,
        help="Fenêtre temporelle en jours (défaut: 30)"
    )
    parser.add_argument(
        "--top", type=int, default=30,
        help="Nombre d'entités à conserver (défaut: 30)"
    )
    parser.add_argument(
        "--entity", type=str, default=None,
        help="Filtrer sur une entité spécifique (recherche dans la valeur)"
    )
    parser.add_argument(
        "--type", type=str, default=None, dest="entity_type",
        help="Filtrer sur un type d'entité (PERSON, ORG, GPE…)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Affiche le résultat sans sauvegarder"
    )
    return parser.parse_args()


def main():
    args = parse_args()

    project_root = _PROJECT_ROOT

    default_logger.info("=== Chronologie des entités WUDD.ai ===")
    default_logger.info(
        f"Fenêtre : {args.days} jours | Top {args.top}"
        + (f" | Entité : {args.entity}" if args.entity else "")
        + (f" | Type : {args.entity_type}" if args.entity_type else "")
    )

    raw_timeline = collect_timeline(
        project_root,
        days=args.days,
        entity_filter=args.entity,
        type_filter=args.entity_type,
    )
    default_logger.info(f"  → {len(raw_timeline)} entités distinctes trouvées")

    # Garder seulement les top_n entités (par total de mentions)
    top_entities = build_top_entities(raw_timeline, top_n=args.top)
    top_keys = {e["key"] for e in top_entities}
    filtered_timeline = {k: v for k, v in raw_timeline.items() if k in top_keys}

    # Remplir les dates manquantes pour séries continues
    filled = fill_missing_dates(filtered_timeline, days=args.days)

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window_days": args.days,
        "top_entities": top_entities,
        "timeline": filled,
    }

    if args.dry_run:
        default_logger.info("[DRY-RUN] Résultat non sauvegardé.")
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return

    _OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    _OUTPUT_FILE.write_text(
        json.dumps(output, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    default_logger.info(f"Chronologie sauvegardée dans {_OUTPUT_FILE}")
    default_logger.info(
        f"  {len(filled)} entités | {args.days} jours de données"
    )


if __name__ == "__main__":
    main()
