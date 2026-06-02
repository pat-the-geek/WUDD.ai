#!/usr/bin/env python3
"""
cluster_articles.py — Clustering thématique des articles par entités et mots-clés

Regroupe les articles en clusters thématiques en utilisant les entités nommées
comme features principales (pas de dépendance scikit-learn nécessaire).

Algorithme : clustering greedy par co-entité (simple, sans dépendances externes)
  1. Extrait les entités de chaque article
  2. Calcule la similarité Jaccard entre articles (intersection/union d'entités)
  3. Regroupe les articles dont la similarité Jaccard > seuil

Usage:
    python3 scripts/cluster_articles.py [--days N] [--min-size N] [--output FILE]
"""

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
sys.path.insert(0, str(_PROJECT_ROOT))

try:
    from utils.logging import print_console
except ImportError:
    def print_console(msg, level="info"):
        print(f"[{level.upper()}] {msg}")

from utils.date_utils import parse_article_date


ENTITY_TYPES = {"PERSON", "ORG", "GPE", "PRODUCT", "EVENT", "NORP", "LOC"}

# Thématiques issues des entités dominantes
THEMATIC_KEYWORDS = {
    "Intelligence artificielle": {"openai", "chatgpt", "mistral", "gemini", "claude", "llm", "gpt", "ia", "ai", "deepmind", "anthropic"},
    "Géopolitique": {"ukraine", "russie", "chine", "états-unis", "otan", "onu", "poutine", "zelensky", "biden", "trump", "gaza", "israël"},
    "Économie": {"inflation", "taux", "banque", "bce", "fed", "bourse", "pib", "récession", "euro", "dollar", "budget"},
    "Technologie": {"apple", "google", "microsoft", "amazon", "meta", "nvidia", "samsung", "chip", "processeur"},
    "Santé": {"vaccin", "cancer", "covid", "médecin", "hôpital", "oms", "pandémie", "traitement", "médicament"},
    "Environnement": {"climat", "cop", "carbone", "énergie", "nucléaire", "renouvelable", "pollution", "biodiversité"},
    "Politique française": {"macron", "lepen", "mélenchon", "gouvernement", "assemblée", "sénat", "élection", "premier ministre"},
    "Sports": {"foot", "football", "ligue", "champions", "tennis", "cyclisme", "jo", "olympique", "nba"},
}


def _parse_date(date_str: str):
    """Datetime UTC (tz-aware) ou None — corpus mixte ISO 8601 / DD/MM/YYYY / RFC 2822."""
    dt = parse_article_date(date_str or "")
    return dt.replace(tzinfo=timezone.utc) if dt is not None else None


def load_articles(project_root: Path, days: int = 7) -> list[dict]:
    """Charge les articles des N derniers jours depuis data/."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    articles = []
    seen_urls = set()

    for data_dir in [project_root / "data" / "articles", project_root / "data" / "articles-from-rss"]:
        if not data_dir.exists():
            continue
        for json_file in data_dir.rglob("*.json"):
            if "cache" in str(json_file):
                continue
            try:
                arts = json.loads(json_file.read_text(encoding="utf-8", errors="replace"))
                if not isinstance(arts, list):
                    continue
            except (json.JSONDecodeError, OSError):
                continue

            for art in arts:
                url = art.get("URL", "")
                if url and url in seen_urls:
                    continue
                if url:
                    seen_urls.add(url)
                dt = _parse_date(art.get("Date de publication", ""))
                if dt and dt < cutoff:
                    continue
                articles.append(art)

    return articles


def extract_entity_set(article: dict) -> frozenset:
    """Retourne l'ensemble des entités normalisées d'un article."""
    ents = article.get("entities", {})
    if not isinstance(ents, dict):
        return frozenset()
    result = set()
    for etype, vals in ents.items():
        if etype not in ENTITY_TYPES:
            continue
        if not isinstance(vals, list):
            continue
        for v in vals:
            if isinstance(v, str) and len(v.strip()) >= 3:
                result.add(v.strip().lower())
    return frozenset(result)


def detect_thematic(entity_set: frozenset, resume: str) -> str:
    """Détecte la thématique dominante d'un article."""
    resume_lower = (resume or "").lower()
    scores = {}
    for theme, keywords in THEMATIC_KEYWORDS.items():
        # Score = entités matchantes + mots du résumé
        entity_score = len(entity_set & keywords)
        text_score = sum(1 for kw in keywords if kw in resume_lower)
        total = entity_score * 2 + text_score
        if total > 0:
            scores[theme] = total
    return max(scores, key=scores.get) if scores else "Autre"


