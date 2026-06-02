#!/usr/bin/env python3
"""Suivi de la santé des sources de veille.

Analyse les fichiers JSON dans data/ et data/articles-from-rss/ pour détecter :
- Sources silencieuses (aucun article depuis N jours)
- Sources avec taux d'erreur élevé (résumés contenant des messages d'erreur)
- Sources avec peu d'articles relatifs à leur historique

Résultats sauvegardés dans data/source_health.json.

Usage:
    python3 scripts/check_source_health.py
    python3 scripts/check_source_health.py --days 7 --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))

from utils.config import get_config
from utils.logging import default_logger as LOG
from utils.date_utils import parse_article_date

# Messages d'erreur reconnus dans les résumés (issus de l'API)
_ERROR_MARKERS = [
    "Erreur API",
    "erreur api",
    "timeout",
    "Timeout",
    "ConnectionError",
    "HTTPError",
    "Échec du résumé",
    "Impossible de générer",
    "Résumé non disponible",
    "erreur lors",
    "API call failed",
]

OUTPUT_FILE = PROJECT_ROOT / "data" / "source_health.json"


def _parse_date(d: str) -> datetime | None:
    """Datetime UTC (tz-aware) ou None — corpus mixte ISO 8601 / DD/MM/YYYY / RFC 2822."""
    dt = parse_article_date(d or "")
    return dt.replace(tzinfo=timezone.utc) if dt is not None else None


def _is_error_summary(resume: str) -> bool:
    """Retourne True si le résumé contient un message d'erreur API."""
    if not isinstance(resume, str):
        return False
    return any(marker.lower() in resume.lower() for marker in _ERROR_MARKERS)


def collect_source_stats(project_root: Path, days: int = 14) -> dict[str, dict]:
    """Collecte les statistiques par source sur les `days` derniers jours.

    Returns:
        Dict {source_name: {total, recent, error_count, last_date, error_rate}}
    """
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)
    stats: dict[str, dict] = {}

    def _process_article(art: dict) -> None:
        src = str(art.get("Sources", "")).strip()
        if not src:
            return
        resume = art.get("Résumé", "") or ""
        date_str = art.get("Date de publication", "") or ""
        pub_dt = _parse_date(date_str)

        if src not in stats:
            stats[src] = {"total": 0, "recent": 0, "error_count": 0, "last_date": None}

        stats[src]["total"] += 1
        if _is_error_summary(resume):
            stats[src]["error_count"] += 1
        if pub_dt:
            last = stats[src]["last_date"]
            if last is None or pub_dt > last:
                stats[src]["last_date"] = pub_dt
            if pub_dt >= cutoff:
                stats[src]["recent"] += 1

    # Parcourir tous les JSON articles
    for source_dir in [project_root / "data" / "articles-from-rss",
                        project_root / "data" / "articles"]:
        if not source_dir.exists():
            continue
        for json_file in source_dir.rglob("*.json"):
            if "cache" in str(json_file) or "index" in json_file.name or "health" in json_file.name:
                continue
            try:
                data = json.loads(json_file.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    for art in data:
                        _process_article(art)
                elif isinstance(data, dict) and "items" in data:
                    for art in data["items"]:
                        _process_article(art)
            except Exception:
                continue

    return stats


def compute_health_report(stats: dict[str, dict], days: int = 14, error_threshold: float = 0.3) -> list[dict]:
    """Calcule le rapport de santé par source.

    Args:
        stats           : résultat de collect_source_stats
        days            : fenêtre d'analyse
        error_threshold : seuil d'alerte taux d'erreur (défaut 30%)

    Returns:
        Liste de dicts triée par niveau d'alerte puis par source.
    """
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)
    report = []

    for src, s in stats.items():
        total = s["total"]
        recent = s["recent"]
        errors = s["error_count"]
        last_dt = s["last_date"]

        error_rate = errors / total if total > 0 else 0.0
        days_since_last = None
        if last_dt:
            days_since_last = (now - last_dt).days

        # Détermination du statut
        issues = []
        if days_since_last is not None and days_since_last > days:
            issues.append(f"Silencieuse depuis {days_since_last}j")
        if error_rate >= error_threshold and errors >= 3:
            issues.append(f"Taux d'erreur élevé ({error_rate:.0%})")
        if recent == 0 and total > 0:
            issues.append("Aucun article récent")

        if not issues:
            statut = "ok"
            niveau = "info"
        elif error_rate >= 0.5 or (days_since_last is not None and days_since_last > days * 2):
            statut = "critique"
            niveau = "critique"
        else:
            statut = "alerte"
            niveau = "modéré"

        report.append({
            "source": src,
            "statut": statut,
            "niveau": niveau,
            "total_articles": total,
            "articles_recents": recent,
            "erreurs": errors,
            "taux_erreur": round(error_rate, 3),
            "derniere_publication": last_dt.strftime("%Y-%m-%dT%H:%M:%SZ") if last_dt else None,
            "jours_depuis_publication": days_since_last,
            "problemes": issues,
        })

    # Trier : critiques en premier, puis modérés, puis ok
    order = {"critique": 0, "modéré": 1, "info": 2}
    report.sort(key=lambda r: (order.get(r["niveau"], 9), r["source"]))
    return report


def run_check(project_root: Path, days: int = 14, dry_run: bool = False) -> list[dict]:
    """Lance le diagnostic santé sources et sauvegarde les résultats."""
    LOG.info(f"[source_health] Analyse santé sources sur {days} jours…")
    stats = collect_source_stats(project_root, days=days)
    LOG.info(f"[source_health] {len(stats)} sources analysées")

    report = compute_health_report(stats, days=days)

    critiques = [r for r in report if r["niveau"] == "critique"]
    alertes = [r for r in report if r["niveau"] == "modéré"]
    ok = [r for r in report if r["statut"] == "ok"]

    LOG.info(f"[source_health] {len(critiques)} critique(s) | {len(alertes)} alerte(s) | {len(ok)} OK")

    if not dry_run:
        output = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "days_window": days,
            "summary": {
                "total_sources": len(report),
                "critiques": len(critiques),
                "alertes": len(alertes),
                "ok": len(ok),
            },
            "sources": report,
        }
        OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_FILE.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
        LOG.info(f"[source_health] Rapport sauvegardé : {OUTPUT_FILE}")

    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Suivi santé sources WUDD.ai")
    parser.add_argument("--days", type=int, default=14, help="Fenêtre d'analyse en jours (défaut: 14)")
    parser.add_argument("--dry-run", action="store_true", help="Simulation sans écriture")
    args = parser.parse_args()

    config = get_config()
    report = run_check(config.project_root, days=args.days, dry_run=args.dry_run)

    critiques = [r for r in report if r["niveau"] == "critique"]
    if critiques:
        print(f"\n⚠ {len(critiques)} source(s) en état critique :")
        for r in critiques[:10]:
            print(f"  • {r['source']} — {', '.join(r['problemes'])}")
    else:
        print("✓ Aucune source en état critique")


if __name__ == "__main__":
    main()
