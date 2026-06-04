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
from utils.summary_formatter import format_summary_markdown


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


def _render_article_block(art: dict, score: float, use_ai: bool = True) -> list[str]:
    """Rend un article du digest : titre H3, image cliquable, corps chapitré (Résumé_md
    ou généré par IA si absent) avec NER, lien en fin."""
    src = art.get("Sources", "Source inconnue")
    url = art.get("URL", "#")
    _dt_pub = parse_article_date(art.get("Date de publication") or "")
    date_pub = _dt_pub.strftime("%d/%m/%Y") if _dt_pub else (art.get("Date de publication") or "")[:10]
    resume = art.get("Résumé", "") or ""
    resume_lines = [l.strip() for l in resume.splitlines() if l.strip()]
    ents = art.get("entities", {}) or {}

    titre_field = (art.get("Titre") or "").strip()
    titre = titre_field or (resume_lines[0] if resume_lines else f"{src} — {date_pub}")

    # Corps chapitré : Résumé_md si présent, sinon généré par IA, sinon paragraphe brut.
    md_body = (art.get("Résumé_md") or "").strip()
    if not md_body and use_ai and resume.strip():
        try:
            md_body = (format_summary_markdown(resume) or "").strip()
        except Exception:
            md_body = ""
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
    if img_url:
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


def _collect_articles(project_root: Path, days: int) -> list[dict]:
    """Collecte les articles récents des N derniers jours."""
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)
    articles = []

    for source_dir in [project_root / "data" / "articles-from-rss",
                        project_root / "data" / "articles"]:
        if not source_dir.exists():
            continue
        for json_file in sorted(source_dir.rglob("*.json"),
                                key=lambda f: f.stat().st_mtime, reverse=True)[:30]:
            if "cache" in str(json_file) or "index" in json_file.name:
                continue
            try:
                data = json.loads(json_file.read_text(encoding="utf-8"))
                if not isinstance(data, list):
                    continue
                for art in data:
                    d = art.get("Date de publication", "") or ""
                    # Accepter les dates récentes
                    articles.append(art)
            except Exception:
                continue

    return articles


def _score_article_for_profile(article: dict, profile: dict) -> float:
    """Calcule un score de pertinence d'un article pour un profil (0.0 à 1.0+)."""
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

    return score


def generate_profile_digest(
    project_root: Path,
    profile: dict,
    days: int = 7,
    dry_run: bool = False,
    use_ai: bool = True,
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

    # Scorer et filtrer
    scored = []
    for art in articles:
        s = _score_article_for_profile(art, profile)
        if s >= 0:
            scored.append((s, art))
    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:top_n]

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

    if not top:
        lines.append("*Aucun article pertinent trouvé pour ce profil sur cette période.*")
    else:
        # Synthèse & mise en perspective IA (en tête, en encadré)
        synthese = _generate_synthesis(top, profile_name, days, use_ai=use_ai)
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
        thematiques = _load_thematiques(project_root)
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
            lines += [f"## {emoji} {theme} ({len(arts)})", ""]
            for score, art in arts:
                lines += _render_article_block(art, score, use_ai=use_ai)

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
        )
        if out:
            print(f"Digest généré : {out}")


if __name__ == "__main__":
    main()
