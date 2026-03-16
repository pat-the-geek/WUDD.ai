"""
Script : get-keyword-from-rss.py

Pour chaque flux RSS dans WUDD.opml :
- Consulte le flux RSS (xmlUrl)
- Pour chaque article publié il y a moins d'une semaine :
    - Si le titre contient un mot-clé de keyword-to-search.json :
        - Enregistre l'URL dans un fichier JSON nommé par mot-clé (sans doublon)
        - Format de sortie = articles_generated_YYYY-MM-DD_YYYY-MM-DD.json
        - Résumé généré par IA EurIA (Qwen3)
        - Images extraites selon la méthode du projet
        - Clés : Date de publication, Sources, URL, Résumé, Images
        - Fichiers créés dans data/articles-from-rss/
"""


import os
import re
import sys
import json
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Ajout du dossier racine au sys.path pour les imports relatifs (utils.*)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.api_client import get_ai_client
from utils.article_index import get_article_index
from utils.deduplication import Deduplicator
from utils.entity_index import get_entity_index
from utils.http_utils import fetch_and_extract_text, extract_top_n_largest_images
from utils.logging import print_console
from utils.quota import get_quota_manager
from utils.rolling_window import update_rolling_window
from utils.source_credibility import CredibilityEngine

# Constantes

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OPML_PATH = PROJECT_ROOT / "data/WUDD.opml"
KEYWORDS_PATH = PROJECT_ROOT / "config/keyword-to-search.json"
OUTPUT_DIR = PROJECT_ROOT / "data/articles-from-rss"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
PROGRESS_FILE = PROJECT_ROOT / "data" / "rss_progress.json"


def _write_progress(data: dict) -> None:
    """Écrit (de manière atomique) le fichier de progression."""
    try:
        tmp = PROGRESS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(PROGRESS_FILE)
    except Exception:
        pass  # Ne jamais planter le script à cause du tracking


def _parse_feed_items(xml_root) -> list:
    """Extrait et normalise les articles d'un flux RSS 2.0 ou Atom.

    Retourne une liste de tuples (title, link, pub_date_str, pub_dt) où
    pub_date_str est toujours au format RFC 822 pour cohérence avec le pipeline.
    """
    ATOM_NS = "http://www.w3.org/2005/Atom"
    normalized = []

    # ── RSS 2.0 : balises <item> ──────────────────────────────────────────────
    for item in xml_root.findall(".//item"):
        title     = item.findtext("title") or ""
        link      = item.findtext("link") or ""
        pub_date  = item.findtext("pubDate") or ""
        try:
            pub_dt = datetime.strptime(pub_date[:25], "%a, %d %b %Y %H:%M:%S")
        except Exception:
            continue
        normalized.append((title, link, pub_date, pub_dt))

    # ── Atom : balises <entry> ────────────────────────────────────────────────
    for entry in xml_root.findall(f".//{{{ATOM_NS}}}entry"):
        title = entry.findtext(f"{{{ATOM_NS}}}title") or ""
        # Lien : préfère rel="alternate", sinon premier <link>
        link = ""
        for lk in entry.findall(f"{{{ATOM_NS}}}link"):
            if lk.get("rel", "alternate") in ("alternate", ""):
                link = lk.get("href", "")
                break
        if not link:
            lk = entry.find(f"{{{ATOM_NS}}}link")
            if lk is not None:
                link = lk.get("href", "")
        # Date : <published> ou <updated>
        pub_date_iso = (
            entry.findtext(f"{{{ATOM_NS}}}published") or
            entry.findtext(f"{{{ATOM_NS}}}updated") or ""
        )
        if not pub_date_iso:
            continue
        try:
            pub_dt_aware = datetime.fromisoformat(pub_date_iso.replace("Z", "+00:00"))
            pub_dt = pub_dt_aware.replace(tzinfo=None)
            # Convertir en RFC 822 pour cohérence avec le reste du pipeline
            pub_date_rfc = pub_dt.strftime("%a, %d %b %Y %H:%M:%S")
        except Exception:
            continue
        normalized.append((title, link, pub_date_rfc, pub_dt))

    return normalized

# Fenêtre temporelle : 7 derniers jours
now = datetime.utcnow()
one_week_ago = now - timedelta(days=7)

one_week_ago = now - timedelta(days=7)

# Charger les mots-clés (objets complets pour accéder aux collections or/and)
print_console("Chargement des mots-clés depuis keyword-to-search.json...")
with open(KEYWORDS_PATH, "r", encoding="utf-8") as f:
    keywords = json.load(f)
print_console(f"{len(keywords)} mots-clés chargés : {[k['keyword'] for k in keywords]}")

# Charger les flux RSS depuis OPML
print_console("Chargement des flux RSS depuis WUDD.opml...")
with open(OPML_PATH, "r", encoding="utf-8") as f:
    tree = ET.parse(f)
    root = tree.getroot()
    outlines = root.findall(".//outline[@type='rss']")
    feeds = [(o.attrib["xmlUrl"], o.attrib.get("title", "Unknown")) for o in outlines]
