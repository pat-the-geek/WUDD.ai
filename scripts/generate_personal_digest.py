#!/usr/bin/env python3
"""Digest personnalisé par profil utilisateur.

Génère un rapport Markdown dans rapports/markdown/_WUDD.AI_/ pour chaque profil
défini dans config/user_profiles.json, en filtrant et classant les articles
selon les préférences du profil (entités, thèmes, sources, mots-clés), enrichis
par le scoring unifié, les entités surveillées et les tendances.

Améliorations : scoring unifié (ScoringEngine) + boost entités surveillées +
boost tendances + poids configurables par profil ; anti-répétition (mémoire des
articles déjà envoyés) ; regroupement par « histoire » (couverture multi-sources) ;
synthèse IA citée + « à retenir » + mini-synthèse par thématique ; métadonnées
(temps de lecture, crédibilité, ton) + « pourquoi cet article » ; sommaire à
ancres ; chapitrage cloud parallélisé (réutilise un Résumé_md propre) ; export
Discord, newsletter e-mail, flux Atom et Obsidian.

Usage:
    python3 scripts/generate_personal_digest.py
    python3 scripts/generate_personal_digest.py --profile default
    python3 scripts/generate_personal_digest.py --days 7 --dry-run
    python3 scripts/generate_personal_digest.py --email          # envoi newsletter
    python3 scripts/generate_personal_digest.py --no-discord --no-atom --no-obsidian
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata
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

_CJK_RE = re.compile(r"[一-鿿㐀-䶿豈-﫿]")
# Détection de mots collés type « lesiPhone » : minuscule suivie d'une vraie
# MAJUSCULE à l'intérieur d'un mot. La classe majuscule est explicite
# ([A-ZÀ-ÖØ-Þ]) pour NE PAS inclure les minuscules accentuées (à-ÿ).
_GLUE_WORD_RE = re.compile(r"[a-zà-ÿ][A-ZÀ-ÖØ-Þ]")
_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)
_LONGWORD_RE = re.compile(r"\S{30,}")  # token improbablement long (collé)
# Marques/produits à camelCase légitime (ne pas considérer comme « collés »)
_GLUE_WHITELIST = {
    "youtube", "macbook", "iphone", "ipad", "ipados", "airpods", "imac", "macos",
    "ios", "tvos", "watchos", "openai", "github", "chatgpt", "deepmind", "deepseek",
    "appleinsider", "powerpoint", "javascript", "spacex", "biontech", "blackrock",
    "wuddai", "tiktok", "linkedin", "paypal", "wechat", "mastercard",
}

# Poids par défaut du scoring (surchargés par profile["weights"])
_DEFAULT_WEIGHTS = {
    "engine":   0.5,   # pertinence unifiée (ScoringEngine) normalisée /100
    "watched":  0.8,   # entité surveillée (data/watched_entities.json)
    "trending": 0.8,   # entité en tendance (data/alertes.json)
    "entity":   0.6,   # entité du profil
    "keyword":  0.4,   # mot-clé du profil
    "theme":    0.25,  # thème du profil
    "source":   0.4,   # source favorite du profil
}

# Rétention de la mémoire anti-répétition (jours)
_SENT_RETENTION_DAYS = 14


# ── Utilitaires texte ─────────────────────────────────────────────────────────

def _deburr(s: str) -> str:
    """Minuscule sans accents (pour comparaisons/ancres)."""
    return "".join(
        c for c in unicodedata.normalize("NFKD", s.lower()) if not unicodedata.combining(c)
    )


def _slug(text: str) -> str:
    """Ancre Markdown façon GitHub (slug du titre)."""
    s = _deburr(text)
    s = re.sub(r"[^a-z0-9\s-]", "", s)
    s = re.sub(r"\s+", "-", s.strip())
    return re.sub(r"-{2,}", "-", s)


def _article_title(art: dict) -> str:
    """Titre d'un article : champ « Titre », sinon 1re ligne du résumé, sinon source."""
    t = (art.get("Titre") or "").strip()
    if t:
        return t
    rl = [l.strip() for l in (art.get("Résumé") or "").splitlines() if l.strip()]
    return rl[0] if rl else (art.get("Sources") or "Article")


def _highlight_entities(text: str, entities: dict) -> str:
    """Met en **gras** la première occurrence de chaque entité nommée dans le texte."""
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


