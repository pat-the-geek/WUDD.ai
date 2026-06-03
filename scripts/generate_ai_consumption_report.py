#!/usr/bin/env python3
"""
scripts/generate_ai_consumption_report.py

Génère un rapport de consommation quotidienne des services IA.
Agrège les articles traités par jour (quota_state.json + quota_history/),
parse les tokens EurIA/Claude depuis les logs cron, et produit un rapport
Markdown avec diagramme Mermaid xychart-beta.

Sortie : rapports/markdown/_WUDD.AI_/ai_consumption_report.md
         (même nom à chaque exécution — fichier remplacé)

Usage :
  python3 scripts/generate_ai_consumption_report.py [--dry-run]
"""

import argparse
import json
import re
import sys
from calendar import monthrange
from datetime import datetime, timedelta
from pathlib import Path

SCRIPT_DIR   = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))

from utils.scheduler_toggle import should_run_task

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
USAGE_LINE_OLLAMA = re.compile(r"\[Ollama[^\]]*\]\s*Usage", re.IGNORECASE)
USAGE_LINE_PATTERN = re.compile(r"\[(?:EurIA|Claude[^\]]*|Ollama[^\]]*)]\s*Usage", re.IGNORECASE)

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


def parse_tokens_from_logs(project_root: Path, date_str: str | None = None) -> dict:
    """Parse les fichiers de log cron pour extraire la consommation de tokens.

    Args:
        date_str: Date au format YYYY-MM-DD. Si None, utilise aujourd'hui.

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
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")
    reports_dir = project_root / "rapports"
    stats = {}

    for log_name in LOG_FILES:
        log_path = reports_dir / log_name
        if not log_path.exists():
            continue

        service_key = log_name.replace("cron_", "").replace(".log", "")
        euria  = _empty_provider()
        claude = _empty_provider()
        ollama = _empty_provider()

        try:
            text = log_path.read_text(encoding="utf-8", errors="ignore")
            for line in text.splitlines():
                if not line.startswith(date_str):
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
                elif USAGE_LINE_OLLAMA.search(line):
                    # Pattern Ollama : même format que EurIA (prompt + completion + total)
                    m3 = TOKEN_PATTERN_EURIA.search(line)
                    if m3:
                        ollama["prompt"]     += int(m3.group(1))
                        ollama["completion"] += int(m3.group(2))
                        ollama["total"]      += int(m3.group(3))
                        ollama["calls"]      += 1

        except Exception:
            pass

        total_calls = euria["calls"] + claude["calls"] + ollama["calls"]
        if total_calls > 0:
            stats[service_key] = {
                "euria":  euria,
                "claude": claude,
                "ollama": ollama,
                "total":  euria["total"] + claude["total"] + ollama["total"],
                "calls":  total_calls,
            }

    return stats


def parse_tokens_history(project_root: Path, all_history: list) -> dict:
    """Parse les tokens pour chaque date présente dans all_history.

    Retourne un dict {"YYYY-MM-DD": total_tokens_jour} en agrégeant tous les services.
    """
    token_by_date: dict[str, int] = {}
    dates = sorted(set(e["date"] for e in all_history))
    for date_str in dates:
        day_stats = parse_tokens_from_logs(project_root, date_str)
        token_by_date[date_str] = sum(s["total"] for s in day_stats.values())
    return token_by_date


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


_MONTHS     = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
_MONTHS_FR  = ["jan", "fév", "mars", "avr", "mai", "juin",
               "juil", "aoû", "sept", "oct", "nov", "déc"]


def load_all_quota_history(project_root: Path) -> list:
    """Charge tous les snapshots quota disponibles dans data/quota_history/.

    Retourne une liste d'entrées triées par date ASC incluant aujourd'hui.
    """
    history_dir = project_root / "data" / "quota_history"
    today = datetime.now().date()
    today_iso = today.isoformat()
    entries: dict[str, dict] = {}

    # Charger tous les fichiers historiques disponibles
    if history_dir.exists():
        for hist_file in sorted(history_dir.glob("*.json")):
            iso = hist_file.stem  # YYYY-MM-DD
            try:
                datetime.fromisoformat(iso)  # validation
            except ValueError:
                continue
            try:
                data = json.loads(hist_file.read_text(encoding="utf-8"))
                entries[iso] = {
                    "date":         iso,
                    "global_count": data.get("global_count", 0),
                    "keywords":     data.get("keywords", {}),
                }
            except Exception:
                pass

    # Ajouter aujourd'hui depuis quota_state.json
    entry_today = {"date": today_iso, "global_count": 0, "keywords": {}}
    state_file = project_root / "data" / "quota_state.json"
    if state_file.exists():
        try:
            state = json.loads(state_file.read_text(encoding="utf-8"))
            if state.get("date") == today_iso:
                entry_today["global_count"] = state.get("global_count", 0)
                entry_today["keywords"]     = state.get("keywords", {})
        except Exception:
            pass
    entries[today_iso] = entry_today

    return sorted(entries.values(), key=lambda e: e["date"])


def _aggregate_by_month(all_history: list) -> dict:
    """Agrège les entrées journalières par mois (YYYY-MM).

    Retourne un dict ordonné : {"YYYY-MM": {"total": int, "active_days": int,
    "avg_per_active_day": int, "max_day": int, "days_in_month": int}}
    """
    months: dict[str, list] = {}
    for entry in all_history:
        ym = entry["date"][:7]  # "YYYY-MM"
        months.setdefault(ym, []).append(entry["global_count"])

    result = {}
    for ym, counts in sorted(months.items()):
        year, month = int(ym[:4]), int(ym[5:7])
        days_in_month = monthrange(year, month)[1]
        active = [c for c in counts if c > 0]
        total  = sum(counts)
        result[ym] = {
            "total":              total,
            "active_days":        len(active),
            "avg_per_active_day": round(total / len(active)) if active else 0,
            "max_day":            max(counts) if counts else 0,
            "days_in_month":      days_in_month,
        }
    return result


def _month_label(ym: str) -> str:
    """Formate YYYY-MM en label court sans caractères spéciaux : Jan26."""
    year, month = int(ym[:4]), int(ym[5:7])
    return f"{_MONTHS[month - 1]}{str(year)[-2:]}"


def build_monthly_mermaid_chart(all_history: list, token_by_date: dict) -> str:
    """Génère un diagramme xychart-beta mensuel (une barre par mois) basé sur les tokens."""
    # Agrège les tokens par mois
    months_tok: dict[str, int] = {}
    for entry in all_history:
        ym = entry["date"][:7]
        months_tok[ym] = months_tok.get(ym, 0) + token_by_date.get(entry["date"], 0)

    if not months_tok:
        return "_Aucune donnée historique disponible._"

    labels = [_month_label(ym) for ym in sorted(months_tok)]
    values_list = [months_tok[ym] for ym in sorted(months_tok)]
    values = [str(v) for v in values_list]

    y_max = max(values_list) if values_list else 1
    y_max = y_max + round(y_max * 0.15) + 1  # +15 % de marge

    labels_str = ", ".join(labels)
    values_str = ", ".join(values)

    return "\n".join([
        "```mermaid",
        "xychart-beta",
        f"    x-axis [{labels_str}]",
        f"    y-axis Tokens 0 --> {y_max}",
        f"    bar [{values_str}]",
        "```",
    ])


def build_monthly_stats_table(all_history: list, token_by_date: dict) -> str:
    """Génère un tableau comparatif mois par mois basé sur les tokens."""
    # Agrège les tokens et jours actifs par mois
    months_data: dict[str, dict] = {}
    for entry in all_history:
        ym = entry["date"][:7]
        tok = token_by_date.get(entry["date"], 0)
        if ym not in months_data:
            year, month_num = int(ym[:4]), int(ym[5:7])
            months_data[ym] = {
                "total": 0,
                "active_days": 0,
                "max_day": 0,
                "days_in_month": monthrange(year, month_num)[1],
            }
        months_data[ym]["total"] += tok
        if tok > 0:
            months_data[ym]["active_days"] += 1
        if tok > months_data[ym]["max_day"]:
            months_data[ym]["max_day"] = tok

    if not months_data:
        return "_Aucune donnée historique disponible._"

    lines = [
        "| Mois | Total tokens | Jours actifs | Moy./jour actif | Max/jour |",
        "|---|---|---|---|---|",
    ]

    prev_total = None
    for ym in sorted(months_data):
        m = months_data[ym]
        year, month_num = int(ym[:4]), int(ym[5:7])
        month_label_fr = f"{_MONTHS_FR[month_num - 1]} {year}"
        avg_active = round(m["total"] / m["active_days"]) if m["active_days"] else 0

        # Indicateur d'évolution vs mois précédent
        if prev_total is not None and prev_total > 0:
            delta = m["total"] - prev_total
            pct   = round(delta / prev_total * 100)
            if pct > 10:
                trend = f"↑ +{pct} %"
            elif pct < -10:
                trend = f"↓ {pct} %"
            else:
                trend = f"→ {pct:+d} %"
            total_cell = f"**{m['total']:,}** ({trend})"
        else:
            total_cell = f"**{m['total']:,}**"

        lines.append(
            f"| {month_label_fr} "
            f"| {total_cell} "
            f"| {m['active_days']} / {m['days_in_month']} "
            f"| {avg_active:,} "
            f"| {m['max_day']:,} |"
        )
        prev_total = m["total"]

    return "\n".join(lines)


def build_day_comparison_table(all_history: list, token_by_date: dict) -> str:
    """Génère un tableau de comparaison hier / aujourd'hui / moyenne 7j basé sur les tokens."""
    if len(all_history) < 2:
        return "_Historique insuffisant pour la comparaison._"

    today_entry     = all_history[-1]
    yesterday_entry = all_history[-2]
    history_7d      = all_history[-7:]

    today_count     = token_by_date.get(today_entry["date"], 0)
    yesterday_count = token_by_date.get(yesterday_entry["date"], 0)
    avg_7d          = round(sum(token_by_date.get(e["date"], 0) for e in history_7d) / len(history_7d))

    def _delta(val: int, ref: int) -> str:
        if ref == 0:
            return "—"
        d   = val - ref
        pct = round(d / ref * 100)
        sign = "+" if d >= 0 else ""
        return f"{sign}{d:,} ({sign}{pct} %)"

    lines = [
        "| Période | Tokens | Δ vs hier | Δ vs moy. 7j |",
        "|---|---|---|---|",
        f"| Aujourd'hui ({today_entry['date']}) | **{today_count:,}** | {_delta(today_count, yesterday_count)} | {_delta(today_count, avg_7d)} |",
        f"| Hier ({yesterday_entry['date']}) | {yesterday_count:,} | — | {_delta(yesterday_count, avg_7d)} |",
        f"| Moyenne 7 jours | {avg_7d:,} | — | — |",
    ]
    return "\n".join(lines)


