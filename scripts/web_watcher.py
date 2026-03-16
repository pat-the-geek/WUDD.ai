#!/usr/bin/env python3
"""
web_watcher.py — Surveillance des sources web sans flux RSS (via sitemap.xml)

Appelé périodiquement par cron (toutes les 2h).
Pour chaque source active dans config/web_sources.json :
  - Lit le sitemap.xml pour découvrir les nouvelles URLs (filtrées par url_pattern)
  - Pour chaque nouvelle URL (non encore traitée, max max_per_run par run) :
      * Fetch la page HTML
      * Extrait titre, date, texte, images avec BeautifulSoup
      * Vérifie la présence d'un mot-clé (keyword_filter ou keyword) dans le titre — sinon ignoré
      * Génère un résumé en français via l'API EurIA
      * Sauvegarde dans data/articles-from-rss/<keyword>.json (sans doublon)
      * Met à jour data/articles-from-rss/_WUDD.AI_/48-heures.json

État persisté dans data/web_watcher_state.json :
  { "source_name": {"processed_urls": ["url1", "url2", ...]} }

Usage:
    python3 scripts/web_watcher.py
    python3 scripts/web_watcher.py --dry-run         # Liste les URLs sans appel IA
    python3 scripts/web_watcher.py --source moma-ps1-programs  # Source unique
"""

import argparse
import json
import re
import sys
import requests
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin
from bs4 import BeautifulSoup

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.api_client import get_ai_client
from utils.article_index import get_article_index
from utils.entity_index import get_entity_index
from utils.logging import print_console
from utils.quota import get_quota_manager
from utils.rolling_window import update_rolling_window
from utils.source_credibility import CredibilityEngine

_credibility = CredibilityEngine(PROJECT_ROOT)

# ─── Constantes ──────────────────────────────────────────────────────────────

CONFIG_PATH  = PROJECT_ROOT / "config" / "web_sources.json"
STATE_FILE   = PROJECT_ROOT / "data" / "web_watcher_state.json"
OUTPUT_DIR   = PROJECT_ROOT / "data" / "articles-from-rss"
WUDD_DIR     = OUTPUT_DIR / "_WUDD.AI_"
HTTP_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; WUDD.ai/2.2; +https://wudd.ai)"}

# Domaines de stockage générique dont les URLs og:image sont peu fiables
GENERIC_IMAGE_HOSTS = {"filepicker.io", "filestack.com", "cloudinary.com"}

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
WUDD_DIR.mkdir(parents=True, exist_ok=True)

# ─── Utilitaires généraux ────────────────────────────────────────────────────

def _write_atomic(path: Path, data: list | dict) -> None:
    """Écriture atomique JSON via fichier temporaire."""
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=4), encoding="utf-8")
    tmp.replace(path)


def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_state(state: dict) -> None:
    _write_atomic(STATE_FILE, state)


def _normalize_url(url: str) -> str:
    """Normalise une URL pour déduplication (lowercase + retire slash final)."""
    return url.strip().rstrip("/").lower()


# ─── Gestion des dates ───────────────────────────────────────────────────────

# Formats ISO 8601 non-ambigus — testés en priorité pour toutes les langues
_DATE_FORMATS_ISO = [
    "%Y-%m-%dT%H:%M:%S.%fZ",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d",
    "%Y/%m/%d",
]

# Formats locale-dépendants pour les sites en anglais (MM/DD/YYYY en priorité)
_DATE_FORMATS_EN = [
    "%m/%d/%Y",   # 03/09/2026 → March 9, 2026
    "%m-%d-%Y",   # 03-09-2026 → March 9, 2026
    "%B %d, %Y",  # March 9, 2026
    "%b %d, %Y",  # Mar 9, 2026
    "%d/%m/%Y",   # 09/03/2026 — fallback si le site utilise le format européen
]

# Formats locale-dépendants pour les sites en français (DD/MM/YYYY en priorité)
_DATE_FORMATS_FR = [
    "%d/%m/%Y",   # 09/03/2026 → 9 mars 2026 (format français)
    "%d-%m-%Y",   # 09-03-2026 → 9 mars 2026
    "%d.%m.%Y",   # 09.03.2026 → 9 mars 2026
    "%m/%d/%Y",   # fallback si le site utilise le format américain
]


