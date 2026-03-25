#!/usr/bin/env python3
"""
scripts/generate_ai_consumption_report.py

Génère un rapport de consommation quotidienne des services IA.
Agrège les articles traités par jour (quota_state.json + quota_history/),
parse les tokens EurIA/Claude depuis les logs cron, et produit un rapport
Markdown avec diagramme Mermaid xychart-beta.

Sortie : rapports/markdown/_MORNING_DIGEST_/ai_consumption_report.md
         (même nom à chaque exécution — fichier remplacé)

Usage :
  python3 scripts/generate_ai_consumption_report.py [--dry-run]
"""

import argparse
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

SCRIPT_DIR   = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Fichiers de log à analyser pour la consommation de tokens
LOG_FILES = [
    "cron_morning_digest.log",
    "cron_enrich_entities.log",
    "cron_sentiment.log",
    "cron_briefing.log",
    "cron_48h_report.log",
    "cron_trends.log",
    "cron_reading_notes.log",
    "cron_get_keyword.log",
    "cron_web_watcher.log",
    "cron_repair.log",
    "cron_repair_enrichments.log",
    "cron_flux_watcher.log",
]

# Pattern pour les lignes de tokens EurIA : "[EurIA] Usage — prompt: 400 tokens, completion: 105 tokens, total: 505 tokens"
# Pattern pour Claude : "[Claude/model] Usage — input: X tokens, output: Y tokens"
TOKEN_PATTERN_EURIA = re.compile(
    r"prompt[:\s]+(\d+)\s*tokens?,\s*completion[:\s]+(\d+)\s*tokens?,\s*total[:\s]+(\d+)\s*tokens?",
    re.IGNORECASE,
)
TOKEN_PATTERN_CLAUDE = re.compile(
    r"input[:\s]+(\d+)\s*tokens?,\s*output[:\s]+(\d+)\s*tokens?",
    re.IGNORECASE,
)
USAGE_LINE_EURIA  = re.compile(r"\[EurIA\]\s*Usage", re.IGNORECASE)
USAGE_LINE_CLAUDE = re.compile(r"\[Claude[^\]]*\]\s*Usage", re.IGNORECASE)
USAGE_LINE_PATTERN = re.compile(r"\[(?:EurIA|Claude[^\]]*)\]\s*Usage", re.IGNORECASE)

MOIS_FR = [
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
]


def _date_fr(dt: datetime) -> str:
    return f"{dt.day} {MOIS_FR[dt.month - 1]} {dt.year}"


def load_quota_history(project_root: Path, days: int = 7) -> list:
    """Charge les snapshots quota des <days> derniers jours.

    - Pour aujourd'hui : lit data/quota_state.json (valeur en cours de journée)
    - Pour les jours précédents : lit data/quota_history/YYYY-MM-DD.json
    """
    history_dir = project_root / "data" / "quota_history"
    today = datetime.now().date()
    results = []

    for i in range(days - 1, -1, -1):
        d = today - timedelta(days=i)
        iso = d.isoformat()
        entry = {"date": iso, "global_count": 0, "keywords": {}}

        if i == 0:
            # Aujourd'hui — quota en temps réel
            state_file = project_root / "data" / "quota_state.json"
            if state_file.exists():
                try:
                    state = json.loads(state_file.read_text(encoding="utf-8"))
                    if state.get("date") == iso:
                        entry["global_count"] = state.get("global_count", 0)
                        entry["keywords"] = state.get("keywords", {})
                except Exception:
                    pass
        else:
            hist_file = history_dir / f"{iso}.json"
            if hist_file.exists():
                try:
                    data = json.loads(hist_file.read_text(encoding="utf-8"))
                    entry["global_count"] = data.get("global_count", 0)
                    entry["keywords"] = data.get("keywords", {})
                except Exception:
                    pass

        results.append(entry)

    return results


def _empty_provider() -> dict:
    return {"prompt": 0, "completion": 0, "total": 0, "calls": 0}