# ── Thématiques de veille ───────────────────────────────────────────────────

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
    """Charge les thématiques de veille triées par rang (nom, regex mots-clés)."""
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
    """Retourne la thématique dominante ou None.

    Le titre pèse plus lourd que le résumé : c'est le signal le plus topical
    et le moins bruité. Un mot-clé polysémique croisé dans le corps du résumé
    (ex. « climat économique », « traitement des syndiqués ») ne doit pas
    l'emporter sur le sujet réel exprimé dans le titre.
    """
    title = str(art.get("Titre") or "")
    body_parts = [str(art.get("Résumé") or "")]
    for vals in (art.get("entities") or {}).values():
        if isinstance(vals, list):
            body_parts.extend(str(v) for v in vals)
    body = " ".join(body_parts)
    best, best_n = None, 0
    for name, pattern in thematiques:
        n = len(pattern.findall(body)) + 3 * len(pattern.findall(title))
        if n > best_n:
            best_n, best = n, name
    return best


def _classify_articles_ai(top: list, thematiques: list, use_ai: bool = True) -> dict:
    """Classe chaque article retenu dans UNE thématique de la liste fermée, via un
    seul appel IA groupé.

    Bien plus robuste que le comptage de mots-clés pour les termes polysémiques
    (« climat économique », « traitement des syndiqués », « santé » incident) : le
    modèle choisit la thématique *dominante* selon le sujet réel, pas un mot
    accessoire. Repli automatique sur la classification par mots-clés
    (`_classify_article`) si l'IA est désactivée, indisponible ou répond hors-liste.

    Retourne {id(art): nom_thématique}.
    """
    # Repli mot-clé — toujours calculé pour garantir une valeur par article.
    fallback = {id(art): (_classify_article(art, thematiques) or _THEME_AUTRES)
                for _s, art in top}
    if not use_ai or not top:
        return fallback

    theme_names = [name for name, _ in thematiques]
    items = []
    for i, (_s, art) in enumerate(top, 1):
        extrait = " ".join((art.get("Résumé") or "").split())[:240]
        items.append(f"[{i}] {_article_title(art)} — {extrait}")
    liste = "\n".join(theme_names + [_THEME_AUTRES])
    prompt = (
        "Tu es documentaliste de veille. Classe chaque article ci-dessous dans UNE "
        "SEULE thématique, choisie STRICTEMENT dans cette liste (recopie le libellé "
        "exact) :\n"
        f"{liste}\n\n"
        "Retiens la thématique DOMINANTE selon le sujet réel de l'article, jamais un "
        "mot accessoire cité au passage. Si aucune ne convient vraiment, réponds "
        "« Autres ».\n"
        "Réponds UNIQUEMENT par un objet JSON valide indexé par le numéro de "
        "l'article, p. ex. {\"1\": \"Santé\", \"2\": \"Autres\"}. Aucun commentaire.\n\n"
        "Articles :\n" + "\n".join(items)
    )
    try:
        from utils.api_client import get_ai_client
        raw = (get_ai_client().ask(prompt, timeout=90, max_tokens=400) or "").strip()
    except Exception as exc:
        LOG.warning(f"[digest] Classement thématique IA indisponible : {exc}")
        return fallback
    if _CJK_RE.search(raw):
        return fallback
    data = _parse_json_block(raw)
    if not isinstance(data, dict) or not data:
        return fallback

    valid = {t.lower(): t for t in theme_names}
    valid[_THEME_AUTRES.lower()] = _THEME_AUTRES
    result = dict(fallback)
    for i, (_s, art) in enumerate(top, 1):
        label = str(data.get(str(i), "")).strip().lower()
        if label in valid:
            result[id(art)] = valid[label]
    return result


# ── Sources de signaux (entités surveillées, tendances) ──────────────────────

def _load_watched_entities(project_root: Path) -> set[str]:
    """Ensemble des valeurs d'entités surveillées (minuscules)."""
    f = project_root / "data" / "watched_entities.json"
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    out = set()
    for e in (data if isinstance(data, list) else []):
        v = str(e.get("value", "")).strip().lower()
        if v:
            out.add(v)
    return out


def _load_trending_entities(project_root: Path) -> dict[str, float]:
    """Entités en tendance → poids 0–1, depuis data/alertes.json (trend_detector)."""
    f = project_root / "data" / "alertes.json"
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    niveau_w = {"info": 0.4, "modéré": 0.7, "élevé": 1.0, "critique": 1.0}
    out: dict[str, float] = {}
    for a in (data if isinstance(data, list) else []):
        if a.get("type") == "silence":   # alerte de silence : pas un boost
            continue
        v = str(a.get("entity_value", "")).strip().lower()
        if not v:
            continue
        w = niveau_w.get(a.get("niveau", ""), 0.4)
        out[v] = max(out.get(v, 0.0), w)
    return out


def _article_entity_values(art: dict) -> set[str]:
    """Valeurs d'entités d'un article (minuscules)."""
    out = set()
    for vals in (art.get("entities") or {}).values():
        if isinstance(vals, list):
            for v in vals:
                if isinstance(v, str) and v.strip():
                    out.add(v.strip().lower())
    return out


