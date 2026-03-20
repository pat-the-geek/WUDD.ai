#!/usr/bin/env python3
"""
cross_flux_analysis.py — Analyse croisée des flux (Priorité 7)

Détecte les entités et thèmes communs entre plusieurs flux de veille, révélant
les sujets qui transcendent les domaines surveillés. Utile pour identifier les
signaux forts et les convergences thématiques.

Sortie : data/cross_flux_report.json + rapports/markdown/_CROSSFLUX_/cross_flux_YYYY-MM-DD.md

Usage :
    python3 scripts/cross_flux_analysis.py
    python3 scripts/cross_flux_analysis.py --days 7
    python3 scripts/cross_flux_analysis.py --min-flux 2 --top 20
    python3 scripts/cross_flux_analysis.py --dry-run
"""

import argparse
import json
import re
import sys
import unicodedata
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from utils.logging import print_console, default_logger

# ── Constantes ───────────────────────────────────────────────────────────────

_OUTPUT_JSON = _PROJECT_ROOT / "data" / "cross_flux_report.json"
_OUTPUT_DIR  = _PROJECT_ROOT / "rapports" / "markdown" / "_CROSSFLUX_"

_ENTITY_TYPES_PERTINENTS = {
    "PERSON", "ORG", "GPE", "PRODUCT", "EVENT", "NORP"
}

_DATE_FMTS = (
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%d",
    "%d/%m/%Y",
)


# ── Parsing de date ───────────────────────────────────────────────────────────

def _parse_date(date_str: str) -> datetime | None:
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


# ── Collecte par flux ─────────────────────────────────────────────────────────

def _file_path_to_flux_name(file_path: str) -> str:
    """Dérive le nom du flux depuis le chemin relatif stocké dans l'entity_index."""
    if not file_path:
        return ""
    parts = Path(file_path).parts
    # data/articles/<flux_dir>/...json
    if len(parts) >= 3 and parts[1] == "articles":
        return parts[2]
    # data/articles-from-rss/<subdir>/<file>.json
    if len(parts) == 4 and parts[1] == "articles-from-rss":
        return f"rss:{parts[2]}/{Path(file_path).stem}"
    # data/articles-from-rss/<file>.json
    if len(parts) == 3 and parts[1] == "articles-from-rss":
        return f"rss:{Path(file_path).stem}"
    return ""


