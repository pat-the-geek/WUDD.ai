#!/usr/bin/env python3
"""
generate_morning_digest.py — Digest quotidien du matin (07h30)

Agrège les meilleures actualités et tendances des 24 dernières heures
en un rapport synthétique conçu pour être lu en 2 minutes.

Sources de données (lecture seule) :
  - data/articles-from-rss/_WUDD.AI_/48-heures.json  (articles enrichis)
  - data/alertes.json                                  (tendances, générées à 7h00)

Sorties :
  - rapports/markdown/_WUDD.AI_/digest_YYYY-MM-DD.md

Usage :
    python3 scripts/generate_morning_digest.py
    python3 scripts/generate_morning_digest.py --ai          # + synthèse narrative EurIA
    python3 scripts/generate_morning_digest.py --send-email  # + envoi SMTP
    python3 scripts/generate_morning_digest.py --no-notify   # sans webhooks
    python3 scripts/generate_morning_digest.py --dry-run     # affiche sans sauvegarder
"""

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))

from utils.api_client import get_ai_client
from utils.config import get_config
from utils.logging import print_console
from utils.scoring import get_scoring_engine
from utils.scheduler_toggle import should_run_task
from utils.date_utils import parse_article_date

# Types d'entités pertinentes pour le classement
ENTITY_TYPES_PERTINENTS = {"PERSON", "ORG", "GPE", "PRODUCT", "EVENT", "NORP", "FAC", "LOC"}

NIVEAU_EMOJI = {
    "critique": "🔴",
    "élevé":    "🟠",
    "modéré":   "🟡",
    "faible":   "🟢",
}

SENTIMENT_EMOJI = {
    "positif": "🟢",
    "neutre":  "⚪",
    "négatif": "🔴",
}


# ── Chargement des données ────────────────────────────────────────────────────

def load_48h_articles(project_root: Path) -> list:
    """Charge data/articles-from-rss/_WUDD.AI_/48-heures.json."""
    f = project_root / "data" / "articles-from-rss" / "_WUDD.AI_" / "48-heures.json"
    if not f.exists():
        print_console(f"Fichier 48h introuvable : {f}", level="warning")
        return []
    try:
        return json.loads(f.read_text(encoding="utf-8")) or []
    except Exception as e:
        print_console(f"Erreur lecture 48-heures.json : {e}", level="error")
        return []


def load_alerts(project_root: Path) -> list:
    """Charge data/alertes.json (générées par trend_detector.py à 7h00)."""
    f = project_root / "data" / "alertes.json"
    if not f.exists():
        return []
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception as e:
        print_console(f"Erreur lecture alertes.json : {e}", level="warning")
        return []


# ── Calculs ───────────────────────────────────────────────────────────────────

def compute_top_entities(articles: list, top_n: int = 10) -> list:
    """Compte les entités nommées et retourne les top N.

    Returns:
        Liste de tuples (nom_original, type_entité, nb_occurrences).
    """
    counter: Counter = Counter()
    type_map: dict = {}

    for article in articles:
        entities = article.get("entities", {})
        if not isinstance(entities, dict):
            continue
        for entity_type, names in entities.items():
            if entity_type not in ENTITY_TYPES_PERTINENTS:
                continue
            if not isinstance(names, list):
                continue
            for name in names:
                name_clean = str(name).strip()
                if len(name_clean) < 3:
                    continue
                key = name_clean.lower()
                counter[key] += 1
                if key not in type_map:
                    type_map[key] = (name_clean, entity_type)

    top = []
    for key, count in counter.most_common(top_n):
        name_original, entity_type = type_map[key]
        top.append((name_original, entity_type, count))
    return top


def compute_cooccurrences(articles: list, entity_value: str, top_n: int = 5) -> list:
    """Retourne les entités co-occurentes (L1) avec entity_value dans les mêmes articles."""
    entity_lower = entity_value.lower()
    counter: Counter = Counter()

    for article in articles:
        entities = article.get("entities", {})
        if not isinstance(entities, dict):
            continue
        # Vérifie si l'article mentionne l'entité cible
        found = any(
            str(name).lower() == entity_lower
            for names in entities.values()
            if isinstance(names, list)
            for name in names
        )
        if not found:
            continue
        # Collecte toutes les autres entités du même article
        for etype, names in entities.items():
            if etype not in ENTITY_TYPES_PERTINENTS or not isinstance(names, list):
                continue
            for name in names:
                name_clean = str(name).strip()
                if name_clean.lower() == entity_lower or len(name_clean) < 3:
                    continue
                counter[name_clean] += 1

    return [name for name, _ in counter.most_common(top_n)]


