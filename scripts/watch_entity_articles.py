#!/usr/bin/env python3
"""Veille horaire d'entités surveillées.

À chaque passage (cron horaire), détecte le dernier article fraîchement
collecté qui mentionne une entité de ``data/watched_entities.json`` et envoie
une notification Discord avec **grande image + résumé**. Au plus 1 article par
passage (le plus récent non encore notifié).

Garde-fous d'envoi :
  * **Fenêtre horaire** : notifications uniquement entre 7h et 22h (heure locale).
  * **1 notification par entité et par jour** : une entité déjà notifiée le jour
    même n'est pas re-notifiée (jour calendaire local).
  * **Filtre anti-publicité** : les articles promotionnels (bons plans, codes
    promo, soldes, contenus sponsorisés, affiliation…) ne sont pas notifiés.
  * **Priorité aux entités sous-médiatisées** : à fraîcheur comparable, on
    notifie d'abord l'article d'une entité ayant la plus faible présence
    médiatique récente (nb d'articles sur ~24h), pour équilibrer la couverture.

Détection via ``entity_index`` (mis à jour dès la collecte par flux_watcher et
get-keyword-from-rss). Les articles sans NER au moment de la collecte (ex. flux
RSS bruts) ne sont vus qu'après l'enrichissement NER nocturne.

État : ``data/watched_article_state.json`` (URLs déjà notifiées + date de
dernière notification par entité). Au premier lancement, l'état est initialisé
avec les articles existants SANS notifier (évite un flot initial) ; seuls les
articles apparus ensuite déclenchent un envoi.

Usage :
    python3 scripts/watch_entity_articles.py [--dry-run] [--force] [--max N]
        [--window-days D] [--no-commercial-filter] [--ignore-window]
"""

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from utils.logging import default_logger
from utils.config import get_config
from utils.date_utils import parse_article_date
from utils.entity_index import get_entity_index
from utils.deduplication import Deduplicator
from utils.entity_canonicalization import get_entity_canonicalizer

_WATCHED_FILE = _PROJECT_ROOT / "data" / "watched_entities.json"
_STATE_FILE = _PROJECT_ROOT / "data" / "watched_article_state.json"

_DEFAULT_MAX_PER_RUN = 1     # 1 article max par passage horaire
_DEFAULT_WINDOW_DAYS = 2     # ne considérer que les articles récents
_MAX_STATE_URLS = 1000       # borne la taille du fichier d'état

# Dédup inter-sources / inter-entités d'une MÊME histoire (anti-spam) : deux
# articles couvrant le même événement depuis des sources différentes ont des
# titres/résumés distincts (résumés générés par article) mais partagent leurs
# entités nommées saillantes. On déduplique donc par recouvrement d'entités
# (Jaccard), persisté entre passages, en complément du Deduplicator (doublons
# exacts URL/texte). Empêche qu'une même histoire soit notifiée plusieurs fois
# via plusieurs entités surveillées.
_STORY_SALIENT_TYPES = {
    "PERSON", "ORG", "LAW", "GPE", "PRODUCT", "EVENT", "WORK_OF_ART", "NORP", "FAC",
}
_STORY_SIM_THRESHOLD = 0.5   # Jaccard d'entités ≥ seuil → même histoire
_STORY_MIN_ENTITIES = 3      # en deçà, signature trop pauvre pour décider
_MAX_STATE_SIGS = 300        # borne la mémoire des histoires déjà notifiées

# Fenêtre horaire d'envoi des notifications (heure locale du conteneur).
# 7h00 inclus → 22h00 exclu (dernière notification possible à 21h59).
_NOTIFY_HOUR_START = 7
_NOTIFY_HOUR_END = 22

# Fenêtre de mesure de la « présence médiatique » d'une entité : nombre
# d'articles récents qui la mentionnent. Sert à favoriser, à fraîcheur égale,
# les entités les moins médiatisées.
_PRESENCE_WINDOW_DAYS = 1