def _collect_entities_from_index(
    project_root: Path,
    days: int,
) -> dict[str, dict[str, int]] | None:
    """Construit l'analyse croisée depuis l'entity_index sans scan rglob.

    Retourne None si l'index est absent ou vide (→ fallback rglob).
    """
    try:
        from utils.entity_index import get_entity_index
        eidx = get_entity_index(project_root)
        all_entries = eidx.get_all_entries()
    except Exception:
        return None

    if not all_entries:
        return None

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days) if days > 0 else None

    flux_entities: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for entity_key, refs in all_entries.items():
        if ":" not in entity_key:
            continue
        etype = entity_key.split(":", 1)[0]
        if etype not in _ENTITY_TYPES_PERTINENTS:
            continue

        for ref in refs:
            date_str = ref.get("date", "")
            if cutoff and date_str:
                try:
                    dt = datetime.strptime(date_str[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
                    if dt < cutoff:
                        continue
                except ValueError:
                    pass

            flux_name = _file_path_to_flux_name(ref.get("file", ""))
            if flux_name:
                flux_entities[flux_name][entity_key] += 1

    return {flux: dict(counts) for flux, counts in flux_entities.items()}


# ── Comptage des articles par flux ──────────────────────────────────────────

def _sanitize_for_mermaid(name: str) -> str:
    """Supprime accents et caractères spéciaux pour les labels Mermaid."""
    nfkd = unicodedata.normalize('NFKD', name)
    ascii_str = nfkd.encode('ascii', 'ignore').decode('ascii')
    clean = re.sub(r'[^a-zA-Z0-9 \-_]', '-', ascii_str)
    clean = re.sub(r'-{2,}', '-', clean).strip('-')
    return clean[:28]


def _count_articles_in_file(json_file: Path, cutoff: datetime | None) -> int:
    """Compte les articles valides dans une fenêtre temporelle."""
    try:
        data = json.loads(json_file.read_text(encoding="utf-8", errors="replace"))
        if not isinstance(data, list):
            return 0
    except (json.JSONDecodeError, OSError):
        return 0
    if cutoff is None:
        return len(data)
    count = 0
    for article in data:
        dt = _parse_date(article.get("Date de publication", ""))
        if dt is not None and dt >= cutoff:
            count += 1
    return count


def collect_article_counts_by_flux(
    project_root: Path,
    days: int = 30,
) -> dict[str, int]:
    """Compte le nombre d'articles par flux dans la fenêtre temporelle."""
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days) if days > 0 else None
    counts: dict[str, int] = defaultdict(int)

    articles_dir = project_root / "data" / "articles"
    if articles_dir.exists():
        for flux_dir in articles_dir.iterdir():
            if not flux_dir.is_dir():
                continue
            flux_name = flux_dir.name
            for json_file in flux_dir.rglob("*.json"):
                if "cache" in json_file.relative_to(articles_dir).parts:
                    continue
                counts[flux_name] += _count_articles_in_file(json_file, cutoff)

    rss_dir = project_root / "data" / "articles-from-rss"
    if rss_dir.exists():
        for json_file in rss_dir.rglob("*.json"):
            if "cache" in json_file.relative_to(rss_dir).parts:
                continue
            flux_name = (
                f"rss:{json_file.parent.name}/{json_file.stem}"
                if json_file.parent != rss_dir
                else f"rss:{json_file.stem}"
            )
            counts[flux_name] += _count_articles_in_file(json_file, cutoff)

    return dict(counts)


def collect_entities_by_flux(
    project_root: Path,
    days: int = 30,
) -> dict[str, dict[str, int]]:
    """Collecte les entités par flux (nom du répertoire parent).

    Essaie d'abord l'entity_index (lecture unique), puis fallback scan rglob.

    Returns:
        { "nom_flux" : { "TYPE:valeur" : count } }
    """
    result = _collect_entities_from_index(project_root, days)
    if result is not None:
        return result

    # Fallback : scan rglob complet
    now    = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days) if days > 0 else None

    # flux_entities[flux_name][entity_key] = count
    flux_entities: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    articles_dir = project_root / "data" / "articles"
    if articles_dir.exists():
        for flux_dir in articles_dir.iterdir():
            if not flux_dir.is_dir():
                continue
            flux_name = flux_dir.name
            for json_file in flux_dir.rglob("*.json"):
                if "cache" in json_file.relative_to(articles_dir).parts:
                    continue
                _collect_from_file(json_file, flux_name, cutoff, flux_entities)

    # articles-from-rss : chaque fichier JSON est un "flux" nommé par son stem
    rss_dir = project_root / "data" / "articles-from-rss"
    if rss_dir.exists():
        for json_file in rss_dir.rglob("*.json"):
            if "cache" in json_file.relative_to(rss_dir).parts:
                continue
            flux_name = f"rss:{json_file.parent.name}/{json_file.stem}" if json_file.parent != rss_dir else f"rss:{json_file.stem}"
            _collect_from_file(json_file, flux_name, cutoff, flux_entities)

    # Convertir defaultdicts en dicts normaux
    return {flux: dict(counts) for flux, counts in flux_entities.items()}


def _collect_from_file(
    json_file: Path,
    flux_name: str,
    cutoff: datetime | None,
    flux_entities: dict,
) -> None:
    """Remplit flux_entities depuis un fichier JSON d'articles."""
    try:
        data = json.loads(json_file.read_text(encoding="utf-8", errors="replace"))
        if not isinstance(data, list):
            return
    except (json.JSONDecodeError, OSError):
        return

    for article in data:
        if cutoff:
            dt = _parse_date(article.get("Date de publication", ""))
            if dt is None or dt < cutoff:
                continue
        entities = article.get("entities")
        if not isinstance(entities, dict):
            continue
        for etype, values in entities.items():
            if etype not in _ENTITY_TYPES_PERTINENTS:
                continue
            if not isinstance(values, list):
                continue
            for v in values:
                if isinstance(v, str) and v.strip():
                    flux_entities[flux_name][f"{etype}:{v.strip()}"] += 1


# ── Analyse croisée ───────────────────────────────────────────────────────────

