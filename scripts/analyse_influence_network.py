"""scripts/analyse_influence_network.py — Analyse du réseau d'influence des sources.

Construit un graphe pondéré sources ↔ sources basé sur les co-mentions d'entités,
puis applique l'algorithme de Louvain pour détecter les communautés éditoriales.

Usage :
  python3 scripts/analyse_influence_network.py
  python3 scripts/analyse_influence_network.py --days 30
  python3 scripts/analyse_influence_network.py --dry-run
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
import sys
sys.path.insert(0, str(PROJECT_ROOT))

from utils.logging import print_console

OUTPUT_FILE = PROJECT_ROOT / "data" / "influence_network.json"


def main():
    parser = argparse.ArgumentParser(description="Analyse réseau influence sources")
    parser.add_argument("--days", type=int, default=30, help="Fenêtre temporelle en jours (défaut: 30)")
    parser.add_argument("--dry-run", action="store_true", help="Ne pas écrire le fichier de sortie")
    args = parser.parse_args()

    print_console(f"Analyse du réseau d'influence ({args.days}j)…")

    try:
        from utils.network_analysis import build_influence_report
        report = build_influence_report(PROJECT_ROOT, days=args.days)
    except Exception as e:
        print_console(f"Erreur : {e}")
        return

    print_console(f"{report['nodes_count']} sources, {report['edges_count']} liens, "
                  f"{len(report.get('communities', []))} communautés détectées")

    if report.get("hubs"):
        print_console("Top 5 hubs :")
        for h in report["hubs"][:5]:
            print_console(f"  - {h['id']} (centralité={h['centrality']:.3f}, poids={h['degree']})")

    if not args.dry_run:
        OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_FILE.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print_console(f"Résultats sauvegardés → {OUTPUT_FILE}")
    else:
        print_console("[dry-run] Résultats non sauvegardés")


if __name__ == "__main__":
    main()
