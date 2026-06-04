"""Notifications webhook — Discord, Slack, Ntfy.

Envoie des alertes de tendance (ou tout message structuré) vers
les plateformes configurées dans .env.

Variables .env supportées :
  WEBHOOK_DISCORD   : URL webhook Discord
  WEBHOOK_SLACK     : URL webhook Slack (Incoming Webhooks)
  NTFY_URL          : URL Ntfy (ex: https://ntfy.sh/wudd-alerts)
  NTFY_TOKEN        : Token Ntfy (optionnel)

Usage :
    from utils.exporters.webhook import notify_alerts
    notify_alerts(alerts)  # alerts = liste retournée par trend_detector.py
"""

import json
import os
from typing import Optional

from ..http_utils import create_session_with_retries
from ..logging import default_logger

# Limites Discord
_DISCORD_DESC_LIMIT = 4000   # description d'embed (limite API : 4096)
_DISCORD_MAX_EMBEDS = 10     # nombre maximum d'embeds par message (limite API)

# Couleurs d'embed Discord (entier décimal) par niveau.
_NIVEAU_COLOR = {
    "critique": 0xE74C3C,  # rouge
    "élevé":    0xE67E22,  # orange
    "modéré":   0xF1C40F,  # jaune
    "info":     0x3498DB,  # bleu
}
_NIVEAU_RANK = {"info": 0, "modéré": 1, "élevé": 2, "critique": 3}


# ── Helpers ───────────────────────────────────────────────────────────────────

_NIVEAU_EMOJI = {
    "critique": "🔴",
    "élevé": "🟠",
    "modéré": "🟡",
    "info": "🔵",
}

_ENTITY_TYPE_FR = {
    "PERSON": "Personne",
    "ORG": "Organisation",
    "GPE": "Lieu/Pays",
    "PRODUCT": "Produit",
    "EVENT": "Événement",
    "NORP": "Groupe",
    "LOC": "Lieu",
    "FAC": "Lieu",
    "LAW": "Loi/Régulation",
    "DISEASE": "Maladie",
    "WORK_OF_ART": "Œuvre",
    "LANGUAGE": "Langue",
}


def _format_alert_text(alert: dict, *, markdown: bool = True) -> str:
    """Formate une alerte en une ligne lisible.

    Distingue tendance / nouveauté / silence / veille, ajoute la prédiction de
    franchissement de seuil et un lien vers l'article déclencheur si présent.

    Args:
        markdown : si vrai, le lien article est rendu en Markdown ``[source](url)``
                   (Discord/Slack) ; sinon en texte brut (Ntfy).
    """
    niveau = alert.get("niveau", "modéré")
    etype = _ENTITY_TYPE_FR.get(alert.get("entity_type", ""), alert.get("entity_type", ""))
    value = alert.get("entity_value", "")
    count_24h = alert.get("count_24h", 0)
    count_7j = alert.get("count_7j", 0)
    ratio = alert.get("ratio", 0)

    # Corps selon la nature de l'alerte
    if alert.get("type") == "silence":
        baseline = alert.get("baseline_avg_per_day", round(count_7j / 7.0, 1) if count_7j else 0)
        emoji = "🔇"
        body = f"**{value}** ({etype}) — silence : 0 mention/24h (moy. {baseline}/j sur 7j)"
    elif alert.get("nouveaute"):
        emoji = "🆕"
        body = f"**{value}** ({etype}) — {count_24h} mentions/24h · nouvelle entité (×{ratio})"
    else:
        emoji = _NIVEAU_EMOJI.get(niveau, "⚪")
        body = (f"**{value}** ({etype}) — {count_24h} mentions/24h vs {count_7j}/7j "
                f"· ratio {ratio}x")

    if alert.get("watched"):
        emoji = f"👁{emoji}"

    line = f"{emoji} {body}"

    # Prédiction de franchissement de seuil critique
    pred = alert.get("prediction_seuil_dans_minutes")
    if pred is not None:
        if pred <= 0:
            line += " · 🔮 seuil critique atteint"
        else:
            line += f" · 🔮 seuil critique dans ~{pred} min"

    # Lien vers l'article déclencheur
    url = (alert.get("article_url") or "").strip()
    if url:
        src = (alert.get("article_source") or "lien").strip() or "lien"
        if markdown:
            line += f" · [{src}]({url})"
        else:
            line += f" · {url}"

    return line