# ── Mémoire anti-répétition (#5) ─────────────────────────────────────────────

def _state_path(project_root: Path) -> Path:
    return project_root / "data" / "digest_sent.json"


def _load_digest_state(project_root: Path) -> dict:
    f = _state_path(project_root)
    if not f.exists():
        return {}
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_digest_state(project_root: Path, state: dict) -> None:
    f = _state_path(project_root)
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(f)
    except OSError as exc:
        LOG.warning(f"[digest] Mémoire anti-répétition non sauvegardée : {exc}")


def _recently_sent_urls(state: dict, profile_id: str, retention_days: int) -> set[str]:
    """URLs envoyées récemment pour ce profil (dans la fenêtre de rétention)."""
    entry = state.get(profile_id, {})
    sent = entry.get("sent", {}) if isinstance(entry, dict) else {}
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    out = set()
    for url, iso in sent.items():
        try:
            if _to_utc(datetime.fromisoformat(iso)) >= cutoff:
                out.add(url)
        except (ValueError, TypeError):
            out.add(url)  # date illisible → on considère récent (prudence)
    return out


# ── Regroupement par « histoire » (#6) ───────────────────────────────────────

def _title_tokens(art: dict) -> set[str]:
    return set(re.findall(r"[a-z0-9]{4,}", _deburr(art.get("Titre") or "")))


def _same_story(a: dict, b: dict) -> bool:
    """Heuristique : deux articles couvrent le même événement."""
    ta, tb = _title_tokens(a), _title_tokens(b)
    if ta and tb:
        jac = len(ta & tb) / len(ta | tb)
        if jac >= 0.6:
            return True
        ea, eb = _article_entity_values(a), _article_entity_values(b)
        if len(ea & eb) >= 2 and len(ta & tb) >= 2:
            return True
    return False


def _cluster_stories(scored: list, cap: int = 150) -> list:
    """Regroupe les articles d'un même événement (scored trié par score desc).

    Le représentant est le mieux noté ; on annote `_coverage` (nb d'articles) et
    `_coverage_sources` (sources distinctes). Retourne la liste des représentants.
    """
    reps: list = []
    for item in scored[:cap]:
        art = item[1]
        for rscore, rart in reps:
            if _same_story(rart, art):
                rart["_coverage"] = rart.get("_coverage", 1) + 1
                srcs = set(rart.get("_coverage_sources") or [rart.get("Sources", "")])
                srcs.add(art.get("Sources", ""))
                rart["_coverage_sources"] = sorted(s for s in srcs if s)
                break
        else:
            art["_coverage"] = 1
            art["_coverage_sources"] = [art.get("Sources", "")] if art.get("Sources") else []
            reps.append(item)
    # Articles au-delà du cap : conservés tels quels (sans clustering)
    reps.extend(scored[cap:])
    return reps


# ── Rendu Markdown ────────────────────────────────────────────────────────────

def _demote_headings(md: str) -> str:
    """Ajoute un niveau (#) à chaque titre pour l'imbriquer sous le titre d'article."""
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


_IMG_VALID_CACHE: dict[str, bool] = {}


def _image_is_valid(url: str) -> bool:
    """Vérifie qu'une URL d'image est accessible (pas de lien cassé dans le rapport)."""
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
            r = requests.get(url, timeout=6, stream=True, headers=headers)
            ctype = r.headers.get("Content-Type", "").lower()
        ok = (r.status_code == 200) and ctype.startswith("image")
        r.close()
    except Exception:
        ok = False
    _IMG_VALID_CACHE[url] = ok
    return ok


def _first_image_url(art: dict) -> str:
    imgs = art.get("Images")
    if isinstance(imgs, list) and imgs:
        first = imgs[0]
        if isinstance(first, dict):
            return (first.get("URL") or first.get("url") or "").strip()
        if isinstance(first, str):
            return first.strip()
    return ""


# ── Chapitrage IA (#15 parallèle, #16 réutilisation md propre) ────────────────

def _looks_degraded(md: str) -> bool:
    """Détecte un Markdown de mauvaise qualité (CJK, mots collés).

    Un seul mot à majuscule interne est souvent une marque légitime (WebKit,
    TechRepublic…) : on ne considère le texte dégradé qu'à partir de DEUX mots
    suspects distincts (la dégradation Ollama « lesiPhone/irréalitables… » en
    produit plusieurs).
    """
    if not md or _CJK_RE.search(md):
        return True
    if _LONGWORD_RE.search(md):
        return True
    suspects = {
        word.lower()
        for word in _WORD_RE.findall(md)
        if _GLUE_WORD_RE.search(word) and word.lower() not in _GLUE_WHITELIST
    }
    return len(suspects) >= 2