def parse_tokens_from_logs(project_root: Path) -> dict:
    """Parse les fichiers de log cron pour extraire la consommation de tokens du jour.

    Returns:
        dict {
            nom_service: {
                "euria":  {"prompt": int, "completion": int, "total": int, "calls": int},
                "claude": {"prompt": int, "completion": int, "total": int, "calls": int},
                "total":  int,   # somme euria+claude
                "calls":  int,
            }
        }
    """
    today_str = datetime.now().strftime("%Y-%m-%d")
    reports_dir = project_root / "rapports"
    stats = {}

    for log_name in LOG_FILES:
        log_path = reports_dir / log_name
        if not log_path.exists():
            continue

        service_key = log_name.replace("cron_", "").replace(".log", "")
        euria  = _empty_provider()
        claude = _empty_provider()

        try:
            text = log_path.read_text(encoding="utf-8", errors="ignore")
            for line in text.splitlines():
                if not line.startswith(today_str):
                    continue
                if not USAGE_LINE_PATTERN.search(line):
                    continue

                if USAGE_LINE_EURIA.search(line):
                    # Pattern EurIA : prompt + completion + total explicite
                    m = TOKEN_PATTERN_EURIA.search(line)
                    if m:
                        euria["prompt"]     += int(m.group(1))
                        euria["completion"] += int(m.group(2))
                        euria["total"]      += int(m.group(3))
                        euria["calls"]      += 1
                elif USAGE_LINE_CLAUDE.search(line):
                    # Pattern Claude : input + output
                    m2 = TOKEN_PATTERN_CLAUDE.search(line)
                    if m2:
                        p = int(m2.group(1))
                        c = int(m2.group(2))
                        claude["prompt"]     += p
                        claude["completion"] += c
                        claude["total"]      += p + c
                        claude["calls"]      += 1

        except Exception:
            pass

        total_calls = euria["calls"] + claude["calls"]
        if total_calls > 0:
            stats[service_key] = {
                "euria":  euria,
                "claude": claude,
                "total":  euria["total"] + claude["total"],
                "calls":  total_calls,
            }

    return stats


def load_quota_config(project_root: Path) -> dict:
    defaults = {
        "global_daily_limit":      200,
        "per_keyword_daily_limit":  30,
        "per_source_daily_limit":   10,
        "per_entity_daily_limit":   15,
    }
    cfg_file = project_root / "config" / "quota.json"
    if cfg_file.exists():
        try:
            return {**defaults, **json.loads(cfg_file.read_text(encoding="utf-8"))}
        except Exception:
            pass
    return defaults


def build_mermaid_xychart(history: list, global_limit: int, title: str = "") -> str:
    """Génère un diagramme xychart-beta : articles traités + ligne de quota.

    Pour 30 jours, n'affiche une étiquette que tous les 5 jours afin d'éviter la
    surcharge de l'axe X (les valeurs de la barre restent toutes présentes).
    """
    n = len(history)
    # Pour ≤ 10 jours : toutes les dates ; au-delà : une étiquette tous les 5 jours
    step = 1 if n <= 10 else 5

    labels = []
    values = []
    for i, entry in enumerate(history):
        dt = datetime.fromisoformat(entry["date"])
        # Afficher l'étiquette uniquement aux positions multiples de step (et toujours la dernière)
        if i % step == 0 or i == n - 1:
            labels.append(dt.strftime("%d/%m"))
        else:
            labels.append("")
        values.append(str(entry["global_count"]))

    labels_str = ", ".join(f'"{l}"' for l in labels)
    values_str = ", ".join(values)
    limit_str  = ", ".join([str(global_limit)] * n)
    y_max      = global_limit + round(global_limit * 0.1)
    chart_title = title or f"Articles traites par IA - {n} derniers jours"

    return "\n".join([
        "```mermaid",
        "xychart-beta",
        f'    title "{chart_title}"',
        f"    x-axis [{labels_str}]",
        f'    y-axis "Articles" 0 --> {y_max}',
        f"    bar [{values_str}]",
        f"    line [{limit_str}]",
        "```",
    ])


def build_keyword_table(today_entry: dict) -> str:
    keywords = today_entry.get("keywords", {})
    if not keywords:
        return "_Aucune donnée par mot-clé disponible aujourd'hui._"

    rows = sorted(keywords.items(), key=lambda x: x[1].get("total", 0), reverse=True)
    lines = [
        "| Mot-clé | Articles | Sources actives |",
        "|---|---|---|",
    ]
    for kw, data in rows[:20]:
        total   = data.get("total", 0)
        sources = len(data.get("sources", {}))
        lines.append(f"| {kw} | {total} | {sources} |")

    return "\n".join(lines)


