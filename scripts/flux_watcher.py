#!/usr/bin/env python3
"""
flux_watcher.py — Surveillance round-robin des flux RSS WUDD.opml

Appelé toutes les 5 minutes par cron.
Traite UN flux à la fois en round-robin depuis data/WUDD.opml :
  - Sélectionne le prochain flux non encore traité
  - Pour chaque article récent (≤ 7 jours) du flux :
      * Si le titre correspond à un mot-clé de keyword-to-search.json
      * Génère un résumé IA + entités NER + image principale
      * Sauvegarde dans data/articles-from-rss/<keyword>.json (sans doublon)
  - Met à jour data/articles-from-rss/_WUDD.AI_/48-heures.json de façon incrémentale

État mémorisé dans data/flux_watcher_state.json pour le round-robin.

Usage:
    python3 scripts/flux_watcher.py
    python3 scripts/flux_watcher.py --dry-run   # Affiche le flux sélectionné sans traitement IA
"""

import argparse
import json
import os
import re
import sys
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.api_client import get_ai_client, get_summary_client
from utils.http_utils import fetch_and_extract_text, extract_top_n_largest_images, RSS_FEED_HEADERS, fetch_rss_feed
from utils.logging import print_console
from utils.quota import get_quota_manager
from utils.article_index import get_article_index
from utils.entity_index import get_entity_index
from utils.rolling_window import update_rolling_window
from utils.rss_file_naming import keyword_json_path, keyword_alias_paths
from utils.ner_guardrails import sanitize_entities

# ─── Constantes ──────────────────────────────────────────────────────────────

OPML_PATH     = PROJECT_ROOT / "data" / "WUDD.opml"
KEYWORDS_PATH = PROJECT_ROOT / "config" / "keyword-to-search.json"
OUTPUT_DIR    = PROJECT_ROOT / "data" / "articles-from-rss"
STATE_FILE    = PROJECT_ROOT / "data" / "flux_watcher_state.json"
WUDD_DIR      = OUTPUT_DIR / "_WUDD.AI_"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
WUDD_DIR.mkdir(parents=True, exist_ok=True)

DATE_FORMAT_RSS = "%a, %d %b %Y %H:%M:%S"

# ─── Utilitaires ─────────────────────────────────────────────────────────────

def _write_atomic(path: Path, data: list | dict) -> None:
    """Écriture atomique d'un JSON via fichier temporaire."""
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=4), encoding="utf-8")
    tmp.replace(path)


def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"last_feed_idx": -1, "feed_count": 0, "last_feed_title": ""}


def _save_state(idx: int, total: int, feed_title: str, articles_added: int) -> None:
    _write_atomic(STATE_FILE, {
        "last_feed_idx": idx,
        "feed_count": total,
        "last_feed_title": feed_title,
        "last_run": datetime.now(timezone.utc).isoformat(),
        "articles_added": articles_added,
    })


