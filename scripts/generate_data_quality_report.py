#!/usr/bin/env python3
"""Génère un rapport de qualité des données WUDD.ai en Markdown.

Scanne data/articles/ et data/articles-from-rss/ et produit un rapport listant
pour chaque fichier JSON :
  - Nombre total d'articles
  - Articles sans résumé, sans entités, sans sentiment, sans image, sans date
  - Taux d'erreurs API/parse (echec_api, echec_parse)
  - Score de qualité global (0–100)

Le rapport est sauvegardé dans rapports/markdown/_WUDD.AI_/data-quality_<date>.md

Usage :
    python3 scripts/generate_data_quality_report.py
    python3 scripts/generate_data_quality_report.py --dry-run   # Affiche sans sauvegarder
    python3 scripts/generate_data_quality_report.py --dir rss   # Seulement articles-from-rss
    python3 scripts/generate_data_quality_report.py --dir articles  # Seulement data/articles
    python3 scripts/generate_data_quality_report.py --output /chemin/rapport.md
"""

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))

from utils.logging import print_console
from utils.report_cleanup import cleanup_old_dated_reports


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Génère un rapport Markdown de qualité des données WUDD.ai."
    )
    parser.add_argument(
        "--dir",
        choices=["articles", "rss", "all"],
        default="all",
        help="Sous-répertoire à analyser (défaut : all).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Affiche le rapport sur stdout sans sauvegarder.",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Chemin de sortie du rapport Markdown (défaut : rapports/markdown/_WUDD.AI_/).",
    )
    return parser.parse_args()


def scan_directory(scan_dir: Path, project_root: Path) -> list[dict]:
    """Scanne un répertoire et retourne les stats par fichier JSON."""
    results = []
    if not scan_dir.exists():
        return results

    for json_file in sorted(scan_dir.rglob("*.json")):
        if "cache" in json_file.relative_to(scan_dir).parts:
            continue
        try:
            articles = json.loads(json_file.read_text(encoding="utf-8", errors="replace"))
        except (json.JSONDecodeError, OSError) as e:
            print_console(f"  Impossible de lire {json_file.name} : {e}", level="warning")
            continue

        if not isinstance(articles, list) or not articles:
            continue

        stats = {
            "total": len(articles),
            "sans_resume": 0,
            "sans_entites": 0,
            "sans_sentiment": 0,
            "echec_api": 0,
            "echec_parse": 0,
            "sans_image": 0,
            "sans_date": 0,
        }
        for a in articles:
            if not isinstance(a, dict):
                continue
            resume = a.get("Résumé", "")
            if not resume or not str(resume).strip():
                stats["sans_resume"] += 1
            if not a.get("entities"):
                stats["sans_entites"] += 1
            if not a.get("sentiment"):
                stats["sans_sentiment"] += 1
            statut = a.get("enrichissement_statut", "")
            if statut == "echec_api":
                stats["echec_api"] += 1
            elif statut == "echec_parse":
                stats["echec_parse"] += 1
            images = a.get("Images", [])
            if not images:
                stats["sans_image"] += 1
            if not a.get("Date de publication", ""):
                stats["sans_date"] += 1

        pct_ok = round(
            100 * (1 - (stats["sans_resume"] + stats["sans_entites"]) / (2 * stats["total"])),
            1,
        ) if stats["total"] > 0 else 100.0

        results.append({
            "file": str(json_file.relative_to(project_root)).replace("\\", "/"),
            "quality_score": pct_ok,
            **stats,
        })

    return results


def _score_emoji(score: float) -> str:
    if score >= 90:
        return "✅"
    if score >= 70:
        return "🟡"
    return "🔴"