print_console(f"{len(feeds)} flux RSS trouvés.")

# Fenêtre temporelle : 7 derniers jours
now = datetime.utcnow()
one_week_ago = now - timedelta(days=7)
print_console(f"Fenêtre temporelle : {one_week_ago.date()} à {now.date()}")

# Initialiser le client IA
print_console("Initialisation du client IA...")
api_client = get_ai_client()

# Initialiser la crédibilité sources (proposition 3)
_credibility = CredibilityEngine(PROJECT_ROOT)

# Initialiser le gestionnaire de quotas
quota = get_quota_manager()
if quota.enabled:
    print_console(f"Quotas activés — global: {quota._config.get('global_daily_limit')}/j, "
                  f"par mot-clé: {quota._config.get('per_keyword_daily_limit')}/j, "
                  f"par source: {quota._config.get('per_source_daily_limit')}/source, "
                  f"par entité: {quota._config.get('per_entity_daily_limit', 10)}/entité")
else:
    print_console("Quotas désactivés.")

# Index par mot-clé
results = {kw_obj["keyword"]: {} for kw_obj in keywords}

# Démarrage du suivi de progression
_progress = {
    "started_at": datetime.now(timezone.utc).isoformat(),
    "finished_at": None,
    "current_feed_idx": 0,
    "current_feed_title": "",
    "total_feeds": len(feeds),
    "last_action": "Démarrage…",
    "articles_added": 0,
    "returncode": None,
}
_write_progress(_progress)

total_feeds = len(feeds)
for feed_idx, (feed_url, feed_title) in enumerate(feeds, 1):
    _progress["current_feed_idx"] = feed_idx
    _progress["current_feed_title"] = feed_title
    _progress["last_action"] = f"Lecture flux : {feed_title}"
    _write_progress(_progress)
    print_console(f"Lecture du flux {feed_idx} sur {total_feeds} : {feed_title} ({feed_url})")
    try:
        resp = requests.get(feed_url, timeout=15)
        resp.raise_for_status()
        print_console(f"  ✓ Flux chargé avec succès.")
        rss = ET.fromstring(resp.content)
        parsed_items = _parse_feed_items(rss)
        print_console(f"  {len(parsed_items)} articles trouvés dans le flux.")
        for idx, (title, link, pub_date, pub_dt) in enumerate(parsed_items, 1):
            if pub_dt < one_week_ago:
                continue
            # Arrêt global si le plafond journalier est atteint
            if quota.is_global_exhausted():
                print_console("Plafond global de quota atteint — traitement interrompu.", level="warning")
                break
            # Tri adaptatif : traiter en priorité les mots-clés les moins consommés
            kw_names = [k["keyword"] for k in keywords]
            sorted_kw_names = quota.sort_by_priority(kw_names)
            kw_map = {k["keyword"]: k for k in keywords}
            sorted_keywords = [kw_map[n] for n in sorted_kw_names]
            for kw_obj in sorted_keywords:
                kw = kw_obj["keyword"]
                or_words = kw_obj.get("or", [])
                and_words = kw_obj.get("and", [])
                title_lower = title.lower()

                # 1. Correspondance sur le mot-clé principal (frontière de mot pour éviter les faux positifs)
                matched = bool(re.search(r'\b' + re.escape(kw.lower()) + r'\b', title_lower))

                # 2. Si pas trouvé, tester les mots de la collection "or" (frontière de mot)
                if not matched and or_words:
                    matched = any(re.search(r'\b' + re.escape(w.lower()) + r'\b', title_lower) for w in or_words)

                # 3. Si correspondance, vérifier la contrainte "and" (au moins un mot présent, frontière de mot)
                if matched and and_words:
                    matched = any(re.search(r'\b' + re.escape(w.lower()) + r'\b', title_lower) for w in and_words)

                if not matched:
                    continue

                out_path = OUTPUT_DIR / f"{kw.replace(' ', '-').lower()}.json"
                # Charger existant pour éviter doublons
                if out_path.exists():
                    with open(out_path, "r", encoding="utf-8") as f:
                        existing_urls = {a["URL"] for a in json.load(f)}
                else:
                    existing_urls = set()
                # Vérifier si déjà traité
                if link in existing_urls or link in results[kw]:
                    print_console(f"    [Article {idx}] Déjà présent pour '{kw}', ignoré.", level="debug")
                    continue
                # Vérifier le quota (global + par mot-clé + par source)
                if not quota.can_process(kw, feed_title):
                    print_console(f"    [Article {idx}] Quota atteint pour '{kw}' / '{feed_title}', ignoré.", level="debug")
                    continue
                print_console(f"    [Article {idx}] Mot-clé '{kw}' trouvé dans le titre.")
                print_console(f"      Extraction du texte de l'article...")
                text = fetch_and_extract_text(link)
                if text.startswith("Erreur"):
                    print_console(f"      Article inaccessible ignoré ('{text[:70]}').", level="warning")
                    continue
                print_console(f"      Génération du résumé IA...")
                try:
                    resume = api_client.generate_summary(text, max_lines=20)
                except RuntimeError as e:
                    print_console(f"      Résumé impossible pour '{link}', article ignoré : {e}", level="warning")
                    continue
                print_console(f"      Extraction des entités nommées...")
                entities = api_client.generate_entities(resume)
                # Vérifier le quota par entité (après détection, avant ajout)
                if entities:
                    ok, saturated = quota.can_process_entities(entities)
                    if not ok:
                        print_console(f"      Quota entité atteint pour '{saturated}', article ignoré.", level="debug")
                        continue
                print_console(f"      Extraction de l'image principale...")
                images = extract_top_n_largest_images(link, n=1, min_width=500)
                article = {
                    "Titre": title,
                    "Date de publication": pub_dt.strftime("%d/%m/%Y"),
                    "Sources": feed_title,
                    "URL": link,
                    "Résumé": resume,
                    "Images": images,
                    "score_source": round(_credibility.get_composite_score(feed_title)),
                }
                if entities:
                    article["entities"] = entities
                results[kw][link] = article
                quota.record_article(kw, feed_title, entities if entities else None)
                _progress["articles_added"] += 1
                _progress["last_action"] = f"Article ajouté '{kw}' — {feed_title}"
                _write_progress(_progress)
                print_console(f"      ✓ Article ajouté pour '{kw}'.")
                # Vérification après ajout : quota global épuisé → stop ce flux
                if quota.is_global_exhausted():
                    print_console("Plafond global atteint après ajout — passage au flux suivant.", level="warning")
                    break
    except Exception as e:
        print_console(f"Erreur flux {feed_url}: {e}", level="error")