def _highest_niveau(alerts: list) -> str:
    """Retourne le niveau le plus élevé présent dans la liste d'alertes."""
    best = "modéré"
    for a in alerts:
        if _NIVEAU_RANK.get(a.get("niveau", "modéré"), 1) > _NIVEAU_RANK.get(best, 1):
            best = a.get("niveau", "modéré")
    return best


# ── Discord ──────────────────────────────────────────────────────────────────

def send_discord(
    alerts: list,
    webhook_url: Optional[str] = None,
    title: str = "WUDD.ai · Tendances détectées",
    top_n: int = 10,
) -> bool:
    """Envoie les alertes vers un webhook Discord.

    Returns:
        True si l'envoi a réussi.
    """
    url = webhook_url or os.getenv("WEBHOOK_DISCORD", "")
    if not url:
        default_logger.debug("WEBHOOK_DISCORD non configuré — Discord ignoré")
        return False

    selection = alerts[:top_n]
    if not selection:
        return False

    # Un embed par alerte (max 10). Image bannière pour la 1re, vignette pour
    # les suivantes. Au-delà de 10, les entités restantes sont listées.
    rich = selection[:_DISCORD_MAX_EMBEDS]
    overflow = selection[_DISCORD_MAX_EMBEDS:]

    embeds: list[dict] = []
    for i, a in enumerate(rich):
        embed = {
            "description": _format_alert_text(a, markdown=True)[:_DISCORD_DESC_LIMIT],
            "color": _NIVEAU_COLOR.get(a.get("niveau", "modéré"), 0x95A5A6),
        }
        img = (a.get("article_image") or "").strip()
        if img:
            # Grande image pour l'alerte en tête, vignette pour les autres.
            embed["image" if i == 0 else "thumbnail"] = {"url": img}
        embeds.append(embed)

    # Titre global porté par le premier embed.
    embeds[0]["author"] = {"name": title}

    # Entités au-delà de la limite d'embeds : listées de façon compacte.
    if overflow:
        names = ", ".join(a.get("entity_value", "") for a in overflow)
        extra = f"\n… +{len(overflow)} autre(s) : {names}"
        embeds[-1]["description"] = (embeds[-1]["description"] + extra)[:_DISCORD_DESC_LIMIT]

    niveau = _highest_niveau(selection)
    embeds[-1]["footer"] = {
        "text": f"WUDD.ai · {len(selection)} alerte(s) · niveau max : {niveau}"
    }
    payload = {"embeds": embeds}

    try:
        session = create_session_with_retries(total_retries=3, backoff_factor=0.5)
        r = session.post(url, json=payload, timeout=10)
        r.raise_for_status()
        default_logger.info(f"Notification Discord envoyée ({len(selection)} alertes)")
        return True
    except Exception as e:
        default_logger.warning(f"Erreur Discord : {e}")
        return False


def send_article_discord(
    article: dict,
    entity_label: str,
    *,
    image_url: str = "",
    title: str = "",
    body_markdown: str = "",
    webhook_url: Optional[str] = None,
) -> bool:
    """Envoie une notification Discord pour UN article (grande image + résumé).

    Utilisé pour la veille horaire d'entités surveillées.

    Args:
        article       : dict article WUDD.ai (Résumé, Sources, URL, Date…)
        entity_label  : nom de l'entité surveillée concernée
        image_url     : URL de la grande image (sinon tentée depuis article["Images"])
        title         : titre de l'article (sinon repli sur la source)
        body_markdown : corps Markdown pré-formaté (chapitres/gras/italique) ;
                        si vide, on utilise le résumé brut de l'article
    """
    url = webhook_url or os.getenv("WEBHOOK_DISCORD", "")
    if not url:
        default_logger.debug("WEBHOOK_DISCORD non configuré — Discord ignoré")
        return False

    resume = (body_markdown or article.get("Résumé") or "").strip()
    if len(resume) > _DISCORD_DESC_LIMIT:
        resume = resume[: _DISCORD_DESC_LIMIT - 1].rstrip() + "…"
    source = (article.get("Sources") or "").strip()
    date = (article.get("Date de publication") or "").strip()
    link = (article.get("URL") or "").strip()

    if not image_url:
        imgs = article.get("Images")
        if isinstance(imgs, list) and imgs and isinstance(imgs[0], dict):
            image_url = (imgs[0].get("URL") or imgs[0].get("url") or "").strip()

    embed: dict = {
        "author": {"name": f"👁 Veille · {entity_label}"},
        "title": (title or source or "Article")[:256],
        "description": resume or "_(résumé indisponible)_",
        "color": _NIVEAU_COLOR["info"],
        "footer": {"text": " · ".join(x for x in [source, date] if x)},
    }
    if link:
        embed["url"] = link
    if image_url.startswith(("http://", "https://")):
        embed["image"] = {"url": image_url}

    payload = {"embeds": [embed]}
    try:
        session = create_session_with_retries(total_retries=3, backoff_factor=0.5)
        r = session.post(url, json=payload, timeout=10)
        r.raise_for_status()
        default_logger.info(f"Notification Discord article envoyée (veille : {entity_label})")
        return True
    except Exception as e:
        default_logger.warning(f"Erreur Discord (article veille) : {e}")
        return False


