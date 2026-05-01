"""scripts/detect_narrative_propagation.py — Détection de la propagation
de narratifs entre sources d'actualités.

Pour chaque entité/thème, identifie :
- La source qui a publié un fait en premier
- Les sources qui ont repris ce fait (propagation)
- Le délai de propagation (en heures)
- Le score de viralité (nb sources × vitesse de propagation)

Usage :
  python3 scripts/detect_narrative_propagation.py
  python3 scripts/detect_narrative_propagation.py --entity "OpenAI" --days 14
  python3 scripts/detect_narrative_propagation.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
import sys
sys.path.insert(0, str(PROJECT_ROOT))

from utils.logging import print_console


# ── Constantes ────────────────────────────────────────────────────────────────

OUTPUT_FILE = PROJECT_ROOT / "data" / "narrative_propagation.json"

# Seuil de similarité Jaccard pour considérer deux résumés comme couvrant le même fait
JACCARD_THRESHOLD = 0.25

# Fenêtre de temps pour grouper les articles couvrant le même narratif (en heures)
PROPAGATION_WINDOW_HOURS = 72


# ── Chargement articles ───────────────────────────────────────────────────────

def _load_all_articles(project_root: Path, days: int = 14) -> list[dict]:
    """Charge tous les articles des derniers `days` jours depuis data/."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    articles: list[dict] = []

    # data/articles/<flux>/
    articles_dir = project_root / "data" / "articles"
    if articles_dir.exists():
        for json_file in articles_dir.rglob("*.json"):
            if "cache" in json_file.parts:
                continue
            try:
                data = json.loads(json_file.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    for art in data:
                        art["_file"] = str(json_file)
                    articles.extend(data)
            except Exception:
                pass

    # data/articles-from-rss/<keyword>.json
    rss_dir = project_root / "data" / "articles-from-rss"
    if rss_dir.exists():
        for json_file in rss_dir.glob("*.json"):
            try:
                data = json.loads(json_file.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    for art in data:
                        art["_file"] = str(json_file)
                    articles.extend(data)
            except Exception:
                pass

    # Filtrer par date
    def _parse_date(art: dict) -> datetime | None:
        raw = art.get("Date de publication", "")
        from utils.date_utils import parse_date
        try:
            return parse_date(raw)
        except Exception:
            return None

    result = []
    for art in articles:
        d = _parse_date(art)
        if d is None:
            continue
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        if d >= cutoff:
            art["_parsed_date"] = d
            result.append(art)

    return result


# ── Extraction de n-grammes ───────────────────────────────────────────────────

def _ngrams(text: str, n: int = 3) -> set[str]:
    words = re.sub(r"[^\w\s]", "", text.lower()).split()
    if len(words) < n:
        return set(words)
    return {" ".join(words[i:i+n]) for i in range(len(words) - n + 1)}


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


# ── Groupement en narratifs ───────────────────────────────────────────────────

def _group_by_narrative(articles: list[dict], entity_filter: str | None = None) -> list[list[dict]]:
    """Groupe les articles couvrant le même narratif (par similarité de résumés).

    Si entity_filter est fourni, ne conserve que les articles mentionnant cette entité.
    """
    candidates = []
    for art in articles:
        resume = art.get("Résumé", "") or ""
        if len(resume) < 80:
            continue
        if entity_filter:
            # Vérifier présence dans entités ou dans le résumé
            ents = art.get("entities", {})
            all_ents = [v for vals in ents.values() for v in (vals if isinstance(vals, list) else [])]
            match_ent = any(entity_filter.lower() in e.lower() for e in all_ents)
            match_text = entity_filter.lower() in resume.lower()
            if not match_ent and not match_text:
                continue
        art["_ngrams"] = _ngrams(resume, n=3)
        candidates.append(art)

    if not candidates:
        return []

    # Trier par date croissante
    candidates.sort(key=lambda a: a["_parsed_date"])

    # Clustering glouton : chaque article est assigné au premier groupe
    # dont le représentant est suffisamment similaire ET dans la fenêtre temporelle
    clusters: list[list[dict]] = []
    representative_ngrams: list[set] = []
    representative_dates: list[datetime] = []

    for art in candidates:
        assigned = False
        for idx, (rep_ngrams, rep_date) in enumerate(zip(representative_ngrams, representative_dates)):
            time_diff = (art["_parsed_date"] - rep_date).total_seconds() / 3600
            if time_diff > PROPAGATION_WINDOW_HOURS:
                continue
            sim = _jaccard(art["_ngrams"], rep_ngrams)
            if sim >= JACCARD_THRESHOLD:
                clusters[idx].append(art)
                # Mettre à jour le représentant avec l'union des n-grammes
                representative_ngrams[idx] |= art["_ngrams"]
                assigned = True
                break
        if not assigned:
            clusters.append([art])
            representative_ngrams.append(set(art["_ngrams"]))
            representative_dates.append(art["_parsed_date"])

    # Ne garder que les clusters avec au moins 2 sources différentes
    multi = []
    for cluster in clusters:
        sources = {art.get("Sources", "") for art in cluster}
        if len(sources) >= 2:
            multi.append(cluster)

    return multi


# ── Analyse de propagation ────────────────────────────────────────────────────

def _analyse_cluster(cluster: list[dict]) -> dict:
    """Calcule les stats de propagation pour un cluster d'articles."""
    cluster.sort(key=lambda a: a["_parsed_date"])
    first = cluster[0]
    first_source = first.get("Sources", "Inconnu")
    first_date = first["_parsed_date"]

    propagated_by = []
    for art in cluster[1:]:
        source = art.get("Sources", "Inconnu")
        delay_hours = round((art["_parsed_date"] - first_date).total_seconds() / 3600, 1)
        propagated_by.append({
            "source": source,
            "date": art["_parsed_date"].isoformat(),
            "url": art.get("URL", ""),
            "delay_hours": delay_hours,
        })

    # Titre indicatif = premiers mots du résumé du premier article
    titre = (first.get("Résumé", "") or "")[:120].replace("\n", " ") + "…"

    # Score de viralité : nb_sources × (1 / délai_moyen en heures + 1)
    delays = [p["delay_hours"] for p in propagated_by] or [0]
    avg_delay = sum(delays) / len(delays)
    viral_score = round(len(propagated_by) / (avg_delay / 24 + 1), 2)

    return {
        "titre": titre,
        "first_source": first_source,
        "first_date": first_date.isoformat(),
        "first_url": first.get("URL", ""),
        "propagated_by": propagated_by,
        "nb_sources": 1 + len(propagated_by),
        "avg_delay_hours": round(avg_delay, 1),
        "viral_score": viral_score,
    }


# ── Fonction principale ───────────────────────────────────────────────────────

def detect_narrative_propagation(
    project_root: Path,
    entity: str | None = None,
    days: int = 14,
    dry_run: bool = False,
) -> list[dict]:
    """Détecte la propagation de narratifs et sauvegarde le résultat.

    Returns:
        Liste des narratifs avec leurs stats de propagation, triée par viral_score décroissant.
    """
    print_console(f"Chargement des articles ({days}j)…")
    articles = _load_all_articles(project_root, days=days)
    print_console(f"{len(articles)} articles chargés")

    print_console(f"Groupement en narratifs" + (f" pour '{entity}'" if entity else "") + "…")
    clusters = _group_by_narrative(articles, entity_filter=entity)
    print_console(f"{len(clusters)} narratifs multi-sources détectés")

    results = []
    for cluster in clusters:
        analysis = _analyse_cluster(cluster)
        results.append(analysis)

    # Trier par viral_score décroissant
    results.sort(key=lambda r: r["viral_score"], reverse=True)

    if not dry_run:
        output = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "days_window": days,
            "entity_filter": entity,
            "narratives_count": len(results),
            "narratives": results,
        }
        OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_FILE.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
        print_console(f"Résultats sauvegardés → {OUTPUT_FILE}")
    else:
        print_console(f"[dry-run] {len(results)} narratifs (non sauvegardés)")

    return results


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Détection propagation narratifs")
    parser.add_argument("--entity", default=None, help="Filtrer par entité/mot-clé")
    parser.add_argument("--days", type=int, default=14, help="Fenêtre temporelle en jours (défaut: 14)")
    parser.add_argument("--dry-run", action="store_true", help="Ne pas écrire le fichier de sortie")
    args = parser.parse_args()

    narratives = detect_narrative_propagation(
        project_root=PROJECT_ROOT,
        entity=args.entity,
        days=args.days,
        dry_run=args.dry_run,
    )

    if narratives:
        print_console(f"\nTop 5 narratifs les plus viraux :")
        for i, n in enumerate(narratives[:5], 1):
            print_console(f"  {i}. [{n['viral_score']:.1f}] {n['first_source']} → "
                          f"{n['nb_sources']-1} sources | "
                          f"délai moyen {n['avg_delay_hours']}h | "
                          f"{n['titre'][:80]}…")


if __name__ == "__main__":
    main()
