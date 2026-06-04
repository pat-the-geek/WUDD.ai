#!/usr/bin/env python3
"""Digest personnalisé par profil utilisateur.

Génère un rapport Markdown dans rapports/markdown/_WUDD.AI_/ pour chaque profil
défini dans config/user_profiles.json, en filtrant et classant les articles
selon les préférences du profil (entités, thèmes, sources, mots-clés).

Usage:
    python3 scripts/generate_personal_digest.py
    python3 scripts/generate_personal_digest.py --profile default
    python3 scripts/generate_personal_digest.py --days 7 --dry-run
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))

from utils.config import get_config
from utils.logging import default_logger as LOG
from utils.date_utils import parse_article_date
from utils.report_cleanup import cleanup_old_dated_reports
from utils.deduplication import Deduplicator
from utils.source_credibility import CredibilityEngine
from utils.exporters.webhook import send_digest_discord


def _article_title(art: dict) -> str:
    """Titre d'un article : champ « Titre », sinon 1re ligne du résumé, sinon source."""
    t = (art.get("Titre") or "").strip()
    if t:
        return t
    rl = [l.strip() for l in (art.get("Résumé") or "").splitlines() if l.strip()]
    return rl[0] if rl else (art.get("Sources") or "Article")


def _highlight_entities(text: str, entities: dict) -> str:
    """Met en **gras** la première occurrence de chaque entité nommée dans le texte.

    Une seule passe regex (alternatives triées par longueur décroissante) pour
    éviter les imbrications ; chaque entité n'est mise en gras qu'une fois.
    """
    if not text or not isinstance(entities, dict):
        return text
    values = {
        v.strip()
        for vals in entities.values() if isinstance(vals, list)
        for v in vals
        if isinstance(v, str) and len(v.strip()) >= 3
    }
    if not values:
        return text
    ordered = sorted(values, key=len, reverse=True)
    pattern = re.compile(
        r"(?<!\*)\b(" + "|".join(re.escape(v) for v in ordered) + r")\b(?!\*)",
        re.IGNORECASE,
    )
    seen: set[str] = set()

    def _repl(m: re.Match) -> str:
        val = m.group(0)
        key = val.lower()
        if key in seen:
            return val
        seen.add(key)
        return f"**{val}**"

    return pattern.sub(_repl, text)


# Thématiques de veille (config/thematiques_societales.json) — emoji par thème
_THEME_EMOJI = {
    "Intelligence Artificielle & Technologie": "🤖",
    "Économie & Entreprises": "📈",
    "Protection des Consommateurs": "🛒",
    "Politique & Géopolitique": "🌍",
    "Médias & Information": "📰",
    "Éthique & Droits": "🧭",
    "Sécurité & Cybersécurité": "🔒",
    "Justice & Réglementation": "⚖️",
    "Santé": "🏥",
    "Emploi & Travail": "💼",
    "Éducation & Formation": "🎓",
    "Environnement": "🌱",
}
_THEME_AUTRES = "Autres"


def _load_thematiques(project_root: Path) -> list[tuple[str, "re.Pattern"]]:
    """Charge les thématiques de veille triées par rang.

    Retourne une liste de (nom, regex compilée des mots-clés, bornée par \\b).
    """
    path = project_root / "config" / "thematiques_societales.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    them = data.get("thematiques", {})
    ordered = sorted(them.items(), key=lambda kv: kv[1].get("rang", 999))
    result: list[tuple[str, "re.Pattern"]] = []
    for name, info in ordered:
        mots = [m for m in info.get("mots_cles", []) if isinstance(m, str) and m.strip()]
        if not mots:
            continue
        pattern = re.compile(
            r"\b(" + "|".join(re.escape(m) for m in mots) + r")\b", re.IGNORECASE
        )
        result.append((name, pattern))
    return result


def _classify_article(art: dict, thematiques: list) -> str | None:
    """Retourne la thématique dominante (plus d'occurrences de mots-clés) ou None."""
    parts = [str(art.get("Titre") or ""), str(art.get("Résumé") or "")]
    for vals in (art.get("entities") or {}).values():
        if isinstance(vals, list):
            parts.extend(str(v) for v in vals)
    text = " ".join(parts)
    best, best_n = None, 0
    for name, pattern in thematiques:
        n = len(pattern.findall(text))
        if n > best_n:
            best_n, best = n, name
    return best


