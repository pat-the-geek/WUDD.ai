#!/usr/bin/env python3
"""
Analyse la valeur des flux RSS en OPML et produit un rapport de recommandations.

Critères d'évaluation :
- Nombre d'articles détectés par source
- Recouvrement des entités entre sources (similarité Jaccard)
- Flux n'ayant jamais détecté d'article
- Sources avec faible apport par rapport à d'autres sources similaires

Les flux marqués bypassQuota=true dans WUDD.opml sont préservés.
"""

import json
import os
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# Chemins
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent

OPML_PATH   = PROJECT_ROOT / "data" / "WUDD.opml"
RSS_DIR     = PROJECT_ROOT / "data" / "articles-from-rss"
RAPPORT_DIR = PROJECT_ROOT / "rapports" / "markdown" / "_WUDD.AI_"
RAPPORT_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Seuils
# ---------------------------------------------------------------------------
SEUIL_ARTICLES_FAIBLE   = 5     # < N articles au total → très faible
SEUIL_ARTICLES_MOYEN    = 30    # < N articles → faible
SEUIL_COVERAGE_NOTABLE  = 0.45  # si ≥ 45% des entités de B couvertes par A → recouvrement notable
SEUIL_COVERAGE_FORT     = 0.65  # recouvrement fort (entités de B très couvertes par A)

def print_console(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"{ts} {msg}")


# ===========================================================================
# 1. Charger les flux OPML
# ===========================================================================
def load_opml_feeds(opml_path: Path) -> list[dict]:
    """Retourne la liste des flux RSS avec leurs attributs."""
    tree = ET.parse(opml_path)
    root = tree.getroot()
    outlines = root.findall(".//outline[@type='rss']")
    feeds = []
    for o in outlines:
        feeds.append({
            "title":        o.attrib.get("title", "Unknown"),
            "xmlUrl":       o.attrib.get("xmlUrl", ""),
            "htmlUrl":      o.attrib.get("htmlUrl", ""),
            "category":     o.getparent().attrib.get("text", "") if hasattr(o, "getparent") else "",
            "bypassQuota":  o.attrib.get("bypassQuota", "false").lower() == "true",
        })
    return feeds


# ===========================================================================
# 2. Charger tous les articles depuis data/articles-from-rss/
# ===========================================================================
def load_all_articles(rss_dir: Path) -> list[dict]:
    """Charge tous les articles de tous les fichiers JSON RSS."""
    all_articles = []
    for json_file in sorted(rss_dir.glob("*.json")):
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
            if isinstance(data, list):
                all_articles.extend(data)
        except Exception as e:
            print_console(f"  ⚠️  Erreur lecture {json_file.name}: {e}")
    return all_articles


# ===========================================================================
# 3. Stats par source
# ===========================================================================
def compute_source_stats(articles: list[dict]) -> dict[str, dict]:
    """Calcule les statistiques par source RSS (title dans OPML)."""
    stats = defaultdict(lambda: {
        "count":    0,
        "keywords": defaultdict(int),
        "entities": defaultdict(set),   # type → set(valeur)
        "entities_flat": set(),         # toutes entités confondues
        "urls":     set(),
        "keywords_set": set(),
    })

    for art in articles:
        source = art.get("Sources", "").strip()
        if not source:
            continue
        stats[source]["count"] += 1
        kw = art.get("mot_cle", "")
        if kw:
            stats[source]["keywords"][kw] += 1
            stats[source]["keywords_set"].add(kw)
        if art.get("entities"):
            for ent_type, values in art["entities"].items():
                if ent_type in ("DATE", "TIME", "CARDINAL", "ORDINAL", "PERCENT", "MONEY", "QUANTITY"):
                    continue
                for v in (values if isinstance(values, list) else [values]):
                    v_norm = v.strip().lower()
                    stats[source]["entities"][ent_type].add(v_norm)
                    stats[source]["entities_flat"].add(v_norm)
        url = art.get("URL", "")
        if url:
            stats[source]["urls"].add(url)
    return stats