# Heuristique anti-publicité : on ne notifie pas les articles promotionnels
# (bons plans, codes promo, soldes, contenus sponsorisés, affiliation…).
_COMMERCIAL_PATTERNS = [
    r"bons?\s+plans?",
    r"codes?\s+promo",
    r"code\s+promotionnel",
    r"code\s+avantage",
    r"\bsoldes?\b",
    r"black\s+friday",
    r"cyber\s+monday",
    r"prix\s+cass[ée]s?",
    r"meilleur\s+prix",
    r"à\s+prix\s+r[ée]duit",
    r"offres?\s+sp[ée]ciales?",
    r"offres?\s+exclusives?",
    r"contenus?\s+sponsoris[ée]s?",
    r"sponsoris[ée]s?",
    r"publi-?r[ée]dactionnel",
    r"publireportage",
    r"en\s+partenariat\s+avec",
    r"affili[ée]s?",
    r"\d{1,3}\s?%\s+de\s+r[ée]duction",
    r"\d{1,3}\s?%\s+de\s+remise",
]
_COMMERCIAL_RE = re.compile("|".join(_COMMERCIAL_PATTERNS), re.IGNORECASE)


def _is_commercial(article: dict) -> bool:
    """Détecte un article promotionnel/publicitaire qu'il ne faut pas notifier.

    Recherche des marqueurs commerciaux (bon plan, code promo, soldes, contenu
    sponsorisé, affiliation, % de réduction…) dans le titre/résumé/source/URL.
    """
    haystack = " ".join(
        s for s in (
            article.get("Titre") or "",
            article.get("Résumé") or "",
            article.get("Sources") or "",
            article.get("URL") or "",
        ) if s
    )
    return bool(_COMMERCIAL_RE.search(haystack))


def _media_presence(eidx, etype: str, value: str, cutoff: str) -> int:
    """Présence médiatique récente d'une entité = nb d'articles la mentionnant
    depuis ``cutoff`` (date ISO ``YYYY-MM-DD``). Plus le nombre est faible, plus
    l'entité est sous-médiatisée — et donc à favoriser.

    Repli : 0 en cas d'erreur (traité comme faible présence → favorisé).
    """
    try:
        refs = eidx.get_refs(etype, value)
    except Exception:
        return 0
    return sum(1 for r in refs if (r.get("date") or "") >= cutoff)


def _load_watched() -> list[dict]:
    if not _WATCHED_FILE.exists():
        return []
    try:
        data = json.loads(_WATCHED_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _load_state() -> dict:
    if not _STATE_FILE.exists():
        return {}
    try:
        data = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save_state(
    notified_urls: list[str],
    entity_daily: dict | None = None,
    notified_sigs: list[list[str]] | None = None,
) -> None:
    try:
        _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "notified": notified_urls[-_MAX_STATE_URLS:],
            "entity_daily": entity_daily or {},
            # Signatures d'entités des histoires déjà notifiées (dédup inter-sources).
            "notified_sigs": (notified_sigs or [])[-_MAX_STATE_SIGS:],
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        _STATE_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as exc:
        default_logger.warning(f"Impossible d'écrire {_STATE_FILE.name} : {exc}")


def _entity_signature(article: dict, canonicalizer=None) -> frozenset[str]:
    """Empreinte d'une histoire = ensemble de ses entités nommées saillantes.

    Robuste entre sources (contrairement au titre/résumé qui varient) : deux
    articles sur le même événement partagent l'essentiel de leurs entités. Les
    entités sont canonicalisées (« l'AI Act » → « AI Act ») pour que les
    variantes ne fassent pas diverger artificiellement la signature.
    """
    ents = article.get("entities") or {}
    if not isinstance(ents, dict):
        return frozenset()
    tokens: set[str] = set()
    for etype, values in ents.items():
        if etype not in _STORY_SALIENT_TYPES or not isinstance(values, list):
            continue
        for v in values:
            if not isinstance(v, str) or not v.strip():
                continue
            if canonicalizer is not None:
                ctype, cval = canonicalizer.canonicalize(etype, v)
                tokens.add(f"{ctype}:{cval.strip().lower()}")
            else:
                tokens.add(f"{etype}:{v.strip().lower()}")
    return frozenset(tokens)


def _same_story(sig: frozenset[str], seen_sigs: list[frozenset[str]]) -> bool:
    """Vrai si la signature recouvre fortement (Jaccard ≥ seuil) une histoire vue.

    Ignore les signatures trop pauvres (< _STORY_MIN_ENTITIES) pour éviter de
    fusionner à tort des articles peu annotés.
    """
    if len(sig) < _STORY_MIN_ENTITIES:
        return False
    for seen in seen_sigs:
        if len(seen) < _STORY_MIN_ENTITIES:
            continue
        inter = len(sig & seen)
        if inter == 0:
            continue
        union = len(sig | seen)
        if union and inter / union >= _STORY_SIM_THRESHOLD:
            return True
    return False


def _article_sort_key(article: dict):
    """Clé de tri par date de publication décroissante (None en dernier)."""
    dt = parse_article_date(article.get("Date de publication", ""), date_only_policy="end")
    return dt or datetime.min


def _is_fresh(article: dict, window_days: int) -> bool:
    """Vrai si la date de publication RÉELLE de l'article est < window_days jours.

    Re-vérification défensive : ne se fie pas à la seule date de l'index. Une
    date mal normalisée (ex. RFC 2822 stockée brute) pouvait passer le
    ``cutoff_date`` lexicographique de l'index et faire paraître un vieil article
    frais. On reparse ici la date du champ ``Date de publication`` et on écarte
    tout ce qui ne tombe pas dans la fenêtre (date non parsable → écarté : on ne
    notifie jamais un article dont la fraîcheur n'est pas prouvée).
    """
    dt = parse_article_date(article.get("Date de publication", ""), date_only_policy="end")
    if dt is None:
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt >= datetime.now(timezone.utc) - timedelta(days=window_days)


def collect_candidates(project_root: Path, watched: list[dict], window_days: int) -> list[dict]:
    """Retourne les articles récents mentionnant une entité surveillée.

    Returns:
        Liste de dict {article, entity_label}, dédupliquée par URL,
        triée par date de publication décroissante.
    """
    eidx = get_entity_index(project_root)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=window_days)).strftime("%Y-%m-%d")

    seen_urls: set[str] = set()
    candidates: list[dict] = []
    for w in watched:
        etype = (w.get("type") or "").strip().upper()
        value = (w.get("value") or "").strip()
        if not etype or not value:
            continue
        try:
            # canonicalize=True : fusionne les variantes d'une même entité
            # (ex. « l'AI Act » → « AI Act ») via config/entity_canonicalization.json,
            # pour une couverture et un plafond/dédup cohérents.
            arts = eidx.load_articles(
                etype, value, max_articles=20, cutoff_date=cutoff, canonicalize=True
            )
        except Exception as exc:
            default_logger.debug(f"load_articles({etype}:{value}) a échoué : {exc}")
            continue
        for art in arts:
            url = (art.get("URL") or "").strip()
            if not url or url in seen_urls:
                continue
            # Garde-fou de fraîcheur sur la VRAIE date (pas seulement l'index).
            if not _is_fresh(art, window_days):
                continue
            seen_urls.add(url)
            candidates.append({
                "article": art,
                "entity_label": value,
                "entity_type": etype,
                "entity_key": f"{etype}:{value}".lower(),
            })

    candidates.sort(key=lambda c: _article_sort_key(c["article"]), reverse=True)
    return candidates