def send_digest_discord(
    *,
    title: str,
    synthesis: str = "",
    articles: Optional[list] = None,
    footer: str = "",
    webhook_url: Optional[str] = None,
) -> bool:
    """Envoie un digest sous forme de notification Discord MULTI-EMBED.

    Un embed « synthèse » en tête, puis un embed par article (vignette de l'image
    de l'article + titre cliquable + thématique + accroche). Discord limite à 10
    embeds par message : on garde la synthèse + les premiers articles.

    Args:
        title     : titre de l'embed de synthèse (ex. « 🗞️ Digest — 04/06/2026 »)
        synthesis : texte de synthèse/mise en perspective (Markdown)
        articles  : liste de dicts {title, url, image, theme, snippet}
        footer    : pied du dernier embed (ex. « 10 articles · 9 thématiques »)
    """
    url = webhook_url or os.getenv("WEBHOOK_DISCORD", "")
    if not url:
        default_logger.debug("WEBHOOK_DISCORD non configuré — digest Discord ignoré")
        return False

    articles = articles or []
    embeds: list[dict] = []

    # Embed de tête : titre + synthèse
    head: dict = {"title": (title or "Digest WUDD.ai")[:256], "color": _NIVEAU_COLOR["info"]}
    if synthesis.strip():
        head["description"] = synthesis.strip()[:_DISCORD_DESC_LIMIT]
    embeds.append(head)

    # Un embed par article (avec sa vignette) — dans la limite des 10 embeds
    slots = _DISCORD_MAX_EMBEDS - len(embeds)
    shown = articles[:slots]
    for art in shown:
        t = " ".join(str(art.get("title") or "Article").split())
        e: dict = {"title": t[:256], "color": _NIVEAU_COLOR["info"]}
        if art.get("url"):
            e["url"] = art["url"]
        bits = []
        if art.get("theme"):
            bits.append(f"*{art['theme']}*")
        if art.get("snippet"):
            bits.append(str(art["snippet"]))
        if bits:
            e["description"] = "\n".join(bits)[:_DISCORD_DESC_LIMIT]
        img = str(art.get("image") or "")
        if img.startswith(("http://", "https://")):
            e["thumbnail"] = {"url": img}
        embeds.append(e)

    # Mention des articles non affichés (au-delà de la limite d'embeds)
    overflow = len(articles) - len(shown)
    foot = footer + (f" · +{overflow} autres" if overflow > 0 else "")
    if foot:
        embeds[-1]["footer"] = {"text": foot[:2048]}

    payload = {"embeds": embeds}
    try:
        session = create_session_with_retries(total_retries=3, backoff_factor=0.5)
        r = session.post(url, json=payload, timeout=10)
        r.raise_for_status()
        default_logger.info(f"Notification Discord digest envoyée ({len(shown)} articles)")
        return True
    except Exception as e:
        default_logger.warning(f"Erreur Discord (digest) : {e}")
        return False


