#!/usr/bin/env python3
"""Détection de contradictions entre sources sur le même événement.

Usage :
  # Analyse depuis un article spécifique (mode viewer — logs stdout pour SSE)
  python3 scripts/detect_contradictions.py --article <url>

  # Analyse globale (fenêtre glissante, cron nocturne)
  python3 scripts/detect_contradictions.py [--days 2] [--flux NOM] [--dry-run]
"""

import argparse
import hashlib
import json
import re
import sys
import time
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path

# ── Path resolution ───────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Rediriger les logs Python (INFO/DEBUG) vers stderr
# → seul stdout (notre log()) est capturé par le SSE du viewer
import logging
logging.basicConfig(stream=sys.stderr, level=logging.INFO)

from utils.config import get_config
from utils.api_client import get_ai_client
from utils.claim_extractor import extract_claims
from utils.contradiction_engine import compare_claims_deterministic, arbitrate_with_llm

# ── Constantes ────────────────────────────────────────────────────────────────
JACCARD_CLUSTER_THRESHOLD = 0.45   # seuil BAS : grouper, pas exclure
MIN_COMMON_ENTITIES = 2            # entités ORG/PERSON/GPE minimum en commun
DATE_WINDOW_DAYS = 3               # fenêtre ±jours
MIN_SCORE_CONFIANCE = 0.55         # seuil minimum pour sauvegarder

_STOPWORDS = frozenset([
    "le", "la", "les", "un", "une", "des", "du", "de", "et", "en",
    "au", "aux", "que", "qui", "se", "sa", "son", "ses", "ce", "cet",
    "cette", "ces", "par", "sur", "pour", "dans", "avec", "à", "il",
    "elle", "ils", "elles", "on", "nous", "vous", "je", "tu",
    "the", "a", "an", "of", "in", "to", "and", "is", "it",
])


# ── Logging stdout (capturé par SSE) ─────────────────────────────────────────

def log(msg: str) -> None:
    """Écrit sur stdout sans buffer — capturé en temps réel par Flask SSE."""
    print(msg, flush=True)


# ── Helpers similarité ────────────────────────────────────────────────────────

def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", errors="ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _bigrams(text: str) -> frozenset:
    tokens = [w for w in _normalize(text).split() if w not in _STOPWORDS and len(w) > 1]
    if len(tokens) < 2:
        return frozenset()
    return frozenset(zip(tokens[:-1], tokens[1:]))


def _content_words(text: str) -> set:
    """Mots de contenu significatifs (>4 chars, hors stopwords).
    Résistant au bilinguisme FR/EN : même sujet = mots propres communs.
    Ex: "villeneuve", "chalamet", "trailer", "partie" → même article Dune 3.
    """
    return {w for w in _normalize(text).split()
            if len(w) > 4 and w not in _STOPWORDS}


def jaccard(text_a: str, text_b: str) -> float:
    bg_a = _bigrams(text_a)
    bg_b = _bigrams(text_b)
    if not bg_a or not bg_b:
        return 0.0
    inter = len(bg_a & bg_b)
    union = len(bg_a | bg_b)
    return inter / union if union > 0 else 0.0


# ── Chargement des articles ───────────────────────────────────────────────────

def _parse_date(raw: str) -> datetime | None:
    if not raw:
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(raw[:19], fmt)
        except ValueError:
            continue
    return None


def load_articles(days: int = 3, flux: str | None = None) -> list[dict]:
    """Charge tous les articles des N derniers jours depuis data/."""
    config = get_config()
    cutoff = datetime.now() - timedelta(days=days + DATE_WINDOW_DAYS)

    articles = []
    dirs = []
    if flux:
        flux_dir = config.data_articles_dir / flux
        if flux_dir.exists():
            dirs.append(flux_dir)
    else:
        if config.data_articles_dir.exists():
            dirs += [d for d in config.data_articles_dir.iterdir() if d.is_dir()]
        rss_dir = config.project_root / "data" / "articles-from-rss"
        if rss_dir.exists():
            dirs.append(rss_dir)

    for d in dirs:
        for f in d.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                if not isinstance(data, list):
                    continue
                for art in data:
                    if not isinstance(art, dict):
                        continue
                    d_pub = _parse_date(art.get("Date de publication", ""))
                    if d_pub and d_pub < cutoff:
                        continue
                    art["_source_file"] = str(f)
                    articles.append(art)
            except Exception:
                continue

    return articles


