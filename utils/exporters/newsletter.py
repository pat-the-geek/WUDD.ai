"""Générateur de newsletter HTML.

Produit un email HTML responsive depuis les articles récents (format 48h)
ou depuis une liste d'articles fournie.

Usage :
    from utils.exporters.newsletter import generate_newsletter_html
    html = generate_newsletter_html(articles, title="WUDD.ai — Veille du 6 mars 2026")
    with open("rapports/html/newsletter_2026-03-06.html", "w") as f:
        f.write(html)

Pour envoi SMTP (si SMTP_HOST configuré dans .env) :
    from utils.exporters.newsletter import send_newsletter
    send_newsletter(html, subject="Veille du 6 mars 2026")
"""

import os
import smtplib
import json
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional

from ..date_utils import parse_article_date
from ..logging import default_logger


def _display_date_fr(raw: str) -> str:
    """Formate une date article (ISO 8601, DD/MM/YYYY, RFC 2822) en DD/MM/YYYY.

    Le corpus mélange les formats ; on normalise l'affichage pour éviter de
    montrer « 2026-05-25 » à côté de « 25/05/2026 ». Repli sur la chaîne brute
    tronquée si non parsable.
    """
    dt = parse_article_date(raw or "")
    if dt is not None:
        return dt.strftime("%d/%m/%Y")
    return (raw or "")[:10]


# ── Template HTML ─────────────────────────────────────────────────────────────

