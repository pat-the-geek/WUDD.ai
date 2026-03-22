"""
viewer/routes/rss_direct.py — Mode Direct : lecture round-robin des flux RSS en SSE.

Routes :
  GET  /api/rss/direct/stream?interval=30    Flux SSE round-robin OPML
  POST /api/rss/direct/article               Génère résumé + entités à la volée (sans save)
"""
import json
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import requests as _req
from flask import Blueprint, Response, jsonify, request, stream_with_context

from viewer.helpers import PROJECT_ROOT

rss_direct_bp = Blueprint("rss_direct", __name__)

_HEADERS      = {"User-Agent": "WUDD.ai/2.4 Direct/1.0"}
_FEED_TIMEOUT = 10   # secondes pour fetcher un flux RSS
_ART_TIMEOUT  = 15   # secondes pour fetcher le HTML d'un article


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_opml_feeds() -> list[dict]:
    """Parse data/WUDD.opml et retourne les flux RSS dans l'ordre OPML (non trié)."""
    opml_path = PROJECT_ROOT / "data" / "WUDD.opml"
    if not opml_path.exists():
        return []
    try:
        tree = ET.parse(opml_path)
        root = tree.getroot()
        feeds = []
        for o in root.findall(".//outline[@type='rss']"):
            title   = o.get("title") or o.get("text") or ""
            xml_url = o.get("xmlUrl") or ""
            if xml_url:
                feeds.append({"title": title, "xmlUrl": xml_url})
        return feeds
    except Exception:
        return []


def _parse_rss_date(date_str: str) -> datetime:
    """Parse une date RSS (RFC 2822 ou ISO 8601) → datetime UTC naive."""
    if not date_str:
        return datetime.min
    # RFC 2822 (format standard RSS)
    try:
        dt = parsedate_to_datetime(date_str)
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    except Exception:
        pass
    # ISO 8601
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(date_str[:len(fmt)], fmt)
        except Exception:
            pass
    return datetime.min


def _fetch_feed_articles(feed_url: str) -> list[dict]:
    """Fetche un flux RSS/Atom et retourne les articles sous forme de dicts."""
    try:
        r = _req.get(feed_url, timeout=_FEED_TIMEOUT, headers=_HEADERS)
        r.raise_for_status()
        root = ET.fromstring(r.content)
    except Exception:
        return []

    articles = []

    # ── RSS 2.0 ───────────────────────────────────────────────────────────────
    channel = root.find("channel")
    if channel is not None:
        feed_title = (channel.findtext("title") or "").strip()
        for item in channel.findall("item"):
            title    = (item.findtext("title")       or "").strip()
            url      = (item.findtext("link")         or "").strip()
            pub_date = (item.findtext("pubDate")      or "").strip()
            desc     = (item.findtext("description")  or "").strip()
            if url:
                dt = _parse_rss_date(pub_date)
                articles.append({
                    "title":          title,
                    "url":            url,
                    "pubDate":        pub_date,
                    "pubDateParsed":  dt.isoformat() if dt != datetime.min else None,
                    "description":    desc[:500] if desc else "",
                    "feedTitle":      feed_title,
                })
        return articles

    # ── Atom ─────────────────────────────────────────────────────────────────
    ATOM = "http://www.w3.org/2005/Atom"
    feed_title_el = root.find(f"{{{ATOM}}}title") or root.find("title")
    feed_title    = (feed_title_el.text or "").strip() if feed_title_el is not None else ""
    for entry in root.findall(f"{{{ATOM}}}entry"):
        title_el = entry.find(f"{{{ATOM}}}title")
        title    = (title_el.text or "").strip() if title_el is not None else ""
        link_el  = entry.find(f"{{{ATOM}}}link")
        url      = link_el.get("href", "") if link_el is not None else ""
        pub_el   = (entry.find(f"{{{ATOM}}}published")
                    or entry.find(f"{{{ATOM}}}updated"))
        pub_date = (pub_el.text or "").strip() if pub_el is not None else ""
        if url:
            dt = _parse_rss_date(pub_date)
            articles.append({
                "title":         title,
                "url":           url,
                "pubDate":       pub_date,
                "pubDateParsed": dt.isoformat() if dt != datetime.min else None,
                "description":   "",
                "feedTitle":     feed_title,
            })
    return articles


# ── Routes ────────────────────────────────────────────────────────────────────