def find_article_by_url(url: str) -> dict | None:
    """Trouve un article par son URL dans tous les fichiers JSON."""
    config = get_config()
    for pattern in ["data/articles/**/*.json", "data/articles-from-rss/*.json"]:
        for f in config.project_root.glob(pattern):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                if not isinstance(data, list):
                    continue
                for art in data:
                    if isinstance(art, dict) and art.get("URL") == url:
                        art["_source_file"] = str(f)
                        return art
            except Exception:
                continue
    return None


# ── Clustering par événement ──────────────────────────────────────────────────

def _common_entities(art_a: dict, art_b: dict) -> int:
    """Nombre d'entités ORG/PERSON/GPE en commun entre deux articles."""
    ent_a = set()
    ent_b = set()
    for etype in ("ORG", "PERSON", "GPE"):
        ent_a.update(art_a.get("entities", {}).get(etype, []))
        ent_b.update(art_b.get("entities", {}).get(etype, []))
    if not ent_a or not ent_b:
        return 0
    return len(ent_a & ent_b)


def _has_entities(article: dict) -> bool:
    """Retourne True si l'article a au moins une entité NER enrichie."""
    ents = article.get("entities", {})
    if not ents:
        return False
    return any(len(v) > 0 for v in ents.values() if isinstance(v, list))


MIN_CONTENT_WORDS = 4   # mots de contenu communs suffisants pour cluster sans NER


def build_cluster(reference: dict, candidates: list[dict]) -> tuple[list[dict], dict]:
    """Retourne les articles candidats formant un cluster avec l'article de référence.

    Filtres (appliqués en séquence) :
      1. Fenêtre temporelle ±DATE_WINDOW_DAYS
      2. Sources différentes
      3a. Si NER disponible sur les deux articles : ≥ MIN_COMMON_ENTITIES entités communes
      3b. Si NER absent : clustering par similarité uniquement
      4. Jaccard ≥ seuil   OU   mots de contenu communs ≥ MIN_CONTENT_WORDS
         Le 2e critère est résistant au bilinguisme FR/EN (noms propres, termes techniques).

    Retourne : (cluster, stats) où stats contient les compteurs de rejet pour diagnostic.
    """
    ref_date    = _parse_date(reference.get("Date de publication", ""))
    ref_resume  = reference.get("Résumé", "")
    ref_source  = reference.get("Sources", "")
    ref_has_ner = _has_entities(reference)
    ref_cw      = _content_words(ref_resume)

    cluster = []
    stats = {
        "total": 0, "meme_source": 0, "hors_fenetre": 0,
        "entites_insuffisantes": 0, "similarite_trop_faible": 0,
        "retenus": 0, "top_scores": [],
    }

    for art in candidates:
        if art.get("URL") == reference.get("URL"):
            continue
        stats["total"] += 1

        # Filtre : même source
        if art.get("Sources") == ref_source:
            stats["meme_source"] += 1
            continue

        # Filtre temporel
        art_date = _parse_date(art.get("Date de publication", ""))
        if ref_date and art_date:
            if abs((ref_date - art_date).days) > DATE_WINDOW_DAYS:
                stats["hors_fenetre"] += 1
                continue

        art_resume  = art.get("Résumé", "")
        art_has_ner = _has_entities(art)

        # Filtre entités — uniquement si les deux articles sont enrichis NER
        ner_ok = False
        if ref_has_ner and art_has_ner:
            if _common_entities(reference, art) < MIN_COMMON_ENTITIES:
                stats["entites_insuffisantes"] += 1
                continue
            ner_ok = True

        # Critère 1 : Jaccard sur bigrammes
        jac = jaccard(ref_resume, art_resume)

        # Critère 2 : mots de contenu communs (résistant au bilinguisme FR/EN)
        art_cw = _content_words(art_resume)
        common_cw = ref_cw & art_cw

        threshold = JACCARD_CLUSTER_THRESHOLD if ner_ok else 0.35
        passes_jaccard = jac >= threshold
        passes_keywords = len(common_cw) >= MIN_CONTENT_WORDS

        # Conserver les meilleurs scores pour le log de diagnostic
        if jac > 0.10 or len(common_cw) >= 2:
            stats["top_scores"].append({
                "source": art.get("Sources", "—"),
                "jaccard": round(jac, 2),
                "mots_communs": len(common_cw),
                "exemples_mots": sorted(common_cw)[:4],
            })

        if not passes_jaccard and not passes_keywords:
            stats["similarite_trop_faible"] += 1
            continue

        match_type = "NER+Jaccard" if ner_ok else ("Jaccard" if passes_jaccard else "keywords")
        art["_jaccard_score"] = round(jac, 2)
        art["_common_words"]  = len(common_cw)
        art["_match_type"]    = match_type
        stats["retenus"] += 1
        cluster.append(art)

    # Trier les top_scores pour le diagnostic
    stats["top_scores"] = sorted(
        stats["top_scores"], key=lambda x: (x["jaccard"], x["mots_communs"]), reverse=True
    )[:5]

    return cluster, stats


