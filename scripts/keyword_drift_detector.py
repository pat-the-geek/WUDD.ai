#!/usr/bin/env python3
"""Détecteur de dérive des mots-clés (Axe 6).

Analyse sur 30 jours la pertinence de chaque keyword configuré dans
config/keyword-to-search.json et génère un rapport Markdown avec :
  - Keywords à faible pertinence (suggestion de suppression)
  - Keywords redondants entre eux (suggestion de fusion)
  - Entités émergentes non couvertes par les keywords actuels

Sortie : rapports/markdown/_WUDD.AI_/keyword_drift_YYYY-MM.md

Usage :
    python3 scripts/keyword_drift_detector.py [--dry-run] [--days N]
"""

import argparse
import json
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from utils.logging import default_logger
from utils.date_utils import parse_article_date


def _load_keywords() -> list[dict]:
    kw_file = _PROJECT_ROOT / "config" / "keyword-to-search.json"
    if not kw_file.exists():
        return []
    try:
        return json.loads(kw_file.read_text(encoding="utf-8"))
    except Exception:
        return []


def _flat_terms(kw_entry: dict) -> list[str]:
    """Extrait tous les termes d'une entrée keyword."""
    terms = []
    for field in ("keyword", "or", "and"):
        v = kw_entry.get(field)
        if isinstance(v, list):
            terms.extend([t.lower() for t in v if isinstance(t, str)])
        elif isinstance(v, str):
            terms.append(v.lower())
    return terms


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union > 0 else 0.0


def analyse_keyword_drift(days: int = 30) -> dict:
    """Analyse la pertinence des keywords sur les N derniers jours.

    Returns:
        dict avec keywords_stats, low_relevance, redundant_pairs, emerging_entities
    """
    keywords = _load_keywords()
    if not keywords:
        return {"error": "Aucun keyword trouvé"}

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)

    # Charger les articles récents depuis data/articles-from-rss/
    rss_dir = _PROJECT_ROOT / "data" / "articles-from-rss"
    articles_by_keyword: dict[str, list] = {}
    all_entities: defaultdict[str, int] = defaultdict(int)

    for json_file in rss_dir.glob("*.json"):
        keyword_name = json_file.stem
        try:
            articles = json.loads(json_file.read_text(encoding="utf-8", errors="replace"))
            if not isinstance(articles, list):
                continue
        except Exception:
            continue

        recent = []
        for art in articles:
            dt = parse_article_date(
                art.get("Date de publication", ""),
                date_only_policy="end",
            )
            if dt is None:
                continue
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if dt >= cutoff:
                recent.append(art)
                # Collecter les entités
                for etype, vals in art.get("entities", {}).items():
                    if isinstance(vals, list):
                        for v in vals:
                            all_entities[v] += 1

        articles_by_keyword[keyword_name] = recent

    # ── Métriques par keyword ─────────────────────────────────────────────────

    kw_stats: dict[str, dict] = {}
    for kw_entry in keywords:
        name = kw_entry.get("keyword") or (
            str(kw_entry.get("or", [""])[0]) if isinstance(kw_entry.get("or"), list) else ""
        )
        if not name:
            continue

        articles = articles_by_keyword.get(name, [])
        n_articles = len(articles)
        terms = set(_flat_terms(kw_entry))

        # Taux de pertinence : % d'articles dont le résumé contient au moins 1 terme
        relevant = 0
        if articles:
            for art in articles:
                resume = (art.get("Résumé") or "").lower()
                if any(t in resume for t in terms):
                    relevant += 1
        relevance_rate = relevant / n_articles if n_articles > 0 else 0.0

        # Entités les plus fréquentes dans les articles de ce keyword
        entity_freq: defaultdict[str, int] = defaultdict(int)
        for art in articles:
            for etype, vals in art.get("entities", {}).items():
                if isinstance(vals, list):
                    for v in vals:
                        entity_freq[v] += 1
        top_entities = sorted(entity_freq.items(), key=lambda x: -x[1])[:5]

        kw_stats[name] = {
            "terms": list(terms),
            "article_count": n_articles,
            "relevance_rate": round(relevance_rate, 3),
            "top_entities": top_entities,
        }

    # ── Détection des keywords à faible pertinence ─────────────────────────────
    LOW_RELEVANCE_THRESHOLD = 0.30
    FEW_ARTICLES_THRESHOLD  = 5

    low_relevance = [
        {"keyword": k, **{m: v for m, v in s.items() if m != "top_entities"}}
        for k, s in kw_stats.items()
        if s["relevance_rate"] < LOW_RELEVANCE_THRESHOLD
        or s["article_count"] < FEW_ARTICLES_THRESHOLD
    ]

    # ── Détection des keywords redondants ──────────────────────────────────────
    REDUNDANCY_THRESHOLD = 0.50
    redundant_pairs = []
    kw_names = list(kw_stats.keys())
    for i in range(len(kw_names)):
        for j in range(i + 1, len(kw_names)):
            a, b = kw_names[i], kw_names[j]
            terms_a = set(kw_stats[a]["terms"])
            terms_b = set(kw_stats[b]["terms"])
            sim = _jaccard(terms_a, terms_b)
            if sim >= REDUNDANCY_THRESHOLD:
                redundant_pairs.append({
                    "keyword_a": a,
                    "keyword_b": b,
                    "similarity": round(sim, 3),
                })

    # ── Entités émergentes non couvertes ───────────────────────────────────────
    all_keyword_terms: set[str] = set()
    for s in kw_stats.values():
        all_keyword_terms.update(s["terms"])

    # Entités fréquentes non mentionnées dans les keywords
    emerging = [
        {"entity": ent, "count": cnt}
        for ent, cnt in sorted(all_entities.items(), key=lambda x: -x[1])[:50]
        if ent.lower() not in all_keyword_terms and cnt >= 5
    ][:15]

    return {
        "period_days": days,
        "generated_at": now.strftime("%d/%m/%Y"),
        "keywords_stats": kw_stats,
        "low_relevance": low_relevance,
        "redundant_pairs": redundant_pairs,
        "emerging_entities": emerging,
    }