# ===========================================================================
# 4. Similarité dirigée : fraction des entités de B couverte par A
# ===========================================================================
def directed_coverage(ent_big: set, ent_small: set) -> float:
    """Retourne |A∩B| / |B| : fraction des entités de B déjà dans A."""
    if not ent_small:
        return 0.0
    return len(ent_big & ent_small) / len(ent_small)


def jaccard(set_a: set, set_b: set) -> float:
    if not set_a and not set_b:
        return 0.0
    inter = len(set_a & set_b)
    union = len(set_a | set_b)
    return inter / union if union else 0.0


# ===========================================================================
# 5. Analyse principale
# ===========================================================================
def analyse(feeds: list[dict], source_stats: dict[str, dict]) -> dict:
    """
    Retourne un dict d'analyse :
    - feeds_no_articles       : feeds OPML sans aucun article
    - feeds_low_value         : feeds avec peu d'articles et/ou fort recouvrement
    - directed_overlaps       : couples (big, small) avec fort recouvrement dirigé
    - feeds_to_remove         : liste finale de recommandations de suppression
    - source_stats_sorted     : sources triées par nb d'articles décroissant
    """
    import math
    opml_titles   = {f["title"]: f for f in feeds}
    bypass_titles = {f["title"] for f in feeds if f["bypassQuota"]}

    # -- a) Feeds OPML sans aucun article détecté --
    feeds_no_articles = []
    for f in feeds:
        if f["title"] not in source_stats:
            feeds_no_articles.append(f)

    # -- b) Tri des sources connues par nombre d'articles --
    source_stats_sorted = sorted(
        source_stats.items(),
        key=lambda x: x[1]["count"],
        reverse=True
    )

    # -- c) Recouvrement dirigé : pour chaque paire, fraction des entités de
    #       la source minoritaire déjà couverte par la source majoritaire --
    active_sources = [s for s, st in source_stats.items()
                      if st["count"] > 0 and st["entities_flat"]]

    directed_overlaps = []
    max_coverage_by_source = defaultdict(float)  # source → couverture max par une grande source

    for i in range(len(active_sources)):
        for j in range(i + 1, len(active_sources)):
            src_a = active_sources[i]
            src_b = active_sources[j]
            cnt_a = source_stats[src_a]["count"]
            cnt_b = source_stats[src_b]["count"]
            ent_a = source_stats[src_a]["entities_flat"]
            ent_b = source_stats[src_b]["entities_flat"]

            # big = source avec plus d'articles; small = source avec moins
            if cnt_a >= cnt_b:
                big, small = src_a, src_b
                ent_big, ent_small = ent_a, ent_b
            else:
                big, small = src_b, src_a
                ent_big, ent_small = ent_b, ent_a

            cov = directed_coverage(ent_big, ent_small)
            common = len(ent_big & ent_small)

            if cov >= SEUIL_COVERAGE_NOTABLE:
                directed_overlaps.append({
                    "coverage":   round(cov, 3),
                    "src_big":    big,
                    "cnt_big":    source_stats[big]["count"],
                    "ent_big":    len(ent_big),
                    "src_small":  small,
                    "cnt_small":  source_stats[small]["count"],
                    "ent_small":  len(ent_small),
                    "common":     common,
                })
                max_coverage_by_source[small] = max(max_coverage_by_source[small], cov)

    directed_overlaps.sort(key=lambda x: x["coverage"], reverse=True)

    # -- d) Calcul couverture globale : % des entités d'une source couvertes
    #       par AU MOINS UNE autre source plus grande --
    global_coverage = {}
    for src in active_sources:
        ent_src = source_stats[src]["entities_flat"]
        if not ent_src:
            global_coverage[src] = 0.0
            continue
        other_pool = set()
        for other in active_sources:
            if other != src and source_stats[other]["count"] > source_stats[src]["count"]:
                other_pool |= source_stats[other]["entities_flat"]
        covered = len(ent_src & other_pool) / len(ent_src) if ent_src else 0.0
        global_coverage[src] = round(covered, 3)

    # -- e) Identification des sources à faible valeur --
    removal_candidates = set()
    removal_reasons     = defaultdict(list)

    # 1. Feeds OPML jamais actifs
    for f in feeds_no_articles:
        if not f["bypassQuota"]:
            removal_candidates.add(f["title"])
            removal_reasons[f["title"]].append("Aucun article jamais détecté")

    # 2. Sources actives avec très peu d'articles
    for src, st in source_stats.items():
        if st["count"] <= SEUIL_ARTICLES_FAIBLE:
            if src not in bypass_titles:
                removal_candidates.add(src)
                removal_reasons[src].append(f"Très faible volume : {st['count']} article(s) au total")

    # 3. Sources avec fort recouvrement dirigé (entités doublées par plus grande source)
    for ov in directed_overlaps:
        small = ov["src_small"]
        big   = ov["src_big"]
        cov   = ov["coverage"]
        if small in bypass_titles:
            continue
        if cov >= SEUIL_COVERAGE_FORT:
            removal_candidates.add(small)
            removal_reasons[small].append(
                f"Recouvrement fort {cov:.0%} — {ov['common']}/{ov['ent_small']} entités "
                f"déjà couvertes par « {big} » ({ov['cnt_big']} articles)"
            )
        elif cov >= SEUIL_COVERAGE_NOTABLE and ov["cnt_small"] <= SEUIL_ARTICLES_MOYEN:
            removal_candidates.add(small)
            removal_reasons[small].append(
                f"Recouvrement notable {cov:.0%} et faible volume ({ov['cnt_small']} art.) — "
                f"couvert par « {big} »"
            )

    # -- f) Score de valeur global par source --
    max_count = max((st["count"] for st in source_stats.values()), default=1)

    scores = {}
    for src, st in source_stats.items():
        count_score  = math.log(st["count"] + 1) / math.log(max_count + 1)
        uniq_ratio   = (1.0 - global_coverage.get(src, 0.0))
        ov_penalty   = max_coverage_by_source.get(src, 0.0)
        value_score  = round(count_score * 0.55 + uniq_ratio * 0.45 - ov_penalty * 0.20, 3)
        scores[src]  = max(0.0, value_score)

    return {
        "feeds_no_articles":      feeds_no_articles,
        "directed_overlaps":      directed_overlaps[:60],
        "global_coverage":        global_coverage,
        "max_coverage_by_source": dict(max_coverage_by_source),
        "removal_candidates":     removal_candidates,
        "removal_reasons":        dict(removal_reasons),
        "source_stats_sorted":    source_stats_sorted,
        "value_scores":           scores,
        "bypass_titles":          bypass_titles,
        "opml_titles":            opml_titles,
    }