# ── NER à la volée ────────────────────────────────────────────────────────────

def _enrich_ner_on_demand(article: dict) -> dict:
    """Calcule les entités NER d'un article via l'API IA sans sauvegarder.
    Utilisé quand l'enrichissement nocturne n'a pas encore tourné.
    """
    try:
        client = get_ai_client()
        resume = article.get("Résumé", "")
        if not resume:
            return article
        entities = client.generate_entities(resume)
        if entities and isinstance(entities, dict):
            article = dict(article)   # copie — ne pas modifier l'original en mémoire
            article["entities"] = entities
    except Exception:
        pass
    return article


def _format_entities(article: dict) -> str:
    """Résumé lisible des entités NER pour le log."""
    ents = article.get("entities", {})
    parts = []
    for etype in ("PERSON", "ORG", "GPE"):
        vals = ents.get(etype, [])
        if vals:
            parts.append(f"{etype}: {', '.join(vals[:3])}")
    return " · ".join(parts) if parts else "aucune entité détectée"


# ── Pipeline principal ────────────────────────────────────────────────────────

def _contradiction_id(url_a: str, url_b: str, ctype: str) -> str:
    key = f"{min(url_a, url_b)}|{max(url_a, url_b)}|{ctype}"
    return "c_" + hashlib.md5(key.encode()).hexdigest()[:10]