def _demote_headings(md: str) -> str:
    """Ajoute un niveau (#) à chaque titre pour l'imbriquer sous le titre d'article (###)."""
    out = []
    for line in md.splitlines():
        s = line.lstrip()
        if s.startswith("#"):
            n = len(s) - len(s.lstrip("#"))
            out.append("#" * min(n + 1, 6) + s[n:])
        else:
            out.append(line)
    return "\n".join(out)


def _highlight_md_body(md: str, entities: dict) -> str:
    """Surligne les NER ligne par ligne, en laissant les titres `#` intacts."""
    return "\n".join(
        line if line.lstrip().startswith("#") else _highlight_entities(line, entities)
        for line in md.splitlines()
    )


def _as_blockquote(text: str) -> str:
    """Transforme un texte multi-lignes en citation Markdown (encadré visuel)."""
    return "\n".join(("> " + l) if l.strip() else ">" for l in text.splitlines())


def _generate_synthesis(top: list, profile_name: str, days: int, use_ai: bool = True) -> str:
    """Génère une synthèse & mise en perspective via l'IA configurée (EurIA/Claude/Ollama).

    Retourne du Markdown (paragraphes) ou "" si IA désactivée / indisponible.
    """
    if not use_ai or not top:
        return ""
    items = []
    for _score, art in top[:15]:
        titre = (art.get("Titre") or "").strip()
        if not titre:
            rl = [l.strip() for l in (art.get("Résumé") or "").splitlines() if l.strip()]
            titre = rl[0] if rl else (art.get("Sources") or "")
        src = art.get("Sources", "")
        extrait = " ".join((art.get("Résumé") or "").split())[:300]
        items.append(f"- [{src}] {titre} — {extrait}")
    contexte = "\n".join(items)
    prompt = (
        "Tu es analyste de veille informationnelle. À partir de la sélection d'articles "
        f"ci-dessous (profil « {profile_name} », {days} derniers jours), rédige en français une "
        "SYNTHÈSE & MISE EN PERSPECTIVE de qualité éditoriale. Règles :\n"
        "- 2 à 4 paragraphes rédigés (pas de liste, pas de titre) ;\n"
        "- dégage les tendances de fond, les liens entre sujets et les signaux faibles ;\n"
        "- mets en **gras** quelques points-clés, avec parcimonie ;\n"
        "- n'invente aucun fait : appuie-toi uniquement sur les articles fournis ;\n"
        "- style fluide et soigné (lissage global de la qualité).\n\n"
        f"Articles :\n{contexte}"
    )
    try:
        from utils.api_client import get_ai_client
        out = (get_ai_client().ask(prompt, timeout=120, max_tokens=900) or "").strip()
    except Exception as exc:
        LOG.warning(f"[digest] Synthèse IA indisponible : {exc}")
        return ""
    low = out.lower()
    if not out or low.startswith("erreur") or low.startswith("désolé"):
        return ""
    return out


_IMG_VALID_CACHE: dict[str, bool] = {}


def _image_is_valid(url: str) -> bool:
    """Vérifie qu'une URL d'image est accessible (pas de lien cassé dans le rapport).

    HEAD puis GET de secours ; exige un statut 200 et un Content-Type image/*.
    Résultats mis en cache pour la durée du run.
    """
    if not url or not url.lower().startswith(("http://", "https://")):
        return False
    if url in _IMG_VALID_CACHE:
        return _IMG_VALID_CACHE[url]
    ok = False
    try:
        import requests
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.head(url, timeout=5, allow_redirects=True, headers=headers)
        ctype = r.headers.get("Content-Type", "").lower()
        if r.status_code >= 400 or r.status_code == 405 or not ctype.startswith("image"):
            # HEAD non supporté / Content-Type absent → GET de secours
            r = requests.get(url, timeout=6, stream=True, headers=headers)
            ctype = r.headers.get("Content-Type", "").lower()
        ok = (r.status_code == 200) and ctype.startswith("image")
        r.close()
    except Exception:
        ok = False
    _IMG_VALID_CACHE[url] = ok
    return ok


_CJK_RE = re.compile(r"[一-鿿㐀-䶿豈-﫿]")


