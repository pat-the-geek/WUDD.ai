"""Générateur de flux Atom augmenté.

Produit un flux Atom 1.0 exposant les articles résumés + entités,
consommable par tout agrégateur (Reeder, NetNewsWire, Miniflux…).

Usage :
    from utils.exporters.atom_feed import generate_atom_feed
    xml = generate_atom_feed(articles, feed_title="WUDD.ai · IA & Tech")
    with open("rapports/wudd-feed.xml", "w") as f:
        f.write(xml)

Ou via Flask : GET /api/export/atom?flux=Intelligence-artificielle
"""

import hashlib
import html as _html_module
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..date_utils import parse_article_date
from ..logging import default_logger


_FEED_ID_BASE = "tag:wudd.ai,2026:"
_SELF_URL = "http://localhost:5050/api/export/atom"  # Remplacer par votre domaine en prod


def _escape(text: str) -> str:
    return _html_module.escape(str(text), quote=True)


def _stable_id(url: str) -> str:
    """Génère un identifiant stable basé sur le MD5 de l'URL de l'article."""
    digest = hashlib.md5(url.encode("utf-8")).hexdigest()[:16]
    return f"{_FEED_ID_BASE}article-{digest}"


def _normalize_date_rfc3339(date_str: str) -> str:
    """Convertit une date en RFC 3339 (requis par Atom)."""
    if not date_str:
        return datetime.now(timezone.utc).isoformat()
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            dt = datetime.strptime(date_str, fmt).replace(tzinfo=timezone.utc)
            return dt.isoformat()
        except ValueError:
            continue
    try:
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(date_str).isoformat()
    except Exception:
        pass
    return datetime.now(timezone.utc).isoformat()


def _article_to_entry(article: dict, index: int) -> str:
    """Convertit un article en entrée Atom XML."""
    raw_url = article.get("URL", "")
    url = _escape(raw_url)
    source = _escape(article.get("Sources", "Source inconnue"))
    date_str = article.get("Date de publication", "")
    updated = _normalize_date_rfc3339(date_str)
    resume = article.get("Résumé", "")
    if not isinstance(resume, str):
        resume = ""

    # Titre = première ligne significative du résumé
    lines = [l.strip() for l in resume.splitlines() if l.strip()]
    title = _escape(lines[0][:120] if lines else f"{article.get('Sources', 'WUDD.ai')} · {updated[:10]}")

    # Contenu HTML : résumé en paragraphes + image + entités + sentiment
    paragraphs = "".join(f"<p>{_escape(l)}</p>" for l in lines if l)

    # Image
    images = article.get("Images", [])
    img_html = ""
    if isinstance(images, list) and images and isinstance(images[0], dict):
        img_url = images[0].get("url") or images[0].get("URL", "")
        if img_url and img_url.startswith("http"):
            # Utiliser _escape pour les attributs XML mais préserver l'URL lisible
            # html.escape encode & → &amp; ce qui est requis dans le contenu HTML
            img_html = f'<p><img src="{_escape(img_url)}" alt="illustration" style="max-width:100%" /></p>'

    # Entités
    entities = article.get("entities")
    ent_html = ""
    if isinstance(entities, dict) and entities:
        ent_parts = []
        for etype, values in entities.items():
            if isinstance(values, list) and values:
                ent_parts.append(f"<strong>{_escape(etype)}</strong>: {', '.join(_escape(v) for v in values[:5])}")
        if ent_parts:
            ent_html = "<p><small>" + " &nbsp;|&nbsp; ".join(ent_parts) + "</small></p>"

    # Sentiment
    sentiment = article.get("sentiment", "")
    ton = article.get("ton_editorial", "")
    sent_html = ""
    if sentiment or ton:
        sent_html = f"<p><small>Sentiment: {_escape(sentiment)} &nbsp;·&nbsp; Ton: {_escape(ton)}</small></p>"

    # ID stable basé sur l'URL (Reeder exige des IDs stables entre refreshes)
    entry_id = _stable_id(raw_url) if raw_url else f"{_FEED_ID_BASE}article-{index}"
    content = img_html + paragraphs + ent_html + sent_html

    return f"""  <entry>
    <id>{entry_id}</id>
    <title>{title}</title>
    <link href="{url}" rel="alternate" type="text/html"/>
    <updated>{updated}</updated>
    <author><name>{source}</name></author>
    <content type="html">{content}</content>
  </entry>"""


def generate_atom_feed(
    articles: list,
    feed_title: str = "WUDD.ai · Veille automatisée",
    feed_id: Optional[str] = None,
    self_url: Optional[str] = None,
    max_entries: int = 50,
) -> str:
    """Génère un flux Atom 1.0 depuis une liste d'articles.

    Args:
        articles   : liste de dicts article (format WUDD.ai)
        feed_title : titre du feed
        feed_id    : identifiant unique du feed (auto si None)
        self_url   : URL canonique du feed (pour <link rel="self">)
        max_entries: nombre max d'entrées (défaut: 50)

    Returns:
        Chaîne XML du flux Atom.
    """
    now = datetime.now(timezone.utc).isoformat()
    fid = feed_id or f"{_FEED_ID_BASE}main-feed"
    surl = self_url or _SELF_URL

    entries = []
    for i, article in enumerate(articles[:max_entries]):
        try:
            entries.append(_article_to_entry(article, i))
        except Exception as e:
            default_logger.warning(f"Entrée Atom ignorée (index {i}) : {e}")

    entries_xml = "\n".join(entries)

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>{_escape(feed_title)}</title>
  <id>{_escape(fid)}</id>
  <updated>{now}</updated>
  <link href="{_escape(surl)}" rel="self" type="application/atom+xml"/>
  <generator uri="https://github.com/patrickostertag/WUDD.ai">WUDD.ai</generator>
{entries_xml}
</feed>"""


def generate_atom_from_flux(project_root: Path, flux: str, max_entries: int = 50, self_url: Optional[str] = None) -> str:
    """Génère un flux Atom pour un flux donné (dossier data/articles/<flux>/).

    Args:
        project_root : racine du projet
        flux         : nom du flux (ex: "Intelligence-artificielle")
        max_entries  : nombre max d'entrées
        self_url     : URL canonique du feed (utilise l'URL de la requête si fournie)

    Returns:
        Chaîne XML du flux Atom.
    """
    flux_dir = project_root / "data" / "articles" / flux
    articles = []

    if flux_dir.exists():
        for json_file in sorted(flux_dir.rglob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True):
            if "cache" in str(json_file):
                continue
            try:
                data = json.loads(json_file.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    articles.extend(data)
            except Exception:
                continue

    # Tri chronologique robuste (corpus mixte ISO 8601 / DD/MM/YYYY / RFC 2822).
    articles.sort(
        key=lambda a: parse_article_date(a.get("Date de publication", "")) or datetime.min,
        reverse=True,
    )
    return generate_atom_feed(
        articles,
        feed_title=f"WUDD.ai · {flux}",
        feed_id=f"{_FEED_ID_BASE}flux-{flux.lower()}",
        self_url=self_url or f"{_SELF_URL}?flux={flux}",
        max_entries=max_entries,
    )