@rss_direct_bp.route("/api/rss/direct/stream")
def api_rss_direct_stream():
    """Flux SSE round-robin sur les flux OPML.

    Query params :
      interval : secondes d'attente entre chaque flux (défaut: 30, min: 5, max: 300)
    """
    interval = max(5, min(300, int(request.args.get("interval", 30))))

    def generate():
        feeds = _parse_opml_feeds()
        if not feeds:
            yield "data: " + json.dumps({
                "type":    "error",
                "message": "Aucun flux OPML trouvé"
            }) + "\n\n"
            return

        # last_seen[feed_url] = set des URLs d'articles déjà émis dans cette session
        last_seen: dict[str, set] = {}
        feed_idx = 0

        while True:
            feed       = feeds[feed_idx % len(feeds)]
            feed_url   = feed["xmlUrl"]
            feed_title = feed["title"]

            # Signaler le scan en cours
            yield "data: " + json.dumps({
                "type":      "scanning",
                "feedTitle": feed_title,
                "feedUrl":   feed_url,
            }) + "\n\n"

            articles = _fetch_feed_articles(feed_url)

            if feed_url not in last_seen:
                # Premier passage : émettre les 3 articles les plus récents pour
                # peupler immédiatement le log, puis mémoriser toutes les URLs.
                last_seen[feed_url] = {a["url"] for a in articles}
                recent = sorted(articles, key=lambda a: a.get("pubDateParsed", ""), reverse=True)[:3]
                for art in reversed(recent):  # chronologique dans le log
                    yield "data: " + json.dumps({
                        "type":          "article",
                        "title":         art["title"],
                        "url":           art["url"],
                        "pubDate":       art["pubDate"],
                        "pubDateParsed": art["pubDateParsed"],
                        "feedTitle":     art["feedTitle"],
                        "description":   art["description"],
                    }) + "\n\n"
            else:
                seen         = last_seen[feed_url]
                new_articles = [a for a in articles if a["url"] not in seen]
                # Trier chronologiquement (plus ancien → plus récent dans le log)
                new_articles.sort(key=lambda a: a.get("pubDateParsed", ""))
                for art in new_articles:
                    seen.add(art["url"])
                    yield "data: " + json.dumps({
                        "type":         "article",
                        "title":        art["title"],
                        "url":          art["url"],
                        "pubDate":      art["pubDate"],
                        "pubDateParsed": art["pubDateParsed"],
                        "feedTitle":    art["feedTitle"],
                        "description":  art["description"],
                    }) + "\n\n"

            feed_idx += 1

            # Pause inter-flux avec keepalive SSE chaque seconde
            for _ in range(interval):
                time.sleep(1)
                yield ": keepalive\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control":    "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@rss_direct_bp.route("/api/rss/direct/article", methods=["POST"])
def api_rss_direct_article():
    """Génère résumé + entités pour un article RSS et le sauvegarde dans direct.json et 48-heures.json.

    Body JSON :
      url         : URL de l'article (obligatoire)
      title       : Titre issu du flux RSS
      source      : Nom de la source (feedTitle)
      pub_date    : Date brute du flux RSS
      description : Extrait/description RSS (optionnel, fallback si fetch échoue)
    """
    sys.path.insert(0, str(PROJECT_ROOT))

    data        = request.get_json(force=True) or {}
    url         = data.get("url",         "").strip()
    title       = data.get("title",       "").strip()
    source      = data.get("source",      "").strip()
    pub_date    = data.get("pub_date",    "").strip()
    description = data.get("description", "").strip()

    if not url:
        return jsonify({"error": "URL manquante"}), 400

    # ── 1. Fetch HTML → texte brut + og:image ─────────────────────────────────
    page_text  = ""
    main_image = None
    try:
        from bs4 import BeautifulSoup
        r = _req.get(url, timeout=_ART_TIMEOUT, headers=_HEADERS)
        r.raise_for_status()
        soup = BeautifulSoup(r.content, "html.parser")

        # og:image / twitter:image
        for prop in ("og:image", "twitter:image"):
            tag = (soup.find("meta", property=prop)
                   or soup.find("meta", attrs={"name": prop}))
            if tag and tag.get("content"):
                main_image = tag["content"]
                break

        # Texte brut (hors navigation/scripts/styles)
        for tag in soup(["script", "style", "nav", "header", "footer", "aside", "iframe"]):
            tag.decompose()
        page_text = soup.get_text(separator="\n", strip=True)[:8000]
    except Exception:
        page_text = description or title

    # ── 2. Résumé IA ──────────────────────────────────────────────────────────
    resume = ""
    try:
        from utils.api_client import get_ai_client
        client = get_ai_client()
        resume = client.generate_summary(page_text or title) or ""
    except Exception:
        resume = description or ""

    # ── 3. Entités NER ────────────────────────────────────────────────────────
    entities = {}
    if resume:
        try:
            from utils.api_client import get_ai_client
            client = get_ai_client()
            entities = client.generate_entities(resume) or {}
        except Exception:
            pass

    # ── 4. Normaliser la date en DD/MM/YYYY ───────────────────────────────────
    date_fr = ""
    try:
        dt = _parse_rss_date(pub_date)
        if dt != datetime.min:
            date_fr = dt.strftime("%d/%m/%Y")
    except Exception:
        pass

    # ── 5. Construire le dict article au format WUDD.ai ───────────────────────
    article = {
        "Titre":               title,
        "Sources":             source,
        "URL":                 url,
        "Date de publication": date_fr,
        "Résumé":              resume,
        "entities":            entities,
    }
    if main_image:
        article["Images"] = [{"URL": main_image, "Width": 1200}]

    # ── 6. Sauvegarde dans direct.json et 48-heures.json ──────────────────────
    try:
        from utils.rolling_window import update_rolling_window
        from utils.article_index import get_article_index

        wudd_dir     = PROJECT_ROOT / "data" / "articles-from-rss" / "_WUDD.AI_"
        direct_path  = wudd_dir / "direct.json"
        heures48_path = wudd_dir / "48-heures.json"

        update_rolling_window([article], direct_path,   hours=48)
        update_rolling_window([article], heures48_path, hours=48)

        # Mise à jour de l'index article
        aidx = get_article_index(PROJECT_ROOT)
        aidx.update([article], str(direct_path))
    except Exception:
        pass  # Non bloquant : l'affichage fonctionne même si la sauvegarde échoue

    return jsonify(article)