def _parse_date(date_str: str, langue: str = "en") -> datetime:
    """Parse une date selon la langue de la source.

    Tente d'abord les formats ISO 8601 non-ambigus (valables quelle que soit
    la langue), puis les formats locale-dépendants dans l'ordre approprié :
    - langue='en' : MM/DD/YYYY prioritaire (format américain)
    - langue='fr' : DD/MM/YYYY prioritaire (format français)

    Fallback : maintenant (datetime.utcnow()).
    """
    if not date_str:
        return datetime.utcnow()
    clean = re.sub(r"[+-]\d{2}:\d{2}$", "", date_str.strip())

    # Formats ISO (non-ambigus) — priorité maximale
    for fmt in _DATE_FORMATS_ISO:
        try:
            return datetime.strptime(clean[:26], fmt)
        except (ValueError, TypeError):
            continue

    # Formats locale-dépendants selon la langue de la source
    locale_formats = _DATE_FORMATS_FR if langue == "fr" else _DATE_FORMATS_EN
    for fmt in locale_formats:
        try:
            return datetime.strptime(clean, fmt)
        except (ValueError, TypeError):
            continue

    return datetime.utcnow()


def _fmt_ddmmyyyy(dt: datetime) -> str:
    return dt.strftime("%d/%m/%Y")


# ─── Lecture sitemap ─────────────────────────────────────────────────────────

def _find_el(parent, tag_ns: str, tag_plain: str):
    """Cherche un élément d'abord avec namespace, puis sans. Évite l'opérateur
    `or` sur les éléments ElementTree (déprécié depuis Python 3.8)."""
    el = parent.find(tag_ns)
    if el is None:
        el = parent.find(tag_plain)
    return el


def _findall_el(parent, tag_ns: str, tag_plain: str) -> list:
    """Cherche des éléments d'abord avec namespace, puis sans."""
    results = parent.findall(tag_ns)
    if not results:
        results = parent.findall(tag_plain)
    return results


def _fetch_sitemap(sitemap_url: str, depth: int = 0) -> list[tuple[str, str]]:
    """Parse un sitemap.xml (ou sitemapindex) et retourne [(url, lastmod), …].

    Gère les sitemapindex récursivement (profondeur max 2).
    lastmod est '' si absent dans le sitemap.
    """
    if depth > 2:
        return []
    SM = "http://www.sitemaps.org/schemas/sitemap/0.9"
    results: list[tuple[str, str]] = []
    try:
        resp = requests.get(sitemap_url, timeout=15, headers=HTTP_HEADERS)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        tag = root.tag  # ex: "{http://...}urlset" ou "{http://...}sitemapindex"

        if "sitemapindex" in tag:
            for sm in _findall_el(root, f"{{{SM}}}sitemap", "sitemap"):
                loc = _find_el(sm, f"{{{SM}}}loc", "loc")
                if loc is not None and loc.text:
                    results.extend(_fetch_sitemap(loc.text.strip(), depth + 1))
        else:
            for url_el in _findall_el(root, f"{{{SM}}}url", "url"):
                loc = _find_el(url_el, f"{{{SM}}}loc", "loc")
                lm  = _find_el(url_el, f"{{{SM}}}lastmod", "lastmod")
                if loc is not None and loc.text:
                    lastmod = lm.text.strip() if lm is not None and lm.text else ""
                    results.append((loc.text.strip(), lastmod))
    except Exception as e:
        print_console(f"Erreur sitemap {sitemap_url} : {e}", level="error")
    return results


# ─── Extraction de contenu de page ───────────────────────────────────────────