def detect_for_article(reference: dict, all_articles: list[dict], dry_run: bool = False) -> list[dict]:
    """Détecte les contradictions entre un article de référence et son cluster."""
    _start = time.time()

    def ts() -> str:
        """Timestamp MM:SS réel depuis le début de l'analyse."""
        s = int(time.time() - _start)
        return f"[{s // 60:02d}:{s % 60:02d}]"

    ref_url    = reference.get("URL", "")
    ref_source = reference.get("Sources", "—")
    ref_resume = reference.get("Résumé", "")

    log(f"{ts()} ⚖️  Analyse de contradictions")
    log(f"{ts()}     Source  : {ref_source}")
    log(f"{ts()}     URL     : {ref_url[:80]}{'…' if len(ref_url) > 80 else ''}")

    # ── Étape 1 : cluster ────────────────────────────────────────────────────
    log(f"{ts()} ────────────────────────────────────────")
    log(f"{ts()} 🗂️  {len(all_articles)} articles dans la fenêtre")

    cluster, stats = build_cluster(reference, all_articles)

    ref_has_ner = _has_entities(reference)
    if not ref_has_ner:
        log(f"{ts()} ℹ️  NER absent sur cet article — calcul à la volée…")
        reference = _enrich_ner_on_demand(reference)
        ref_has_ner = _has_entities(reference)
        if ref_has_ner:
            log(f"{ts()} ✓  NER calculé : {_format_entities(reference)}")
            cluster, stats = build_cluster(reference, all_articles)
        else:
            log(f"{ts()} ℹ️  NER indisponible — mode similarité textuelle seule")

    if not cluster:
        log(f"{ts()} ℹ️  Aucun article du même cluster trouvé")
        log(f"{ts()}     Diagnostic : {stats['total']} candidats analysés")
        log(f"{ts()}       · {stats['hors_fenetre']} hors fenêtre temporelle")
        log(f"{ts()}       · {stats['entites_insuffisantes']} entités insuffisantes")
        log(f"{ts()}       · {stats['similarite_trop_faible']} similarité trop faible")
        if stats["top_scores"]:
            log(f"{ts()}     Scores les plus proches :")
            for s in stats["top_scores"][:3]:
                log(f"{ts()}       · {s['source']} — Jaccard {s['jaccard']} · {s['mots_communs']} mots {s['exemples_mots']}")
        elapsed = int(time.time() - _start)
        log(f"{ts()} ────────────────────────────────────────")
        log(f"{ts()} ✅ Analyse terminée en {elapsed}s — aucune contradiction à signaler")
        for _ in range(14):
            log("")
        return []

    ner_note = "" if ref_has_ner else " — mode similarité"
    log(f"{ts()} 🔗 {len(cluster)} article(s) dans le cluster événementiel{ner_note} :")
    for a in cluster:
        log(f"{ts()}       · {a.get('Sources', '—')} (Jaccard {a['_jaccard_score']} · {a['_common_words']} mots · {a['_match_type']})")

    # ── Étape 2 : extraction claims ──────────────────────────────────────────
    log(f"{ts()} ────────────────────────────────────────")
    log(f"{ts()} 📝 Extraction des claims factuels via l'API IA…")

    log(f"{ts()}    Référence — {ref_source}…")
    ref_claims = extract_claims(ref_resume, ref_source)
    types_ref = [c["type"] for c in ref_claims]
    log(f"{ts()} ✓  {len(ref_claims)} claim(s) : {', '.join(set(types_ref)) or 'aucun'}")

    cluster_claims: list[tuple[dict, list[dict]]] = []
    for i, art in enumerate(cluster, 1):
        src = art.get("Sources", "—")
        log(f"{ts()}    [{i}/{len(cluster)}] {src}…")
        claims = extract_claims(art.get("Résumé", ""), src)
        types = [c["type"] for c in claims]
        log(f"{ts()} ✓  {len(claims)} claim(s) : {', '.join(set(types)) or 'aucun'}")
        cluster_claims.append((art, claims))

    # ── Étape 3 : comparaison ────────────────────────────────────────────────
    log(f"{ts()} ────────────────────────────────────────")
    log(f"{ts()} ⚖️  Comparaison des claims ({len(cluster)} paire(s))…")

    contradictions = []
    llm_needed = []

    for art_b, claims_b in cluster_claims:
        for ca in ref_claims:
            for cb in claims_b:
                result = compare_claims_deterministic(ca, cb)
                if result:
                    log(f"{ts()} ⚠️  {result['type']} : {result['description']}")
                    contradictions.append(_build_contradiction(
                        reference, art_b, ca, cb, result
                    ))
                else:
                    if ca.get("sujet") and cb.get("sujet"):
                        s_a = ca["sujet"].lower()
                        s_b = cb["sujet"].lower()
                        if s_a in s_b or s_b in s_a:
                            llm_needed.append((art_b, ca, cb))

    # Passe LLM sur les cas ambigus
    if llm_needed:
        log(f"{ts()}    Passe 2 — arbitrage LLM ({len(llm_needed)} cas ambigu(s))…")
        for art_b, ca, cb in llm_needed[:5]:
            log(f"{ts()}    ⏳ Arbitrage {reference.get('Sources','A')} ↔ {art_b.get('Sources','B')}…")
            result = arbitrate_with_llm(reference, art_b, ca, cb)
            if result and result.get("score_confiance", 0) >= MIN_SCORE_CONFIANCE:
                log(f"{ts()} ✓  Contradiction confirmée (confiance {result['score_confiance']:.0%})")
                contradictions.append(_build_contradiction(
                    reference, art_b, ca, cb, result
                ))

    # ── Résumé final ─────────────────────────────────────────────────────────
    elapsed = int(time.time() - _start)
    log(f"{ts()} ────────────────────────────────────────")
    log(f"{ts()} ✅ Analyse terminée en {elapsed}s")
    log(f"{ts()}")
    log(f"{ts()} RÉSULTAT")

    if contradictions:
        for c in contradictions:
            emoji = "🚨" if c["score_confiance"] >= 0.80 else "⚠️"
            log(f"{ts()}   {emoji} {c['type_contradiction']} · confiance {c['score_confiance']:.0%}")
    else:
        log(f"{ts()}   ✓  Aucune contradiction détectée entre les sources")

    for _ in range(14):
        log("")

    return contradictions