def _generate_markdown(analysis: dict) -> str:
    """Génère le rapport Markdown de dérive des keywords."""
    now_str = analysis["generated_at"]
    days    = analysis["period_days"]
    stats   = analysis["keywords_stats"]
    low_rel = analysis["low_relevance"]
    redund  = analysis["redundant_pairs"]
    emerging = analysis["emerging_entities"]

    lines = [
        f"# Rapport de dérive des mots-clés — {now_str}",
        "",
        f"Analyse sur **{days} jours**. {len(stats)} keywords surveillés.",
        "",
        "---",
        "",
    ]

    # Tableau de synthèse
    lines += [
        "## Vue d'ensemble",
        "",
        "| Keyword | Articles | Pertinence | Statut |",
        "|---|---|---|---|",
    ]
    for kw, s in sorted(stats.items(), key=lambda x: -x[1]["relevance_rate"]):
        rate_pct = f"{s['relevance_rate']:.0%}"
        n = s["article_count"]
        if s["relevance_rate"] < 0.30 or n < 5:
            status = "⚠️ Faible"
        elif s["relevance_rate"] > 0.70:
            status = "✅ Pertinent"
        else:
            status = "🔵 Acceptable"
        lines.append(f"| {kw} | {n} | {rate_pct} | {status} |")
    lines.append("")

    # Keywords à faible pertinence
    if low_rel:
        lines += ["## ⚠️ Keywords à faible pertinence (action recommandée)", ""]
        for item in low_rel:
            kw = item["keyword"]
            lines.append(
                f"- **{kw}** — {item['article_count']} articles, "
                f"pertinence {item['relevance_rate']:.0%}"
            )
            lines.append(f"  → *Suggestion : réviser les termes ou supprimer ce keyword*")
        lines.append("")

    # Paires redondantes
    if redund:
        lines += ["## 🔁 Keywords redondants (chevauchement de termes)", ""]
        for pair in redund:
            lines.append(
                f"- **{pair['keyword_a']}** ↔ **{pair['keyword_b']}** "
                f"(similarité {pair['similarity']:.0%})"
            )
            lines.append("  → *Suggestion : fusionner ces deux keywords*")
        lines.append("")

    # Entités émergentes
    if emerging:
        lines += ["## 🆕 Entités émergentes non couvertes", ""]
        lines.append("Ces entités sont fréquemment mentionnées mais absentes de vos keywords :")
        lines.append("")
        for item in emerging:
            lines.append(f"- **{item['entity']}** ({item['count']} mentions)")
        lines.append("")
        lines.append(
            "*Suggestion : envisager d'ajouter ces entités comme nouveaux keywords ou "
            "les intégrer dans des keywords existants.*"
        )
        lines.append("")

    lines += [
        "---",
        "",
        f"*Rapport généré automatiquement par WUDD.ai — {now_str}*",
    ]

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Détecte la dérive des mots-clés.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--days", type=int, default=30, help="Fenêtre d'analyse en jours")
    args = parser.parse_args()

    default_logger.info(f"[keyword_drift] Analyse sur {args.days} jours…")
    analysis = analyse_keyword_drift(days=args.days)

    if "error" in analysis:
        default_logger.error(f"[keyword_drift] {analysis['error']}")
        sys.exit(1)

    kw_stats = analysis["keywords_stats"]
    default_logger.info(f"[keyword_drift] {len(kw_stats)} keywords analysés")
    default_logger.info(
        f"[keyword_drift] {len(analysis['low_relevance'])} keywords à faible pertinence"
    )
    default_logger.info(
        f"[keyword_drift] {len(analysis['redundant_pairs'])} paires redondantes"
    )
    default_logger.info(
        f"[keyword_drift] {len(analysis['emerging_entities'])} entités émergentes"
    )

    if args.dry_run:
        default_logger.info("[keyword_drift] (dry-run) Aucune écriture.")
        return

    # Générer et sauvegarder le rapport
    report_dir = _PROJECT_ROOT / "rapports" / "markdown" / "_WUDD.AI_"
    report_dir.mkdir(parents=True, exist_ok=True)

    month_str = date.today().strftime("%Y-%m")
    report_path = report_dir / f"keyword_drift_{month_str}.md"

    md_content = _generate_markdown(analysis)
    report_path.write_text(md_content, encoding="utf-8")
    default_logger.info(f"[keyword_drift] Rapport généré : {report_path}")


if __name__ == "__main__":
    main()