def _chapter_via_ai(resume: str) -> str:
    """Reformate le résumé en chapitres Markdown via le provider cloud configuré.

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
    # La sortie cloud (gros modèle) est propre : on ne garde que le garde-fou langue.
    low = out.lower()
    if not out or low.startswith(("erreur", "désolé")) or _CJK_RE.search(out):
        return ""
    return out


def _build_chapters(top: list, use_ai: bool) -> dict[str, str]:
    """Pré-calcule les chapitres Markdown des articles, EN PARALLÈLE (#15).

    Réutilise un `Résumé_md` stocké s'il est propre (#16) ; sinon génère via le
    cloud. Retourne {url: markdown}.
    """
    if not use_ai:
        return {}
    chapters: dict[str, str] = {}
    to_generate: list[dict] = []
    for _s, art in top:
        url = art.get("URL", "")
        stored = (art.get("Résumé_md") or "").strip()
        if stored and not _looks_degraded(stored):
            chapters[url] = stored          # #16 : réutilisation directe
        elif (art.get("Résumé") or "").strip():
            to_generate.append(art)

    if to_generate:
        try:
            from utils.parallel import run_parallel
            results = run_parallel(
                lambda a: (a.get("URL", ""), _chapter_via_ai(a.get("Résumé") or "")),
                to_generate,
                max_workers=5,
            )
        except Exception as exc:
            LOG.warning(f"[digest] Chapitrage parallèle indisponible ({exc}) — séquentiel.")
            results = [(a.get("URL", ""), _chapter_via_ai(a.get("Résumé") or "")) for a in to_generate]
        for url, md in results:
            if md:
                chapters[url] = md
    return chapters


# ── Synthèse, à-retenir (#7,#8) et mini-synthèses par thème (#9) ──────────────

def _parse_json_block(raw: str) -> dict:
    """Extrait le 1er objet JSON d'une réponse IA (robuste aux préambules)."""
    raw = (raw or "").strip()
    try:
        return json.loads(raw)
    except Exception:
        pass
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            return {}
    return {}


def _link_citations(text: str, top: list) -> str:
    """Remplace les marqueurs [n] de la synthèse par des liens vers l'article n (#8)."""
    def repl(m: re.Match) -> str:
        n = int(m.group(1))
        if 1 <= n <= len(top):
            url = top[n - 1][1].get("URL", "")
            if url:
                return f"[[{n}]]({url})"
        return m.group(0)
    return re.sub(r"\[(\d{1,2})\]", repl, text)


def _generate_synthesis(top: list, profile_name: str, days: int, use_ai: bool = True) -> dict:
    """Synthèse & mise en perspective + « à retenir » (un seul appel IA).

    Retourne {"synthese": str (avec citations [n] liées), "takeaways": [str]}.
    """
    empty = {"synthese": "", "takeaways": []}
    if not use_ai or not top:
        return empty
    items = []
    for i, (_s, art) in enumerate(top[:15], 1):
        extrait = " ".join((art.get("Résumé") or "").split())[:280]
        items.append(f"[{i}] {_article_title(art)} ({art.get('Sources', '')}) — {extrait}")
    contexte = "\n".join(items)
    prompt = (
        "Tu es analyste de veille informationnelle. À partir de la sélection d'articles "
        f"numérotés ci-dessous (profil « {profile_name} », {days} derniers jours), produis un "
        "objet JSON STRICTEMENT valide, en français, avec deux champs :\n"
        '- "synthese" : 2 à 4 paragraphes rédigés (pas de liste) dégageant les tendances de '
        "fond, les liens entre sujets et les signaux faibles ; cite tes sources en insérant "
        "le numéro entre crochets, p. ex. [2], juste après l'affirmation concernée ; mets en "
        "**gras** quelques points-clés avec parcimonie ;\n"
        '- "a_retenir" : 3 à 5 points-clés très courts (chaîne par point).\n'
        "Commence DIRECTEMENT par le JSON, sans préambule. N'invente aucun fait.\n\n"
        f"Articles :\n{contexte}"
    )
    try:
        from utils.api_client import get_ai_client
        raw = (get_ai_client().ask(prompt, timeout=120, max_tokens=1000) or "").strip()
    except Exception as exc:
        LOG.warning(f"[digest] Synthèse IA indisponible : {exc}")
        return empty
    if _CJK_RE.search(raw):
        return empty
    data = _parse_json_block(raw)
    synthese = str(data.get("synthese", "")).strip()
    takeaways = [str(t).strip() for t in data.get("a_retenir", []) if str(t).strip()]
    if not synthese and not takeaways:
        return empty
    return {"synthese": _link_citations(synthese, top), "takeaways": takeaways[:5]}


def _generate_theme_intros(grouped: dict, use_ai: bool = True) -> dict[str, str]:
    """Mini-synthèse d'une phrase par thématique (#9), en un seul appel IA."""
    if not use_ai or not grouped:
        return {}
    blocks = []
    for theme, arts in grouped.items():
        titres = "; ".join(_article_title(a) for _s, a in arts[:6])
        blocks.append(f"- {theme} : {titres}")
    prompt = (
        "Pour chaque thématique ci-dessous (avec ses titres d'articles), rédige UNE phrase "
        "de synthèse en français. Réponds UNIQUEMENT par un objet JSON valide "
        "{\"<thématique>\": \"<phrase>\"}. N'invente aucun fait.\n\n" + "\n".join(blocks)
    )
    try:
        from utils.api_client import get_ai_client
        raw = (get_ai_client().ask(prompt, timeout=90, max_tokens=600) or "").strip()
    except Exception as exc:
        LOG.warning(f"[digest] Mini-synthèses indisponibles : {exc}")
        return {}
    if _CJK_RE.search(raw):
        return {}
    data = _parse_json_block(raw)
    # Indexe par thème en minuscules pour un appariement robuste
    return {str(k).strip().lower(): str(v).strip() for k, v in data.items() if str(v).strip()}


# ── Scoring (#1,#2,#3,#4,#12) ─────────────────────────────────────────────────

def _score_article_for_profile(article, profile, now=None, days=7, cred=None,
                               watched=None, trending=None, engine=None,
                               weights=None) -> tuple[float, str]:
    """Score de pertinence d'un article pour un profil + raison de sélection (#12).

    Combine : pertinence unifiée (ScoringEngine #4), boost entités surveillées (#1),
    boost tendances (#2), préférences du profil pondérées (#3). Retourne (-1, "")
    si l'article est exclu.
    """
    w = {**_DEFAULT_WEIGHTS, **(weights or {}), **(profile.get("weights") or {})}
    src = str(article.get("Sources", "")).strip()
    resume = str(article.get("Résumé", "") or "").lower()
    art_ents = _article_entity_values(article)

    # Exclusions
    if src in profile.get("exclude_sources", []):
        return -1.0, ""
    for kw in profile.get("exclude_keywords", []):
        if kw.lower() in resume:
            return -1.0, ""

    score = 0.0
    reason = ""

    # #4 — pertinence unifiée (ScoringEngine, normalisée /100)
    if engine is not None:
        try:
            score += w["engine"] * (float(engine.score_article(article, now=now)) / 100.0)
        except Exception:
            engine = None
    if engine is None:
        # Repli : récence + crédibilité (comme avant)
        dt = _to_utc(parse_article_date(article.get("Date de publication") or ""))
        if dt is not None and now is not None:
            age = max(0.0, (now - dt).total_seconds() / 86400.0)
            score += 0.3 * max(0.0, 1.0 - age / max(days, 1))
        cv = article.get("score_source")
        if cv is None and cred is not None:
            try:
                cv = cred.get_score(src)
            except Exception:
                cv = None
        if cv is not None:
            try:
                score += 0.2 * (float(cv) / 100.0)
            except (TypeError, ValueError):
                pass

    # #1 — entités surveillées
    if watched:
        hit = next((e for e in art_ents if e in watched), None)
        if hit:
            score += w["watched"]
            reason = reason or f"🔔 Entité surveillée : {hit}"

    # #2 — tendances
    if trending:
        best_tr = max((trending[e] for e in art_ents if e in trending), default=0.0)
        if best_tr > 0:
            score += w["trending"] * best_tr
            hit = next((e for e in art_ents if e in trending), "")
            reason = reason or f"📈 Tendance : {hit}"

    # #3 — préférences du profil
    if profile.get("sources") and src in profile["sources"]:
        score += w["source"]
        reason = reason or "⭐ Source favorite"
    for ent in profile.get("entities", []):
        if ent.lower() in art_ents:
            score += w["entity"]
            reason = reason or f"Entité suivie : {ent}"
    for kw in profile.get("keywords", []):
        if kw.lower() in resume:
            score += w["keyword"]
            reason = reason or f"Mot-clé : {kw}"
    for theme in profile.get("themes", []):
        if theme.lower() in resume:
            score += w["theme"]
            reason = reason or f"Thème : {theme}"

    if not reason:
        reason = "Sélection : récence & crédibilité"
    return score, reason


# ── Sélection diversifiée (round-robin thématique) ───────────────────────────

def _select_digest(scored: list, top_n: int, thematiques: list,
                   max_per_source: int = 2) -> list:
    """Round-robin par thématique + plafond par source, pour un vrai digest diversifié."""
    from collections import OrderedDict
    by_theme: "OrderedDict[str, list]" = OrderedDict()
    for item in scored:
        theme = _classify_article(item[1], thematiques) or _THEME_AUTRES
        by_theme.setdefault(theme, []).append(item)

    theme_keys = sorted(by_theme, key=lambda t: by_theme[t][0][0], reverse=True)
    idx = {t: 0 for t in theme_keys}
    selected, per_source, chosen_ids = [], {}, set()

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

    if len(selected) < top_n:
        for item in scored:
            if len(selected) >= top_n:
                break
            if id(item[1]) not in chosen_ids:
                selected.append(item)
    return selected[:top_n]


# ── Article : rendu d'un bloc ─────────────────────────────────────────────────

def _render_article_block(art: dict, score: float, chapter_md: str = "") -> list[str]:
    """Rend un article : titre H3, métadonnées riches, « pourquoi », image, corps, lien."""
    src = art.get("Sources", "Source inconnue")
    url = art.get("URL", "#")
    _dt = parse_article_date(art.get("Date de publication") or "")
    date_pub = _dt.strftime("%d/%m/%Y") if _dt else (art.get("Date de publication") or "")[:10]
    resume = art.get("Résumé", "") or ""
    resume_lines = [l.strip() for l in resume.splitlines() if l.strip()]
    ents = art.get("entities", {}) or {}

    titre_field = (art.get("Titre") or "").strip()
    titre = titre_field or (resume_lines[0] if resume_lines else f"{src} — {date_pub}")

    # Corps : chapitres (md propre réutilisé ou généré), sinon paragraphe brut
    if chapter_md:
        resume_body = _highlight_md_body(_demote_headings(chapter_md), ents)
    else:
        body_lines = resume_lines if titre_field else resume_lines[1:]
        resume_body = _highlight_entities(" ".join(body_lines), ents)

    sentiment = art.get("sentiment", "")
    sentiment_emoji = {"positif": "🟢", "négatif": "🔴", "neutre": "⚪"}.get(sentiment, "")

    # #10 — métadonnées : temps de lecture, crédibilité source, ton éditorial
    meta = [f"**{src}**", date_pub, f"score {score:.2f}"]
    # Temps de lecture : champ stocké si présent, sinon estimé depuis le résumé
    label = art.get("temps_lecture_label")
    if not label and resume.strip():
        try:
            from utils.reading_time import estimate_reading_time
            label = estimate_reading_time(resume).get("temps_lecture_label")
        except Exception:
            label = None
    if label:
        meta.append(f"⏱ {label}")
    if art.get("score_source") is not None:
        meta.append(f"🛡 crédibilité {art['score_source']}/100")
    if art.get("ton_editorial"):
        meta.append(f"🎙 {art['ton_editorial']}")

    img_url = _first_image_url(art)
    titre_alt = titre.replace("[", "(").replace("]", ")")

    block = [
        f"### {titre} {sentiment_emoji}".rstrip(),
        "",
        "*" + " · ".join(meta) + "*",
        "",
    ]
    # #12 — pourquoi cet article + #6 couverture multi-sources
    notes = []
    if art.get("_digest_reason"):
        notes.append(f"_Pourquoi ?_ {art['_digest_reason']}")
    cov = art.get("_coverage", 1)
    if cov > 1:
        srcs = ", ".join((art.get("_coverage_sources") or [])[:5])
        notes.append(f"_Couverture :_ {cov} sources ({srcs})")
    if notes:
        block += ["  ·  ".join(notes), ""]

    if img_url and _image_is_valid(img_url):
        block += [f"[![{titre_alt}]({img_url})]({url})", ""]
    if resume_body:
        block += [resume_body, ""]
    block += [f"[🔗 Lire l'article original]({url})", "", "---", ""]
    return block


# ── Chargement profils + util datetime ───────────────────────────────────────

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
    """Collecte et déduplique les articles publiés dans la fenêtre des N derniers jours."""
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)
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
                if dt is not None and dt < cutoff:
                    continue
                articles.append(art)

    try:
        articles = Deduplicator().deduplicate(articles)
    except Exception as exc:
        LOG.warning(f"[digest] Déduplication ignorée : {exc}")
    return articles


