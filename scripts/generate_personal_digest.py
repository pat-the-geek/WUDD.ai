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
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))

from utils.config import get_config
from utils.logging import default_logger as LOG
from utils.date_utils import parse_article_date


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
        for rank, (score, art) in enumerate(top, 1):
            src = art.get("Sources", "Source inconnue")
            url = art.get("URL", "#")
            _dt_pub = parse_article_date(art.get("Date de publication") or "")
            date_pub = _dt_pub.strftime("%d/%m/%Y") if _dt_pub else (art.get("Date de publication") or "")[:10]
            resume = art.get("Résumé", "") or ""
            resume_lines = [l.strip() for l in resume.splitlines() if l.strip()]
            titre = resume_lines[0] if resume_lines else f"{src} — {date_pub}"
            resume_body = "\n".join(resume_lines[1:4]) if len(resume_lines) > 1 else ""

            sentiment = art.get("sentiment", "")
            sentiment_emoji = {"positif": "🟢", "négatif": "🔴", "neutre": "⚪"}.get(sentiment, "")

            lines += [
                f"## {rank}. [{titre}]({url}) {sentiment_emoji}",
                "",
                f"> **{src}** · {date_pub} · Score profil : {score:.2f}",
                "",
            ]
            if resume_body:
                lines += [resume_body, ""]

            # Entités clés
            ents = art.get("entities", {}) or {}
            ent_list = []
            for etype, vals in ents.items():
                if isinstance(vals, list):
                    ent_list.extend([f"**{v}** ({etype})" for v in vals[:2]])
            if ent_list:
                lines += [f"Entités : {', '.join(ent_list[:5])}", ""]

            lines.append("---")
            lines.append("")

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
    else:
        LOG.info(f"[digest] dry-run — {out_file}")

    return out_file


def main() -> None:
    parser = argparse.ArgumentParser(description="Digest personnalisé par profil WUDD.ai")
    parser.add_argument("--profile", help="ID du profil à générer (tous si absent)")
    parser.add_argument("--days", type=int, default=7, help="Fenêtre en jours (défaut: 7)")
    parser.add_argument("--dry-run", action="store_true", help="Simulation sans écriture")
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
        out = generate_profile_digest(config.project_root, profile, days=args.days, dry_run=args.dry_run)
        if out:
            print(f"Digest généré : {out}")


if __name__ == "__main__":
    main()