def cluster_articles(articles: list[dict], min_similarity: float = 0.15) -> list[dict]:
    """
    Clustering greedy par co-entités.
    Retourne une liste de clusters [{theme, articles, top_entities}].
    """
    # 1. Préparer les features de chaque article
    features = [(a, extract_entity_set(a)) for a in articles]

    # 2. Regrouper d'abord par thématique détectée
    thematic_groups: dict[str, list] = defaultdict(list)
    for art, ents in features:
        theme = detect_thematic(ents, art.get("Résumé", ""))
        thematic_groups[theme].append((art, ents))

    # 3. Pour chaque thématique, compter les entités les plus fréquentes
    clusters = []
    for theme, group in thematic_groups.items():
        entity_counts: dict[str, int] = defaultdict(int)
        for _, ents in group:
            for e in ents:
                entity_counts[e] += 1

        top_entities = sorted(entity_counts.items(), key=lambda x: x[1], reverse=True)[:10]

        cluster_articles_list = []
        for art, _ in sorted(
            group,
            key=lambda x: _parse_date(x[0].get("Date de publication", "")) or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )[:20]:
            cluster_articles_list.append({
                "Date de publication": art.get("Date de publication", ""),
                "Sources": art.get("Sources", ""),
                "URL": art.get("URL", ""),
                "Résumé": (art.get("Résumé") or "")[:300],
                "sentiment": art.get("sentiment", ""),
                "score_pertinence": art.get("score_pertinence"),
            })

        clusters.append({
            "theme": theme,
            "count": len(group),
            "top_entities": [{"value": v, "count": c} for v, c in top_entities],
            "articles": cluster_articles_list,
        })

    # Trier par nombre d'articles décroissant
    clusters.sort(key=lambda c: c["count"], reverse=True)
    return clusters


def main():
    parser = argparse.ArgumentParser(description="Clustering thématique des articles WUDD.ai")
    parser.add_argument("--days", type=int, default=7, help="Fenêtre temporelle en jours (défaut: 7)")
    parser.add_argument("--min-size", type=int, default=2, help="Taille minimale d'un cluster (défaut: 2)")
    parser.add_argument("--output", type=str, default=None, help="Fichier de sortie JSON (défaut: stdout)")
    parser.add_argument("--dry-run", action="store_true", help="Affiche sans sauvegarder")
    args = parser.parse_args()

    print_console(f"Clustering des articles des {args.days} derniers jours…")
    articles = load_articles(_PROJECT_ROOT, days=args.days)
    print_console(f"{len(articles)} articles chargés")

    clusters = cluster_articles(articles)
    clusters = [c for c in clusters if c["count"] >= args.min_size]
    print_console(f"{len(clusters)} clusters détectés")

    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window_days": args.days,
        "total_articles": len(articles),
        "clusters": clusters,
    }

    output = json.dumps(result, ensure_ascii=False, indent=2)

    if args.dry_run or not args.output:
        print(output[:3000])
        if len(output) > 3000:
            print(f"\n[...tronqué — {len(output)} chars au total]")
        return

    out_file = Path(args.output) if args.output else _PROJECT_ROOT / "data" / "clusters.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(output, encoding="utf-8")
    print_console(f"Résultats sauvegardés : {out_file}")


if __name__ == "__main__":
    main()