# Sauvegarde par mot-clé
for kw, articles in results.items():
    if not articles:
        print_console(f"Aucun article pour le mot-clé '{kw}', aucun fichier généré.", level="info")
        continue
    out_path = OUTPUT_DIR / f"{kw.replace(' ', '-').lower()}.json"
    # Charger existant pour éviter doublons
    if out_path.exists():
        with open(out_path, "r", encoding="utf-8") as f:
            existing_list = json.load(f)
        print_console(f"{len(existing_list)} articles déjà présents dans {out_path.name}")
    else:
        existing_list = []
    # Déduplication avancée (URL + similarité de titre)
    dedup = Deduplicator(title_threshold=0.85)
    new_list = list(articles.values())
    unique_new = dedup.deduplicate_incremental(new_list, existing_list)
    if dedup.stats["removed"] > 0:
        print_console(
            f"  Déduplication : {dedup.stats['removed']} doublon(s) supprimé(s) pour '{kw}'"
        )
    merged = existing_list + unique_new
    # Écriture atomique (H)
    _tmp_kw = out_path.with_suffix(".tmp")
    _tmp_kw.write_text(json.dumps(merged, ensure_ascii=False, indent=4), encoding="utf-8")
    _tmp_kw.replace(out_path)
    print_console(f"✓ {len(merged)} articles pour le mot-clé '{kw}' dans {out_path}")
    # Mise à jour des indexes article + entités (A)
    try:
        _rel_kw = str(out_path.relative_to(PROJECT_ROOT)).replace("\\", "/")
        get_article_index(PROJECT_ROOT).update(merged, _rel_kw)
        if any("entities" in a for a in merged):
            get_entity_index(PROJECT_ROOT).update(merged, _rel_kw)
    except Exception as _e:
        print_console(f"  Avertissement : index non mis à jour ({_e})", level="warning")

# ─────────────────────────────────────────────────────────────────────────────
# Génération du fichier 48-heures.json dans data/articles-from-rss/_WUDD.AI_/
# Reconstruit la fenêtre depuis tous les fichiers JSON d'articles-from-rss/
# ─────────────────────────────────────────────────────────────────────────────
print_console("Génération du fichier 48-heures.json (_WUDD.AI_)...")

WUDD_DIR = OUTPUT_DIR / "_WUDD.AI_"
WUDD_DIR.mkdir(parents=True, exist_ok=True)
wudd_path = WUDD_DIR / "48-heures.json"

nb_48h = update_rolling_window([], wudd_path, hours=48, source_dir=OUTPUT_DIR)
print_console(f"✓ {nb_48h} articles des dernières 48h dans {wudd_path}")

# Mise à jour de l'index pour 48-heures.json
try:
    _wudd_articles = json.loads(wudd_path.read_text(encoding="utf-8"))
    _rel_wudd = str(wudd_path.relative_to(PROJECT_ROOT)).replace("\\", "/")
    get_article_index(PROJECT_ROOT).update(_wudd_articles, _rel_wudd)
    if any("entities" in a for a in _wudd_articles):
        get_entity_index(PROJECT_ROOT).update(_wudd_articles, _rel_wudd)
except Exception as _e_48:
    print_console(f"  Avertissement : index 48h non mis à jour ({_e_48})", level="warning")

# Marquer la progression comme terminée
_progress["finished_at"] = datetime.now(timezone.utc).isoformat()
_progress["last_action"] = f"Terminé — {_progress['articles_added']} articles ajoutés"
_progress["returncode"] = 0
_write_progress(_progress)
