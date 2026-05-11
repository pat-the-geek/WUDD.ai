"""
viewer/routes/rss_direct.py — Mode Direct : lecture parallèle de tous les flux RSS en SSE.

Routes :
  GET  /api/rss/direct/stream?interval=30    Flux SSE — scan parallèle de tous les flux (OPML + sites_actualite.json)
  POST /api/rss/direct/article               Génère résumé + entités à la volée (sans save)
"""
import json
import random
import re
import sys
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlparse

import requests as _req
from flask import Blueprint, Response, jsonify, request, stream_with_context

from viewer.helpers import PROJECT_ROOT

rss_direct_bp = Blueprint("rss_direct", __name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "DNT": "1",
}
_HOMEPAGE_HEADERS = {**_HEADERS, "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}
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


def _parse_sites_actualite_feeds() -> list[dict]:
    """Lit config/sites_actualite.json et retourne les flux RSS."""
    path = PROJECT_ROOT / "config" / "sites_actualite.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        feeds = []
        for entry in data:
            title   = (entry.get("Titre") or "").strip()
            xml_url = (entry.get("URL")   or "").strip()
            if xml_url:
                feeds.append({"title": title, "xmlUrl": xml_url})
        return feeds
    except Exception:
        return []


def _all_feeds() -> list[dict]:
    """Retourne uniquement les flux de data/WUDD.opml (identiques aux Réglages)."""
    return _parse_opml_feeds()



# Fuseaux horaires abréviés non couverts par email.utils (ex: CNN utilise "EST")
_TZ_OFFSETS = {
    "EST": -5, "EDT": -4, "CST": -6, "CDT": -5,
    "MST": -7, "MDT": -6, "PST": -8, "PDT": -7,
    "GMT": 0,  "UTC": 0,  "BST": 1,  "CET": 1, "CEST": 2,
}

_NS_DC      = "http://purl.org/dc/elements/1.1/"
_NS_CONTENT = "http://purl.org/rss/1.0/modules/content/"
_NS_MEDIA   = "http://search.yahoo.com/mrss/"

# Largeur minimale (px) pour accepter une image RSS déclarée
_MIN_IMAGE_WIDTH = 600

# Patterns d'URL indiquant une image de mauvaise qualité (icône, logo, tracking…)
_BAD_IMAGE_RE = re.compile(
    r"/(icon|logo|avatar|thumb(?:nail)?|tiny|small|pixel|tracking|badge|spinner|"
    r"placeholder|default|blank|empty|1x1|ads?|banner)",
    re.IGNORECASE,
)


def _filter_quality_image(url: str) -> "str | None":
    """Retourne l'URL si elle désigne une image de bonne qualité, sinon None."""
    if not url or not url.startswith("http"):
        return None
    if _BAD_IMAGE_RE.search(url):
        return None
    return url


def _extract_rss_image(item) -> "str | None":
    """Extrait la première image de qualité depuis un item RSS/Atom (aucune requête HTTP).

    Priorité : media:content > enclosure > media:thumbnail.
    Une image est acceptée si :
      - son URL est absolue (http/https)
      - sa largeur déclarée est ≥ _MIN_IMAGE_WIDTH (ou non déclarée)
      - son URL ne correspond pas à _BAD_IMAGE_RE
    """
    candidates: list[tuple[str, int]] = []  # (url, width_score)

    # media:content url="..." medium="image"
    for el in item.findall(f"{{{_NS_MEDIA}}}content"):
        url    = el.get("url", "").strip()
        medium = el.get("medium", "").lower()
        width  = int(el.get("width", 0) or 0)
        if url and medium in ("image", ""):
            if width == 0 or width >= _MIN_IMAGE_WIDTH:
                filtered = _filter_quality_image(url)
                if filtered:
                    candidates.append((filtered, width or 9999))

    # enclosure url="..." type="image/..."
    enc = item.find("enclosure")
    if enc is not None:
        url  = enc.get("url", "").strip()
        mime = enc.get("type", "").lower()
        if url and mime.startswith("image/"):
            filtered = _filter_quality_image(url)
            if filtered:
                candidates.append((filtered, 9998))

    # media:thumbnail url="..."
    for el in item.findall(f"{{{_NS_MEDIA}}}thumbnail"):
        url   = el.get("url", "").strip()
        width = int(el.get("width", 0) or 0)
        if url and (width == 0 or width >= _MIN_IMAGE_WIDTH):
            filtered = _filter_quality_image(url)
            if filtered:
                candidates.append((filtered, width or 9997))

    if not candidates:
        return None
    # Retourner l'image avec la plus grande largeur déclarée
    return max(candidates, key=lambda x: x[1])[0]


def _domain_label(xml_url: str) -> str:
    """Extrait le domaine lisible d'une URL de flux (ex: 'edition.cnn.com' → 'cnn.com')."""
    try:
        host = urlparse(xml_url).hostname or ""
        parts = host.split(".")
        # Supprimer les sous-domaines courants : feeds., rss., feed., www.
        if len(parts) >= 2 and parts[0] in ("www", "rss", "feeds", "feed"):
            parts = parts[1:]
        return ".".join(parts) if parts else xml_url
    except Exception:
        return xml_url


def _strip_html(text: str) -> str:
    """Supprime les balises HTML et normalise les espaces blancs."""
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _parse_rss_date(date_str: str) -> datetime:
    """Parse une date RSS (RFC 2822, ISO 8601, abbrev TZ) → datetime UTC naive."""
    if not date_str:
        return datetime.min
    s = date_str.strip()
    # RFC 2822 standard ("Sat, 22 Mar 2026 10:30:00 +0100")
    try:
        dt = parsedate_to_datetime(s)
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    except Exception:
        pass
    # RFC 2822 avec timezone abrégée non reconnue (ex CNN: "Mon, 22 Mar 2026 10:30:00 EST")
    m = re.match(
        r"(\w+,\s+\d+\s+\w+\s+\d{4}\s+\d{2}:\d{2}:\d{2})\s+([A-Z]{2,5})$", s
    )
    if m:
        offset = _TZ_OFFSETS.get(m.group(2), 0)
        try:
            dt = datetime.strptime(m.group(1), "%a, %d %b %Y %H:%M:%S")
            return dt.replace(tzinfo=timezone.utc) - __import__("datetime").timedelta(hours=offset)
        except Exception:
            pass
    # ISO 8601 — normaliser Z et fractions de secondes
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    s = re.sub(r"(\.\d{6})\d+", r"\1", s)
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo:
            return dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt
    except Exception:
        pass
    # Formats date seule ou datetime sans T
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y", "%d %b %Y"):
        try:
            return datetime.strptime(date_str.strip(), fmt)
        except Exception:
            pass
    return datetime.min


def _fetch_feed_articles(feed_url: str) -> list[dict]:
    """Fetche un flux RSS/Atom et retourne les articles sous forme de dicts.
    Stratégie anti-403 : fallback session+cookies si la requête directe échoue."""
    try:
        r = _req.get(feed_url, timeout=_FEED_TIMEOUT, headers=_HEADERS)
        if r.status_code == 403:
            raise _req.exceptions.HTTPError(response=r)
        r.raise_for_status()
        root = ET.fromstring(r.content)
    except _req.exceptions.HTTPError as _e:
        if _e.response is not None and _e.response.status_code == 403:
            # Fallback : session + visite homepage pour cookies WAF/CDN
            try:
                _s = _req.Session()
                _domain = "/".join(feed_url.split("/")[:3])
                _s.get(_domain, timeout=20, headers=_HOMEPAGE_HEADERS)
                r = _s.get(feed_url, timeout=_FEED_TIMEOUT, headers=_HEADERS)
                r.raise_for_status()
                root = ET.fromstring(r.content)
            except Exception:
                return []
        else:
            return []
    except Exception:
        return []

    # Heure actuelle UTC comme fallback si la date de l'article est manquante/illisible
    now_iso = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')

    def _resolved_date(pub_date: str) -> str:
        dt = _parse_rss_date(pub_date)
        return (dt.isoformat() + 'Z') if dt != datetime.min else now_iso

    articles = []

    # ── RSS 2.0 ───────────────────────────────────────────────────────────────
    channel = root.find("channel")
    if channel is not None:
        feed_title = (channel.findtext("title") or "").strip()
        for item in channel.findall("item"):
            title    = (item.findtext("title") or "").strip()
            url      = (item.findtext("link")  or "").strip()
            if not url:
                continue
            # Date : pubDate → dc:date
            pub_date = (
                item.findtext("pubDate")
                or item.findtext(f"{{{_NS_DC}}}date")
                or ""
            ).strip()
            # Texte : content:encoded → description (les deux peuvent contenir du HTML)
            raw = (
                item.findtext(f"{{{_NS_CONTENT}}}encoded")
                or item.findtext("description")
                or ""
            )
            desc = _strip_html(raw)[:500] or title
            if not title and not desc:
                continue   # article sans titre ni texte → ignoré
            image = _extract_rss_image(item)
            art = {
                "title":         title or desc[:80],
                "url":           url,
                "pubDate":       pub_date,
                "pubDateParsed": _resolved_date(pub_date),
                "description":   desc,
                "feedTitle":     feed_title,
            }
            if image:
                art["image"] = image
            articles.append(art)
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
        # Texte : summary → content (peuvent contenir du HTML ou du texte brut)
        sum_el   = (entry.find(f"{{{ATOM}}}summary")
                    or entry.find(f"{{{ATOM}}}content"))
        raw      = (sum_el.text or "") if sum_el is not None else ""
        desc  = _strip_html(raw)[:500] or title
        if not url or (not title and not desc):
            continue   # article sans URL ou sans titre ni texte → ignoré
        # Images Atom : media:content, media:thumbnail, link rel=enclosure
        image = _extract_rss_image(entry)
        # Atom : lien enclosure via <link rel="enclosure">
        if not image:
            for link_el in entry.findall(f"{{{ATOM}}}link"):
                if link_el.get("rel") == "enclosure":
                    href = link_el.get("href", "").strip()
                    mime = link_el.get("type", "").lower()
                    if href and mime.startswith("image/"):
                        image = _filter_quality_image(href)
                        if image:
                            break
        art = {
            "title":         title or desc[:80],
            "url":           url,
            "pubDate":       pub_date,
            "pubDateParsed": _resolved_date(pub_date),
            "description":   desc,
            "feedTitle":     feed_title,
        }
        if image:
            art["image"] = image
        articles.append(art)
    return articles


# ── Routes ────────────────────────────────────────────────────────────────────

_MAX_WORKERS = 12   # connexions HTTP parallèles pour le scan des flux


def _emit_article(art: dict) -> str:
    payload = {
        "type":          "article",
        "title":         art["title"],
        "url":           art["url"],
        "pubDate":       art["pubDate"],
        "pubDateParsed": art["pubDateParsed"],
        "feedTitle":     art["feedTitle"],
        "description":   art["description"],
    }
    if art.get("image"):
        payload["image"] = art["image"]
    return "data: " + json.dumps(payload) + "\n\n"


@rss_direct_bp.route("/api/rss/direct/stream")
def api_rss_direct_stream():
    """Flux SSE — scan parallèle de tous les flux à chaque cycle.

    Tous les flux (OPML + sites_actualite.json) sont fetchés en parallèle
    (_MAX_WORKERS connexions simultanées). Les articles arrivent au fil du scan,
    puis le générateur attend `interval` secondes avant le cycle suivant.

    Query params :
      interval : secondes d'attente entre chaque cycle complet (défaut: 30, min: 5, max: 300)
    """
    interval = max(5, min(300, int(request.args.get("interval", 30))))

    def generate():
        # last_seen[feed_url] = set des URLs d'articles déjà émis dans cette session
        last_seen: dict[str, set] = {}

        while True:
            # ── Rechargement de l'OPML à chaque cycle (reflète les modifs Réglages)
            feeds = _all_feeds()
            if not feeds:
                yield "data: " + json.dumps({
                    "type":    "error",
                    "message": "Aucun flux RSS trouvé dans data/WUDD.opml",
                }) + "\n\n"
                for _ in range(interval):
                    time.sleep(1)
                    yield ": keepalive\n\n"
                continue

            random.shuffle(feeds)

            # ── Scan parallèle de tous les flux ───────────────────────────────
            cycle_success = 0

            yield "data: " + json.dumps({
                "type":  "cycle_start",
                "total": len(feeds),
            }) + "\n\n"

            with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as executor:
                future_to_feed = {
                    executor.submit(_fetch_feed_articles, f["xmlUrl"]): f
                    for f in feeds
                }
                for future in as_completed(future_to_feed):
                    feed       = future_to_feed[future]
                    feed_url   = feed["xmlUrl"]
                    feed_title = feed["title"]

                    try:
                        articles = future.result()
                    except Exception:
                        articles = []

                    # Normaliser le feedTitle : canal RSS → titre OPML → domaine
                    label = feed_title or _domain_label(feed_url)
                    for art in articles:
                        if not art.get("feedTitle"):
                            art["feedTitle"] = label

                    # Signaler le flux en cours de traitement
                    yield "data: " + json.dumps({
                        "type":      "scanning",
                        "feedTitle": feed_title,
                        "feedUrl":   feed_url,
                    }) + "\n\n"

                    if articles:
                        cycle_success += 1

                    if feed_url not in last_seen:
                        # Premier passage : émettre les 3 plus récents, mémoriser tout
                        last_seen[feed_url] = {a["url"] for a in articles}
                        recent = sorted(
                            articles,
                            key=lambda a: a.get("pubDateParsed") or "",
                            reverse=True,
                        )[:3]
                        for art in reversed(recent):
                            yield _emit_article(art)
                    else:
                        seen         = last_seen[feed_url]
                        new_articles = [a for a in articles if a["url"] not in seen]
                        new_articles.sort(key=lambda a: a.get("pubDateParsed") or "")
                        for art in new_articles:
                            seen.add(art["url"])
                            yield _emit_article(art)

            yield "data: " + json.dumps({
                "type":    "cycle_end",
                "total":   len(feeds),
                "success": cycle_success,
            }) + "\n\n"

            # ── Pause inter-cycle avec keepalive SSE ──────────────────────────
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
      url          : URL de l'article (obligatoire)
      title        : Titre issu du flux RSS
      source       : Nom de la source (feedTitle)
      pub_date     : Date brute du flux RSS
      description  : Extrait/description RSS (optionnel, fallback si fetch échoue)
      entity_type  : Type NER de l'entité cliquée (ex. "PERSON") — optionnel
      entity_value : Nom de l'entité cliquée (ex. "Elon Musk") — optionnel
    """
    sys.path.insert(0, str(PROJECT_ROOT))

    data         = request.get_json(force=True) or {}
    url          = data.get("url",          "").strip()
    title        = data.get("title",        "").strip()
    source       = data.get("source",       "").strip()
    pub_date     = data.get("pub_date",     "").strip()
    description  = data.get("description",  "").strip()
    entity_type  = data.get("entity_type",  "").strip()
    entity_value = data.get("entity_value", "").strip()

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
        from utils.api_client import get_summary_client
        client = get_summary_client()
        resume = client.generate_summary(page_text or title) or ""
    except Exception:
        resume = description or ""

    # ── 3. Entités NER ────────────────────────────────────────────────────────
    entities = {}
    if resume:
        try:
            from utils.api_client import get_ner_client
            client = get_ner_client()
            entities = client.generate_entities(resume) or {}
        except Exception:
            pass

    # Garantir que l'entité cliquée (depuis la carte) est présente dans les entités,
    # même si le NER complet l'a manquée ou retourné un nom légèrement différent.
    if entity_type and entity_value:
        bucket = entities.setdefault(entity_type, [])
        if not any(isinstance(v, str) and v.lower() == entity_value.lower() for v in bucket):
            bucket.append(entity_value)

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
        from utils.entity_index import get_entity_index

        wudd_dir      = PROJECT_ROOT / "data" / "articles-from-rss" / "_WUDD.AI_"
        direct_path   = wudd_dir / "direct.json"
        heures48_path = wudd_dir / "48-heures.json"

        wudd_dir.mkdir(parents=True, exist_ok=True)

        update_rolling_window([article], direct_path,   hours=48)
        update_rolling_window([article], heures48_path, hours=48)

        # Recharger direct.json complet pour les index (update() remplace toutes
        # les refs du fichier source — il faut donc lui passer TOUS les articles)
        try:
            all_direct = json.loads(direct_path.read_text(encoding="utf-8"))
            if not isinstance(all_direct, list):
                all_direct = [article]
        except Exception:
            all_direct = [article]

        # Mise à jour de l'index article
        aidx = get_article_index(PROJECT_ROOT)
        aidx.update(all_direct, str(direct_path))

        # Mise à jour de l'index entités — indispensable pour EntityArticlePanel
        eidx = get_entity_index(PROJECT_ROOT)
        eidx.update(all_direct, str(direct_path))
    except Exception:
        pass  # Non bloquant : l'affichage fonctionne même si la sauvegarde échoue

    return jsonify(article)


@rss_direct_bp.route("/api/rss/direct/ner", methods=["POST"])
def api_rss_direct_ner():
    """Extrait les entités NER d'un titre + description d'article RSS (léger, sans fetch HTML).

    Body JSON :
      title       : Titre de l'article
      description : Description/extrait RSS (optionnel)

    Retourne un dict {TYPE: [noms]} identique au format WUDD.ai entities.
    """
    sys.path.insert(0, str(PROJECT_ROOT))
    body = request.get_json(force=True) or {}
    title       = (body.get("title")       or "").strip()
    description = (body.get("description") or "").strip()
    text = (title + "\n" + description).strip()[:2000]
    if not text:
        return jsonify({})
    try:
        from utils.api_client import get_ai_client
        client   = get_ai_client()
        entities = client.generate_entities(text) or {}
        return jsonify(entities)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
