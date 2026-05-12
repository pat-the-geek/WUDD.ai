#!/usr/bin/env python3
"""Rapport hebdomadaire des entités surveillées.

Génère un rapport Markdown dans rapports/markdown/_WUDD.AI_/
listant l'activité des entités de data/watched_entities.json
sur les 7 derniers jours.

Usage:
    python3 scripts/generate_watched_report.py
    python3 scripts/generate_watched_report.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

SCRIPT_DIR = Path(__file__).parent.resolve()
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))

from utils.config import get_config
from utils.logging import default_logger as LOG
from utils.entity_index import get_entity_index
from utils.date_utils import parse_article_date
from utils.scheduler_toggle import should_run_task


def _load_watched(project_root: Path) -> list[dict]:
    f = project_root / "data" / "watched_entities.json"
    if not f.exists():
        return []
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _load_timeline(project_root: Path) -> dict:
    f = project_root / "data" / "entity_timeline.json"
    if not f.exists():
        return {}
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _load_alerts(project_root: Path) -> list[dict]:
    f = project_root / "data" / "alertes.json"
    if not f.exists():
        return []
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _count_mentions(entity_key: str, index: dict, days: int, now: datetime) -> int:
    """Compte les mentions de l'entité dans la fenêtre de `days` jours."""
    cutoff = now - timedelta(days=days)
    refs = index.get(entity_key, [])
    count = 0
    for ref in refs:
        d = ref.get("date", "")
        try:
            dt = datetime.fromisoformat(d.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if dt >= cutoff.replace(tzinfo=timezone.utc):
                count += 1
        except Exception:
            pass
    return count


def _get_recent_articles(
    entity_key: str, index: dict, project_root: Path, days: int, now: datetime, max_items: int = 5
) -> list[dict]:
    """Retourne les articles récents mentionnant cette entité."""
    cutoff = now - timedelta(days=days)
    refs = index.get(entity_key, [])
    recent = []
    for ref in refs:
        d = ref.get("date", "")
        try:
            dt = datetime.fromisoformat(d.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if dt >= cutoff.replace(tzinfo=timezone.utc):
                recent.append(ref)
        except Exception:
            pass
    recent.sort(key=lambda r: r.get("date", ""), reverse=True)

    articles = []
    seen_files: dict[str, list] = {}
    for ref in recent[:max_items]:
        f = ref.get("file", "")
        if f not in seen_files:
            p = project_root / f
            try:
                seen_files[f] = json.loads(p.read_text(encoding="utf-8")) if p.exists() else []
            except Exception:
                seen_files[f] = []
        arts = seen_files[f]
        idx = ref.get("idx", 0)
        if 0 <= idx < len(arts):
            articles.append(arts[idx])
    return articles


def generate_watched_report(project_root: Path, days: int = 7, dry_run: bool = False) -> Optional[Path]:
    """Génère le rapport Markdown hebdomadaire des entités surveillées."""
    config = get_config()
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y-%m-%d")

    watched = _load_watched(project_root)
    if not watched:
        LOG.info("[watched_report] Aucune entité surveillée — rapport non généré")
        return None

    timeline = _load_timeline(project_root)
    alerts = _load_alerts(project_root)
    alerts_by_key: dict[str, dict] = {
        f"{a.get('type', '')}:{a.get('entity', '').lower()}": a
        for a in alerts if a.get("entity")
    }

    # Charger l'index entités
    try:
        raw = json.loads((project_root / "data" / "entity_index.json").read_text(encoding="utf-8"))
        entity_index = raw.get("index", raw)
        entity_caps = raw.get("caps", {})
    except Exception:
        entity_index = {}
        entity_caps = {}

    lines = [
        "---",
        f'title: "Rapport entités surveillées — {date_str}"',
        f"date: {date_str}",
        'type: rapport-veille',
        f'tags: ["wudd-ai", "veille", "entites-surveillees"]',
        "---",
        "",
        f"# Rapport de veille — Entités surveillées",
        "",
        f"> **Période** : {(now - timedelta(days=days)).strftime('%d/%m/%Y')} → {now.strftime('%d/%m/%Y')} ({days} jours)  ",
        f"> **Entités suivies** : {len(watched)}  ",
        f"> **Généré le** : {now.strftime('%d/%m/%Y à %H:%M')}",
        "",
        "---",
        "",
        "## Résumé",
        "",
    ]

    # Stats globales
    total_mentions = 0
    active = []
    for ent in watched:
        key = f"{ent.get('type', 'PERSON')}:{ent.get('value', '').lower()}"
        count = _count_mentions(key, entity_index, days, now)
        total_mentions += count
        if count > 0:
            active.append((ent, key, count))

    active.sort(key=lambda x: x[2], reverse=True)

    lines += [
        f"- **{total_mentions}** mentions cumulées sur {days} jours",
        f"- **{len(active)}/{len(watched)}** entités actives",
        f"- **{len([a for a in alerts if a.get('watched')])}** alertes liées à des entités surveillées",
        "",
        "---",
        "",
        "## Détail par entité",
        "",
    ]

    for ent, key, count in active:
        name = ent.get("value", "")
        etype = ent.get("type", "")
        alert = alerts_by_key.get(key)
        niveau = alert.get("niveau", "") if alert else ""
        ratio = alert.get("ratio", 0.0) if alert else 0.0

        alert_str = ""
        if niveau == "critique":
            alert_str = " 🔴 CRITIQUE"
        elif niveau == "élevé":
            alert_str = " 🟠 ÉLEVÉ"
        elif niveau == "modéré":
            alert_str = " 🟡 MODÉRÉ"

        # Timeline 7 derniers jours depuis entity_timeline
        tl_data = timeline.get(key, timeline.get(ent.get("value", "").lower(), {}))
        tl_mentions = tl_data.get("mentions", []) if tl_data else []
        recent_tl = sorted(tl_mentions, key=lambda m: m.get("date", ""), reverse=True)[:7]
        sparkline = " ".join(f"`{m.get('date','')[:10]}:{m.get('count',0)}`" for m in reversed(recent_tl))

        lines += [
            f"### {name} ({etype}){alert_str}",
            "",
            f"> **{count} mentions** en {days} jours",
        ]
        if ratio:
            lines.append(f"> Ratio d'activité : **×{ratio:.1f}** vs moyenne")
        if sparkline:
            lines += [f"> Tendance : {sparkline}", ""]
        if ent.get("notes"):
            lines += [f"> *Note* : {ent['notes']}", ""]

        # Articles récents
        articles = _get_recent_articles(key, entity_index, project_root, days, now)
        if articles:
            lines += ["**Articles récents :**", ""]
            for art in articles:
                src = art.get("Sources", "")
                url = art.get("URL", "#")
                date_pub = art.get("Date de publication", "")[:10]
                resume = art.get("Résumé", "")[:120].replace("\n", " ")
                lines.append(f"- [{src} — {date_pub}]({url}) : {resume}…")
            lines.append("")

        lines.append("---")
        lines.append("")

    # Entités inactives
    inactive = [w for w in watched if w.get("value") not in {a[0].get("value") for a in active}]
    if inactive:
        lines += [
            "## Entités sans activité cette semaine",
            "",
        ]
        for ent in inactive:
            lines.append(f"- **{ent.get('value')}** ({ent.get('type')}) — aucune mention")
        lines += ["", "---", ""]

    lines += [
        "",
        "*Rapport généré automatiquement par WUDD.ai — `generate_watched_report.py`*",
    ]

    # Écriture
    out_dir = project_root / "rapports" / "markdown" / "_WUDD.AI_"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"veille-entites_{date_str}.md"

    if not dry_run:
        out_file.write_text("\n".join(lines), encoding="utf-8")
        LOG.info(f"[watched_report] Rapport créé : {out_file}")
    else:
        LOG.info(f"[watched_report] dry-run — rapport serait créé : {out_file}")

    return out_file


def main() -> None:
    if not should_run_task("reports.watched_entities"):
        return

    parser = argparse.ArgumentParser(description="Rapport hebdomadaire entités surveillées")
    parser.add_argument("--days", type=int, default=7, help="Fenêtre en jours (défaut: 7)")
    parser.add_argument("--dry-run", action="store_true", help="Simulation sans écriture")
    args = parser.parse_args()

    config = get_config()
    out = generate_watched_report(config.project_root, days=args.days, dry_run=args.dry_run)
    if out:
        print(f"Rapport généré : {out}")
    else:
        print("Aucun rapport généré (pas d'entités surveillées ?)")


if __name__ == "__main__":
    main()