# ===========================================================================
# 6. Générer le rapport Markdown
# ===========================================================================
def generate_report(analysis: dict, feeds: list[dict]) -> str:
    today = datetime.now().strftime("%d/%m/%Y")
    bypass = analysis["bypass_titles"]
    candidates = analysis["removal_candidates"]
    reasons   = analysis["removal_reasons"]
    source_stats_sorted = analysis["source_stats_sorted"]
    value_scores = analysis["value_scores"]
    opml_by_title = analysis["opml_titles"]
    global_cov    = analysis["global_coverage"]

    lines = []
    lines.append(f"# Rapport d'analyse des flux RSS WUDD.ai")
    lines.append(f"\n**Date :** {today}  ")
    lines.append(f"**Flux OPML analysés :** {len(feeds)}  ")
    lines.append(f"**Sources ayant détecté au moins un article :** {len(source_stats_sorted)}  ")
    lines.append(f"**Articles analysés :** {sum(st['count'] for _, st in source_stats_sorted)}  \n")
    lines.append("> **Méthodologie** : Le recouvrement est mesuré par *similarité dirigée* — "
                 "fraction des entités nommées d'une source (PERSON, ORG, GPE, PRODUCT…) "
                 "déjà présentes dans une source plus grande. "
                 "Les entités temporelles (DATE, MONEY, CARDINAL…) sont exclues.\n")

    # --- Flux bypassQuota (à préserver) ---
    lines.append("---")
    lines.append("\n## ⚡ Flux prioritaires (bypassQuota — à conserver absolument)\n")
    for f in feeds:
        if f["bypassQuota"]:
            cnt = 0
            for src, st in source_stats_sorted:
                if src == f["title"]:
                    cnt = st["count"]
                    break
            lines.append(f"- **{f['title']}** — {cnt} article(s) détecté(s)  \n  `{f['xmlUrl']}`")
    lines.append("")

    # --- Flux sans aucun article ---
    lines.append("---")
    lines.append("\n## ❌ Flux sans articles détectés ({} flux)\n".format(len(analysis["feeds_no_articles"])))
    no_art = analysis["feeds_no_articles"]
    if no_art:
        lines.append(f"Ces {len(no_art)} flux n'ont jamais contribué d'article :\n")
        for f in sorted(no_art, key=lambda x: x["title"]):
            bypass_tag = " ⚡ **PROTÉGÉ**" if f["bypassQuota"] else ""
            lines.append(f"- **{f['title']}**{bypass_tag}  \n  `{f['xmlUrl']}`")
    else:
        lines.append("_Tous les flux ont contribué au moins un article._")
    lines.append("")

    # --- Top 20 sources les plus actives ---
    lines.append("---")
    lines.append("\n## 🏆 Top 20 sources les plus actives\n")
    lines.append("| Rang | Source | Articles | Entités uniques | Couv. par autres | Score valeur |")
    lines.append("|------|--------|----------|-----------------|------------------|--------------|")
    for rank, (src, st) in enumerate(source_stats_sorted[:20], 1):
        score = value_scores.get(src, 0.0)
        cov   = global_cov.get(src, 0.0)
        bypass_tag = " ⚡" if src in bypass else ""
        lines.append(
            f"| {rank} | {src}{bypass_tag} | {st['count']} "
            f"| {len(st['entities_flat'])} | {cov:.0%} | {score:.3f} |"
        )
    lines.append("")

    # --- Recouvrements dirigés significatifs ---
    overlaps = analysis["directed_overlaps"]
    if overlaps:
        lines.append("---")
        lines.append(
            f"\n## 🔄 Recouvrements dirigés (couverture ≥ {SEUIL_COVERAGE_NOTABLE:.0%})\n"
        )
        lines.append(
            "_Pour chaque paire : % des entités de la source **minoritaire** "
            "déjà présentes dans la source **majoritaire**._\n"
        )
        lines.append(
            "| Couverture | Source majoritaire | Art. | "
            "Source minoritaire | Art. | Entités communes |"
        )
        lines.append("|------------|-------------------|------|------------------|------|-----------------|")
        for ov in overlaps[:40]:
            tag_big   = " ⚡" if ov["src_big"]   in bypass else ""
            tag_small = " ⚡" if ov["src_small"] in bypass else ""
            lines.append(
                f"| {ov['coverage']:.0%} | {ov['src_big']}{tag_big} | {ov['cnt_big']} "
                f"| {ov['src_small']}{tag_small} | {ov['cnt_small']} "
                f"| {ov['common']}/{ov['ent_small']} |"
            )
    lines.append("")

    # --- Sources avec forte couverture globale ---
    high_cov = [(src, st, global_cov.get(src, 0.0), value_scores.get(src, 0.0))
                for src, st in source_stats_sorted
                if global_cov.get(src, 0.0) >= 0.60 and src not in bypass]
    if high_cov:
        lines.append("---")
        lines.append("\n## 📊 Sources avec couverture globale ≥ 60%\n")
        lines.append(
            "_Ces sources ont ≥ 60 % de leurs entités déjà détectées "
            "par d'autres sources plus grandes._\n"
        )
        lines.append("| Source | Articles | Entités uniq. | Couv. globale | Score | Mots-clés |")
        lines.append("|--------|----------|---------------|---------------|-------|-----------|")
        for src, st, cov, score in sorted(high_cov, key=lambda x: -x[2]):
            kws = ", ".join(sorted(st["keywords_set"])[:4])
            lines.append(
                f"| {src} | {st['count']} | {len(st['entities_flat'])} "
                f"| {cov:.0%} | {score:.3f} | {kws} |"
            )
    lines.append("")

    # --- Sources à faible volume ---
    low_value = [(src, st, value_scores.get(src, 0.0))
                 for src, st in source_stats_sorted
                 if st["count"] <= SEUIL_ARTICLES_MOYEN and src not in bypass]
    if low_value:
        lines.append("---")
        lines.append(f"\n## ⚠️ Sources à faible volume (≤ {SEUIL_ARTICLES_MOYEN} articles)\n")
        lines.append("| Source | Articles | Entités uniq. | Couv. globale | Score |")
        lines.append("|--------|----------|---------------|---------------|-------|")
        for src, st, score in sorted(low_value, key=lambda x: x[1]["count"]):
            cov = global_cov.get(src, 0.0)
            lines.append(
                f"| {src} | {st['count']} | {len(st['entities_flat'])} "
                f"| {cov:.0%} | {score:.3f} |"
            )
    lines.append("")

    # --- Recommandations de suppression ---
    lines.append("---")
    lines.append("\n## 🗑️ Recommandations de suppression\n")
    lines.append("> Les flux bypassQuota sont **EXCLUS** de cette liste même s'ils remplissent les critères.\n")

    to_remove = {r for r in candidates if r not in bypass}
    never_detected = [f for f in analysis["feeds_no_articles"] if f["title"] not in bypass]
    weak_active    = [(src, st) for src, st in source_stats_sorted
                      if src in to_remove and src not in {f["title"] for f in never_detected}]

    lines.append(f"**Total recommandations : {len(never_detected) + len(weak_active)} flux**\n")

    if never_detected:
        lines.append(f"### 1. Flux OPML inactifs ({len(never_detected)} flux)\n")
        lines.append("_N'ont jamais contribué d'article → suppression sans risque._\n")
        for f in sorted(never_detected, key=lambda x: x["title"]):
            rsns = "; ".join(reasons.get(f["title"], ["Aucun article détecté"]))
            lines.append(f"- **{f['title']}**  \n  `{f['xmlUrl']}`  \n  _{rsns}_\n")

    if weak_active:
        lines.append(f"### 2. Sources actives à faible valeur ({len(weak_active)} sources)\n")
        lines.append(
            "Sources combinant faible volume d'articles **et/ou** fort recouvrement "
            "par des sources plus grandes.\n"
        )
        for src, st in sorted(weak_active, key=lambda x: x[1]["count"]):
            score    = value_scores.get(src, 0.0)
            cov      = global_cov.get(src, 0.0)
            rsns     = "; ".join(set(reasons.get(src, [])))
            feed_url = opml_by_title.get(src, {}).get("xmlUrl", "URL inconnue")
            kw_list  = ", ".join(f"{k} ({v})" for k, v in
                                  sorted(st["keywords"].items(), key=lambda x: -x[1])[:5])
            lines.append(
                f"- **{src}** — {st['count']} article(s) | couv. {cov:.0%} | score {score:.3f}  \n"
                f"  `{feed_url}`  \n"
                f"  Mots-clés : {kw_list or 'N/A'}  \n"
                f"  _{rsns}_\n"
            )

    # --- Tableau récapitulatif complet ---
    lines.append("---")
    lines.append("\n## 📋 Tableau complet (toutes sources actives)\n")
    lines.append(
        "| Source | Articles | Entités uniq. | Couv. globale | Score | bypassQuota | Candidat suppression |"
    )
    lines.append(
        "|--------|----------|---------------|---------------|-------|-------------|---------------------|"
    )
    for src, st in source_stats_sorted:
        score = value_scores.get(src, 0.0)
        cov   = global_cov.get(src, 0.0)
        bp    = "⚡ Oui" if src in bypass else "Non"
        cand  = "🗑️ Oui" if src in to_remove else "Non"
        lines.append(
            f"| {src} | {st['count']} | {len(st['entities_flat'])} "
            f"| {cov:.0%} | {score:.3f} | {bp} | {cand} |"
        )
    lines.append("")

    lines.append("---")
    lines.append(f"\n_Rapport généré le {today} par `scripts/analyse_rss_feeds.py`_")
    return "\n".join(lines)