def _provider_totals(token_stats: dict, provider: str) -> dict:
    """Agrège les compteurs d'un provider (euria|claude) sur tous les services."""
    t = _empty_provider()
    for s in token_stats.values():
        p = s[provider]
        t["prompt"]     += p["prompt"]
        t["completion"] += p["completion"]
        t["total"]      += p["total"]
        t["calls"]      += p["calls"]
    return t


def build_token_table(token_stats: dict) -> str:
    if not token_stats:
        return "_Aucun token tracé dans les logs aujourd'hui._"

    rows = sorted(token_stats.items(), key=lambda x: x[1]["total"], reverse=True)

    # ── Tableau détaillé par service ────────────────────────────────────────────
    header = (
        "| Service / opération "
        "| EurIA appels | EurIA tokens "
        "| Claude appels | Claude tokens "
        "| Total tokens |"
    )
    sep = "|---|---|---|---|---|---|"
    lines = [header, sep]

    gt_euria_calls = gt_euria_tok = gt_claude_calls = gt_claude_tok = gt_all = 0
    for key, s in rows:
        e = s["euria"]
        c = s["claude"]
        e_calls = f"{e['calls']}" if e["calls"] else "—"
        e_tok   = f"{e['total']:,}" if e["total"] else "—"
        c_calls = f"{c['calls']}" if c["calls"] else "—"
        c_tok   = f"{c['total']:,}" if c["total"] else "—"
        lines.append(
            f"| `{key}` | {e_calls} | {e_tok} | {c_calls} | {c_tok} | {s['total']:,} |"
        )
        gt_euria_calls  += e["calls"]
        gt_euria_tok    += e["total"]
        gt_claude_calls += c["calls"]
        gt_claude_tok   += c["total"]
        gt_all          += s["total"]

    lines.append(
        f"| **Total** "
        f"| **{gt_euria_calls}** | **{gt_euria_tok:,}** "
        f"| **{gt_claude_calls}** | **{gt_claude_tok:,}** "
        f"| **{gt_all:,}** |"
    )

    table_detail = "\n".join(lines)

    # ── Synthèse comparative EurIA vs Claude ────────────────────────────────────
    synth_lines = [
        "| Provider | Appels API | Tokens prompt | Tokens réponse | Total tokens | Part |",
        "|---|---|---|---|---|---|",
    ]
    total_all = max(gt_euria_tok + gt_claude_tok, 1)
    for provider_label, provider_key, calls, tok in [
        ("EurIA (Infomaniak)", "euria",  gt_euria_calls,  gt_euria_tok),
        ("Claude (Anthropic)", "claude", gt_claude_calls, gt_claude_tok),
    ]:
        pt = _provider_totals(token_stats, provider_key)
        pct = round(tok / total_all * 100)
        synth_lines.append(
            f"| {provider_label} | {calls} | {pt['prompt']:,} | {pt['completion']:,} | {tok:,} | {pct} % |"
        )
    synth = "\n".join(synth_lines)

    return f"{synth}\n\n### Détail par service\n\n{table_detail}"