def compute_cross_flux(
    flux_entities: dict[str, dict[str, int]],
    min_flux: int = 2,
    top_n: int = 30,
) -> list[dict]:
    """Identifie les entités présentes dans au moins min_flux flux distincts.

    Args:
        flux_entities : { flux_name : { entity_key : count } }
        min_flux      : nombre minimal de flux où l'entité doit apparaître
        top_n         : nombre d'entités à retourner

    Returns:
        Liste de dicts triée par nombre de flux décroissant, puis total.
    """
    # entity_key → { flux_name : count }
    entity_flux_map: dict[str, dict[str, int]] = defaultdict(dict)

    for flux_name, entities in flux_entities.items():
        for entity_key, count in entities.items():
            entity_flux_map[entity_key][flux_name] = count

    results = []
    for entity_key, flux_counts in entity_flux_map.items():
        nb_flux = len(flux_counts)
        if nb_flux < min_flux:
            continue

        total = sum(flux_counts.values())
        etype, value = entity_key.split(":", 1) if ":" in entity_key else ("?", entity_key)

        results.append({
            "entity_key":  entity_key,
            "entity_type": etype,
            "entity_value": value,
            "nb_flux":     nb_flux,
            "total_mentions": total,
            "flux_details": [
                {"flux": f, "mentions": c}
                for f, c in sorted(flux_counts.items(), key=lambda x: -x[1])
            ],
        })

    results.sort(key=lambda x: (-x["nb_flux"], -x["total_mentions"]))
    return results[:top_n]


# ── Génération du rapport Markdown ───────────────────────────────────────────

