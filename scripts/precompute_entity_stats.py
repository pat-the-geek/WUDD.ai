#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/precompute_entity_stats.py — Pré-calcul nightly des statistiques d'entités.

Génère data/entity_stats.json depuis entity_index (ou DuckDB en fallback).
Ce fichier sert de cache chaud pour api_entities_dashboard() et évite le
recalcul à chaque démarrage du viewer.

Usage :
  python3 scripts/precompute_entity_stats.py [--dry-run]

Cron (ex. avant le briefing du matin) :
  30 1 * * * python3 /app/scripts/precompute_entity_stats.py >> /var/log/wudd_precompute.log 2>&1
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()
PROJECT_ROOT = SCRIPT_DIR.parent

sys.path.insert(0, str(PROJECT_ROOT))

from utils.logging import print_console, setup_logger

logger = setup_logger("precompute_entity_stats")

OUTPUT_FILE = PROJECT_ROOT / "data" / "entity_stats.json"
SCHEMA_VERSION = 2


def _build_from_entity_index() -> dict | None:
    """Construit les stats depuis entity_index (chemin rapide, O(index_keys))."""
    try:
        from utils.entity_index import get_entity_index
        eidx = get_entity_index(PROJECT_ROOT)
        all_entries = eidx.get_all_entries()   # {TYPE:value: [{file, idx, date}]}
        if not all_entries:
            return None

        by_type: dict[str, dict[str, int]] = {}
        for key, refs in all_entries.items():
            parts = key.split(":", 1)
            if len(parts) != 2:
                continue
            etype, value = parts[0], parts[1].strip()
            if not value:
                continue
            by_type.setdefault(etype, {})
            by_type[etype][value] = by_type[etype].get(value, 0) + len(refs)

        return by_type
    except Exception as e:
        print_console(f"  entity_index indisponible : {e}", level="warning")
        return None


def _build_from_duckdb() -> dict | None:
    """Construit les stats depuis DuckDB (I/O parallèles, plus rapide sur grand corpus)."""
    try:
        from utils.db import get_db
        db = get_db(PROJECT_ROOT)
        if not db.available:
            return None
        print_console("  Utilisation de DuckDB pour le calcul des stats…")
        raw = db.top_entities_by_type(top_n=200)
        if not raw:
            return None
        # Convertir en {etype: {value: count}}
        by_type: dict[str, dict[str, int]] = {}
        for etype, items in raw.items():
            by_type[etype] = {item["value"]: item["count"] for item in items}
        return by_type
    except Exception as e:
        print_console(f"  DuckDB indisponible : {e}", level="warning")
        return None


def build_entity_stats() -> dict:
    """Construit le dict complet des stats d'entités (by_type + top50 par type)."""
    print_console("Calcul des stats d'entités depuis l'index…")
    by_type = _build_from_entity_index()

    if not by_type:
        print_console("Fallback vers DuckDB…")
        by_type = _build_from_duckdb()

    if not by_type:
        print_console("Aucune source disponible. stats vides générées.", level="warning")
        by_type = {}

    result_types = []
    for etype, value_counts in by_type.items():
        sorted_values = sorted(value_counts.items(), key=lambda x: x[1], reverse=True)
        result_types.append({
            "type": etype,
            "unique_count": len(sorted_values),
            "mention_count": sum(c for _, c in sorted_values),
            "top": [{"value": v, "count": c} for v, c in sorted_values[:50]],
        })
    result_types.sort(key=lambda x: x["mention_count"], reverse=True)

    # Stats article_index
    total_articles = 0
    total_with_entities = 0
    total_files = 0
    try:
        from utils.article_index import get_article_index
        aidx = get_article_index(PROJECT_ROOT)
        astats = aidx.stats()
        total_articles = astats.get("total", 0)
        total_with_entities = astats.get("with_entities", 0)
        total_files = astats.get("total_files", 0)
    except Exception:
        pass

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_files": total_files,
        "total_articles": total_articles,
        "total_with_entities": total_with_entities,
        "by_type": result_types,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Pré-calcule data/entity_stats.json depuis entity_index."
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Calcule sans écrire le fichier de sortie.")
    args = parser.parse_args()

    print_console("=== precompute_entity_stats démarré ===")
    stats = build_entity_stats()

    n_types = len(stats["by_type"])
    n_entities = sum(t["unique_count"] for t in stats["by_type"])
    msg = (
        f"{n_types} type(s), {n_entities} entité(s) unique(s), "
        f"{stats['total_with_entities']}/{stats['total_articles']} articles enrichis"
    )
    print_console(f"Résultat : {msg}")

    if args.dry_run:
        print_console("[DRY-RUN] Fichier non écrit.")
    else:
        OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = OUTPUT_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(OUTPUT_FILE)
        print_console(f"✓ {OUTPUT_FILE.relative_to(PROJECT_ROOT)} mis à jour.")

    print_console("=== precompute_entity_stats terminé ===")


if __name__ == "__main__":
    main()