def compute_sentiment_stats(articles: list) -> dict:
    """Calcule la répartition des sentiments en pourcentages."""
    counts = Counter(
        a.get("sentiment", "").lower()
        for a in articles
        if a.get("sentiment")
    )
    total = sum(counts.values()) or 1
    return {k: round(v * 100 / total) for k, v in counts.items()}


def compute_top_sources(articles: list, top_n: int = 5) -> list:
    """Retourne les sources les plus fréquentes."""
    counter = Counter(
        str(a.get("Sources", "")).strip()
        for a in articles
        if a.get("Sources")
    )
    return counter.most_common(top_n)


def first_image_url(article: dict) -> str:
    """Extrait l'URL de la première image valide d'un article."""
    images = article.get("Images", [])
    if not isinstance(images, list):
        return ""
    for img in images:
        if isinstance(img, dict):
            u = img.get("url") or img.get("URL", "")
            if u and str(u).startswith("http"):
                return str(u)
    return ""


# ── Construction du Markdown ──────────────────────────────────────────────────

def _highlight_ner(text: str, entities: dict) -> str:
    """Met en gras les entités NER dans le texte avec indication du type.

    Ex : "OpenAI" → "**OpenAI** *(ORG)*"
    Traite les entités de la plus longue à la plus courte pour éviter les
    remplacements partiels. Le remplacement se fait en un seul passage regex
    pour éviter d'injecter du Markdown puis de rematcher à l'intérieur.
    """
    import re
    if not entities or not isinstance(entities, dict):
        return text

    # Construire la liste (nom, type), triée par longueur décroissante.
    replacements: dict[str, tuple[str, str]] = {}
    escaped_names: list[str] = []
    seen: set[str] = set()

    for etype, names in entities.items():
        if etype not in ENTITY_TYPES_PERTINENTS or not isinstance(names, list):
            continue
        for name in names:
            name_clean = str(name).strip()
            if len(name_clean) < 3:
                continue
            key = name_clean.casefold()
            if key in seen:
                continue
            seen.add(key)
            replacements[key] = (name_clean, etype)
            escaped_names.append(re.escape(name_clean))

    if not escaped_names:
        return text

    escaped_names.sort(key=len, reverse=True)
    pattern = re.compile(
        r'(?<!\w)(' + '|'.join(escaped_names) + r')(?!\w)',
        re.IGNORECASE | re.UNICODE,
    )

    highlighted: set[str] = set()

    def _replace(match: re.Match) -> str:
        matched_text = match.group(0)
        key = matched_text.casefold()
        canonical_name, etype = replacements.get(key, (matched_text, ""))
        if key in highlighted:
            return matched_text
        highlighted.add(key)
        label = canonical_name if canonical_name else matched_text
        return f"**{label}** *({etype})*"

    return pattern.sub(_replace, text)


def _article_display_title(article: dict) -> str:
    """Retourne le meilleur titre affichable pour un article du digest."""
    for key in ("Titre", "title", "title_rendered"):
        value = str(article.get(key, "") or "").strip()
        if value:
            return value

    images = article.get("Images", [])
    if isinstance(images, list):
        for image in images:
            if not isinstance(image, dict):
                continue
            value = str(image.get("title", "") or image.get("alt", "") or "").strip()
            if value:
                return value

    resume = str(article.get("Résumé", "") or "").strip()
    if resume:
        title_lines = [line.strip() for line in resume.split("\n") if line.strip()]
        if title_lines:
            return title_lines[0]

    return "Sans titre"