def _format_summary_markdown(article: dict, entity_label: str) -> str:
    """Reformate le résumé d'un article en Markdown (chapitres + gras/italique).

    Délègue au helper partagé `utils.summary_formatter`. Compatible Discord
    (Markdown standard). Repli : chaîne vide → l'appelant utilise le résumé brut.
    """
    from utils.summary_formatter import format_summary_markdown
    return format_summary_markdown(
        article.get("Résumé") or "",
        entity_label=entity_label,
        max_chars=1200,
    )


def _resolve_image(article: dict) -> tuple[str, str]:
    """Retourne (image_url, titre). Récupère l'og:image à la volée si absente."""
    imgs = article.get("Images")
    if isinstance(imgs, list) and imgs and isinstance(imgs[0], dict):
        url = (imgs[0].get("URL") or imgs[0].get("url") or "").strip()
        if url:
            return url, ""

    link = (article.get("URL") or "").strip()
    if not link:
        return "", ""
    try:
        from utils.http_utils import extract_top_n_largest_images
        res = extract_top_n_largest_images(link, n=1)
        if isinstance(res, list) and res:
            return (res[0].get("url", "") or "").strip(), (res[0].get("title", "") or "").strip()
    except Exception as exc:
        default_logger.debug(f"Récupération og:image échouée pour {link} : {exc}")
    return "", ""