def _assign_flux_letters(flux_names_sorted: list[str]) -> dict[str, str]:
    """Assigne une lettre A-Z (puis AA, AB...) à chaque flux trié."""
    import string
    letters = list(string.ascii_uppercase)
    mapping: dict[str, str] = {}
    for i, name in enumerate(flux_names_sorted):
        if i < 26:
            mapping[name] = letters[i]
        else:
            mapping[name] = letters[(i // 26) - 1] + letters[i % 26]
    return mapping


def _build_mermaid_top_flux(
    flux_article_counts: dict[str, int],
    flux_letter_map: dict[str, str],
    top_n: int = 10,
) -> str:
    """Génère un diagramme Mermaid xychart-beta (barres) pour les top_n flux.
    Utilise les lettres assignées comme labels pour éviter les caractères spéciaux.
    """
    if not flux_article_counts:
        return ""
    sorted_flux = sorted(flux_article_counts.items(), key=lambda x: -x[1])[:top_n]
    labels = [f'"{flux_letter_map.get(name, _sanitize_for_mermaid(name))}"' for name, _ in sorted_flux]
    values = [str(count) for _, count in sorted_flux]
    max_val = max(c for _, c in sorted_flux)
    y_max = ((max_val // 10) + 1) * 10
    lines = [
        "```mermaid",
        "xychart-beta",
        '    title "Top flux - nombre articles"',
        f"    x-axis [{', '.join(labels)}]",
        f"    y-axis " + '"Articles" ' + f"0 --> {y_max}",
        f"    bar [{', '.join(values)}]",
        "```",
    ]
    return "\n".join(lines)


def build_cross_flux_markdown(
    date_str: str,
    days: int,
    flux_names: list[str],
    cross_entities: list[dict],
    flux_article_counts: dict[str, int] | None = None,
) -> str:
    """Génère le rapport Markdown de l'analyse croisée."""
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    counts = flux_article_counts or {}

    lines = [
        "---",
        f"title: \"Analyse croisée des flux — {date_str}\"",
        f"date: \"{date_str}\"",
        f"window_days: {days}",
        "tags: [cross-flux, entités, veille]",
        "---",
        "",
        f"# 🔀 Analyse croisée des flux — {date_str}",
        "",
        f"> Généré le {now_str} | Fenêtre : {days} jours",
        f"> Flux analysés : {len(flux_names)}",
        "",
        "## Flux inclus dans l'analyse",
        "",
    ]

    # N'inclure que les flux avec au moins 1 article
    sorted_flux_names = sorted(f for f in flux_names if counts.get(f, 0) > 0)
    flux_letter_map = _assign_flux_letters(sorted_flux_names)

    # Graphique Mermaid top 10 flux (avec lettres comme labels)
    if counts:
        mermaid_chart = _build_mermaid_top_flux(counts, flux_letter_map, top_n=10)
        if mermaid_chart:
            lines.append(mermaid_chart)
            lines.append("")

    # Liste compacte : lettre — flux séparés par des virgules avec nombre d'articles
    flux_items = []
    for f in sorted_flux_names:
        nb = counts.get(f, 0)
        letter = flux_letter_map[f]
        flux_items.append(f"**{letter}** `{f}` ({nb} article(s))")
    lines.append(", ".join(flux_items))
    lines.append("")

    if not cross_entities:
        lines += [
            "## Résultat",
            "",
            "*Aucune entité commune détectée sur la période.*",
        ]
        return "\n".join(lines)

    lines += [
        "## Entités présentes dans plusieurs flux",
        "",
        f"*{len(cross_entities)} entité(s) détectée(s) dans ≥ 2 flux*",
        "",
        "| Entité | Type | Flux | Mentions tot. | Flux principaux |",
        "|--------|------|------|---------------|-----------------|",
    ]
    for e in cross_entities[:20]:
        flux_str = " / ".join(
            f"{fd['flux']} ({fd['mentions']})"
            for fd in e["flux_details"][:3]
        )
        lines.append(
            f"| **{e['entity_value']}** "
            f"| {e['entity_type']} "
            f"| {e['nb_flux']} "
            f"| {e['total_mentions']} "
            f"| {flux_str} |"
        )
    lines.append("")

    # Détail des entités les plus cross-flux
    if cross_entities:
        lines += ["## Détail des entités multi-flux", ""]
        for e in cross_entities[:5]:
            lines.append(f"### {e['entity_value']} ({e['entity_type']})")
            lines.append(f"Présente dans **{e['nb_flux']} flux** | "
                          f"{e['total_mentions']} mentions au total\n")
            for fd in e["flux_details"]:
                lines.append(f"- **{fd['flux']}** : {fd['mentions']} mention(s)")
            lines.append("")

    lines += ["---", f"*Rapport généré par WUDD.ai — {now_str}*"]
    return "\n".join(lines)


# ── Point d'entrée ────────────────────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(
        description="Analyse croisée des flux WUDD.ai"
    )
    parser.add_argument(
        "--days", type=int, default=30,
        help="Fenêtre temporelle en jours (défaut: 30)"
    )
    parser.add_argument(
        "--min-flux", type=int, default=2,
        help="Nombre minimal de flux pour qu'une entité soit signalée (défaut: 2)"
    )
    parser.add_argument(
        "--top", type=int, default=30,
        help="Nombre d'entités à conserver dans le rapport (défaut: 30)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Affiche le résultat sans sauvegarder"
    )
    return parser.parse_args()


def main():
    args = parse_args()
    project_root = _PROJECT_ROOT
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    print_console(f"=== Analyse croisée des flux WUDD.ai ({args.days}j) ===")

    flux_entities = collect_entities_by_flux(project_root, days=args.days)
    flux_names = list(flux_entities.keys())
    print_console(f"  → {len(flux_names)} flux analysé(s)")

    if len(flux_names) < 2:
        print_console(
            "Moins de 2 flux disponibles. L'analyse croisée nécessite au moins 2 flux.",
            "warning"
        )

    cross_entities = compute_cross_flux(
        flux_entities,
        min_flux=args.min_flux,
        top_n=args.top,
    )
    print_console(
        f"  → {len(cross_entities)} entité(s) présente(s) dans ≥ {args.min_flux} flux"
    )

    output_data = {
        "generated_at":   datetime.now(timezone.utc).isoformat(),
        "window_days":    args.days,
        "min_flux":       args.min_flux,
        "flux_count":     len(flux_names),
        "flux_list":      sorted(flux_names),
        "cross_entities": cross_entities,
    }

    flux_article_counts = collect_article_counts_by_flux(project_root, days=args.days)
    print_console(f"  → {sum(flux_article_counts.values())} article(s) comptabilisé(s) au total")

    report_md = build_cross_flux_markdown(
        date_str=date_str,
        days=args.days,
        flux_names=flux_names,
        cross_entities=cross_entities,
        flux_article_counts=flux_article_counts,
    )

    if args.dry_run:
        print_console("[DRY-RUN] Résultats non sauvegardés.")
        print(json.dumps(output_data, ensure_ascii=False, indent=2))
        return

    # Sauvegarde JSON
    _OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    _OUTPUT_JSON.write_text(
        json.dumps(output_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print_console(f"Rapport JSON sauvegardé : {_OUTPUT_JSON}")

    # Sauvegarde Markdown
    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    md_path = _OUTPUT_DIR / f"cross_flux_{date_str}.md"
    md_path.write_text(report_md, encoding="utf-8")
    print_console(f"Rapport Markdown sauvegardé : {md_path}")


if __name__ == "__main__":
    main()