def _chapter_via_ai(resume: str) -> str:
    """Reformate le résumé en chapitres Markdown via le provider cloud configuré
    (EurIA/Claude) — qualité éditoriale, français propre, espaces corrects.

    Retourne "" en cas d'échec ou de dérive de langue (l'appelant garde le brut).
    """
    resume = (resume or "").strip()
    if not resume:
        return ""
    prompt = (
        "Reformate fidèlement le résumé d'article ci-dessous en Markdown, EN FRANÇAIS, "
        "structuré en chapitres. Règles STRICTES :\n"
        "- N'invente AUCUN fait ; n'ajoute ni ne retire rien au fond.\n"
        "- Commence par « ### En bref » (1 à 2 phrases d'accroche), puis ajoute 1 à 3 "
        "chapitres ### seulement si le contenu le justifie (### Contexte, ### Enjeux, ### Détails).\n"
        "- Rédige des phrases complètes et bien espacées ; AUCUN mot collé.\n"
        "- Réponds UNIQUEMENT avec le Markdown, sans préambule ni commentaire.\n\n"
        f"Résumé :\n{resume}"
    )
    try:
        from utils.api_client import get_ai_client
        out = (get_ai_client().ask(prompt, timeout=90, max_tokens=700) or "").strip()
    except Exception as exc:
        LOG.warning(f"[digest] Chapitrage IA indisponible : {exc}")
        return ""
    low = out.lower()
    if not out or low.startswith(("erreur", "désolé")) or _CJK_RE.search(out):
        return ""
    return out


def _render_article_block(art: dict, score: float, use_ai: bool = True) -> list[str]:
    """Rend un article du digest : titre H3, image cliquable (vérifiée), corps chapitré
    (Résumé_md ou généré par IA si absent) avec NER, lien en fin."""
    src = art.get("Sources", "Source inconnue")
    url = art.get("URL", "#")
    _dt_pub = parse_article_date(art.get("Date de publication") or "")
    date_pub = _dt_pub.strftime("%d/%m/%Y") if _dt_pub else (art.get("Date de publication") or "")[:10]
    resume = art.get("Résumé", "") or ""
    resume_lines = [l.strip() for l in resume.splitlines() if l.strip()]
    ents = art.get("entities", {}) or {}

    titre_field = (art.get("Titre") or "").strip()
    titre = titre_field or (resume_lines[0] if resume_lines else f"{src} — {date_pub}")

    # Corps : chapitrage via le cloud configuré (qualité) si IA activée, sinon
    # paragraphe à partir du résumé brut (propre, espaces garantis).
    md_body = _chapter_via_ai(resume) if (use_ai and resume.strip()) else ""
    if md_body:
        resume_body = _highlight_md_body(_demote_headings(md_body), ents)
    else:
        body_lines = resume_lines if titre_field else resume_lines[1:]
        resume_body = _highlight_entities(" ".join(body_lines), ents)

    sentiment = art.get("sentiment", "")
    sentiment_emoji = {"positif": "🟢", "négatif": "🔴", "neutre": "⚪"}.get(sentiment, "")

    img_url = ""
    images = art.get("Images") or []
    if isinstance(images, list) and images:
        first_img = images[0]
        if isinstance(first_img, dict):
            # Données hétérogènes : clé « URL » (doc) ou « url » (flux RSS)
            img_url = (first_img.get("URL") or first_img.get("url") or "").strip()
        elif isinstance(first_img, str):
            img_url = first_img.strip()
    titre_alt = titre.replace("[", "(").replace("]", ")")

    block = [
        f"### {titre} {sentiment_emoji}".rstrip(),
        "",
        f"*{src} · {date_pub} · score profil {score:.2f}*",
        "",
    ]
    if img_url and _image_is_valid(img_url):
        block += [f"[![{titre_alt}]({img_url})]({url})", ""]
    if resume_body:
        block += [resume_body, ""]
    block += [
        f"[🔗 Lire l'article original]({url})",
        "",
        "---",
        "",
    ]
    return block