def parse_args():
    p = argparse.ArgumentParser(description="Veille horaire d'articles pour entités surveillées")
    p.add_argument("--dry-run", action="store_true", help="Affiche sans notifier ni écrire l'état")
    p.add_argument("--force", action="store_true",
                   help="Ignore l'état : notifie le dernier article même déjà signalé")
    p.add_argument("--max", type=int, default=_DEFAULT_MAX_PER_RUN,
                   help=f"Nombre max d'articles à notifier par passage (défaut {_DEFAULT_MAX_PER_RUN})")
    p.add_argument("--window-days", type=int, default=_DEFAULT_WINDOW_DAYS,
                   help=f"Fenêtre de fraîcheur en jours (défaut {_DEFAULT_WINDOW_DAYS})")
    p.add_argument("--no-format", action="store_true",
                   help="Désactive le reformatage IA (envoie le résumé brut)")
    p.add_argument("--no-commercial-filter", action="store_true",
                   help="Désactive le filtre anti-publicité (notifie aussi les articles promo)")
    p.add_argument("--ignore-window", action="store_true",
                   help=f"Ignore la fenêtre horaire {_NOTIFY_HOUR_START}h–{_NOTIFY_HOUR_END}h")
    return p.parse_args()


def main():
    args = parse_args()

    try:
        project_root = get_config().project_root
    except Exception:
        project_root = _PROJECT_ROOT

    watched = _load_watched()
    if not watched:
        default_logger.info("Aucune entité surveillée — rien à faire.")
        return

    default_logger.info(f"=== Veille articles · {len(watched)} entité(s) surveillée(s) ===")
    candidates = collect_candidates(project_root, watched, args.window_days)
    default_logger.info(f"{len(candidates)} article(s) récent(s) mentionnant une entité surveillée")

    state_exists = _STATE_FILE.exists()
    notified = list(_load_state().get("notified", []))
    notified_set = set(notified)

    # Premier lancement : initialiser la base sans notifier (anti-flot).
    if not state_exists and not args.force:
        seed = [c["article"].get("URL", "").strip() for c in candidates if c["article"].get("URL")]
        if not args.dry_run:
            _save_state(seed)
        default_logger.info(
            f"Initialisation : {len(seed)} article(s) existant(s) marqué(s) comme vus "
            f"(aucune notification au premier passage)."
        )
        return

    # Fenêtre horaire : on ne notifie qu'entre 7h et 22h (heure locale).
    # --force / --dry-run / --ignore-window contournent le garde-fou (tests manuels).
    now = datetime.now()
    in_window = _NOTIFY_HOUR_START <= now.hour < _NOTIFY_HOUR_END
    if not in_window and not (args.force or args.dry_run or args.ignore_window):
        default_logger.info(
            f"Hors fenêtre de notification ({_NOTIFY_HOUR_START}h–{_NOTIFY_HOUR_END}h) — "
            f"heure locale {now.hour:02d}h, aucun envoi."
        )
        return

    # Articles non encore notifiés (ou tous si --force).
    if args.force:
        nouveaux = candidates
    else:
        nouveaux = [c for c in candidates if c["article"].get("URL", "").strip() not in notified_set]

    if not nouveaux:
        default_logger.info("Aucun nouvel article à notifier.")
        return

    # Sélection : on écarte les articles promotionnels et on limite à
    # 1 notification par entité et par jour (jour calendaire local).
    _state = _load_state()
    entity_daily = dict(_state.get("entity_daily", {}))
    # Signatures d'entités des histoires déjà notifiées (dédup inter-sources) :
    # conservées en listes pour la persistance JSON, dérivées en frozensets pour
    # la comparaison de recouvrement.
    persisted_sigs: list[list[str]] = [
        s for s in _state.get("notified_sigs", []) if isinstance(s, list)
    ]
    today = now.strftime("%Y-%m-%d")

    eligible: list[dict] = []
    skipped_commercial: list[str] = []
    skipped_daily = 0
    for c in nouveaux:
        art = c["article"]
        url = (art.get("URL") or "").strip()
        ekey = c.get("entity_key") or c.get("entity_label", "")
        if not args.no_commercial_filter and _is_commercial(art):
            if url:
                skipped_commercial.append(url)
            continue
        if not args.force and entity_daily.get(ekey) == today:
            skipped_daily += 1
            continue
        eligible.append(c)

    if skipped_commercial:
        default_logger.info(f"{len(skipped_commercial)} article(s) promotionnel(s) écarté(s).")
    if skipped_daily:
        default_logger.info(f"{skipped_daily} article(s) écarté(s) (entité déjà notifiée aujourd'hui).")

    # Favoriser les entités à faible présence médiatique : tri STABLE par
    # présence récente croissante (eligible est déjà en fraîcheur décroissante,
    # qui sert donc de départage à présence égale).
    eidx = get_entity_index(project_root)
    presence_cutoff = (now - timedelta(days=_PRESENCE_WINDOW_DAYS)).strftime("%Y-%m-%d")
    presence_cache: dict[str, int] = {}

    def _presence_of(cand: dict) -> int:
        key = cand.get("entity_key", "")
        if key not in presence_cache:
            presence_cache[key] = _media_presence(
                eidx, cand.get("entity_type", ""), cand.get("entity_label", ""), presence_cutoff
            )
        return presence_cache[key]

    eligible.sort(key=_presence_of)

    # Au plus 1 article par entité, même au sein d'un passage à --max > 1.
    # + Dédup d'une MÊME histoire entre sources/entités : on n'envoie pas un
    #   article qui couvre un événement déjà notifié (signature d'entités), ni un
    #   doublon exact (URL/texte via Deduplicator). seen_sigs est amorcé avec les
    #   histoires déjà notifiées lors des passages précédents (anti-répétition).
    a_notifier: list[dict] = []
    seen_ekeys: set[str] = set()
    seen_sigs: list[frozenset[str]] = [frozenset(s) for s in persisted_sigs]
    run_dedup = Deduplicator()
    canonicalizer = get_entity_canonicalizer(project_root)
    skipped_story = 0
    for c in eligible:
        if len(a_notifier) >= max(1, args.max):
            break
        ek = c.get("entity_key", "")
        if ek in seen_ekeys:
            continue
        art = c["article"]
        sig = _entity_signature(art, canonicalizer)
        if not args.force and (run_dedup.is_duplicate(art) or _same_story(sig, seen_sigs)):
            skipped_story += 1
            continue
        seen_ekeys.add(ek)
        seen_sigs.append(sig)
        run_dedup.register(art)
        c["_story_sig"] = sorted(sig)
        a_notifier.append(c)

    if skipped_story:
        default_logger.info(
            f"{skipped_story} article(s) écarté(s) (même histoire déjà notifiée — dédup inter-sources)."
        )

    if a_notifier:
        choix = ", ".join(
            f"{c['entity_label']} (présence 24h : {_presence_of(c)})"
            for c in a_notifier
        )
        default_logger.info(f"Priorité aux entités sous-médiatisées → {choix}")

    if not a_notifier:
        default_logger.info("Aucun nouvel article à notifier après filtrage.")
        # On marque tout de même les articles promo comme vus (anti-réévaluation).
        if not args.dry_run and not args.force and skipped_commercial:
            for url in skipped_commercial:
                if url and url not in notified_set:
                    notified.append(url)
                    notified_set.add(url)
            entity_daily = {k: v for k, v in entity_daily.items() if v == today}
            _save_state(notified, entity_daily, persisted_sigs)
        return

    default_logger.info(
        f"{len(nouveaux)} nouvel(aux) article(s) ; envoi des {len(a_notifier)} plus récent(s)."
    )

    from utils.exporters.webhook import send_article_discord

    sent = 0
    for c in a_notifier:
        art = c["article"]
        label = c["entity_label"]
        ekey = c.get("entity_key") or label
        url = (art.get("URL") or "").strip()
        image_url, title = _resolve_image(art)

        if args.dry_run:
            default_logger.info(
                f"[DRY-RUN] {label} → {title or art.get('Sources', '')} | {url} "
                f"| image: {'oui' if image_url else 'non'} "
                f"| reformatage IA: {'non' if args.no_format else 'à l’envoi'}"
            )
            sent += 1
            continue

        body_md = "" if args.no_format else _format_summary_markdown(art, label)
        ok = send_article_discord(art, label, image_url=image_url, title=title,
                                  body_markdown=body_md)
        if ok:
            sent += 1
            entity_daily[ekey] = today
            # Mémorise la signature de l'histoire notifiée (dédup inter-sources).
            story_sig = c.get("_story_sig")
            if story_sig:
                persisted_sigs.append(story_sig)
            if url and url not in notified_set:
                notified.append(url)
                notified_set.add(url)

    # Les articles promo écartés sont aussi marqués vus pour ne plus les réévaluer.
    for url in skipped_commercial:
        if url and url not in notified_set:
            notified.append(url)
            notified_set.add(url)

    if not args.dry_run and not args.force:
        # On ne conserve que les entrées du jour : reset quotidien implicite.
        entity_daily = {k: v for k, v in entity_daily.items() if v == today}
        _save_state(notified, entity_daily, persisted_sigs)

    default_logger.info(f"{sent} notification(s) envoyée(s).")


if __name__ == "__main__":
    main()