def generate_markdown(results: list[dict], totals: dict, generated_at: str) -> str:
    """Génère le contenu Markdown du rapport."""
    lines = [
        "# Rapport de qualité des données WUDD.ai",
        "",
        f"Généré le : **{generated_at}**",
        "",
        "## Résumé global",
        "",
        f"| Métrique | Valeur |",
        f"|---|---|",
        f"| Fichiers analysés | {len(results)} |",
        f"| Articles totaux | {totals.get('total', 0)} |",
        f"| Sans résumé | {totals.get('sans_resume', 0)} |",
        f"| Sans entités | {totals.get('sans_entites', 0)} |",
        f"| Sans sentiment | {totals.get('sans_sentiment', 0)} |",
        f"| Sans image | {totals.get('sans_image', 0)} |",
        f"| Sans date | {totals.get('sans_date', 0)} |",
        f"| Échec API (echec_api) | {totals.get('echec_api', 0)} |",
        f"| Échec parse (echec_parse) | {totals.get('echec_parse', 0)} |",
        "",
        "## Détail par fichier",
        "",
        "Trié par score de qualité croissant (les fichiers les plus dégradés en premier).",
        "",
        "| Score | Fichier | Total | Sans résumé | Sans entités | Sans sentiment | Échec API | Échec parse | Sans image |",
        "|---|---|---|---|---|---|---|---|---|",
    ]

    for r in sorted(results, key=lambda x: x["quality_score"]):
        score = r["quality_score"]
        emoji = _score_emoji(score)
        fname = r["file"].split("/")[-1]
        lines.append(
            f"| {emoji} {score}% | `{fname}` | {r['total']} | {r['sans_resume']} | "
            f"{r['sans_entites']} | {r['sans_sentiment']} | {r['echec_api']} | "
            f"{r['echec_parse']} | {r['sans_image']} |"
        )

    # Fichiers nécessitant une action
    critical = [r for r in results if r["quality_score"] < 70]
    if critical:
        lines += [
            "",
            "## Fichiers nécessitant une action",
            "",
            "Score < 70% — envisager un ré-enrichissement (`enrich_entities.py --force`) :",
            "",
        ]
        for r in critical:
            lines.append(f"- `{r['file']}` — score {r['quality_score']}%")

    lines += ["", "---", f"*Rapport généré automatiquement par WUDD.ai v2.5*", ""]
    return "\n".join(lines)


def main() -> None:
    args = parse_args()

    scan_dirs = []
    if args.dir in ("articles", "all"):
        scan_dirs.append(PROJECT_ROOT / "data" / "articles")
    if args.dir in ("rss", "all"):
        scan_dirs.append(PROJECT_ROOT / "data" / "articles-from-rss")

    print_console("Analyse de la qualité des données…", level="info")
    all_results: list[dict] = []
    for scan_dir in scan_dirs:
        print_console(f"  Scan : {scan_dir.relative_to(PROJECT_ROOT)}", level="info")
        all_results.extend(scan_directory(scan_dir, PROJECT_ROOT))

    totals: dict = defaultdict(int)
    for r in all_results:
        for k in ("total", "sans_resume", "sans_entites", "sans_sentiment",
                  "echec_api", "echec_parse", "sans_image", "sans_date"):
            totals[k] += r.get(k, 0)

    generated_at = datetime.now().strftime("%d/%m/%Y à %H:%M")
    report = generate_markdown(all_results, totals, generated_at)

    print_console(f"\n{len(all_results)} fichier(s) analysé(s), {totals['total']} article(s) total.", level="info")

    if args.dry_run:
        print(report)
        return

    # Déterminer le chemin de sortie
    if args.output:
        out_path = Path(args.output)
    else:
        out_dir = PROJECT_ROOT / "rapports" / "markdown" / "_WUDD.AI_"
        out_dir.mkdir(parents=True, exist_ok=True)
        date_str = datetime.now().strftime("%Y-%m-%d")
        out_path = out_dir / f"data-quality_{date_str}.md"

    try:
        out_path.write_text(report, encoding="utf-8")
        print_console(f"Rapport sauvegardé : {out_path}", level="info")
        if not args.output:
            cleanup_old_dated_reports(out_path)
    except OSError as e:
        print_console(f"Erreur d'écriture : {e}", level="error")
        sys.exit(1)


if __name__ == "__main__":
    main()