# ── Exports (#13 newsletter/Atom, #14 Obsidian) ──────────────────────────────

def _export_atom(project_root: Path, profile_id: str, profile_name: str, top: list) -> None:
    try:
        from utils.exporters.atom_feed import generate_atom_feed
        arts = [a for _s, a in top]
        xml = generate_atom_feed(arts, feed_title=f"WUDD.ai · Digest {profile_name}")
        out_dir = project_root / "rapports" / "atom"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"digest_{profile_id}.xml").write_text(xml, encoding="utf-8")
        LOG.info(f"[digest] Flux Atom écrit : rapports/atom/digest_{profile_id}.xml")
    except Exception as exc:
        LOG.warning(f"[digest] Export Atom échoué : {exc}")


def _export_obsidian(project_root: Path, out_file: Path) -> None:
    """Copie le digest dans le vault Obsidian si un dossier cible est disponible."""
    base = os.getenv("OBSIDIAN_DIR", "").strip() or ("/obsidian" if Path("/obsidian").is_dir() else "")
    if not base or not Path(base).is_dir():
        return
    try:
        dest_dir = Path(base) / "Digests"
        dest_dir.mkdir(parents=True, exist_ok=True)
        (dest_dir / out_file.name).write_text(out_file.read_text(encoding="utf-8"), encoding="utf-8")
        LOG.info(f"[digest] Exporté vers Obsidian : {dest_dir / out_file.name}")
    except OSError as exc:
        LOG.warning(f"[digest] Export Obsidian échoué : {exc}")


