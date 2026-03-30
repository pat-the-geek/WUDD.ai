"""
viewer/routes/youtube.py — Blueprint Flask pour la sélection de vidéos YouTube.

Routes :
  POST /api/youtube/videos   Retourne les vidéos YouTube pertinentes pour un article

Stratégie :
  - Requête construite à partir des entités nommées (PERSON > ORG > PRODUCT > GPE)
  - Appel YouTube Data API v3 : search.list (FR puis EN si besoin) + videos.list (détails)
  - Filtre langue FR/EN, tri FR d'abord
  - Score de pertinence : chevauchement token Jaccard + bonus entités nommées
  - Quota : search.list = 100 unités | videos.list = 1 unité (sur 10 000/jour gratuits)
  - Cache mémoire TTL 1h — évite les appels redondants pour le même article

Prérequis : YOUTUBE_API_KEY dans .env
"""
import hashlib
import json
import os
import re
import ssl
import time
import threading
import urllib.error
import urllib.parse
import urllib.request

from flask import Blueprint, jsonify, request

youtube_bp = Blueprint("youtube", __name__)

# ── Cache mémoire TTL ─────────────────────────────────────────────────────────
# Clé : MD5(query + max), valeur : {"ts": float, "data": dict}
_CACHE_TTL = 3600          # 1 heure
_cache: dict = {}
_cache_lock = threading.Lock()

# ── SSL — compatible avec les environnements sans certifi (Docker, macOS system Python) ──
_ssl_ctx = ssl.create_default_context()
_ssl_ctx.check_hostname = False
_ssl_ctx.verify_mode = ssl.CERT_NONE

# ── Priorité des types d'entités pour construire la requête de recherche ──────
_ENTITY_PRIORITY = ["PERSON", "ORG", "PRODUCT", "EVENT", "GPE", "LOC"]

# ── Poids par type d'entité pour le scoring de pertinence ────────────────────
_ENTITY_WEIGHTS = {
    "PERSON":  3.0,
    "ORG":     2.5,
    "PRODUCT": 2.0,
    "EVENT":   1.5,
    "GPE":     1.0,
    "LOC":     0.8,
}


# ─── Construction de la requête de recherche ──────────────────────────────────

def _build_query(entities: dict, titre: str, max_terms: int = 3) -> str:
    """
    Construit la requête YouTube à partir des entités de l'article.
    Priorise PERSON > ORG > PRODUCT, exclut les GPE mono-mots (trop génériques).
    Fallback sur les mots du titre si pas assez d'entités.
    """
    terms = []
    for etype in _ENTITY_PRIORITY:
        for value in entities.get(etype, []):
            if etype in ("GPE", "LOC") and len(value.split()) == 1:
                continue
            terms.append(value)
            if len(terms) >= max_terms:
                break
        if len(terms) >= max_terms:
            break

    if len(terms) < 2 and titre:
        words = [w for w in titre.split() if len(w) > 3]
        terms.extend(words[: max_terms - len(terms)])

    return " ".join(terms)


# ─── Score de pertinence ──────────────────────────────────────────────────────

def _tokenize(text: str) -> set:
    return set(re.findall(r"\w+", text.lower()))


def _score_video(video: dict, entities: dict, titre: str) -> int:
    """
    Score 0–100 basé sur :
    - Jaccard token entre (titre article + entités) et (titre vidéo + description)
    - Bonus si un nom d'entité apparaît verbatim dans le titre de la vidéo
    """
    article_tokens = _tokenize(titre)
    for values in entities.values():
        for v in values:
            article_tokens.update(_tokenize(v))

    vid_text = f"{video.get('title', '')} {video.get('description', '')}"
    vid_tokens = _tokenize(vid_text)

    if not article_tokens or not vid_tokens:
        return 0

    intersection = article_tokens & vid_tokens
    union = article_tokens | vid_tokens
    jaccard = len(intersection) / len(union) if union else 0

    # Bonus entités verbatim dans le titre de la vidéo
    vid_title_lower = video.get("title", "").lower()
    bonus = 0.0
    for etype, values in entities.items():
        weight = _ENTITY_WEIGHTS.get(etype, 1.0)
        for v in values:
            if v.lower() in vid_title_lower:
                bonus += weight * 0.12

    score = min(100, int((jaccard * 0.65 + bonus) * 100))
    return score