def build_report(history: list, token_stats: dict, quota_cfg: dict) -> str:
    """history contient 30 entrées (les 30 derniers jours)."""
    today_entry  = history[-1]
    today_str    = today_entry["date"]
    global_count = today_entry["global_count"]
    global_limit = quota_cfg["global_daily_limit"]
    pct          = round(global_count / global_limit * 100) if global_limit else 0
    today_dt     = datetime.fromisoformat(today_str)
    today_fr     = _date_fr(today_dt)

    # Fenêtres temporelles
    history_7d  = history[-7:]
    history_30d = history

    mermaid_7d  = build_mermaid_xychart(
        history_7d,  global_limit, "Articles traites par IA - 7 derniers jours"
    )
    mermaid_30d = build_mermaid_xychart(
        history_30d, global_limit, "Articles traites par IA - 30 derniers jours"
    )

    keyword_table = build_keyword_table(today_entry)
    token_table   = build_token_table(token_stats)

    # Stats 7 jours
    total_7d = sum(e["global_count"] for e in history_7d)
    avg_7d   = round(total_7d / len(history_7d))
    max_7d   = max(e["global_count"] for e in history_7d)

    # Stats 30 jours
    active_30d   = [e["global_count"] for e in history_30d if e["global_count"] > 0]
    total_30d    = sum(e["global_count"] for e in history_30d)
    avg_30d      = round(total_30d / len(active_30d)) if active_30d else 0
    max_30d      = max(e["global_count"] for e in history_30d)
    active_days  = len(active_30d)

    # Tendance : aujourd'hui vs moyenne des 6 jours précédents (actifs)
    prev_6j = [e["global_count"] for e in history_7d[:-1] if e["global_count"] > 0]
    if prev_6j:
        prev_avg  = round(sum(prev_6j) / len(prev_6j))
        trend_pct = round((global_count - prev_avg) / prev_avg * 100) if prev_avg else 0
        if trend_pct > 10:
            trend_str = f"↑ +{trend_pct} % vs moyenne 6j"
        elif trend_pct < -10:
            trend_str = f"↓ {trend_pct} % vs moyenne 6j"
        else:
            trend_str = f"→ {trend_pct:+d} % vs moyenne 6j (stable)"
    else:
        trend_str = "— premier jour de données"

    total_tokens_today = sum(s["total"] for s in token_stats.values())

    # Barre de progression ASCII pour le quota global
    filled = round(pct / 5)
    bar    = "█" * filled + "░" * (20 - filled)

    report = f"""---
title: "Rapport de consommation IA — {today_fr}"
date: {today_str}
type: ai-consumption
---

# Rapport de consommation IA — {today_fr}

## Résumé du jour

| Indicateur | Valeur |
|---|---|
| Articles traités | **{global_count}** / {global_limit} ({pct} %) |
| Progression quota | `{bar}` {pct} % |
| Tendance | {trend_str} |
| Tokens tracés (logs) | {total_tokens_today:,} |

### Statistiques 7 jours

| Indicateur | Valeur |
|---|---|
| Total 7 jours | {total_7d} articles |
| Moyenne / jour | {avg_7d} articles |
| Maximum / jour | {max_7d} articles |

### Statistiques 30 jours

| Indicateur | Valeur |
|---|---|
| Total 30 jours | {total_30d} articles |
| Jours actifs | {active_days} / 30 |
| Moyenne / jour actif | {avg_30d} articles |
| Maximum / jour | {max_30d} articles |

---

## Évolution sur 7 jours

{mermaid_7d}

---

## Évolution sur 30 jours

{mermaid_30d}

> **Barres** = articles traités · **Ligne** = plafond journalier configuré ({global_limit} articles).
> Les étiquettes de l'axe X sont affichées tous les 5 jours.

---

## Consommation par mot-clé (aujourd'hui)

{keyword_table}

---

## Tokens par service (aujourd'hui)

{token_table}

> ⚠️ Les tokens sont extraits des fichiers de log en temps réel.
> Seules les lignes `[EurIA] Usage` et `[Claude/...] Usage` du jour courant sont comptabilisées.
> Un zéro indique soit l'absence d'appels aujourd'hui, soit un script n'ayant pas encore tourné.

---

*Généré automatiquement le {today_fr} par `generate_ai_consumption_report.py`*
"""
    return report.strip()


def main():
    parser = argparse.ArgumentParser(
        description="Génère le rapport de consommation IA quotidien"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Affiche les 3000 premiers caractères du rapport sans le sauvegarder",
    )
    args = parser.parse_args()

    from utils.logging import print_console

    print_console("Génération du rapport de consommation IA...")

    history     = load_quota_history(PROJECT_ROOT, days=30)
    token_stats = parse_tokens_from_logs(PROJECT_ROOT)
    quota_cfg   = load_quota_config(PROJECT_ROOT)

    today_count = history[-1]["global_count"]
    global_limit = quota_cfg["global_daily_limit"]
    total_tokens = sum(s["total"] for s in token_stats.values())

    print_console(f"  Quota aujourd'hui   : {today_count} / {global_limit} articles")
    print_console(f"  Services avec tokens: {len(token_stats)} ({total_tokens:,} tokens tracés)")
    print_console(f"  Historique chargé   : {len(history)} jours")

    report_md = build_report(history, token_stats, quota_cfg)

    if args.dry_run:
        print(report_md[:3000])
        print_console("(dry-run — rapport non sauvegardé)")
        return

    output_dir  = PROJECT_ROOT / "rapports" / "markdown" / "_MORNING_DIGEST_"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / "ai_consumption_report.md"
    output_file.write_text(report_md, encoding="utf-8")
    print_console(f"Rapport sauvegardé → {output_file.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