def _format_article_card(article: dict, rank: int) -> str:
    """Formate un article en bloc Markdown pour le digest.

    Affiche le résumé complet avec les entités NER mises en gras.
    """
    source = article.get("Sources", "Source inconnue")
    url = article.get("URL", "")
    resume = article.get("Résumé", "")
    date_raw = article.get("Date de publication", "")
    score = article.get("score_pertinence", 0)
    sentiment = article.get("sentiment", "")
    entities = article.get("entities", {})

    titre = _article_display_title(article)

    sent_emoji = SENTIMENT_EMOJI.get(sentiment.lower(), "") if sentiment else ""

    # Date lisible — corpus mixte ISO 8601 / DD/MM/YYYY / RFC 2822.
    _dt_lbl = parse_article_date(date_raw)
    date_label = _dt_lbl.strftime("%-d %b %Y, %Hh%M") if _dt_lbl else (date_raw[:10] if date_raw else "")

    lines = [f"### {rank}. {titre}"]
    meta_parts = []
    if sent_emoji:
        meta_parts.append(sent_emoji)
    if score:
        meta_parts.append(f"Score {score:.0f}/100")
    if date_label:
        meta_parts.append(date_label)
    meta_parts.append(f"**{source}**")
    lines.append(" · ".join(meta_parts))

    img_url = first_image_url(article)
    if img_url:
        lines.append(f"\n![]({img_url})")

    # Résumé complet avec entités NER en gras
    if resume:
        resume_highlighted = _highlight_ner(resume, entities if isinstance(entities, dict) else {})
        lines.append(f"\n{resume_highlighted}")

    if url:
        lines.append(f"\n[→ Lire l'article]({url})")

    return "\n".join(lines)


def build_digest_markdown(
    articles_48h: list,
    top_articles: list,
    top_entities: list,
    top_alerts: list,
    sentiment_stats: dict,
    top_sources: list,
    ai_synthesis: str,
    today_str: str,
    today_iso: str,
) -> str:
    """Construit le Markdown complet du digest."""
    nb_articles = len(articles_48h)
    nb_entities = sum(
        len(v) for a in articles_48h
        for v in (a.get("entities") or {}).values()
        if isinstance(v, list)
    )

    lines = [
        "---",
        f'title: "Morning Digest WUDD.ai — {today_str}"',
        f"date: {today_iso}",
        f"période: Dernières 24 heures",
        f"articles_analysés: {nb_articles}",
        f"entités_détectées: {nb_entities}",
        "---",
        "",
        f"# Morning Digest — {today_str}",
        "",
        f"> Généré automatiquement le {today_str} par WUDD.ai · {nb_articles} articles analysés",
        "",
    ]

    # ── Section 1 : Tendances ──────────────────────────────────────────────────
    lines.append("## Tendances du jour")
    lines.append("")
    if top_alerts:
        for alert in top_alerts:
            niveau = alert.get("niveau", "")
            emoji = NIVEAU_EMOJI.get(niveau, "⚪")
            entite = alert.get("entite", alert.get("entity", alert.get("entity_value", "")))
            ratio = alert.get("ratio", 0)
            nb = alert.get("mentions_24h", alert.get("count_24h", ""))
            desc = alert.get("description", "")
            ligne = f"- {emoji} **{entite}**"
            if ratio:
                ligne += f" · ×{ratio:.1f} vs moyenne 7j"
            if nb:
                ligne += f" · {nb} mentions/24h"
            if desc:
                ligne += f" — {desc}"
            cooc = compute_cooccurrences(articles_48h, entite, top_n=5)
            if cooc:
                ligne += f" [{', '.join(cooc)}]"
            lines.append(ligne)
    else:
        lines.append("*Aucune alerte de tendance détectée — `trend_detector.py` n'a pas encore tourné ou aucun seuil n'est dépassé.*")
    lines.append("")

    # ── Section 2 : Top 5 articles ────────────────────────────────────────────
    lines.append("## Top 5 articles du jour")
    lines.append("")
    if top_articles:
        for i, article in enumerate(top_articles, 1):
            lines.append(_format_article_card(article, i))
            lines.append("")
    else:
        lines.append("*Aucun article disponible pour les dernières 24 heures.*")
        lines.append("")

    # ── Section 3 : Top 10 entités ────────────────────────────────────────────
    lines.append("## Top 10 entités (48h)")
    lines.append("")
    if top_entities:
        lines.append("| # | Entité | Type | Occurrences |")
        lines.append("|---|--------|------|------------|")
        for i, (name, etype, count) in enumerate(top_entities, 1):
            lines.append(f"| {i} | **{name}** | {etype} | {count} |")
    else:
        lines.append("*Aucune entité détectée — les articles ne sont peut-être pas encore enrichis.*")
    lines.append("")

    # ── Section 4 : Statistiques ──────────────────────────────────────────────
    lines.append("## Statistiques du jour")
    lines.append("")
    lines.append(f"- **Volume** : {nb_articles} articles analysés sur 48h")

    if sentiment_stats:
        sent_parts = []
        for sentiment, pct in sorted(sentiment_stats.items(), key=lambda x: -x[1]):
            emoji = SENTIMENT_EMOJI.get(sentiment, "")
            sent_parts.append(f"{emoji} {pct}% {sentiment}")
        lines.append(f"- **Sentiments** : {' · '.join(sent_parts)}")

    if top_sources:
        sources_str = ", ".join(f"{src} ({n})" for src, n in top_sources[:3])
        lines.append(f"- **Sources principales** : {sources_str}")

    if top_entities:
        kw_str = ", ".join(name for name, _, _ in top_entities[:5])
        lines.append(f"- **Entités dominantes** : {kw_str}")

    lines.append("")

    # ── Section 5 : Synthèse IA (optionnelle) ─────────────────────────────────
    if ai_synthesis:
        lines.append("## Synthèse IA")
        lines.append("")
        lines.append(ai_synthesis.strip())
        lines.append("")

    # ── Section 6 : Références ────────────────────────────────────────────────
    if top_articles:
        lines.append("## Références")
        lines.append("")
        lines.append("| Date | Source | URL |")
        lines.append("|------|--------|-----|")
        for article in top_articles:
            _dt_ref = parse_article_date(article.get("Date de publication", ""))
            date_raw = _dt_ref.strftime("%d/%m/%Y") if _dt_ref else article.get("Date de publication", "")[:10]
            source = article.get("Sources", "")
            url = article.get("URL", "")
            if url:
                lines.append(f"| {date_raw} | {source} | {url} |")
        lines.append("")

    return "\n".join(lines)