def send_watched_entity_added(
    entity_type: str,
    value: str,
    *,
    notes: str = "",
    explanation: str = "",
    webhook_url: Optional[str] = None,
) -> bool:
    """Notifie Discord de l'ajout d'une nouvelle entité à la liste de surveillance.

    Message d'information avec, si disponible, un court texte explicatif sur
    l'entité (généré par l'IA côté appelant) et la note utilisateur éventuelle.

    Args:
        entity_type : type NER (PERSON, ORG, GPE…)
        value       : valeur/nom de l'entité surveillée
        notes       : note libre saisie à l'ajout (optionnelle)
        explanation : courte explication factuelle de l'entité (optionnelle)

    Returns:
        True si l'envoi a réussi.
    """
    url = webhook_url or os.getenv("WEBHOOK_DISCORD", "")
    if not url:
        default_logger.debug("WEBHOOK_DISCORD non configuré — notification d'ajout ignorée")
        return False

    type_fr = _ENTITY_TYPE_FR.get((entity_type or "").upper(), entity_type or "Entité")

    parts: list[str] = []
    explanation = (explanation or "").strip()
    if explanation:
        parts.append(explanation)
    notes = (notes or "").strip()
    if notes:
        parts.append(f"📝 *Note :* {notes}")
    parts.append(
        "🔔 Vous serez notifié (entre 7h et 22h) dès qu'un nouvel article mentionnant "
        "cette entité sera détecté — en priorisant les entités les moins médiatisées."
    )
    description = "\n\n".join(parts)[:_DISCORD_DESC_LIMIT]

    embed = {
        "author": {"name": "👁 Nouvelle entité surveillée"},
        "title": (value or "Entité")[:256],
        "description": description,
        "color": _NIVEAU_COLOR["info"],
        "footer": {"text": f"WUDD.ai · veille d'entités · {type_fr}"},
    }
    payload = {"embeds": [embed]}
    try:
        session = create_session_with_retries(total_retries=3, backoff_factor=0.5)
        r = session.post(url, json=payload, timeout=10)
        r.raise_for_status()
        default_logger.info(f"Notification Discord envoyée (nouvelle entité surveillée : {value})")
        return True
    except Exception as e:
        default_logger.warning(f"Erreur Discord (ajout entité surveillée) : {e}")
        return False


# ── Slack ─────────────────────────────────────────────────────────────────────

def send_text_discord(
    *,
    title: str,
    description: str,
    footer: str = "",
    color: Optional[int] = None,
    image_bytes: Optional[bytes] = None,
    image_name: str = "chart.png",
    images: Optional[list] = None,
    webhook_url: Optional[str] = None,
) -> bool:
    """Envoie une notification Discord générique : un embed titre + description Markdown.

    Images : `image_bytes` (une seule) OU `images` = liste de (nom, bytes) pour en
    joindre plusieurs (Discord n'affiche qu'une image par embed → on crée un embed
    par image, en réutilisant titre/description sur le premier).
    """
    url = webhook_url or os.getenv("WEBHOOK_DISCORD", "")
    if not url:
        default_logger.debug("WEBHOOK_DISCORD non configuré — Discord ignoré")
        return False

    # Normalise la/les image(s) en liste (nom, bytes)
    imgs: list = []
    if images:
        imgs = [(n, b) for (n, b) in images if b]
    elif image_bytes:
        imgs = [(image_name, image_bytes)]

    base = {
        "title": (title or "WUDD.ai")[:256],
        "description": (description or "")[:_DISCORD_DESC_LIMIT] or "_(vide)_",
        "color": color if color is not None else _NIVEAU_COLOR["info"],
    }
    if footer:
        base["footer"] = {"text": footer[:2048]}

    embeds: list = []
    files: dict = {}
    if imgs:
        for i, (name, data) in enumerate(imgs[:_DISCORD_MAX_EMBEDS]):
            emb = base if i == 0 else {"color": base["color"]}
            emb["image"] = {"url": f"attachment://{name}"}
            embeds.append(emb)
            files[f"file{i}"] = (name, data, "image/png")
    else:
        embeds.append(base)

    payload = {"embeds": embeds}
    try:
        session = create_session_with_retries(total_retries=3, backoff_factor=0.5)
        if files:
            r = session.post(url, data={"payload_json": json.dumps(payload)},
                             files=files, timeout=20)
        else:
            r = session.post(url, json=payload, timeout=10)
        r.raise_for_status()
        default_logger.info("Notification Discord (texte) envoyée")
        return True
    except Exception as e:
        default_logger.warning(f"Erreur Discord (texte) : {e}")
        return False