# ─── Appels YouTube Data API v3 ───────────────────────────────────────────────

def _yt_search(query: str, api_key: str, max_results: int = 8,
               language: str = "fr") -> list[dict]:
    """search.list — coût 100 unités quota."""
    params = {
        "part": "snippet",
        "q": query,
        "type": "video",
        "relevanceLanguage": language,
        "order": "relevance",
        "maxResults": max_results,
        "key": api_key,
    }
    url = "https://www.googleapis.com/youtube/v3/search?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "WUDD.ai/2.4"})
    with urllib.request.urlopen(req, timeout=10, context=_ssl_ctx) as r:
        data = json.loads(r.read())

    results = []
    for item in data.get("items", []):
        snippet = item.get("snippet", {})
        vid_id = item.get("id", {}).get("videoId")
        if not vid_id:
            continue
        results.append({
            "video_id": vid_id,
            "title":       snippet.get("title", ""),
            "channel":     snippet.get("channelTitle", ""),
            "published":   snippet.get("publishedAt", "")[:10],
            "description": snippet.get("description", "")[:200],
            "thumbnail":   (
                snippet.get("thumbnails", {}).get("medium", {}).get("url")
                or snippet.get("thumbnails", {}).get("default", {}).get("url", "")
            ),
        })
    return results


def _yt_details(video_ids: list[str], api_key: str) -> dict[str, dict]:
    """videos.list — coût 1 unité quota (forfait)."""
    if not video_ids:
        return {}
    params = {
        "part": "contentDetails,statistics,snippet,status",
        "id": ",".join(video_ids),
        "key": api_key,
    }
    url = "https://www.googleapis.com/youtube/v3/videos?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "WUDD.ai/2.4"})
    with urllib.request.urlopen(req, timeout=10, context=_ssl_ctx) as r:
        data = json.loads(r.read())

    details = {}
    for item in data.get("items", []):
        vid_id = item["id"]
        cd      = item.get("contentDetails", {})
        stats   = item.get("statistics", {})
        snippet = item.get("snippet", {})
        status  = item.get("status", {})

        # Durée ISO 8601 → "4:13"
        dur_raw = cd.get("duration", "PT0S")
        m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", dur_raw)
        if m:
            h, mn, s = (int(x or 0) for x in m.groups())
            duration = f"{h}:{mn:02d}:{s:02d}" if h else f"{mn}:{s:02d}"
        else:
            duration = "?"

        # Langue : defaultAudioLanguage prioritaire, sinon defaultLanguage
        language = (
            snippet.get("defaultAudioLanguage")
            or snippet.get("defaultLanguage")
            or ""
        ).split("-")[0].lower()

        details[vid_id] = {
            "duration":   duration,
            "views":      int(stats.get("viewCount", 0)),
            "likes":      int(stats.get("likeCount", 0)),
            "language":   language,
            "embeddable": status.get("embeddable", True),
        }
    return details


def _filter_and_sort(videos: list[dict], details: dict[str, dict],
                     allowed: tuple = ("fr", "en")) -> list[dict]:
    """Garde FR/EN/inconnu, trie FR d'abord."""
    priority = {lang: i for i, lang in enumerate(allowed)}

    def sort_key(v):
        lang = details.get(v["video_id"], {}).get("language", "")
        if lang in priority:
            return priority[lang]
        return len(allowed) if lang == "" else len(allowed) + 1

    kept = [
        v for v in videos
        if details.get(v["video_id"], {}).get("language", "") in (*allowed, "")
    ]
    return sorted(kept, key=sort_key)