# ── Synthèse EurIA ────────────────────────────────────────────────────────────

def generate_ai_synthesis(top_articles: list) -> str:
    """Génère une synthèse narrative de 150-200 mots des top articles."""
    if not top_articles:
        return ""

    snippets = []
    for a in top_articles[:5]:
        resume = a.get("Résumé", "")[:600]
        source = a.get("Sources", "")
        snippets.append(f"[{source}] {resume}")

    payload = "\n\n".join(snippets)
    prompt = f"""En te basant sur les extraits d'articles suivants, rédige une synthèse analytique de 150 à 200 mots sur l'actualité du jour. Ton factuel et journalistique. Mets en gras les points clés. Pas de liste à puces.

--- ARTICLES ---
{payload}
--- FIN ---

Synthèse (150-200 mots, français, ton journalistique) :"""

    try:
        client = get_ai_client()
        return client.ask(prompt, max_attempts=2, timeout=90)
    except Exception as e:
        print_console(f"Synthèse IA échouée : {e}", level="warning")
        return ""


# ── Point d'entrée ────────────────────────────────────────────────────────────

def generate_morning_digest(
    ai: bool = False,
    send_email: bool = False,
    no_notify: bool = False,
    dry_run: bool = False,
) -> None:
    config = get_config()
    config.setup_directories()

    now = datetime.now(timezone.utc)
    today_iso = now.strftime("%Y-%m-%d")
    today_str = now.strftime("%-d %B %Y")

    print_console(f"=== Morning Digest {today_str} ===")

    # 1. Charger les données sources
    articles_48h = load_48h_articles(PROJECT_ROOT)
    alerts = load_alerts(PROJECT_ROOT)

    if not articles_48h:
        print_console("Aucun article dans 48-heures.json — digest annulé", level="warning")
        sys.exit(0)

    print_console(f"{len(articles_48h)} articles chargés depuis 48-heures.json")

    # 2. Top 5 articles les mieux scorés (fenêtre 24h, toutes sources)
    engine = get_scoring_engine(PROJECT_ROOT)
    top_articles = engine.get_top_articles_from_index(top_n=10, hours=24, include_rss=True)
    if not top_articles:
        # Fallback : scorer directement les articles 48h sans filtre temporel
        top_articles = engine.score_and_sort(list(articles_48h), top_n=10)

    # Déduplication par URL (un même article peut être indexé dans plusieurs fichiers)
    seen_urls: set = set()
    deduped: list = []
    for art in top_articles:
        url = art.get("URL", "")
        if url and url not in seen_urls:
            seen_urls.add(url)
            deduped.append(art)
        elif not url:
            deduped.append(art)  # articles sans URL : conserver
    top_articles = deduped[:5]
    print_console(f"{len(top_articles)} articles sélectionnés pour le Top 5 (après déduplication)")

    # 3. Calculs statistiques
    top_entities = compute_top_entities(articles_48h, top_n=10)
    sentiment_stats = compute_sentiment_stats(articles_48h)
    top_sources = compute_top_sources(articles_48h, top_n=5)
    top_alerts = [
        a for a in alerts
        if a.get("niveau") in ("critique", "élevé", "modéré")
    ][:5]

    print_console(f"Entités top 1 : {top_entities[0][0] if top_entities else '—'}")
    print_console(f"Alertes actives : {len(top_alerts)}")

    # 4. Synthèse IA (optionnelle)
    ai_synthesis = ""
    if ai and not dry_run:
        print_console("Génération de la synthèse IA (timeout 90s)...")
        ai_synthesis = generate_ai_synthesis(top_articles)
        if ai_synthesis:
            print_console("Synthèse IA générée.")
        else:
            print_console("Synthèse IA indisponible — digest généré sans.", level="warning")

    # 5. Construire le Markdown
    digest_md = build_digest_markdown(
        articles_48h=articles_48h,
        top_articles=top_articles,
        top_entities=top_entities,
        top_alerts=top_alerts,
        sentiment_stats=sentiment_stats,
        top_sources=top_sources,
        ai_synthesis=ai_synthesis,
        today_str=today_str,
        today_iso=today_iso,
    )

    if dry_run:
        print_console("=== MODE DRY-RUN — aperçu du digest ===")
        print(digest_md[:3000])
        if len(digest_md) > 3000:
            print(f"\n[...tronqué — {len(digest_md)} caractères au total]")
        return

    # 6. Sauvegarder le Markdown
    output_dir = PROJECT_ROOT / "rapports" / "markdown" / "_WUDD.AI_"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"digest_{today_iso}.md"
    output_file.write_text(digest_md, encoding="utf-8")
    print_console(f"✓ Digest sauvegardé : {output_file}")

    # 7. Envoi email (optionnel)
    if send_email:
        try:
            from utils.exporters.newsletter import generate_newsletter_html, send_newsletter
            html = generate_newsletter_html(
                top_articles,
                title=f"WUDD.ai Morning Digest — {today_str}",
            )
            send_newsletter(html, subject=f"WUDD.ai Morning Digest — {today_str}")
            print_console("✓ Digest envoyé par email.")
        except Exception as e:
            print_console(f"Envoi email échoué : {e}", level="error")

    # 8. Notifications webhook (si alertes actives, sauf --no-notify)
    if top_alerts and not no_notify:
        try:
            from utils.exporters.webhook import notify_alerts
            notify_alerts(top_alerts)
            print_console(f"✓ {len(top_alerts)} alerte(s) notifiée(s) via webhook.")
        except Exception as e:
            print_console(f"Notification webhook échouée : {e}", level="warning")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Génère le Morning Digest quotidien WUDD.ai"
    )
    parser.add_argument(
        "--ai",
        action="store_true",
        help="Active la synthèse narrative EurIA (1 appel, timeout 90s)",
    )
    parser.add_argument(
        "--send-email",
        action="store_true",
        help="Envoie le digest par SMTP (nécessite SMTP_* dans .env)",
    )
    parser.add_argument(
        "--no-notify",
        action="store_true",
        help="Désactive les notifications webhook Discord/Slack/Ntfy",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Affiche le digest sans sauvegarder ni appeler l'API",
    )
    args = parser.parse_args()
    if not should_run_task("reports.morning_digest"):
        sys.exit(0)
    generate_morning_digest(
        ai=args.ai,
        send_email=args.send_email,
        no_notify=args.no_notify,
        dry_run=args.dry_run,
    )