def _parse_feed_items(xml_root) -> list:
    """Extrait et normalise les articles d'un flux RSS 2.0 ou Atom.

    Retourne une liste de tuples (title, link, pub_date_str, pub_dt, description)
    où description est le texte brut extrait de <description> (RSS) ou <summary> (Atom).
    Ce texte sert de fallback quand le fetch HTML de l'article échoue (ex. 403 Cloudflare).
    """
    import html as _html
    ATOM_NS = "http://www.w3.org/2005/Atom"
    normalized = []

    def _strip_html(raw: str) -> str:
        """Décode les entités HTML et supprime les balises."""
        raw = _html.unescape(raw or "")
        raw = re.sub(r'<[^>]+>', ' ', raw)
        return re.sub(r'\s+', ' ', raw).strip()

    for item in xml_root.findall(".//item"):
        title    = item.findtext("title") or ""
        link     = item.findtext("link") or ""
        pub_date = item.findtext("pubDate") or ""
        desc     = _strip_html(item.findtext("description") or "")
        try:
            pub_dt = datetime.strptime(pub_date[:25], DATE_FORMAT_RSS)
        except Exception:
            continue
        normalized.append((title, link, pub_date, pub_dt, desc))

    for entry in xml_root.findall(f".//{{{ATOM_NS}}}entry"):
        title = entry.findtext(f"{{{ATOM_NS}}}title") or ""
        link = ""
        for lk in entry.findall(f"{{{ATOM_NS}}}link"):
            if lk.get("rel", "alternate") in ("alternate", ""):
                link = lk.get("href", "")
                break
        if not link:
            lk = entry.find(f"{{{ATOM_NS}}}link")
            if lk is not None:
                link = lk.get("href", "")
        pub_date_iso = (
            entry.findtext(f"{{{ATOM_NS}}}published") or
            entry.findtext(f"{{{ATOM_NS}}}updated") or ""
        )
        if not pub_date_iso:
            continue
        try:
            pub_dt_aware = datetime.fromisoformat(pub_date_iso.replace("Z", "+00:00"))
            pub_dt = pub_dt_aware.replace(tzinfo=None)
            pub_date_rfc = pub_dt.strftime(DATE_FORMAT_RSS)
        except Exception:
            continue
        # Atom : description dans <summary> ou <content>
        desc = _strip_html(
            entry.findtext(f"{{{ATOM_NS}}}summary") or
            entry.findtext(f"{{{ATOM_NS}}}content") or ""
        )
        normalized.append((title, link, pub_date_rfc, pub_dt, desc))

    return normalized


# ─── Point d'entrée ──────────────────────────────────────────────────────────