def _load_profiles(project_root: Path) -> list[dict]:
    f = project_root / "config" / "user_profiles.json"
    if not f.exists():
        return []
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _to_utc(dt):
    """Rend un datetime conscient en UTC (suppose UTC si naïf)."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _collect_articles(project_root: Path, days: int) -> list[dict]:
    """Collecte et déduplique les articles publiés dans la fenêtre des N derniers jours.

    - Exclut cache, index et agrégats dérivés `_WUDD.AI_` (évite les doublons).
    - Ne lit que les fichiers modifiés récemment (perf), puis filtre CHAQUE article
      par sa date de publication réelle (`parse_article_date`).
    - Déduplique (URL exacte / résumé / similarité Jaccard).
    """
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)
    # Un article publié dans la fenêtre a forcément été écrit dans la fenêtre :
    # on ignore les fichiers non modifiés récemment (marge de sécurité d'1 jour).
    file_mtime_cutoff = (cutoff - timedelta(days=1)).timestamp()
    articles: list[dict] = []

    for source_dir in [project_root / "data" / "articles-from-rss",
                        project_root / "data" / "articles"]:
        if not source_dir.exists():
            continue
        for json_file in source_dir.rglob("*.json"):
            rel_parts = json_file.relative_to(source_dir).parts
            if "cache" in rel_parts or "_WUDD.AI_" in rel_parts or "index" in json_file.name:
                continue
            try:
                if json_file.stat().st_mtime < file_mtime_cutoff:
                    continue
                data = json.loads(json_file.read_text(encoding="utf-8"))
                if not isinstance(data, list):
                    continue
            except Exception:
                continue
            for art in data:
                if not isinstance(art, dict):
                    continue
                dt = _to_utc(parse_article_date(art.get("Date de publication") or ""))
                # Dans la fenêtre ; on tolère les dates illisibles (dt None)
                if dt is not None and dt < cutoff:
                    continue
                articles.append(art)

    try:
        articles = Deduplicator().deduplicate(articles)
    except Exception as exc:
        LOG.warning(f"[digest] Déduplication ignorée : {exc}")
    return articles


def _score_article_for_profile(article: dict, profile: dict, now=None,
                               days: int = 7, cred: "CredibilityEngine | None" = None) -> float:
    """Calcule un score de pertinence d'un article pour un profil (0.0 à 1.0+).

    Ajoute un score de BASE (récence + crédibilité source) afin que les profils sans
    préférences (ex. « default ») soient tout de même classés de façon pertinente.
    """
    score = 0.0
    entities = profile.get("entities", [])
    themes = profile.get("themes", [])
    sources = profile.get("sources", [])
    keywords = profile.get("keywords", [])
    exclude_sources = profile.get("exclude_sources", [])
    exclude_keywords = profile.get("exclude_keywords", [])

    src = str(article.get("Sources", "")).strip()
    resume = str(article.get("Résumé", "") or "").lower()
    art_entities = article.get("entities", {}) or {}

    # Exclusions
    if src in exclude_sources:
        return -1.0
    for kw in exclude_keywords:
        if kw.lower() in resume:
            return -1.0

    # Sources favorites
    if sources and src in sources:
        score += 0.4

    # Entités surveillées
    all_entity_values = [
        v.lower()
        for vals in art_entities.values()
        for v in (vals if isinstance(vals, list) else [])
    ]
    for ent in entities:
        if ent.lower() in all_entity_values:
            score += 0.5

    # Mots-clés
    for kw in keywords:
        if kw.lower() in resume:
            score += 0.3

    # Thèmes (matching simple sur le résumé)
    for theme in themes:
        if theme.lower() in resume:
            score += 0.2

    # Score de pertinence existant (normalisé /10)
    existing = article.get("score_pertinence")
    if existing is not None:
        score += float(existing) / 10.0

    # Score de BASE — récence (0–0.3) : départage même sans préférences
    if now is not None:
        dt = _to_utc(parse_article_date(article.get("Date de publication") or ""))
        if dt is not None:
            age_days = max(0.0, (now - dt).total_seconds() / 86400.0)
            score += 0.3 * max(0.0, 1.0 - age_days / max(days, 1))

    # Score de BASE — crédibilité de la source (0–0.2)
    cred_val = article.get("score_source")
    if cred_val is None and cred is not None:
        try:
            cred_val = cred.get_score(src)
        except Exception:
            cred_val = None
    if cred_val is not None:
        try:
            score += 0.2 * (float(cred_val) / 100.0)
        except (TypeError, ValueError):
            pass

    return score


def _select_digest(scored: list, top_n: int, thematiques: list,
                   max_per_source: int = 2) -> list:
    """Sélection « vrai digest » : round-robin par thématique pour maximiser la
    diversité des sujets, en plafonnant chaque source (`max_per_source`).

    `scored` est trié par score décroissant. On groupe par thématique dominante,
    puis on pioche tour à tour le meilleur article de chaque thème (en sautant les
    sources saturées). Si la contrainte empêche d'atteindre `top_n`, on complète en
    relâchant le plafond de source.
    """
    from collections import OrderedDict
    by_theme: "OrderedDict[str, list]" = OrderedDict()
    for item in scored:
        theme = _classify_article(item[1], thematiques) or _THEME_AUTRES
        by_theme.setdefault(theme, []).append(item)

    # Thèmes ordonnés par le meilleur score qu'ils contiennent
    theme_keys = sorted(by_theme, key=lambda t: by_theme[t][0][0], reverse=True)
    idx = {t: 0 for t in theme_keys}
    selected, per_source = [], {}
    chosen_ids = set()

    progress = True
    while len(selected) < top_n and progress:
        progress = False
        for t in theme_keys:
            lst = by_theme[t]
            while idx[t] < len(lst):
                cand = lst[idx[t]]
                idx[t] += 1
                src = str(cand[1].get("Sources", ""))
                if per_source.get(src, 0) < max_per_source:
                    selected.append(cand)
                    chosen_ids.add(id(cand[1]))
                    per_source[src] = per_source.get(src, 0) + 1
                    progress = True
                    break
            if len(selected) >= top_n:
                break

    # Complément (sources saturées) : on relâche le plafond pour atteindre top_n
    if len(selected) < top_n:
        for item in scored:
            if len(selected) >= top_n:
                break
            if id(item[1]) not in chosen_ids:
                selected.append(item)
    return selected[:top_n]


def generate_profile_digest(
    project_root: Path,
    profile: dict,
    days: int = 7,
    dry_run: bool = False,
    use_ai: bool = True,
    notify_discord: bool = True,
) -> Path | None:
    """Génère le digest Markdown pour un profil donné."""
    profile_id = profile.get("id", "unknown")
    profile_name = profile.get("name", profile_id)
    top_n = profile.get("top_n", 10)
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y-%m-%d")

    articles = _collect_articles(project_root, days=days)
    if not articles:
        LOG.info(f"[digest] Profil '{profile_id}' : aucun article trouvé")
        return None

    # Scorer (préférences profil + base récence/crédibilité), filtrer, puis
    # sélectionner en round-robin thématique pour un vrai digest diversifié.
    cred = CredibilityEngine(project_root)
    thematiques = _load_thematiques(project_root)
    scored = []
    for art in articles:
        s = _score_article_for_profile(art, profile, now=now, days=days, cred=cred)
        if s >= 0:
            scored.append((s, art))
    scored.sort(key=lambda x: x[0], reverse=True)
    top = _select_digest(scored, top_n, thematiques, max_per_source=2)

    lines = [
        "---",
        f'title: "Digest {profile_name} — {date_str}"',
        f"date: {date_str}",
        'type: digest-personnalise',
        f'profil: "{profile_id}"',
        f'tags: ["wudd-ai", "digest", "{profile_id}"]',
        "---",
        "",
        f"# Digest personnalisé — {profile_name}",
        "",
        f"> **Période** : {(now - timedelta(days=days)).strftime('%d/%m/%Y')} → {now.strftime('%d/%m/%Y')} ({days} jours)  ",
        f"> **{len(top)} articles sélectionnés** parmi {len(articles)} collectés  ",
        f"> **Profil** : {profile.get('description', profile_name)}",
        "",
        "---",
        "",
    ]

    # Données pour la notification Discord (remplies si articles)
    discord_synthese = ""
    discord_articles: list = []
    discord_nb_themes = 0

    if not top:
        lines.append("*Aucun article pertinent trouvé pour ce profil sur cette période.*")
    else:
        # Synthèse & mise en perspective IA (en tête, en encadré)
        synthese = _generate_synthesis(top, profile_name, days, use_ai=use_ai)
        discord_synthese = synthese
        if synthese:
            lines += [
                "## 🧭 Synthèse & mise en perspective",
                "",
                _as_blockquote(synthese),
                "",
                "---",
                "",
            ]

        # Regroupe les articles (déjà triés par score) par thématique de veille dominante
        # (thematiques déjà chargées plus haut pour la sélection)
        grouped: dict[str, list] = {}
        for score, art in top:
            theme = _classify_article(art, thematiques) or _THEME_AUTRES
            grouped.setdefault(theme, []).append((score, art))

        # Ordre d'affichage : thématiques par rang, « Autres » en dernier
        theme_order = [name for name, _ in thematiques if name in grouped]
        if _THEME_AUTRES in grouped:
            theme_order.append(_THEME_AUTRES)

        # Sommaire des thématiques
        lines += ["**Thématiques :** " + " · ".join(
            f"{_THEME_EMOJI.get(t, '🗂️')} {t} ({len(grouped[t])})" for t in theme_order
        ), "", "---", ""]

        for theme in theme_order:
            arts = grouped[theme]
            emoji = _THEME_EMOJI.get(theme, "🗂️")
            theme_label = f"{emoji} {theme}"
            lines += [f"## {theme_label} ({len(arts)})", ""]
            for score, art in arts:
                lines += _render_article_block(art, score, use_ai=use_ai)
                # Données Discord par article : vignette validée + accroche courte
                img = ""
                imgs = art.get("Images")
                if isinstance(imgs, list) and imgs and isinstance(imgs[0], dict):
                    u = (imgs[0].get("URL") or imgs[0].get("url") or "").strip()
                    if u and _image_is_valid(u):
                        img = u
                snippet = " ".join((art.get("Résumé") or "").split())
                if len(snippet) > 220:
                    snippet = snippet[:219].rstrip() + "…"
                discord_articles.append({
                    "title": _article_title(art),
                    "url": art.get("URL", ""),
                    "image": img,
                    "theme": theme_label,
                    "snippet": snippet,
                })

        discord_nb_themes = len(theme_order)

    lines += [
        "",
        f"*Digest généré automatiquement par WUDD.ai — profil `{profile_id}`*",
    ]

    out_dir = project_root / "rapports" / "markdown" / "_WUDD.AI_"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"digest_{profile_id}_{date_str}.md"

    if not dry_run:
        out_file.write_text("\n".join(lines), encoding="utf-8")
        LOG.info(f"[digest] Rapport créé : {out_file}")
        cleanup_old_dated_reports(out_file)

        # Notification Discord (silencieuse si WEBHOOK_DISCORD non configuré)
        if notify_discord and top:
            try:
                send_digest_discord(
                    title=f"🗞️ Digest {profile_name} — {now.strftime('%d/%m/%Y')}",
                    synthesis=discord_synthese,
                    articles=discord_articles,
                    footer=f"{len(top)} articles · {discord_nb_themes} thématiques · WUDD.ai",
                )
            except Exception as exc:
                LOG.warning(f"[digest] Notification Discord échouée : {exc}")
    else:
        LOG.info(f"[digest] dry-run — {out_file}")

    return out_file


def main() -> None:
    parser = argparse.ArgumentParser(description="Digest personnalisé par profil WUDD.ai")
    parser.add_argument("--profile", help="ID du profil à générer (tous si absent)")
    parser.add_argument("--days", type=int, default=7, help="Fenêtre en jours (défaut: 7)")
    parser.add_argument("--dry-run", action="store_true", help="Simulation sans écriture")
    parser.add_argument("--no-ai", action="store_true",
                        help="Désactive la synthèse IA et la génération des chapitres manquants")
    parser.add_argument("--no-discord", action="store_true",
                        help="N'envoie pas la notification Discord du digest")
    args = parser.parse_args()

    config = get_config()
    profiles = _load_profiles(config.project_root)
    if not profiles:
        print("Aucun profil trouvé dans config/user_profiles.json")
        return

    if args.profile:
        profiles = [p for p in profiles if p.get("id") == args.profile]
        if not profiles:
            print(f"Profil '{args.profile}' introuvable")
            return

    for profile in profiles:
        out = generate_profile_digest(
            config.project_root, profile, days=args.days,
            dry_run=args.dry_run, use_ai=not args.no_ai,
            notify_discord=not args.no_discord,
        )
        if out:
            print(f"Digest généré : {out}")


if __name__ == "__main__":
    main()