def _extract_page(url: str) -> dict | None:
    """Fetch une page HTML et extrait : titre, date, texte, images.

    Retourne None en cas d'erreur HTTP ou réseau.
    """
    try:
        resp = requests.get(url, timeout=15, headers=HTTP_HEADERS)
        resp.raise_for_status()
    except requests.exceptions.HTTPError as e:
        code = e.response.status_code if e.response is not None else "?"
        print_console(f"HTTP {code} — {url}", level="warning")
        return None
    except Exception as e:
        print_console(f"Erreur réseau {url} : {e}", level="error")
        return None

    soup = BeautifulSoup(resp.content, "html.parser")

    # ── Titre ────────────────────────────────────────────────────────────────
    title = ""
    og = soup.find("meta", property="og:title")
    if og:
        title = og.get("content", "").strip()
    if not title:
        h1 = soup.find("h1")
        if h1:
            title = h1.get_text(strip=True)
    if not title:
        t = soup.find("title")
        if t:
            title = t.get_text(strip=True)

    # ── Date de publication ───────────────────────────────────────────────────
    pub_date_str = ""
    time_tag = soup.find("time", attrs={"datetime": True})
    if time_tag:
        pub_date_str = time_tag["datetime"]
    if not pub_date_str:
        for prop in ("article:published_time", "og:updated_time", "article:modified_time"):
            pmeta = soup.find("meta", property=prop)
            if pmeta:
                pub_date_str = pmeta.get("content", "")
                break

    # ── Texte principal (nettoyé) ─────────────────────────────────────────────
    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "noscript"]):
        tag.decompose()
    raw = soup.get_text(separator="\n", strip=True)
    lines = [ln for ln in raw.splitlines() if ln.strip()]
    text = "\n".join(lines)[:10000]

    # ── Image principale (Open Graph + twitter:image + fallback <img>) ─────────
    images = []
    fallback_og = None
    for prop in ("og:image", "twitter:image"):
        meta = soup.find("meta", property=prop) or soup.find("meta", attrs={"name": prop})
        if meta:
            img_url = meta.get("content", "").strip()
            if img_url:
                img_url = urljoin(url, img_url)  # résout les URLs relatives
                try:
                    w_tag = soup.find("meta", property="og:image:width")
                    width = int(w_tag.get("content", 1200)) if w_tag else 1200
                except (ValueError, TypeError):
                    width = 1200
                from urllib.parse import urlparse
                host = urlparse(img_url).netloc.lower()
                if any(h in host for h in GENERIC_IMAGE_HOSTS):
                    fallback_og = {"URL": img_url, "Width": width}
                else:
                    images.append({"URL": img_url, "Width": width})
                break
    # Fallback : première <img> pertinente dans le corps de l'article
    if not images:
        for img_tag in soup.find_all("img", src=True):
            src = img_tag.get("src", "").strip()
            if not src or src.startswith("data:"):
                continue
            src = urljoin(url, src)
            try:
                w = int(img_tag.get("width", 0))
            except (ValueError, TypeError):
                w = 0
            if w >= 300 or w == 0:
                images.append({"URL": src, "Width": w if w > 0 else 800})
                break

    # Dernier recours : og:image générique si aucune meilleure image trouvée
    if not images and fallback_og:
        images.append(fallback_og)

    return {
        "title": title,
        "pub_date_str": pub_date_str,
        "text": text,
        "images": images,
    }


# ─── Mise à jour 48-heures.json — déléguée à utils/rolling_window.py ─────────


# ─── Traitement d'une source ─────────────────────────────────────────────────

def _fetch_source_urls(
    source: dict,
    src_state: dict,
) -> list[tuple[str, str]]:
    """Lit le sitemap et retourne les nouvelles URLs filtrées, triées par lastmod décroissant.

    Args:
        source    : définition de la source (config/web_sources.json)
        src_state : état de la source {"processed_urls": [...]}

    Returns:
        Liste de (url, lastmod) — nouvelles URLs non encore traitées, max max_per_run.
    """
    sitemap_url = source["sitemap_url"]
    url_pattern = source["url_pattern"]
    langue      = source.get("langue", "en")
    max_per_run = source.get("max_per_run", 5)
    base_url    = source.get("base_url", "").rstrip("/")

    processed_set = {_normalize_url(u) for u in src_state.get("processed_urls", [])}

    all_entries = _fetch_sitemap(sitemap_url)
    if not all_entries:
        print_console("  Sitemap vide ou inaccessible.", level="warning")
        return []
    print_console(f"  {len(all_entries)} URLs dans le sitemap.")

    pat = re.compile(url_pattern)
    new_entries: list[tuple[str, str]] = []
    for url, lastmod in all_entries:
        full_url = (base_url + url) if url.startswith("/") else url
        if pat.search(full_url) and _normalize_url(full_url) not in processed_set:
            new_entries.append((full_url, lastmod))

    print_console(f"  {len(new_entries)} nouvelles URLs correspondant au pattern.")

    if not new_entries:
        return []

    # Trier par lastmod décroissant (plus récentes en premier), limiter à max_per_run
    new_entries.sort(
        key=lambda e: _parse_date(e[1], langue=langue) if e[1] else datetime.min,
        reverse=True,
    )
    return new_entries[:max_per_run]