def _label(date_str: str) -> str:
    """Formate une date en label Mermaid sans caractères spéciaux : 19Mar, 01Apr..."""
    dt = datetime.fromisoformat(date_str)
    return f"{dt.day:02d}{_MONTHS[dt.month - 1]}"


def build_mermaid_xychart(history: list, token_by_date: dict, title: str = "") -> str:
    """Génère un diagramme xychart-beta basé sur les tokens.

    - <= 10 jours : barre quotidienne, labels DDMMM (ex: 19Mar)
    - >  10 jours : agrégation en périodes de 5 jours (6 points pour 30j).
    """
    n = len(history)

    if n <= 10:
        labels = [_label(e["date"]) for e in history]
        values = [str(token_by_date.get(e["date"], 0)) for e in history]
    else:
        period = 5
        groups = [history[i:i + period] for i in range(0, n, period)]
        labels = [_label(g[0]["date"]) for g in groups]
        values = [str(sum(token_by_date.get(e["date"], 0) for e in g)) for g in groups]

    labels_str = ", ".join(labels)
    values_str = ", ".join(values)
    int_values = [int(v) for v in values]
    y_max = max(int_values) if int_values else 1
    y_max = y_max + round(y_max * 0.15) + 1  # +15 % de marge

    return "\n".join([
        "```mermaid",
        "xychart-beta",
        f"    x-axis [{labels_str}]",
        f"    y-axis Tokens 0 --> {y_max}",
        f"    bar [{values_str}]",
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
    """Agrège les compteurs d'un provider (euria|claude|ollama) sur tous les services."""
    t = _empty_provider()
    for s in token_stats.values():
        p = s.get(provider, _empty_provider())
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
        "| Ollama appels | Ollama tokens "
        "| Total tokens |"
    )
    sep = "|---|---|---|---|---|---|---|---|"
    lines = [header, sep]

    gt_euria_calls = gt_euria_tok = gt_claude_calls = gt_claude_tok = 0
    gt_ollama_calls = gt_ollama_tok = gt_all = 0
    for key, s in rows:
        e = s["euria"]
        c = s["claude"]
        o = s.get("ollama", _empty_provider())
        e_calls = f"{e['calls']}" if e["calls"] else "—"
        e_tok   = f"{e['total']:,}" if e["total"] else "—"
        c_calls = f"{c['calls']}" if c["calls"] else "—"
        c_tok   = f"{c['total']:,}" if c["total"] else "—"
        o_calls = f"{o['calls']}" if o["calls"] else "—"
        o_tok   = f"{o['total']:,}" if o["total"] else "—"
        lines.append(
            f"| `{key}` | {e_calls} | {e_tok} | {c_calls} | {c_tok} | {o_calls} | {o_tok} | {s['total']:,} |"
        )
        gt_euria_calls   += e["calls"]
        gt_euria_tok     += e["total"]
        gt_claude_calls  += c["calls"]
        gt_claude_tok    += c["total"]
        gt_ollama_calls  += o["calls"]
        gt_ollama_tok    += o["total"]
        gt_all           += s["total"]

    lines.append(
        f"| **Total** "
        f"| **{gt_euria_calls}** | **{gt_euria_tok:,}** "
        f"| **{gt_claude_calls}** | **{gt_claude_tok:,}** "
        f"| **{gt_ollama_calls}** | **{gt_ollama_tok:,}** "
        f"| **{gt_all:,}** |"
    )

    table_detail = "\n".join(lines)

    # ── Synthèse comparative EurIA vs Claude vs Ollama ──────────────────────────
    synth_lines = [
        "| Provider | Appels API | Tokens prompt | Tokens réponse | Total tokens | Part |",
        "|---|---|---|---|---|---|",
    ]
    total_all = max(gt_euria_tok + gt_claude_tok + gt_ollama_tok, 1)
    for provider_label, provider_key, calls, tok in [
        ("EurIA (Infomaniak)", "euria",  gt_euria_calls,  gt_euria_tok),
        ("Claude (Anthropic)", "claude", gt_claude_calls, gt_claude_tok),
        ("Ollama (local)",     "ollama", gt_ollama_calls, gt_ollama_tok),
    ]:
        pt = _provider_totals(token_stats, provider_key)
        pct = round(tok / total_all * 100)
        synth_lines.append(
            f"| {provider_label} | {calls} | {pt['prompt']:,} | {pt['completion']:,} | {tok:,} | {pct} % |"
        )
    synth = "\n".join(synth_lines)

    return f"{synth}\n\n### Détail par service\n\n{table_detail}"


def build_report(history: list, token_stats: dict, quota_cfg: dict,
                 all_history: list | None = None,
                 token_by_date: dict | None = None) -> str:
    """history contient 30 entrées (les 30 derniers jours).
    all_history contient toutes les entrées disponibles (tous les mois).
    token_by_date : dict {YYYY-MM-DD: total_tokens} pour l'historique des graphiques.
    """
    today_entry  = history[-1]
    today_str    = today_entry["date"]
    global_count = today_entry["global_count"]
    global_limit = quota_cfg["global_daily_limit"]
    pct_articles = round(global_count / global_limit * 100) if global_limit else 0
    today_dt     = datetime.fromisoformat(today_str)
    today_fr     = _date_fr(today_dt)

    # Utiliser all_history si disponible, sinon retomber sur history
    full_history = all_history if all_history else history

    # token_by_date : si non fourni, utiliser seulement les tokens d'aujourd'hui
    if token_by_date is None:
        token_by_date = {today_str: sum(s["total"] for s in token_stats.values())}

    # Fenêtres temporelles
    history_7d  = history[-7:]
    history_30d = history

    # Tokens aujourd'hui (depuis les logs)
    total_tokens_today = sum(s["total"] for s in token_stats.values())

    # Graphiques tokens
    mermaid_7d  = build_mermaid_xychart(history_7d,  token_by_date)
    mermaid_30d = build_mermaid_xychart(history_30d, token_by_date)

    keyword_table = build_keyword_table(today_entry)
    token_table   = build_token_table(token_stats)

    # Tableaux comparatifs mensuel et quotidien (basés sur les tokens)
    day_comparison_table   = build_day_comparison_table(full_history, token_by_date)
    monthly_stats_table    = build_monthly_stats_table(full_history, token_by_date)
    monthly_mermaid_chart  = build_monthly_mermaid_chart(full_history, token_by_date)

    # Nombre de mois avec données disponibles (fichiers history présents)
    months_available = len(set(e["date"][:7] for e in full_history))

    # Stats tokens 7 jours
    tok_7d       = [token_by_date.get(e["date"], 0) for e in history_7d]
    total_tok_7d = sum(tok_7d)
    avg_tok_7d   = round(total_tok_7d / len(tok_7d)) if tok_7d else 0
    max_tok_7d   = max(tok_7d) if tok_7d else 0

    # Stats tokens 30 jours
    tok_30d        = [token_by_date.get(e["date"], 0) for e in history_30d]
    active_tok_30d = [t for t in tok_30d if t > 0]
    total_tok_30d  = sum(tok_30d)
    avg_tok_30d    = round(total_tok_30d / len(active_tok_30d)) if active_tok_30d else 0
    max_tok_30d    = max(tok_30d) if tok_30d else 0
    active_days_tok = len(active_tok_30d)

    # Tendance tokens : aujourd'hui vs moyenne des 6 jours précédents
    prev_6j_tok = [token_by_date.get(e["date"], 0) for e in history_7d[:-1] if token_by_date.get(e["date"], 0) > 0]
    if prev_6j_tok:
        prev_avg  = round(sum(prev_6j_tok) / len(prev_6j_tok))
        trend_pct = round((total_tokens_today - prev_avg) / prev_avg * 100) if prev_avg else 0
        if trend_pct > 10:
            trend_str = f"↑ +{trend_pct} % vs moyenne 6j"
        elif trend_pct < -10:
            trend_str = f"↓ {trend_pct} % vs moyenne 6j"
        else:
            trend_str = f"→ {trend_pct:+d} % vs moyenne 6j (stable)"
    else:
        trend_str = "— premier jour de données"

    report = f"""---
title: "Rapport de consommation IA — {today_fr}"
date: {today_str}
type: ai-consumption
---

# Rapport de consommation IA — {today_fr}

## Résumé du jour

| Indicateur | Valeur |
|---|---|
| Tokens consommés aujourd'hui | **{total_tokens_today:,}** |
| Tendance tokens | {trend_str} |
| Articles traités (quota) | {global_count} / {global_limit} ({pct_articles} %) |

### Comparaison hier / aujourd'hui (tokens)

{day_comparison_table}

### Statistiques tokens 7 jours

| Indicateur | Valeur |
|---|---|
| Total 7 jours | {total_tok_7d:,} tokens |
| Moyenne / jour | {avg_tok_7d:,} tokens |
| Maximum / jour | {max_tok_7d:,} tokens |

### Statistiques tokens 30 jours

| Indicateur | Valeur |
|---|---|
| Total 30 jours | {total_tok_30d:,} tokens |
| Jours actifs | {active_days_tok} / 30 |
| Moyenne / jour actif | {avg_tok_30d:,} tokens |
| Maximum / jour | {max_tok_30d:,} tokens |

---

## Évolution des tokens sur 7 jours

{mermaid_7d}

---

## Évolution des tokens sur 30 jours

{mermaid_30d}

> **Barres** = tokens consommés · Agrégation par périodes de 5 jours pour le graphe 30j.

---

## Évolution mensuelle des tokens ({months_available} mois disponibles)

{monthly_mermaid_chart}

### Comparaison mois par mois

{monthly_stats_table}

> Les flèches (↑ ↓ →) indiquent l'évolution par rapport au mois précédent.

---

## Tokens par service (aujourd'hui)

{token_table}

> ⚠️ Les tokens sont extraits des fichiers de log cron.
> Seules les lignes `[EurIA] Usage`, `[Claude/...] Usage` et `[Ollama/...] Usage` du jour courant sont comptabilisées.

---

## Consommation par mot-clé (aujourd'hui)

{keyword_table}

---

*Généré automatiquement le {today_fr} par `generate_ai_consumption_report.py`*
"""
    return report.strip()


def main():
    if not should_run_task("reports.ai_consumption"):
        return

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

    today_count  = history[-1]["global_count"]
    global_limit = quota_cfg["global_daily_limit"]
    total_tokens = sum(s["total"] for s in token_stats.values())

    all_history     = load_all_quota_history(PROJECT_ROOT)
    token_by_date   = parse_tokens_history(PROJECT_ROOT, all_history)

    print_console(f"  Quota aujourd'hui   : {today_count} / {global_limit} articles")
    print_console(f"  Tokens aujourd'hui  : {total_tokens:,} (depuis {len(token_stats)} services)")
    print_console(f"  Historique chargé   : {len(history)} jours (30j) / {len(all_history)} jours (total)")
    print_console(f"  Jours avec tokens   : {sum(1 for v in token_by_date.values() if v > 0)} / {len(token_by_date)}")

    report_md = build_report(history, token_stats, quota_cfg, all_history=all_history, token_by_date=token_by_date)

    if args.dry_run:
        print(report_md[:3000])
        print_console("(dry-run — rapport non sauvegardé)")
        return

    output_dir  = PROJECT_ROOT / "rapports" / "markdown" / "_WUDD.AI_"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / "ai_consumption_report.md"
    output_file.write_text(report_md, encoding="utf-8")
    print_console(f"Rapport sauvegardé → {output_file.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