def send_slack(
    alerts: list,
    webhook_url: Optional[str] = None,
    title: str = "WUDD.ai · Tendances détectées",
    top_n: int = 10,
) -> bool:
    """Envoie les alertes vers un webhook Slack Incoming Webhooks.

    Returns:
        True si l'envoi a réussi.
    """
    url = webhook_url or os.getenv("WEBHOOK_SLACK", "")
    if not url:
        default_logger.debug("WEBHOOK_SLACK non configuré — Slack ignoré")
        return False

    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": title}},
        {"type": "divider"},
    ]
    for a in alerts[:top_n]:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": _format_alert_text(a)},
        })

    payload = {"blocks": blocks}
    try:
        session = create_session_with_retries(total_retries=3, backoff_factor=0.5)
        r = session.post(url, json=payload, timeout=10)
        r.raise_for_status()
        default_logger.info(f"Notification Slack envoyée ({len(alerts[:top_n])} alertes)")
        return True
    except Exception as e:
        default_logger.warning(f"Erreur Slack : {e}")
        return False


# ── Ntfy ──────────────────────────────────────────────────────────────────────

def send_ntfy(
    alerts: list,
    ntfy_url: Optional[str] = None,
    ntfy_token: Optional[str] = None,
    top_n: int = 5,
) -> bool:
    """Envoie les alertes vers un serveur Ntfy.

    Returns:
        True si l'envoi a réussi.
    """
    url = ntfy_url or os.getenv("NTFY_URL", "")
    token = ntfy_token or os.getenv("NTFY_TOKEN", "")
    if not url:
        default_logger.debug("NTFY_URL non configuré — Ntfy ignoré")
        return False

    top = alerts[:top_n]
    if not top:
        return True

    # Niveau le plus élevé parmi les alertes
    niveaux_order = {"critique": 3, "élevé": 2, "modéré": 1}
    max_niveau = max(top, key=lambda a: niveaux_order.get(a.get("niveau", "modéré"), 1))
    priority_map = {"critique": "urgent", "élevé": "high", "modéré": "default"}
    priority = priority_map.get(max_niveau.get("niveau", "modéré"), "default")

    title = f"WUDD.ai · {len(top)} tendance(s)"
    lines = [_format_alert_text(a, markdown=False).replace("**", "") for a in top]
    message = "\n".join(lines)

    headers = {
        "Title": title,
        "Priority": priority,
        "Tags": "newspaper,chart_increasing",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        session = create_session_with_retries(total_retries=3, backoff_factor=0.5)
        r = session.post(url, data=message.encode("utf-8"), headers=headers, timeout=10)
        r.raise_for_status()
        default_logger.info(f"Notification Ntfy envoyée ({len(top)} alertes)")
        return True
    except Exception as e:
        default_logger.warning(f"Erreur Ntfy : {e}")
        return False


# ── API publique ──────────────────────────────────────────────────────────────

def notify_alerts(
    alerts: list,
    title: str = "WUDD.ai · Tendances détectées",
    top_n: int = 10,
) -> dict[str, bool]:
    """Envoie les alertes vers toutes les plateformes configurées.

    Returns:
        Dictionnaire {plateforme: bool} indiquant le statut d'envoi.
    """
    if not alerts:
        default_logger.info("Aucune alerte à notifier")
        return {}

    results = {}
    discord_url = os.getenv("WEBHOOK_DISCORD", "")
    slack_url = os.getenv("WEBHOOK_SLACK", "")
    ntfy_url = os.getenv("NTFY_URL", "")

    if discord_url:
        results["discord"] = send_discord(alerts, discord_url, title, top_n)
    if slack_url:
        results["slack"] = send_slack(alerts, slack_url, title, top_n)
    if ntfy_url:
        results["ntfy"] = send_ntfy(alerts, ntfy_url, top_n=min(top_n, 5))

    if not results:
        default_logger.info(
            "Aucune plateforme webhook configurée. "
            "Ajoutez WEBHOOK_DISCORD, WEBHOOK_SLACK ou NTFY_URL dans .env"
        )

    return results
