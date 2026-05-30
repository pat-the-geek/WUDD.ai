#!/usr/bin/env python3
"""Veille horaire d'entités surveillées.

À chaque passage (cron horaire), détecte le dernier article fraîchement
collecté qui mentionne une entité de ``data/watched_entities.json`` et envoie
une notification Discord avec **grande image + résumé**. Au plus 1 article par
passage (le plus récent non encore notifié).

Détection via ``entity_index`` (mis à jour dès la collecte par flux_watcher et
get-keyword-from-rss). Les articles sans NER au moment de la collecte (ex. flux
RSS bruts) ne sont vus qu'après l'enrichissement NER nocturne.

État : ``data/watched_article_state.json`` (URLs déjà notifiées). Au premier
lancement, l'état est initialisé avec les articles existants SANS notifier
(évite un flot initial) ; seuls les articles apparus ensuite déclenchent un envoi.

Usage :
    python3 scripts/watch_entity_articles.py [--dry-run] [--force] [--max N] [--window-days D]
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

_WATCHED_FILE = _PROJECT_ROOT / "data" / "watched_entities.json"
_STATE_FILE = _PROJECT_ROOT / "data" / "watched_article_state.json"

_DEFAULT_MAX_PER_RUN = 1     # 1 article max par passage horaire
_DEFAULT_WINDOW_DAYS = 2     # ne considérer que les articles récents
_MAX_STATE_URLS = 1000       # borne la taille du fichier d'état


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


def _save_state(notified_urls: list[str]) -> None:
    try:
        _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "notified": notified_urls[-_MAX_STATE_URLS:],
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        _STATE_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as exc:
        default_logger.warning(f"Impossible d'écrire {_STATE_FILE.name} : {exc}")


def _article_sort_key(article: dict):
    """Clé de tri par date de publication décroissante (None en dernier)."""
    dt = parse_article_date(article.get("Date de publication", ""), date_only_policy="end")
    return dt or datetime.min


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
            arts = eidx.load_articles(etype, value, max_articles=20, cutoff_date=cutoff)
        except Exception as exc:
            default_logger.debug(f"load_articles({etype}:{value}) a échoué : {exc}")
            continue
        for art in arts:
            url = (art.get("URL") or "").strip()
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            candidates.append({"article": art, "entity_label": value})

    candidates.sort(key=lambda c: _article_sort_key(c["article"]), reverse=True)
    return candidates


_BOLD_RE = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)


def _degrade_overbold(text: str) -> str:
    """Garde-fou contre le sur-gras des petits modèles (ex. qwen2.5:7b).

    Pour chaque ligne hors titre : si une part trop importante du texte est en
    **gras** (≥ 60 % des caractères) ou si la ligne entière est gras, on retire
    les marqueurs ** de cette ligne. Préserve les titres `### …` intacts.
    """
    out_lines = []
    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            out_lines.append(line)
            continue
        bold_chars = sum(len(m.group(1)) for m in _BOLD_RE.finditer(line))
        plain_len = len(_BOLD_RE.sub(r"\1", line).strip())
        # Ligne entièrement gras, ou ratio de gras trop élevé → on déshabille.
        whole_line_bold = bool(re.fullmatch(r"\*\*.+\*\*", stripped, re.DOTALL))
        if whole_line_bold or (plain_len and bold_chars / plain_len >= 0.6):
            line = _BOLD_RE.sub(r"\1", line)
        out_lines.append(line)
    return "\n".join(out_lines)


def _format_summary_markdown(article: dict, entity_label: str) -> str:
    """Reformate le résumé en Markdown Discord (chapitres + gras/italique) via l'IA.

    Repli : chaîne vide en cas d'échec → l'appelant utilisera le résumé brut.
    """
    resume = (article.get("Résumé") or "").strip()
    if not resume:
        return ""
    prompt = (
        "Reformate le résumé d'article ci-dessous en Markdown compatible Discord, EN FRANÇAIS, "
        "pour une notification de veille. Règles STRICTES :\n"
        "- N'invente AUCUN fait : utilise uniquement les informations du résumé.\n"
        "- Structure en chapitres avec des titres de niveau 3 (### Titre).\n"
        "- Commence par « ### En bref » suivi d'une phrase d'accroche (texte normal, NON gras).\n"
        "- Ajoute 1 à 2 chapitres supplémentaires SEULEMENT si le contenu le justifie "
        "(ex. ### Contexte, ### Enjeux). Si le résumé est court, garde uniquement « En bref ».\n"
        "- Le texte des paragraphes reste en clair (non gras). Utilise le **gras** avec "
        f"PARCIMONIE : mets en gras UNIQUEMENT la première mention de l'entité « {entity_label} » "
        "et au plus 2 ou 3 chiffres réellement clés. N'écris JAMAIS une phrase ou une ligne "
        "entière en gras. *Italique* possible pour une nuance ponctuelle.\n"
        "- Réponds UNIQUEMENT avec le Markdown, sans préambule. Maximum ~1200 caractères.\n\n"
        f"Résumé :\n{resume}"
    )
    try:
        # Reformatage = texte libre → on privilégie Ollama local (AI_PROVIDER_SUMMARY)
        # pour économiser des tokens cloud ; fallback EurIA/Claude automatique si Ollama
        # est injoignable ou lève une exception.
        from utils.api_client import get_summary_client
        out = get_summary_client().ask(prompt, timeout=45, max_tokens=600)
    except Exception as exc:
        default_logger.warning(f"Reformatage IA indisponible ({exc}) — résumé brut conservé.")
        return ""
    if not out or out.strip().lower().startswith("erreur"):
        default_logger.warning("Reformatage IA en échec — résumé brut conservé.")
        return ""
    return _degrade_overbold(out.strip())


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

    # Articles non encore notifiés (ou tous si --force).
    if args.force:
        nouveaux = candidates
    else:
        nouveaux = [c for c in candidates if c["article"].get("URL", "").strip() not in notified_set]

    if not nouveaux:
        default_logger.info("Aucun nouvel article à notifier.")
        return

    a_notifier = nouveaux[: max(1, args.max)]
    default_logger.info(
        f"{len(nouveaux)} nouvel(aux) article(s) ; envoi des {len(a_notifier)} plus récent(s)."
    )

    from utils.exporters.webhook import send_article_discord

    sent = 0
    for c in a_notifier:
        art = c["article"]
        label = c["entity_label"]
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
            if url and url not in notified_set:
                notified.append(url)
                notified_set.add(url)

    if not args.dry_run and not args.force:
        _save_state(notified)

    default_logger.info(f"{sent} notification(s) envoyée(s).")


if __name__ == "__main__":
    main()