_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
  body {{ margin:0; padding:0; background:#f4f4f4; font-family:Georgia,'Times New Roman',serif; color:#222; }}
  .wrapper {{ max-width:680px; margin:0 auto; background:#fff; }}
  .header {{ background:#1a1a2e; color:#fff; padding:24px 32px; }}
  .header h1 {{ margin:0; font-size:22px; letter-spacing:1px; }}
  .header .date {{ font-size:13px; color:#aaa; margin-top:4px; }}
  .summary-bar {{ background:#16213e; color:#e0e0e0; padding:12px 32px; font-size:13px; }}
  .article {{ border-bottom:1px solid #eee; padding:20px 32px; }}
  .article:last-child {{ border-bottom:none; }}
  .article .meta {{ font-size:12px; color:#888; margin-bottom:6px; }}
  .article .meta .source {{ font-weight:bold; color:#1a1a2e; }}
  .article h2 {{ margin:0 0 8px; font-size:16px; }}
  .article h2 a {{ color:#1a1a2e; text-decoration:none; }}
  .article h2 a:hover {{ text-decoration:underline; }}
  .article .resume {{ font-size:14px; line-height:1.6; color:#444; }}
  .article img {{ max-width:100%; height:auto; margin-top:10px; border-radius:4px; }}
  .badge {{ display:inline-block; padding:2px 7px; border-radius:3px; font-size:11px; font-weight:bold; margin-left:8px; vertical-align:middle; }}
  .badge-positif {{ background:#d4edda; color:#155724; }}
  .badge-negatif {{ background:#f8d7da; color:#721c24; }}
  .badge-neutre {{ background:#e2e3e5; color:#383d41; }}
  .badge-alarmiste {{ background:#fff3cd; color:#856404; }}
  .badge-score {{ background:#cce5ff; color:#004085; }}
  .footer {{ background:#1a1a2e; color:#888; padding:16px 32px; font-size:12px; }}
  .footer a {{ color:#aaa; }}
  @media (max-width:600px) {{
    .article, .header, .footer, .summary-bar {{ padding-left:16px; padding-right:16px; }}
  }}
</style>
</head>
<body>
<div class="wrapper">
  <div class="header">
    <h1>WUDD.ai — {title}</h1>
    <div class="date">Générée le {generated_at} · {count} articles</div>
  </div>
  <div class="summary-bar">
    Veille automatisée · Intelligence artificielle &amp; actualités · Infomaniak EurIA/Qwen3
  </div>
  {articles_html}
  <div class="footer">
    &copy; WUDD.ai · <a href="https://github.com/patrickostertag">Patrick Ostertag</a>
    · Généré automatiquement — ne pas répondre à cet email.
  </div>
</div>
</body>
</html>"""

_ARTICLE_TEMPLATE = """<div class="article">
  <div class="meta">
    <span class="source">{source}</span> &nbsp;·&nbsp; {date}
    {sentiment_badge}
    {score_badge}
  </div>
  <h2><a href="{url}" target="_blank" rel="noopener">{title_text}</a></h2>
  <div class="resume">{resume_html}</div>
  {image_html}
</div>"""


# ── Helpers ───────────────────────────────────────────────────────────────────

def _sentiment_badge(article: dict) -> str:
    s = article.get("sentiment", "")
    ton = article.get("ton_editorial", "")
    badges = []
    if s in ("positif", "négatif", "neutre"):
        badges.append(f'<span class="badge badge-{s}">{s}</span>')
    if ton == "alarmiste":
        badges.append('<span class="badge badge-alarmiste">⚠ alarmiste</span>')
    return " ".join(badges)


def _score_badge(article: dict) -> str:
    score = article.get("score_pertinence")
    if score is None:
        return ""
    return f'<span class="badge badge-score">Score {score}</span>'


def _first_image(article: dict) -> str:
    images = article.get("Images", [])
    if not isinstance(images, list) or not images:
        return ""
    img = images[0]
    url = img.get("url") or img.get("URL", "")
    if not url:
        return ""
    return f'<img src="{url}" alt="illustration" loading="lazy">'


def _truncate(text: str, max_chars: int = 400) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rsplit(" ", 1)[0] + "…"


# ── API publique ──────────────────────────────────────────────────────────────

def generate_newsletter_html(
    articles: list,
    title: str = "Veille WUDD.ai",
    max_articles: int = 20,
) -> str:
    """Génère le HTML complet de la newsletter.

    Args:
        articles    : liste de dicts article (format WUDD.ai)
        title       : titre de la newsletter
        max_articles: nombre max d'articles à inclure

    Returns:
        HTML complet prêt à envoyer ou à sauvegarder.
    """
    articles_to_render = articles[:max_articles]
    articles_html_parts = []

    for article in articles_to_render:
        url = article.get("URL", "#")
        source = article.get("Sources", "Source inconnue")
        date = _display_date_fr(article.get("Date de publication", ""))
        resume = article.get("Résumé", "")
        if not isinstance(resume, str):
            resume = ""

        # Titre = première ligne du résumé ou source + date (texte complet, sans troncature)
        lines = [l.strip() for l in resume.splitlines() if l.strip()]
        title_text = lines[0] if lines else f"{source} · {date}"

        # Résumé complet — pas de troncature (user request)
        resume_html = resume.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        articles_html_parts.append(_ARTICLE_TEMPLATE.format(
            source=source,
            date=date,
            url=url,
            title_text=title_text.replace("&", "&amp;").replace("<", "&lt;"),
            resume_html=resume_html,
            sentiment_badge=_sentiment_badge(article),
            score_badge=_score_badge(article),
            image_html=_first_image(article),
        ))

    return _HTML_TEMPLATE.format(
        title=title,
        generated_at=datetime.now(timezone.utc).strftime("%d/%m/%Y à %H:%M UTC"),
        count=len(articles_to_render),
        articles_html="\n".join(articles_html_parts),
    )


def generate_newsletter_from_48h(project_root: Path, title: str = None) -> str:
    """Génère une newsletter depuis le fichier 48-heures.json.

    Args:
        project_root : racine du projet
        title        : titre de la newsletter (auto-généré si None)

    Returns:
        HTML de la newsletter.
    """
    now = datetime.now(timezone.utc)
    if title is None:
        title = f"Veille 48h — {now.strftime('%d %B %Y')}"

    wudd_48h = project_root / "data" / "articles-from-rss" / "_WUDD.AI_" / "48-heures.json"
    if not wudd_48h.exists():
        # Fallback : agréger tous les articles-from-rss récents
        articles = []
        rss_dir = project_root / "data" / "articles-from-rss"
        if rss_dir.exists():
            for json_file in sorted(rss_dir.rglob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True)[:5]:
                if "cache" in str(json_file):
                    continue
                try:
                    data = json.loads(json_file.read_text(encoding="utf-8"))
                    if isinstance(data, list):
                        articles.extend(data)
                except Exception:
                    continue
    else:
        try:
            articles = json.loads(wudd_48h.read_text(encoding="utf-8"))
            if not isinstance(articles, list):
                articles = []
        except Exception:
            articles = []

    # Trier par score si disponible, sinon par date
    if articles and "score_pertinence" in articles[0]:
        articles.sort(key=lambda a: a.get("score_pertinence", 0), reverse=True)
    else:
        articles.sort(
            key=lambda a: parse_article_date(a.get("Date de publication", "")) or datetime.min,
            reverse=True,
        )

    return generate_newsletter_html(articles, title=title)


def send_newsletter(
    html: str,
    subject: str,
    smtp_host: Optional[str] = None,
    smtp_port: int = 587,
    smtp_user: Optional[str] = None,
    smtp_password: Optional[str] = None,
    from_addr: Optional[str] = None,
    to_addr: Optional[str] = None,
) -> bool:
    """Envoie la newsletter par SMTP.

    Les paramètres SMTP sont lus depuis les variables d'environnement si non fournis :
      SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM, SMTP_TO

    Returns:
        True si l'envoi a réussi, False sinon.
    """
    host = smtp_host or os.getenv("SMTP_HOST", "")
    port = smtp_port or int(os.getenv("SMTP_PORT", "587"))
    user = smtp_user or os.getenv("SMTP_USER", "")
    password = smtp_password or os.getenv("SMTP_PASSWORD", "")
    from_email = from_addr or os.getenv("SMTP_FROM", user)
    to_email = to_addr or os.getenv("SMTP_TO", "")

    if not host or not to_email:
        default_logger.warning("SMTP non configuré (SMTP_HOST et SMTP_TO requis dans .env)")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_email
    msg["To"] = to_email
    msg.attach(MIMEText(html, "html", "utf-8"))

    try:
        with smtplib.SMTP(host, port, timeout=30) as server:
            server.ehlo()
            server.starttls()
            if user and password:
                server.login(user, password)
            server.sendmail(from_email, [to_email], msg.as_string())
        default_logger.info(f"Newsletter envoyée à {to_email}")
        return True
    except Exception as e:
        default_logger.error(f"Erreur envoi SMTP : {e}")
        return False


# ── Newsletter intelligente ────────────────────────────────────────────────────

def generate_newsletter_auto(
    project_root: Path,
    top_n: int = 5,
    days: int = 7,
    exclude_sent: bool = True,
    title: str | None = None,
    dry_run: bool = False,
) -> str:
    """Génère une newsletter avec les meilleurs articles non encore envoyés.

    Utilise ``ScoringEngine`` pour sélectionner les `top_n` articles les plus
    pertinents des `days` derniers jours. Les URLs des articles envoyés sont
    mémorisées dans ``data/newsletter_sent.json`` pour éviter les doublons.

    Args:
        project_root  : racine du projet
        top_n         : nombre d'articles à inclure (défaut 5)
        days          : fenêtre de collecte en jours (défaut 7)
        exclude_sent  : exclure les articles déjà envoyés (défaut True)
        title         : titre de la newsletter (auto si None)
        dry_run       : si True, ne met pas à jour newsletter_sent.json

    Returns:
        HTML de la newsletter.
    """
    from datetime import timedelta
    from ..scoring import ScoringEngine

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)
    if title is None:
        title = f"Sélection WUDD.ai — {now.strftime('%d %B %Y')}"

    # Charger la liste des URLs déjà envoyées
    sent_path = project_root / "data" / "newsletter_sent.json"
    sent_urls: set[str] = set()
    if exclude_sent and sent_path.exists():
        try:
            sent_data = json.loads(sent_path.read_text(encoding="utf-8"))
            sent_urls = set(sent_data if isinstance(sent_data, list) else [])
        except Exception:
            pass

    # Collecter les articles récents depuis toutes les sources
    articles: list[dict] = []
    for source_dir in [project_root / "data" / "articles-from-rss",
                        project_root / "data" / "articles"]:
        if not source_dir.exists():
            continue
        for json_file in sorted(source_dir.rglob("*.json"),
                                key=lambda f: f.stat().st_mtime, reverse=True)[:20]:
            if "cache" in str(json_file) or "index" in json_file.name:
                continue
            try:
                data = json.loads(json_file.read_text(encoding="utf-8"))
                if not isinstance(data, list):
                    continue
                for art in data:
                    url = art.get("URL", "")
                    if url and url not in sent_urls:
                        articles.append(art)
            except Exception:
                continue

    if not articles:
        default_logger.warning("[newsletter_auto] Aucun article éligible trouvé")
        return generate_newsletter_html([], title=title)

    # Scorer les articles
    try:
        scoring = ScoringEngine()
        scored = scoring.rate_articles(articles)
        scored.sort(key=lambda a: a.get("score_pertinence", 0), reverse=True)
    except Exception as e:
        default_logger.warning(f"[newsletter_auto] ScoringEngine indisponible ({e}), tri par date")
        scored = sorted(
            articles,
            key=lambda a: parse_article_date(a.get("Date de publication", "")) or datetime.min,
            reverse=True,
        )

    top_articles = scored[:top_n]
    default_logger.info(f"[newsletter_auto] {len(top_articles)} articles sélectionnés sur {len(articles)} éligibles")

    # Mettre à jour la liste des URLs envoyées
    if not dry_run and top_articles:
        new_urls = [a.get("URL", "") for a in top_articles if a.get("URL")]
        all_sent = list(sent_urls | set(new_urls))
        try:
            sent_path.parent.mkdir(parents=True, exist_ok=True)
            sent_path.write_text(json.dumps(all_sent, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            default_logger.warning(f"[newsletter_auto] Impossible de sauvegarder newsletter_sent.json : {e}")

    return generate_newsletter_html(top_articles, title=title)