def _process_article(
    url: str,
    lastmod: str,
    source: dict,
    api_client,
    quota,
    src_state: dict,
    processed_set: set,
    existing_urls: set,
) -> dict | None:
    """Traite une URL : extraction → filtre mot-clé → résumé + NER → article dict.

    Met à jour src_state et processed_set dans tous les cas (traité ou ignoré).

    Returns:
        Article dict si l'article a été produit, None si ignoré/erreur.
    """
    keyword   = source["keyword"]
    title_src = source["title"]
    langue    = source.get("langue", "en")

    print_console(f"  → {url[:90]}")

    # Doublon tardif
    if url in existing_urls:
        src_state["processed_urls"].append(url)
        processed_set.add(_normalize_url(url))
        return None

    # Extraction du contenu de la page
    page = _extract_page(url)
    if not page:
        src_state["processed_urls"].append(url)
        processed_set.add(_normalize_url(url))
        return None

    # Filtre par mot-clé sur le titre
    keyword_filter = source.get("keyword_filter") or [keyword]
    if not any(kw.lower() in page["title"].lower() for kw in keyword_filter):
        print_console(
            f"    ✗ Hors sujet (aucun mot-clé parmi {keyword_filter[:3]} dans le titre) — ignoré"
        )
        src_state["processed_urls"].append(url)
        processed_set.add(_normalize_url(url))
        return None

    # Date de publication
    pub_date_str = page["pub_date_str"] or lastmod
    pub_dt = _parse_date(pub_date_str, langue=langue)
    pub_date_fmt = _fmt_ddmmyyyy(pub_dt)

    # Résumé via API IA
    lang_label = "français" if langue == "fr" else "français (article source en anglais)"
    context = f"Source : {title_src}\nURL : {url}\n\n{page['text']}"
    resume = api_client.generate_summary(context, max_lines=15, language=lang_label)

    # Extraction des entités nommées (NER)
    print_console("    Extraction des entités nommées…")
    entities = api_client.generate_entities(resume)

    # Vérification quota par entité (après NER, avant sauvegarde)
    if entities:
        ok, saturated = quota.can_process_entities(entities)
        if not ok:
            print_console(
                f"  Quota entités saturé ({', '.join(saturated[:3])}) — article ignoré.",
                level="warning",
            )
            src_state["processed_urls"].append(url)
            processed_set.add(_normalize_url(url))
            return None

    # Construction de l'article (format standard WUDD.ai)
    article: dict = {
        "Date de publication": pub_date_fmt,
        "Sources": title_src,
        "URL": url,
        "Résumé": resume,
        "Images": page["images"],
        "score_source": round(_credibility.get_composite_score(title_src)),
    }
    if entities:
        article["entities"] = entities
    if page["title"]:
        article["Titre"] = page["title"]

    quota.record_article(keyword, title_src, entities)
    src_state["processed_urls"].append(url)
    processed_set.add(_normalize_url(url))

    print_console(f"    ✓ {(page['title'] or url)[:70]}")
    return article