def _build_contradiction(art_a: dict, art_b: dict, claim_a: dict, claim_b: dict, result: dict) -> dict:
    url_a = art_a.get("URL", "")
    url_b = art_b.get("URL", "")
    ctype = result.get("type", "AUTRE")
    score = result.get("score_confiance", 0.5)

    # Source probable selon arbitrage ou score_source
    source_probable = result.get("source_probable", "INCONNUE")
    if source_probable == "A":
        source_probable = art_a.get("Sources", "Source A")
    elif source_probable == "B":
        source_probable = art_b.get("Sources", "Source B")

    return {
        "id": _contradiction_id(url_a, url_b, ctype),
        "detected_at": datetime.now().isoformat(),
        "type_contradiction": ctype,
        "description": result.get("description", ""),
        "score_confiance": round(score, 2),
        "source_probable": source_probable,
        "justification": result.get("justification", ""),
        "articles_en_conflit": [
            {
                "url": url_a,
                "source": art_a.get("Sources", ""),
                "score_source": art_a.get("score_source", 0),
                "date": art_a.get("Date de publication", ""),
                "claim": claim_a.get("claim", ""),
                "valeur": claim_a.get("valeur", ""),
            },
            {
                "url": url_b,
                "source": art_b.get("Sources", ""),
                "score_source": art_b.get("score_source", 0),
                "date": art_b.get("Date de publication", ""),
                "claim": claim_b.get("claim", ""),
                "valeur": claim_b.get("valeur", ""),
            },
        ],
        "entites_concernees": list(set(
            art_a.get("entities", {}).get("ORG", [])[:3] +
            art_a.get("entities", {}).get("PERSON", [])[:2]
        )),
    }


def save_contradictions(new_items: list[dict], dry_run: bool = False) -> None:
    """Ajoute les nouvelles contradictions à data/contradictions.json (dédup par id)."""
    if dry_run or not new_items:
        return
    config = get_config()
    out_path = config.project_root / "data" / "contradictions.json"

    existing = []
    if out_path.exists():
        try:
            existing = json.loads(out_path.read_text(encoding="utf-8"))
            if not isinstance(existing, list):
                existing = []
        except Exception:
            existing = []

    existing_ids = {c.get("id") for c in existing}
    added = [c for c in new_items if c.get("id") not in existing_ids]
    if not added:
        return

    merged = added + existing
    # Garder les 500 plus récentes
    merged = sorted(merged, key=lambda c: c.get("detected_at", ""), reverse=True)[:500]

    tmp = out_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(out_path)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Détection de contradictions entre sources")
    parser.add_argument("--article", help="URL de l'article de référence (mode viewer)")
    parser.add_argument("--days", type=int, default=2, help="Fenêtre temporelle en jours (défaut: 2)")
    parser.add_argument("--flux", help="Restreindre à un flux spécifique")
    parser.add_argument("--dry-run", action="store_true", help="Analyse sans sauvegarder")
    args = parser.parse_args()

    # Identifier le fournisseur IA
    try:
        from utils.config import get_config as _gc
        cfg = _gc()
        provider = getattr(cfg, "ai_provider", "euria").lower()
        provider_label = "Claude (Anthropic)" if provider == "claude" else "EurIA (Qwen/Qwen3.5-122B-A10B-FP8)"
    except Exception:
        provider_label = "EurIA (Qwen/Qwen3.5-122B-A10B-FP8)"

    log(f"[00:00]     Fournisseur IA : {provider_label}")
    log(f"[00:00]     Durée estimée  : 40–70 secondes (NER à la volée si absent)")

    all_articles = load_articles(days=args.days + DATE_WINDOW_DAYS, flux=args.flux)

    if args.article:
        # Mode article spécifique (depuis le viewer)
        ref = find_article_by_url(args.article)
        if not ref:
            log(f"[00:01] ✗ Article introuvable pour l'URL : {args.article}")
            sys.exit(1)
        results = detect_for_article(ref, all_articles, dry_run=args.dry_run)
        save_contradictions(results, dry_run=args.dry_run)
    else:
        # Mode global (cron)
        config = get_config()
        cutoff = datetime.now() - timedelta(days=args.days)
        recent = [a for a in all_articles if _parse_date(a.get("Date de publication", "")) and
                  _parse_date(a.get("Date de publication", "")) >= cutoff]
        log(f"[00:01] Mode global — {len(recent)} articles récents sur {args.days}j")

        all_results = []
        seen_pairs: set[str] = set()
        for ref in recent:
            cluster, _ = build_cluster(ref, all_articles)
            if not cluster:
                continue
            results = detect_for_article(ref, cluster, dry_run=args.dry_run)
            for r in results:
                if r["id"] not in seen_pairs:
                    seen_pairs.add(r["id"])
                    all_results.append(r)

        save_contradictions(all_results, dry_run=args.dry_run)
        log(f"\n✅ Total : {len(all_results)} contradictions détectées")


if __name__ == "__main__":
    main()