# ─── Route principale ─────────────────────────────────────────────────────────

@youtube_bp.route("/api/youtube/videos", methods=["POST"])
def api_youtube_videos():
    """
    Body JSON attendu :
      {
        "titre":    "Mistral AI lance Le Chat Pro",
        "entities": { "ORG": ["Mistral AI"], "PRODUCT": ["Le Chat"] },
        "max":      5   (optionnel, défaut 5)
      }

    Retourne :
      {
        "query": "Mistral AI Le Chat",
        "videos": [
          {
            "id": "...", "title": "...", "channel": "...", "published": "YYYY-MM-DD",
            "description": "...", "thumbnail": "https://...",
            "duration": "4:13", "views": 492000, "likes": 1200,
            "language": "fr", "embeddable": true, "score": 85
          }
        ]
      }
    """
    api_key = os.environ.get("YOUTUBE_API_KEY", "")
    if not api_key:
        return jsonify({"error": "YOUTUBE_API_KEY manquante dans .env"}), 503

    body = request.get_json(force=True) or {}
    titre    = body.get("titre", "")
    entities = body.get("entities", {})
    max_res  = min(int(body.get("max", 5)), 10)

    if not titre and not entities:
        return jsonify({"error": "titre ou entities requis"}), 400

    query = _build_query(entities, titre)
    if not query:
        return jsonify({"error": "Impossible de construire une requête"}), 400

    # ── Vérification du cache ─────────────────────────────────────────────────
    cache_key = hashlib.md5(f"{query}|{max_res}".encode()).hexdigest()
    with _cache_lock:
        entry = _cache.get(cache_key)
        if entry and (time.time() - entry["ts"]) < _CACHE_TTL:
            return jsonify({**entry["data"], "cached": True})

    try:
        # Étape 1 : recherche FR
        videos_fr = _yt_search(query, api_key, max_results=max_res * 2, language="fr")

        # Étape 2 : EN uniquement si FR renvoie moins de 3 résultats pertinents
        videos_en = []
        if len(videos_fr) < 3:
            videos_en = _yt_search(query, api_key, max_results=max_res * 2, language="en")

        # Déduplique
        seen, candidates = set(), []
        for v in videos_fr + videos_en:
            if v["video_id"] not in seen:
                seen.add(v["video_id"])
                candidates.append(v)

        # Étape 3 : détails (durée, vues, langue, embeddabilité)
        details = _yt_details([v["video_id"] for v in candidates], api_key) if candidates else {}

        # Étape 4 : filtre langue + tri FR d'abord
        filtered = _filter_and_sort(candidates, details)[:max_res]

        # Étape 5 : score de pertinence + construction de la réponse
        result = []
        for v in filtered:
            d = details.get(v["video_id"], {})
            score = _score_video(v, entities, titre)
            result.append({
                "id":          v["video_id"],
                "title":       v["title"],
                "channel":     v["channel"],
                "published":   v["published"],
                "description": v["description"],
                "thumbnail":   v["thumbnail"],
                "duration":    d.get("duration", "?"),
                "views":       d.get("views", 0),
                "likes":       d.get("likes", 0),
                "language":    d.get("language", ""),
                "embeddable":  d.get("embeddable", True),
                "score":       score,
            })

        # Tri final par score décroissant (maintient FR avant EN à score égal)
        result.sort(key=lambda x: -x["score"])

        payload = {"query": query, "videos": result}

        # ── Mise en cache ─────────────────────────────────────────────────────
        with _cache_lock:
            _cache[cache_key] = {"ts": time.time(), "data": payload}

        return jsonify(payload)

    except urllib.error.HTTPError as e:
        body_err = e.read().decode(errors="replace")[:300]
        return jsonify({"error": f"YouTube API HTTP {e.code}", "detail": body_err}), 502
    except Exception as e:
        return jsonify({"error": str(e)}), 500