# ===========================================================================
# main
# ===========================================================================
def main():
    print_console("=== Analyse des flux RSS WUDD.ai ===")

    # 1. Charger OPML
    print_console(f"Chargement OPML : {OPML_PATH}")
    feeds = load_opml_feeds(OPML_PATH)
    # Patch : ET ne supporte pas getparent() — on relit pour les catégories
    print_console(f"  → {len(feeds)} flux chargés ({sum(1 for f in feeds if f['bypassQuota'])} bypassQuota)")

    # 2. Charger articles
    print_console(f"Chargement articles depuis {RSS_DIR} …")
    articles = load_all_articles(RSS_DIR)
    print_console(f"  → {len(articles)} articles chargés")

    # 3. Stats par source
    print_console("Calcul des statistiques par source …")
    source_stats = compute_source_stats(articles)
    print_console(f"  → {len(source_stats)} sources distinctes trouvées dans les articles")

    # 4. Analyse
    print_console("Analyse des recouvrements et détection des flux à faible valeur …")
    analysis = analyse(feeds, source_stats)
    print_console(f"  → {len(analysis['feeds_no_articles'])} flux sans articles")
    print_console(f"  → {len(analysis['directed_overlaps'])} paires avec couverture dirigée ≥ {SEUIL_COVERAGE_NOTABLE:.0%}")
    print_console(f"  → {len(analysis['removal_candidates'])} candidats à la suppression")

    # 5. Rapport
    print_console("Génération du rapport Markdown …")
    rapport = generate_report(analysis, feeds)

    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    rapport_path = RAPPORT_DIR / f"rapport_rss_analyse_{ts}.md"
    rapport_path.write_text(rapport, encoding="utf-8")
    print_console(f"  → Rapport sauvegardé : {rapport_path}")

    # Afficher résumé console
    print()
    print("=" * 70)
    print("RÉSUMÉ")
    print("=" * 70)
    bypass = analysis["bypass_titles"]
    to_remove = {r for r in analysis["removal_candidates"] if r not in bypass}
    print(f"Flux OPML total            : {len(feeds)}")
    print(f"Sources actives            : {len(source_stats)}")
    print(f"Flux jamais actifs         : {len(analysis['feeds_no_articles'])}")
    print(f"Flux bypassQuota (protégés): {len(bypass)}")
    print(f"Candidats suppression      : {len(to_remove)}")
    print()

    # Afficher les recommandations dans le terminal
    never_detected = [f for f in analysis["feeds_no_articles"] if f["title"] not in bypass]
    weak_active    = [
        (src, source_stats[src])
        for src in to_remove
        if src not in [f["title"] for f in never_detected]
    ]

    if never_detected:
        print("→ Flux inactifs (jamais d'article) :")
        for f in sorted(never_detected, key=lambda x: x["title"]):
            print(f"   - {f['title']}")

    if weak_active:
        print(f"\n→ Sources actives faible valeur :")
        for src, st in sorted(weak_active, key=lambda x: x[1]["count"]):
            rsns = " | ".join(analysis["removal_reasons"].get(src, []))
            print(f"   - {src} ({st['count']} art.) — {rsns}")

    print()
    print(f"Rapport complet : {rapport_path}")
    return str(rapport_path)


if __name__ == "__main__":
    main()