def _send_newsletter(profile_name: str, top: list, date_str: str) -> None:
    try:
        from utils.exporters.newsletter import generate_newsletter_html, send_newsletter
        html = generate_newsletter_html([a for _s, a in top], title=f"Digest {profile_name} — {date_str}")
        if send_newsletter(html, subject=f"🗞️ Digest WUDD.ai — {profile_name} ({date_str})"):
            LOG.info("[digest] Newsletter e-mail envoyée")
        else:
            LOG.info("[digest] Newsletter non envoyée (SMTP non configuré)")
    except Exception as exc:
        LOG.warning(f"[digest] Newsletter échouée : {exc}")


# ── Génération principale ─────────────────────────────────────────────────────

def generate_profile_digest(
    project_root: Path,
    profile: dict,
    days: int = 7,
    dry_run: bool = False,
    use_ai: bool = True,
    notify_discord: bool = True,
    allow_repeats: bool = False,
    email: bool = False,
    atom: bool = True,
    obsidian: bool = True,
) -> Path | None:
    """Génère le digest Markdown pour un profil donné (+ exports/notifications)."""
    profile_id = profile.get("id", "unknown")
    profile_name = profile.get("name", profile_id)
    top_n = profile.get("top_n", 10)
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y-%m-%d")

    articles = _collect_articles(project_root, days=days)
    if not articles:
        LOG.info(f"[digest] Profil '{profile_id}' : aucun article trouvé")
        return None

    # #5 — anti-répétition : exclure les articles déjà envoyés récemment
    state = _load_digest_state(project_root)
    already = set() if allow_repeats else _recently_sent_urls(state, profile_id, _SENT_RETENTION_DAYS)

    # Signaux + moteurs
    cred = CredibilityEngine(project_root)
    watched = _load_watched_entities(project_root)        # #1
    trending = _load_trending_entities(project_root)       # #2
    thematiques = _load_thematiques(project_root)
    try:
        from utils.scoring import get_scoring_engine       # #4
        engine = get_scoring_engine(project_root)
    except Exception:
        engine = None

    # Scoring + raison de sélection (#12)
    scored = []
    for art in articles:
        if not allow_repeats and art.get("URL", "") in already:
            continue
        s, reason = _score_article_for_profile(
            art, profile, now=now, days=days, cred=cred,
            watched=watched, trending=trending, engine=engine,
        )
        if s >= 0:
            art["_digest_reason"] = reason
            scored.append((s, art))
    scored.sort(key=lambda x: x[0], reverse=True)

    # #6 — regroupement par histoire (couverture multi-sources)
    scored = _cluster_stories(scored)
    top = _select_digest(scored, top_n, thematiques, max_per_source=2)

    # #15/#16 — chapitres (parallèle, réutilise un Résumé_md propre)
    chapters = _build_chapters(top, use_ai)

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

    discord_synthese = ""
    discord_articles: list = []
    discord_nb_themes = 0

    if not top:
        lines.append("*Aucun article pertinent trouvé pour ce profil sur cette période.*")
    else:
        # #7/#8 — synthèse citée + à retenir
        synth = _generate_synthesis(top, profile_name, days, use_ai=use_ai)
        discord_synthese = synth["synthese"]
        if synth["synthese"]:
            lines += ["## 🧭 Synthèse & mise en perspective", "",
                      _as_blockquote(synth["synthese"]), ""]
        if synth["takeaways"]:
            lines += ["### ✅ À retenir", ""]
            lines += [f"- {t}" for t in synth["takeaways"]]
            lines += [""]
        if synth["synthese"] or synth["takeaways"]:
            lines += ["---", ""]

        # Regroupement par thématique — classement IA (repli mots-clés) des
        # seuls articles retenus, robuste aux termes polysémiques.
        ai_themes = _classify_articles_ai(top, thematiques, use_ai=use_ai)
        grouped: dict[str, list] = {}
        for score, art in top:
            theme = ai_themes.get(id(art)) or _THEME_AUTRES
            grouped.setdefault(theme, []).append((score, art))
        theme_order = [name for name, _ in thematiques if name in grouped]
        if _THEME_AUTRES in grouped:
            theme_order.append(_THEME_AUTRES)

        # #11 — sommaire des thématiques avec ancres cliquables
        toc = []
        for t in theme_order:
            label = f"{_THEME_EMOJI.get(t, '🗂️')} {t}"
            anchor = _slug(f"{_THEME_EMOJI.get(t, '🗂️')} {t} ({len(grouped[t])})")
            toc.append(f"[{label} ({len(grouped[t])})](#{anchor})")
        lines += ["**Thématiques :** " + " · ".join(toc), "", "---", ""]

        # #9 — mini-synthèse par thématique
        intros = _generate_theme_intros(grouped, use_ai=use_ai)

        for theme in theme_order:
            arts = grouped[theme]
            emoji = _THEME_EMOJI.get(theme, "🗂️")
            theme_label = f"{emoji} {theme}"
            lines += [f"## {theme_label} ({len(arts)})", ""]
            intro = intros.get(theme.lower())
            if intro:
                lines += [f"*{intro}*", ""]
            for score, art in arts:
                lines += _render_article_block(art, score, chapter_md=chapters.get(art.get("URL", ""), ""))
                # Données Discord par article
                img = _first_image_url(art)
                discord_articles.append({
                    "title": _article_title(art),
                    "url": art.get("URL", ""),
                    "image": img if (img and _image_is_valid(img)) else "",
                    "theme": theme_label,
                    "snippet": (lambda s: (s[:219].rstrip() + "…") if len(s) > 220 else s)(
                        " ".join((art.get("Résumé") or "").split())),
                })
        discord_nb_themes = len(theme_order)

    lines += ["", f"*Digest généré automatiquement par WUDD.ai — profil `{profile_id}`*"]

    out_dir = project_root / "rapports" / "markdown" / "_WUDD.AI_"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"digest_{profile_id}_{date_str}.md"

    if dry_run:
        LOG.info(f"[digest] dry-run — {out_file}")
        return out_file

    out_file.write_text("\n".join(lines), encoding="utf-8")
    LOG.info(f"[digest] Rapport créé : {out_file}")
    cleanup_old_dated_reports(out_file)

    # #5 — mémoriser les URLs envoyées (avec purge de la rétention)
    if top:
        entry = state.get(profile_id, {}) if isinstance(state.get(profile_id), dict) else {}
        sent = entry.get("sent", {}) if isinstance(entry.get("sent"), dict) else {}
        for _s, art in top:
            u = art.get("URL", "")
            if u:
                sent[u] = now.isoformat()
        cutoff = now - timedelta(days=_SENT_RETENTION_DAYS)
        pruned = {}
        for u, iso in sent.items():
            try:
                if _to_utc(datetime.fromisoformat(iso)) >= cutoff:
                    pruned[u] = iso
            except (ValueError, TypeError):
                pruned[u] = iso
        state[profile_id] = {"sent": pruned, "updated_at": now.isoformat()}
        _save_digest_state(project_root, state)

    # #13 — flux Atom + newsletter e-mail ; #14 — Obsidian
    if atom and top:
        _export_atom(project_root, profile_id, profile_name, top)
    if obsidian:
        _export_obsidian(project_root, out_file)
    if email and top:
        _send_newsletter(profile_name, top, date_str)

    # Notification Discord
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

    return out_file


def main() -> None:
    parser = argparse.ArgumentParser(description="Digest personnalisé par profil WUDD.ai")
    parser.add_argument("--profile", help="ID du profil à générer (tous si absent)")
    parser.add_argument("--days", type=int, default=7, help="Fenêtre en jours (défaut: 7)")
    parser.add_argument("--dry-run", action="store_true", help="Simulation sans écriture")
    parser.add_argument("--no-ai", action="store_true",
                        help="Désactive synthèse, mini-synthèses et chapitrage IA")
    parser.add_argument("--no-discord", action="store_true", help="N'envoie pas la notif Discord")
    parser.add_argument("--allow-repeats", action="store_true",
                        help="Autorise les articles déjà envoyés les jours précédents")
    parser.add_argument("--email", action="store_true", help="Envoie la newsletter par e-mail (SMTP)")
    parser.add_argument("--no-atom", action="store_true", help="N'écrit pas le flux Atom")
    parser.add_argument("--no-obsidian", action="store_true", help="N'exporte pas vers Obsidian")
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
            allow_repeats=args.allow_repeats, email=args.email,
            atom=not args.no_atom, obsidian=not args.no_obsidian,
        )
        if out:
            print(f"Digest généré : {out}")


if __name__ == "__main__":
    main()