def main(dry_run: bool = False) -> None:
    # Charger les flux depuis OPML
    if not OPML_PATH.exists():
        print_console(f"OPML introuvable : {OPML_PATH}", level="error")
        sys.exit(1)

    with open(OPML_PATH, "r", encoding="utf-8") as f:
        tree = ET.parse(f)
        root = tree.getroot()
        outlines = root.findall(".//outline[@type='rss']")
        feeds = [
            (
                o.attrib["xmlUrl"],
                o.attrib.get("title", "Unknown"),
                o.attrib.get("bypassQuota", "false").lower() == "true",
            )
            for o in outlines
        ]

    total = len(feeds)
    if total == 0:
        print_console("Aucun flux RSS trouvé dans WUDD.opml.", level="warning")
        return

    state = _load_state()
    next_idx = (state.get("last_feed_idx", -1) + 1) % total
    feed_url, feed_title, bypass_quota = feeds[next_idx]

    print_console(f"[flux_watcher] Flux [{next_idx + 1}/{total}] : {feed_title}")
    print_console(f"  URL : {feed_url}")

    validate_person_p31 = os.environ.get("NER_VALIDATE_PERSON_P31", "").strip().lower() in {
        "1", "true", "yes", "on"
    }
    if validate_person_p31:
        print_console("  [NER] Validation PERSON via Wikidata P31 active")

    if dry_run:
        print_console("=== DRY-RUN : aucun traitement IA effectué ===")
        _save_state(next_idx, total, feed_title, 0)
        return

    # Charger les mots-clés
    with open(KEYWORDS_PATH, "r", encoding="utf-8") as f:
        keywords = json.load(f)

    print_console(f"  {len(keywords)} mots-clés chargés.")

    # Initialiser le gestionnaire de quotas
    quota = get_quota_manager()
    if quota.enabled:
        print_console(f"  Quotas activés — global: {quota._config.get('global_daily_limit')}/j, "
                      f"par mot-clé: {quota._config.get('per_keyword_daily_limit')}/j, "
                      f"par source: {quota._config.get('per_source_daily_limit')}/source")

    # Arrêt immédiat si le plafond global est déjà atteint (sauf pour les flux bypassQuota)
    if not bypass_quota and quota.is_global_exhausted():
        print_console("Plafond global de quota atteint — flux_watcher ignoré.", level="warning")
        _save_state(next_idx, total, feed_title, 0)
        return
    if bypass_quota:
        print_console(f"  ⚡ Quota ignoré pour ce flux (bypassQuota activé).", level="info")

    now = datetime.utcnow()
    one_week_ago = now - timedelta(days=7)
    api_client = get_summary_client()
    new_articles_all: list = []

    # Titres déjà traités dans ce passage (dédup cross-sources par titre exact)
    _seen_titles: set[str] = set()

    # Charger les URLs masquées — ces articles ne seront pas réimportés
    _annotations_path = PROJECT_ROOT / "data" / "annotations.json"
    _hidden_urls: set[str] = set()
    if _annotations_path.exists():
        try:
            _ann = json.loads(_annotations_path.read_text(encoding="utf-8"))
            _hidden_urls = {url for url, ann in _ann.items() if ann.get("is_hidden")}
        except (json.JSONDecodeError, OSError):
            pass

    # Lire le flux (stratégie anti-403 : fallback session+cookies si besoin)
    try:
        resp = fetch_rss_feed(feed_url, timeout=15)
        rss = ET.fromstring(resp.content)
        parsed_items = _parse_feed_items(rss)
        print_console(f"  {len(parsed_items)} articles dans le flux.")
    except Exception as e:
        print_console(f"Erreur lecture flux {feed_url} : {e}", level="error")
        _save_state(next_idx, total, feed_title, 0)
        return

    for title, link, pub_date, pub_dt, rss_desc in parsed_items:
        if pub_dt < one_week_ago:
            continue

        # Arrêt global si quota épuisé (sauf pour les flux bypassQuota)
        if not bypass_quota and quota.is_global_exhausted():
            print_console("Plafond global de quota atteint — arrêt du traitement.", level="warning")
            break

        # Tri adaptatif : classer les mots-clés par consommation croissante
        kw_names = [k["keyword"] for k in keywords]
        sorted_kw_names = quota.sort_by_priority(kw_names)
        kw_map = {k["keyword"]: k for k in keywords}
        sorted_keywords = [kw_map[n] for n in sorted_kw_names]

        for kw_obj in sorted_keywords:
            kw        = kw_obj["keyword"]
            or_words  = kw_obj.get("or", [])
            and_words = kw_obj.get("and", [])
            title_lower = title.lower()

            trigger_term = None
            if re.search(r'\b' + re.escape(kw.lower()) + r'\b', title_lower):
                trigger_term = kw

            if trigger_term is None and or_words:
                trigger_term = next(
                    (w for w in or_words if re.search(r'\b' + re.escape(w.lower()) + r'\b', title_lower)),
                    None,
                )

            matched = trigger_term is not None

            if matched and and_words:
                matched = any(
                    re.search(r'\b' + re.escape(w.lower()) + r'\b', title_lower)
                    for w in and_words
                )
            if not matched:
                continue

            out_path = keyword_json_path(OUTPUT_DIR, kw)
            existing_urls: set = set()
            for alias_path in keyword_alias_paths(OUTPUT_DIR, kw):
                if not alias_path.exists():
                    continue
                try:
                    with open(alias_path, "r", encoding="utf-8") as f:
                        existing_urls.update(a.get("URL", "") for a in json.load(f) if isinstance(a, dict))
                except Exception:
                    pass
            existing_urls.discard("")

            if link in existing_urls:
                print_console(f"  Déjà présent pour '{kw}' : {link[:60]}...", level="debug")
                continue

            # Déduplication par titre exact cross-sources dans ce passage
            _title_key = title.strip().lower()
            if _title_key in _seen_titles:
                print_console(f"  Titre déjà traité par une autre source, ignoré : {title[:70]}", level="debug")
                continue

            # Vérifier si l'article est masqué par l'utilisateur
            if link in _hidden_urls:
                print_console(f"  Article masqué, ignoré pour '{kw}' : {link[:60]}...", level="debug")
                continue

            # Vérifier le quota (global + par mot-clé + par source) — sauf si bypassQuota activé
            if not bypass_quota and not quota.can_process(kw, feed_title):
                print_console(f"  Quota atteint pour '{kw}' / '{feed_title}', ignoré.", level="debug")
                continue

            print_console(f"  Mot-clé '{kw}' — {link[:70]}...")
            text = fetch_and_extract_text(link)
            if text.startswith("Erreur"):
                if rss_desc:
                    print_console(f"  Article inaccessible ({text[:50]}) — fallback description RSS ({len(rss_desc)} chars).", level="warning")
                    text = rss_desc
                else:
                    print_console(f"  Article inaccessible ignoré ('{text[:70]}').", level="warning")
                    continue
            try:
                resume = api_client.generate_summary(text, max_lines=20)
            except RuntimeError as e:
                print_console(f"  Résumé impossible : {e}", level="warning")
                continue

            entities = api_client.generate_entities(resume)
            if entities:
                entities = sanitize_entities(entities, validate_person_p31=validate_person_p31)
            # Vérifier le quota par entité (après détection, avant ajout) — sauf si bypassQuota activé
            if entities and not bypass_quota:
                ok, saturated = quota.can_process_entities(entities)
                if not ok:
                    print_console(f"  Quota entité atteint pour '{saturated}', article ignoré.", level="debug")
                    continue
            images   = extract_top_n_largest_images(link, n=1, min_width=500)
            if not isinstance(images, list):
                images = []

            article = {
                "Titre": title,
                "Date de publication": pub_date,
                "Sources": feed_title,
                "URL": link,
                "Résumé": resume,
                "Images": images,
                "mot_cle": kw,
                "terme_declencheur": trigger_term,
                "fichier_source": str(out_path.relative_to(PROJECT_ROOT)).replace("\\", "/"),
            }
            if entities:
                article["entities"] = entities

            # Relire le fichier cible (peut avoir changé entre deux itérations)
            existing_list: list = []
            if out_path.exists():
                try:
                    with open(out_path, "r", encoding="utf-8") as f:
                        existing_list = json.load(f)
                except Exception:
                    pass

            existing_list.append(article)
            _write_atomic(out_path, existing_list)
            print_console(f"  ✓ Ajouté dans {out_path.name}")
            _seen_titles.add(title.strip().lower())
            # Pour les flux bypassQuota, on n'incrémente pas les compteurs
            # afin de ne pas consommer le quota des autres flux.
            if not bypass_quota:
                quota.record_article(kw, feed_title, entities if entities else None)
            new_articles_all.append(article)
            # Si quota global atteint après cet ajout, sortir de la boucle mots-clés
            if not bypass_quota and quota.is_global_exhausted():
                print_console("Plafond global atteint après ajout.", level="warning")
                break

    # ── Mise à jour 48-heures.json via rolling_window (proposition 2) ───────
    wudd_path = WUDD_DIR / "48-heures.json"
    nb_48h = update_rolling_window(new_articles_all, wudd_path, hours=48)
    print_console(f"48-heures.json : +{len(new_articles_all)} nouveaux | {nb_48h} articles au total dans la fenêtre 48h")

    # ── Mise à jour des index (article_index + entity_index) ─────────────
    if new_articles_all:
        wudd_path_rel = str(wudd_path.relative_to(PROJECT_ROOT)).replace("\\", "/")
        try:
            # Lire le contenu mis à jour de 48-heures.json pour l'index
            _wudd_articles = json.loads(wudd_path.read_text(encoding="utf-8"))
            art_idx = get_article_index(PROJECT_ROOT)
            art_idx.update(_wudd_articles, source_file=wudd_path_rel)
            print_console(f"  article_index.json mis à jour ({len(new_articles_all)} article(s))")
        except Exception as e:
            print_console(f"  Mise à jour article_index ignorée : {e}", level="warning")
        try:
            ent_idx = get_entity_index(PROJECT_ROOT)
            ent_idx.update(_wudd_articles, source_file=wudd_path_rel)
            print_console(f"  entity_index.json mis à jour")
        except Exception as e:
            print_console(f"  Mise à jour entity_index ignorée : {e}", level="warning")

    # ── Mémoriser l'état ────────────────────────────────────────────────────
    _save_state(next_idx, total, feed_title, len(new_articles_all))
    print_console(
        f"[flux_watcher] Terminé — flux [{next_idx + 1}/{total}] "
        f"{feed_title} : {len(new_articles_all)} nouveaux articles."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Surveillance round-robin des flux RSS WUDD.opml (1 flux par exécution)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Sélectionne et mémorise le flux sans traitement IA"
    )
    args = parser.parse_args()
    main(dry_run=args.dry_run)