def _process_source(
    source: dict,
    state: dict,
    api_client,
    quota,
    dry_run: bool,
) -> int:
    """Orchestre le traitement d'une source : découverte → extraction → sauvegarde.

    Retourne le nombre d'articles ajoutés.
    """
    name      = source["name"]
    title_src = source["title"]
    keyword   = source["keyword"]

    print_console(f"\n[web_watcher] ── {title_src} ──────────────────────────────")

    src_state     = state.setdefault(name, {"processed_urls": []})
    processed_set = {_normalize_url(u) for u in src_state["processed_urls"]}

    to_process = _fetch_source_urls(source, src_state)
    if not to_process:
        return 0

    # Fichier de sortie pour ce keyword
    out_path = OUTPUT_DIR / f"{keyword.replace(' ', '-').lower()}.json"
    existing_articles: list = []
    existing_urls: set = set()
    if out_path.exists():
        try:
            existing_articles = json.loads(out_path.read_text(encoding="utf-8"))
            existing_urls = {a.get("URL", "") for a in existing_articles}
        except Exception:
            pass

    added = 0
    new_for_48h: list = []

    for url, lastmod in to_process:
        if dry_run:
            print_console(f"  [dry-run] {url[:90]}")
            continue

        if quota.is_global_exhausted():
            print_console("  Quota global épuisé — arrêt.", level="warning")
            break

        if not quota.can_process(keyword, title_src):
            print_console(f"  Quota '{keyword}' atteint — arrêt.", level="warning")
            break

        article = _process_article(
            url, lastmod, source, api_client, quota,
            src_state, processed_set, existing_urls,
        )
        if article is None:
            continue

        existing_articles.append(article)
        existing_urls.add(url)
        new_for_48h.append(article)
        added += 1

    # Sauvegarde
    if added > 0:
        existing_articles.sort(
            key=lambda a: (
                datetime.strptime(a.get("Date de publication", ""), "%d/%m/%Y")
                if a.get("Date de publication") else datetime.min
            ),
            reverse=True,
        )
        _write_atomic(out_path, existing_articles)

        # Mise à jour des indexes article + entités
        try:
            _rel_kw = str(out_path.relative_to(PROJECT_ROOT)).replace("\\", "/")
            get_article_index(PROJECT_ROOT).update(existing_articles, _rel_kw)
            if any("entities" in a for a in existing_articles):
                get_entity_index(PROJECT_ROOT).update(existing_articles, _rel_kw)
        except Exception as _e:
            print_console(f"  Avertissement : index non mis à jour ({_e})", level="warning")

        # Mise à jour 48-heures.json via rolling_window
        WUDD_DIR.mkdir(parents=True, exist_ok=True)
        wudd_path = WUDD_DIR / "48-heures.json"
        nb_48h = update_rolling_window(new_for_48h, wudd_path, hours=48)
        print_console(f"48-heures.json : +{len(new_for_48h)} web | {nb_48h} total dans la fenêtre 48h")

        # Mise à jour de l'index pour 48-heures.json
        try:
            _wudd_articles = json.loads(wudd_path.read_text(encoding="utf-8"))
            _rel_wudd = str(wudd_path.relative_to(PROJECT_ROOT)).replace("\\", "/")
            get_article_index(PROJECT_ROOT).update(_wudd_articles, _rel_wudd)
            if any("entities" in a for a in _wudd_articles):
                get_entity_index(PROJECT_ROOT).update(_wudd_articles, _rel_wudd)
        except Exception as _e_48:
            print_console(f"  Avertissement : index 48h non mis à jour ({_e_48})", level="warning")

        print_console(f"  → {added} article(s) sauvegardé(s) dans {out_path.name}")

    return added


# ─── Point d'entrée ──────────────────────────────────────────────────────────

def main(dry_run: bool = False, source_filter: str | None = None) -> None:
    if not CONFIG_PATH.exists():
        print_console(f"Config introuvable : {CONFIG_PATH}", level="error")
        sys.exit(1)

    try:
        sources: list = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        print_console(f"Erreur lecture config : {e}", level="error")
        sys.exit(1)

    active = [s for s in sources if s.get("actif", True)]
    if source_filter:
        active = [s for s in active if s["name"] == source_filter]

    if not active:
        print_console("Aucune source active.", level="warning")
        return

    quota = get_quota_manager()
    if not dry_run and quota.is_global_exhausted():
        print_console("Quota global épuisé — web_watcher ignoré.", level="warning")
        return

    api_client = None if dry_run else get_ai_client()
    state = _load_state()

    total = 0
    for source in active:
        total += _process_source(source, state, api_client, quota, dry_run)

    if not dry_run:
        _save_state(state)

    print_console(f"\n[web_watcher] Terminé — {total} article(s) ajouté(s) au total.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="WUDD.ai — Surveillance sources web sans RSS (sitemap)"
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Liste les nouvelles URLs sans appel IA ni sauvegarde")
    parser.add_argument("--source", metavar="NAME",
                        help="Traite uniquement la source avec ce nom (ex: anthropic-news)")
    args = parser.parse_args()
    main(dry_run=args.dry_run, source_filter=args.source)
