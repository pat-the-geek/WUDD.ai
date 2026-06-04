#!/usr/bin/env python3
"""
cross_flux_analysis.py — Analyse croisée des flux (Priorité 7)

Détecte les entités et thèmes communs entre plusieurs flux de veille, révélant
les sujets qui transcendent les domaines surveillés. Utile pour identifier les
signaux forts et les convergences thématiques.

Sortie : data/cross_flux_report.json + rapports/markdown/_WUDD.AI_/cross_flux_YYYY-MM-DD.md

Usage :
    python3 scripts/cross_flux_analysis.py
    python3 scripts/cross_flux_analysis.py --days 7
    python3 scripts/cross_flux_analysis.py --min-flux 2 --top 20
    python3 scripts/cross_flux_analysis.py --dry-run
"""

import argparse
import json
import re
import sys
import unicodedata
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from utils.logging import print_console, default_logger
from utils.date_utils import parse_article_date
from utils.report_cleanup import cleanup_old_dated_reports
from utils.api_client import get_ai_client
from utils.exporters.webhook import send_text_discord

_CJK_RE = re.compile(r"[一-鿿㐀-䶿豈-﫿]")


def _generate_cross_flux_synthesis(cross_entities: list, counts: dict, days: int,
                                   use_ai: bool = True) -> str:
    """Génère une synthèse IA des éléments de l'analyse croisée (provider configuré).

    Retourne du Markdown (paragraphes) ou "" si IA désactivée/indisponible.
    """
    if not use_ai or (not cross_entities and not counts):
        return ""
    ent_lines = [
        f"- {e['entity_value']} ({e['entity_type']}) : {e['nb_flux']} flux, "
        f"{e['total_mentions']} mentions"
        for e in cross_entities[:15]
    ]
    ent_block = "\n".join(ent_lines) if ent_lines else "(aucune entité transversale détectée)"
    top_flux = sorted(counts.items(), key=lambda x: -x[1])[:10]
    flux_lines = [f"- {n.replace('rss:', '')} : {c} articles" for n, c in top_flux]
    flux_block = "\n".join(flux_lines) if flux_lines else "(aucun volume disponible)"
    prompt = (
        "Tu es analyste de veille informationnelle. Voici une analyse croisée des flux "
        f"de veille (fenêtre {days} jours) : des entités apparaissant dans plusieurs flux, "
        "et le volume d'articles par flux. Rédige en français une SYNTHÈSE des éléments.\n"
        "Règles STRICTES :\n"
        "- Commence DIRECTEMENT par la synthèse, sans phrase d'introduction, sans mentionner "
        "ton rôle, ni d'éventuelles données manquantes.\n"
        "- 2 à 3 paragraphes rédigés (pas de liste) ;\n"
        "- mets en évidence les convergences entre flux, les entités transversales et les "
        "tendances de fond ;\n"
        "- mets en **gras** quelques points-clés, avec parcimonie ;\n"
        "- n'invente aucun fait : appuie-toi uniquement sur les données fournies.\n\n"
        "Entités présentes dans plusieurs flux :\n" + ent_block +
        "\n\nVolume d'articles par flux :\n" + flux_block
    )
    try:
        out = (get_ai_client().ask(prompt, timeout=120, max_tokens=800) or "").strip()
    except Exception as exc:
        default_logger.warning(f"[cross-flux] Synthèse IA indisponible : {exc}")
        return ""
    low = out.lower()
    if not out or low.startswith(("erreur", "désolé")) or _CJK_RE.search(out):
        return ""
    return out


def _render_flux_chart_png(counts: dict, top_n: int = 10) -> bytes | None:
    """Rend un graphique en barres du top flux (PNG via Pillow). None si indisponible."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception:
        return None
    sorted_flux = sorted(counts.items(), key=lambda x: -x[1])[:top_n]
    if not sorted_flux:
        return None

    def _font(size: int):
        for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                  "/System/Library/Fonts/Supplemental/Arial.ttf",
                  "/Library/Fonts/Arial.ttf"):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
        try:
            return ImageFont.load_default(size)
        except Exception:
            return ImageFont.load_default()

    f_title, f_lbl, f_val = _font(18), _font(14), _font(13)
    # Palette de couleurs (une par barre, cyclique)
    palette = [
        (52, 152, 219),   # bleu
        (46, 204, 113),   # vert
        (231, 76, 60),    # rouge
        (155, 89, 182),   # violet
        (241, 196, 15),   # jaune
        (26, 188, 156),   # turquoise
        (230, 126, 34),   # orange
        (52, 73, 94),     # ardoise
        (233, 30, 99),    # rose
        (149, 165, 166),  # gris
    ]
    mx = sorted_flux[0][1] or 1
    W, pad, label_w, row_h, top_off = 760, 16, 190, 30, 48
    bar_x = pad + label_w + 8
    bar_max = W - bar_x - 70
    H = top_off + row_h * len(sorted_flux) + pad

    img = Image.new("RGB", (W, H), (255, 255, 255))
    d = ImageDraw.Draw(img)
    d.text((pad, 16), "Top flux — articles", fill=(20, 20, 20), font=f_title)
    for i, (name, c) in enumerate(sorted_flux):
        y = top_off + i * row_h
        short = name.replace("rss:", "")
        short = (short[:21] + "…") if len(short) > 22 else short
        d.text((pad, y + 5), short, fill=(45, 45, 45), font=f_lbl)
        bw = max(3, int(c / mx * bar_max))
        d.rectangle([bar_x, y + 4, bar_x + bw, y + row_h - 8], fill=palette[i % len(palette)])
        d.text((bar_x + bw + 6, y + 5), str(c), fill=(45, 45, 45), font=f_val)

    import io
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _flux_bar_chart_text(counts: dict, top_n: int = 10, width: int = 18) -> str:
    """Représente le top flux en barres Unicode (pour une notification Discord)."""
    sorted_flux = sorted(counts.items(), key=lambda x: -x[1])[:top_n]
    if not sorted_flux:
        return ""
    mx = sorted_flux[0][1] or 1
    out = []
    for name, c in sorted_flux:
        short = name.replace("rss:", "")
        short = (short[:19] + "…") if len(short) > 20 else short
        bar = "█" * max(1, round(c / mx * width))
        out.append(f"{short:<20} {bar} {c}")
    return "\n".join(out)

# ── Constantes ───────────────────────────────────────────────────────────────

_OUTPUT_JSON = _PROJECT_ROOT / "data" / "cross_flux_report.json"
_OUTPUT_DIR  = _PROJECT_ROOT / "rapports" / "markdown" / "_WUDD.AI_"

_ENTITY_TYPES_PERTINENTS = {
    "PERSON", "ORG", "GPE", "PRODUCT", "EVENT", "DISEASE", "NORP"
}

# Sous-répertoire des fichiers DÉRIVÉS (agrégats : 48-heures.json, direct.json,
# merged/…). Ils dupliquent les articles des vrais flux → exclus du rapport pour
# éviter le double comptage et un faux flux « rss:_WUDD.AI_/… ».
_DERIVED_SUBDIR = "_WUDD.AI_"


def _is_derived_path(parts) -> bool:
    """Vrai si le chemin (parts) traverse le sous-répertoire dérivé _WUDD.AI_."""
    return _DERIVED_SUBDIR in parts

# ── Parsing de date ───────────────────────────────────────────────────────────

def _parse_date(date_str: str) -> datetime | None:
    """Datetime UTC (tz-aware) ou None — corpus mixte ISO 8601 / DD/MM/YYYY / RFC 2822.

    Délègue au parseur canonique (gère l'ISO avec/sans Z et le DD/MM/YYYY) puis
    réattache UTC pour rester comparable aux datetime tz-aware du script.
    """
    dt = parse_article_date(date_str or "")
    return dt.replace(tzinfo=timezone.utc) if dt is not None else None


# ── Collecte par flux ─────────────────────────────────────────────────────────

def _file_path_to_flux_name(file_path: str) -> str:
    """Dérive le nom du flux depuis le chemin relatif stocké dans l'entity_index."""
    if not file_path:
        return ""
    parts = Path(file_path).parts
    # Ignore les agrégats dérivés (_WUDD.AI_/48-heures.json…)
    if _is_derived_path(parts):
        return ""
    # data/articles/<flux_dir>/...json
    if len(parts) >= 3 and parts[1] == "articles":
        return parts[2]
    # data/articles-from-rss/<subdir>/<file>.json
    if len(parts) == 4 and parts[1] == "articles-from-rss":
        return f"rss:{parts[2]}/{Path(file_path).stem}"
    # data/articles-from-rss/<file>.json
    if len(parts) == 3 and parts[1] == "articles-from-rss":
        return f"rss:{Path(file_path).stem}"
    return ""


def _collect_entities_from_index(
    project_root: Path,
    days: int,
) -> dict[str, dict[str, int]] | None:
    """Construit l'analyse croisée depuis l'entity_index sans scan rglob.

    Retourne None si l'index est absent ou vide (→ fallback rglob).
    """
    try:
        from utils.entity_index import get_entity_index
        eidx = get_entity_index(project_root)
        all_entries = eidx.get_all_entries()
    except Exception:
        return None

    if not all_entries:
        return None

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days) if days > 0 else None

    flux_entities: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for entity_key, refs in all_entries.items():
        if ":" not in entity_key:
            continue
        etype = entity_key.split(":", 1)[0]
        if etype not in _ENTITY_TYPES_PERTINENTS:
            continue

        for ref in refs:
            date_str = ref.get("date", "")
            if cutoff and date_str:
                try:
                    dt = datetime.strptime(date_str[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
                    if dt < cutoff:
                        continue
                except ValueError:
                    pass

            flux_name = _file_path_to_flux_name(ref.get("file", ""))
            if flux_name:
                flux_entities[flux_name][entity_key] += 1

    return {flux: dict(counts) for flux, counts in flux_entities.items()}


# ── Comptage des articles par flux ──────────────────────────────────────────

def _sanitize_for_mermaid(name: str) -> str:
    """Supprime accents et caractères spéciaux pour les labels Mermaid."""
    nfkd = unicodedata.normalize('NFKD', name)
    ascii_str = nfkd.encode('ascii', 'ignore').decode('ascii')
    clean = re.sub(r'[^a-zA-Z0-9 \-_]', '-', ascii_str)
    clean = re.sub(r'-{2,}', '-', clean).strip('-')
    return clean[:28]


def _normalize_keyword_stem(kw: str) -> str:
    """Normalise un mot-clé vers le stem du fichier articles-from-rss correspondant."""
    return kw.strip().lower().replace(' ', '-')


def _keyword_sort_key(keyword: str) -> str:
    """Clé de tri alphabétique : sans accents, en minuscules, sans crochets de tête."""
    ascii_form = unicodedata.normalize("NFKD", keyword).encode("ascii", "ignore").decode()
    return ascii_form.lower().lstrip("[](){} ").strip()


def _md_terms_with_counts(terms: list[str], trigger_counts: dict[str, int]) -> str:
    """Formate une liste de termes, chacun suivi de son nombre de détections.

    Préfixe la cellule du nombre de termes ; trie par détections décroissantes
    puis alphabétiquement. ``trigger_counts`` est indexé par terme en minuscules.
    """
    items: list[tuple[str, int]] = []
    for t in (terms or []):
        t = str(t).strip()
        if not t:
            continue
        items.append((t, trigger_counts.get(t.lower(), 0)))
    if not items:
        return "—"
    items.sort(key=lambda it: (-it[1], it[0].lower()))
    parts = []
    for term, count in items:
        esc = term.replace("|", "\\|")
        parts.append(f"{esc} ({count})")
    return f"**{len(items)}** — " + ", ".join(parts)


def _build_keyword_table_block(
    project_root: Path,
    active_stems: set[str] | None = None,
    counts: dict[str, int] | None = None,
    triggers: dict[str, dict[str, int]] | None = None,
) -> str:
    """Génère un tableau Markdown des mots-clés de veille, trié alphabétiquement.

    Colonnes : mot-clé, nombre d'articles détectés (sur la période), variantes
    « OU » et termes « ET », chaque terme suivi de son nombre de détections.

    Args:
        project_root  : racine du projet
        active_stems  : si fourni, ne conserve que les mots-clés dont le stem
                        normalisé est dans cet ensemble (mots-clés avec articles).
        counts        : comptage d'articles par flux (clés ``rss:<stem>``) sur la
                        période, pour la colonne « Articles détectés ».
        triggers      : détections par terme et par flux (clés ``rss:<stem>`` →
                        { terme_minuscule : count }), pour annoter les mots OU/ET.
    """
    kw_file = project_root / "config" / "keyword-to-search.json"
    if not kw_file.exists():
        return ""
    try:
        keywords = json.loads(kw_file.read_text(encoding="utf-8"))
    except Exception:
        return ""
    if not keywords:
        return ""

    if active_stems is not None:
        keywords = [
            entry for entry in keywords
            if _normalize_keyword_stem(entry.get("keyword", "")) in active_stems
        ]

    if not keywords:
        return ""

    keywords = sorted(keywords, key=lambda e: _keyword_sort_key(e.get("keyword", "")))

    counts = counts or {}
    triggers = triggers or {}
    rows = [
        "| Mot-clé | Articles détectés | Variantes OU (détections) | Termes requis ET (détections) |",
        "|---|---:|---|---|",
    ]
    for entry in keywords:
        kw = str(entry.get("keyword", "")).strip().replace("|", "\\|")
        stem = _normalize_keyword_stem(entry.get("keyword", ""))
        n_articles = counts.get(f"rss:{stem}", 0)
        tc = triggers.get(f"rss:{stem}", {})
        rows.append(
            f"| **{kw}** | {n_articles} "
            f"| {_md_terms_with_counts(entry.get('or'), tc)} "
            f"| {_md_terms_with_counts(entry.get('and'), tc)} |"
        )

    return "\n".join(rows)


def _count_articles_in_file(json_file: Path, cutoff: datetime | None) -> int:
    """Compte les articles valides dans une fenêtre temporelle."""
    try:
        data = json.loads(json_file.read_text(encoding="utf-8", errors="replace"))
        if not isinstance(data, list):
            return 0
    except (json.JSONDecodeError, OSError):
        return 0
    if cutoff is None:
        return len(data)
    count = 0
    for article in data:
        dt = _parse_date(article.get("Date de publication", ""))
        if dt is not None and dt >= cutoff:
            count += 1
    return count


def collect_article_counts_by_flux(
    project_root: Path,
    days: int = 30,
) -> dict[str, int]:
    """Compte le nombre d'articles par flux dans la fenêtre temporelle."""
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days) if days > 0 else None
    counts: dict[str, int] = defaultdict(int)

    articles_dir = project_root / "data" / "articles"
    if articles_dir.exists():
        for flux_dir in articles_dir.iterdir():
            if not flux_dir.is_dir() or flux_dir.name == _DERIVED_SUBDIR:
                continue
            flux_name = flux_dir.name
            for json_file in flux_dir.rglob("*.json"):
                if "cache" in json_file.relative_to(articles_dir).parts:
                    continue
                counts[flux_name] += _count_articles_in_file(json_file, cutoff)

    rss_dir = project_root / "data" / "articles-from-rss"
    if rss_dir.exists():
        for json_file in rss_dir.rglob("*.json"):
            rel_parts = json_file.relative_to(rss_dir).parts
            if "cache" in rel_parts or _is_derived_path(rel_parts):
                continue
            flux_name = (
                f"rss:{json_file.parent.name}/{json_file.stem}"
                if json_file.parent != rss_dir
                else f"rss:{json_file.stem}"
            )
            counts[flux_name] += _count_articles_in_file(json_file, cutoff)

    return dict(counts)


def collect_trigger_terms_by_flux(
    project_root: Path,
    days: int = 30,
) -> dict[str, dict[str, int]]:
    """Compte, par flux RSS, le nombre de détections de chaque terme déclencheur.

    Lit le champ ``terme_declencheur`` des articles (clé normalisée en minuscules)
    dans la fenêtre temporelle. Sert à annoter les mots OU/ET du tableau.

    Returns:
        { "rss:<stem>" : { "<terme en minuscules>" : nombre de détections } }
    """
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days) if days > 0 else None
    result: dict[str, dict[str, int]] = {}

    rss_dir = project_root / "data" / "articles-from-rss"
    if not rss_dir.exists():
        return result

    for json_file in rss_dir.rglob("*.json"):
        rel_parts = json_file.relative_to(rss_dir).parts
        if "cache" in rel_parts or _is_derived_path(rel_parts):
            continue
        try:
            data = json.loads(json_file.read_text(encoding="utf-8", errors="replace"))
            if not isinstance(data, list):
                continue
        except (json.JSONDecodeError, OSError):
            continue
        flux_name = (
            f"rss:{json_file.parent.name}/{json_file.stem}"
            if json_file.parent != rss_dir
            else f"rss:{json_file.stem}"
        )
        bucket = result.setdefault(flux_name, {})
        for article in data:
            if not isinstance(article, dict):
                continue
            if cutoff is not None:
                dt = _parse_date(article.get("Date de publication", ""))
                if dt is None or dt < cutoff:
                    continue
            term = article.get("terme_declencheur")
            if isinstance(term, str) and term.strip():
                key = term.strip().lower()
                bucket[key] = bucket.get(key, 0) + 1

    return result


def collect_entities_by_flux(
    project_root: Path,
    days: int = 30,
) -> dict[str, dict[str, int]]:
    """Collecte les entités par flux (nom du répertoire parent).

    Essaie d'abord l'entity_index (lecture unique), puis fallback scan rglob.

    Returns:
        { "nom_flux" : { "TYPE:valeur" : count } }
    """
    result = _collect_entities_from_index(project_root, days)
    # Un dict vide signifie un index absent/dégradé (ou dominé par les dérivés
    # _WUDD.AI_ exclus) : on bascule alors sur le scan rglob complet.
    if result:
        return result

    # Fallback : scan rglob complet
    now    = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days) if days > 0 else None

    # flux_entities[flux_name][entity_key] = count
    flux_entities: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    articles_dir = project_root / "data" / "articles"
    if articles_dir.exists():
        for flux_dir in articles_dir.iterdir():
            if not flux_dir.is_dir() or flux_dir.name == _DERIVED_SUBDIR:
                continue
            flux_name = flux_dir.name
            for json_file in flux_dir.rglob("*.json"):
                if "cache" in json_file.relative_to(articles_dir).parts:
                    continue
                _collect_from_file(json_file, flux_name, cutoff, flux_entities)

    # articles-from-rss : chaque fichier JSON est un "flux" nommé par son stem
    rss_dir = project_root / "data" / "articles-from-rss"
    if rss_dir.exists():
        for json_file in rss_dir.rglob("*.json"):
            rel_parts = json_file.relative_to(rss_dir).parts
            if "cache" in rel_parts or _is_derived_path(rel_parts):
                continue
            flux_name = f"rss:{json_file.parent.name}/{json_file.stem}" if json_file.parent != rss_dir else f"rss:{json_file.stem}"
            _collect_from_file(json_file, flux_name, cutoff, flux_entities)

    # Convertir defaultdicts en dicts normaux
    return {flux: dict(counts) for flux, counts in flux_entities.items()}


def _collect_from_file(
    json_file: Path,
    flux_name: str,
    cutoff: datetime | None,
    flux_entities: dict,
) -> None:
    """Remplit flux_entities depuis un fichier JSON d'articles."""
    try:
        data = json.loads(json_file.read_text(encoding="utf-8", errors="replace"))
        if not isinstance(data, list):
            return
    except (json.JSONDecodeError, OSError):
        return

    for article in data:
        if cutoff:
            dt = _parse_date(article.get("Date de publication", ""))
            if dt is None or dt < cutoff:
                continue
        entities = article.get("entities")
        if not isinstance(entities, dict):
            continue
        for etype, values in entities.items():
            if etype not in _ENTITY_TYPES_PERTINENTS:
                continue
            if not isinstance(values, list):
                continue
            for v in values:
                if isinstance(v, str) and v.strip():
                    flux_entities[flux_name][f"{etype}:{v.strip()}"] += 1


# ── Analyse croisée ───────────────────────────────────────────────────────────

def compute_cross_flux(
    flux_entities: dict[str, dict[str, int]],
    min_flux: int = 2,
    top_n: int = 30,
) -> list[dict]:
    """Identifie les entités présentes dans au moins min_flux flux distincts.

    Args:
        flux_entities : { flux_name : { entity_key : count } }
        min_flux      : nombre minimal de flux où l'entité doit apparaître
        top_n         : nombre d'entités à retourner

    Returns:
        Liste de dicts triée par nombre de flux décroissant, puis total.
    """
    # entity_key → { flux_name : count }
    entity_flux_map: dict[str, dict[str, int]] = defaultdict(dict)

    for flux_name, entities in flux_entities.items():
        for entity_key, count in entities.items():
            entity_flux_map[entity_key][flux_name] = count

    results = []
    for entity_key, flux_counts in entity_flux_map.items():
        nb_flux = len(flux_counts)
        if nb_flux < min_flux:
            continue

        total = sum(flux_counts.values())
        etype, value = entity_key.split(":", 1) if ":" in entity_key else ("?", entity_key)

        results.append({
            "entity_key":  entity_key,
            "entity_type": etype,
            "entity_value": value,
            "nb_flux":     nb_flux,
            "total_mentions": total,
            "flux_details": [
                {"flux": f, "mentions": c}
                for f, c in sorted(flux_counts.items(), key=lambda x: -x[1])
            ],
        })

    results.sort(key=lambda x: (-x["nb_flux"], -x["total_mentions"]))
    return results[:top_n]


# ── Génération du rapport Markdown ───────────────────────────────────────────

def _assign_flux_letters(flux_names_sorted: list[str]) -> dict[str, str]:
    """Assigne une lettre A-Z (puis AA, AB...) à chaque flux trié."""
    import string
    letters = list(string.ascii_uppercase)
    mapping: dict[str, str] = {}
    for i, name in enumerate(flux_names_sorted):
        if i < 26:
            mapping[name] = letters[i]
        else:
            mapping[name] = letters[(i // 26) - 1] + letters[i % 26]
    return mapping


def _build_flux_chart_block(
    flux_article_counts: dict[str, int],
    flux_letter_map: dict[str, str] | None = None,
    top_n: int = 15,
) -> str:
    """Génère un bloc ```flux-chart``` (JSON) rendu par FluxBarChart dans le viewer.
    Inclut la lettre assignée à chaque flux (même ordre que la liste alphabétique).
    """
    if not flux_article_counts:
        return ""
    sorted_flux = sorted(flux_article_counts.items(), key=lambda x: -x[1])[:top_n]
    letter_map = flux_letter_map or {}
    items = [
        {"name": name, "count": count, "letter": letter_map.get(name, "")}
        for name, count in sorted_flux
    ]
    return "```flux-chart\n" + json.dumps(items, ensure_ascii=False) + "\n```"


# ── Enrichissement & analyses avancées ───────────────────────────────────────

_TYPE_EMOJI = {
    "PERSON": "👤", "ORG": "🏢", "GPE": "🌍", "LOC": "📍", "PRODUCT": "📦",
    "EVENT": "📅", "DISEASE": "🦠", "NORP": "🏳️", "LAW": "⚖️", "WORK_OF_ART": "🎨",
}


def _slug(text: str) -> str:
    """Ancre Markdown façon GitHub."""
    s = "".join(c for c in unicodedata.normalize("NFKD", text.lower())
                if not unicodedata.combining(c))
    s = re.sub(r"[^a-z0-9\s-]", "", s)
    return re.sub(r"-{2,}", "-", re.sub(r"\s+", "-", s.strip()))


def _enrich_cross_entities(project_root: Path, cross_entities: list, days: int) -> None:
    """Enrichit chaque entité cross-flux (in place) : articles, sentiments, source
    représentative, crédibilité moyenne, co-occurrences. Via l'entity_index (sain)."""
    try:
        from utils.entity_index import get_entity_index
        from utils.source_credibility import CredibilityEngine
        eidx = get_entity_index(project_root)
        cred = CredibilityEngine(project_root)
    except Exception as exc:
        default_logger.warning(f"[cross-flux] Enrichissement indisponible : {exc}")
        return
    cutoff_iso = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d") if days > 0 else ""
    top_keys = {e["entity_key"] for e in cross_entities}
    for e in cross_entities:
        try:
            arts = eidx.load_articles(e["entity_type"], e["entity_value"],
                                      max_articles=60, cutoff_date=cutoff_iso)
        except Exception:
            arts = []
        sent = {"positif": 0, "neutre": 0, "négatif": 0}
        creds, rep, cooc = [], None, defaultdict(int)
        pos_src, neg_src = set(), set()
        for a in arts:
            s = a.get("sentiment", "")
            if s in sent:
                sent[s] += 1
                src = a.get("Sources", "")
                if s == "positif" and src:
                    pos_src.add(src)
                elif s == "négatif" and src:
                    neg_src.add(src)
            cv = a.get("score_source")
            if cv is None:
                try:
                    cv = cred.get_score(a.get("Sources", ""))
                except Exception:
                    cv = None
            if cv is not None:
                try:
                    creds.append(float(cv))
                except (TypeError, ValueError):
                    pass
            if rep is None and (a.get("URL") or "").strip():
                rep = {"url": a.get("URL", ""), "title": (a.get("Titre") or "").strip(),
                       "source": a.get("Sources", "")}
            # co-occurrences avec les autres entités cross-flux
            for etype, vals in (a.get("entities") or {}).items():
                if isinstance(vals, list):
                    for v in vals:
                        k = f"{etype}:{v}".strip()
                        if k in top_keys and k != e["entity_key"]:
                            cooc[k] += 1
        e["_sentiments"] = sent
        e["_credibility"] = round(sum(creds) / len(creds), 1) if creds else None
        e["_representative"] = rep
        e["_cooc"] = dict(cooc)
        e["_pos_src"] = sorted(pos_src)[:4]
        e["_neg_src"] = sorted(neg_src)[:4]
        # Articles légers (pour la détection de contradictions opt-in)
        e["_articles"] = [{"Résumé": a.get("Résumé", ""), "Sources": a.get("Sources", "")}
                          for a in arts[:5]]


def _load_entity_timeline(project_root: Path) -> dict:
    f = project_root / "data" / "entity_timeline.json"
    try:
        return json.loads(f.read_text(encoding="utf-8")).get("timeline", {})
    except (OSError, json.JSONDecodeError):
        return {}


def _entity_trend(timeline: dict, entity_key: str) -> tuple[str, float]:
    """(flèche, ratio) de tendance à partir de la timeline (7j récents vs 7j précédents)."""
    series = timeline.get(entity_key)
    if not isinstance(series, dict) or len(series) < 8:
        return "", 1.0
    counts = [series[d] for d in sorted(series)]
    recent = sum(counts[-7:])
    prev = sum(counts[-14:-7]) if len(counts) >= 14 else 0
    if prev <= 0:
        return ("📈", float("inf")) if recent > 0 else ("", 1.0)
    ratio = recent / prev
    if ratio >= 1.5:
        return "📈", ratio
    if ratio <= 0.67:
        return "📉", ratio
    return "", ratio


def _composite_importance(e: dict, trend_ratio: float) -> float:
    """Score d'importance cross-flux : diversité flux × mentions × crédibilité × tendance."""
    import math
    cred = (e.get("_credibility") or 50.0) / 100.0
    trend = 1.0 + min(0.5, max(0.0, (trend_ratio - 1.0))) if trend_ratio != float("inf") else 1.5
    return e["nb_flux"] * (1 + math.log1p(e["total_mentions"])) * (0.5 + cred) * trend


def _flux_similarity(flux_entities: dict, top_pairs: int = 5) -> list[tuple]:
    """Paires de flux partageant le plus d'entités (Jaccard)."""
    sets = {f: set(ents) for f, ents in flux_entities.items() if ents}
    names = list(sets)
    pairs = []
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = sets[names[i]], sets[names[j]]
            inter = len(a & b)
            if inter < 2:
                continue
            jac = inter / len(a | b)
            pairs.append((names[i], names[j], inter, round(jac, 2)))
    pairs.sort(key=lambda x: (-x[3], -x[2]))
    return pairs[:top_pairs]


def _cooccurrence_mermaid(cross_entities: list, top_n: int = 12, min_w: int = 2) -> str:
    """Bloc Mermaid du graphe de co-occurrence entre entités cross-flux."""
    sel = cross_entities[:top_n]
    ids = {e["entity_key"]: f"E{i}" for i, e in enumerate(sel)}
    edges, seen = [], set()
    for e in sel:
        for k, w in (e.get("_cooc") or {}).items():
            if k in ids and w >= min_w:
                pair = tuple(sorted((e["entity_key"], k)))
                if pair in seen:
                    continue
                seen.add(pair)
                edges.append(f'    {ids[pair[0]]} --- {ids[pair[1]]}')
    if not edges:
        return ""
    lines = ["```mermaid", "graph LR"]
    for e in sel:
        if any(ids[e["entity_key"]] in edge for edge in edges):
            label = e["entity_value"].replace('"', "'")[:24]
            lines.append(f'    {ids[e["entity_key"]]}["{label}"]')
    lines += edges + ["```"]
    return "\n".join(lines)


def _render_cooc_png(cross_entities: list, top_n: int = 12, min_w: int = 2) -> bytes | None:
    """Rend le graphe de co-occurrence en PNG (layout circulaire, via Pillow)."""
    try:
        from PIL import Image, ImageDraw, ImageFont
        import io
        import math
    except Exception:
        return None
    sel = cross_entities[:top_n]
    ids = {e["entity_key"]: i for i, e in enumerate(sel)}
    edges, seen = [], set()
    for e in sel:
        for k, w in (e.get("_cooc") or {}).items():
            if k in ids and w >= min_w:
                pair = tuple(sorted((e["entity_key"], k)))
                if pair in seen:
                    continue
                seen.add(pair)
                edges.append((ids[pair[0]], ids[pair[1]], w))
    if not edges:
        return None
    used = sorted({a for a, _, _ in edges} | {b for _, b, _ in edges})

    def _font(size):
        for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                  "/System/Library/Fonts/Supplemental/Arial.ttf"):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
        try:
            return ImageFont.load_default(size)
        except Exception:
            return ImageFont.load_default()

    W = H = 860
    cx = cy = H // 2 + 10
    R = 290
    f, ft = _font(15), _font(20)
    pos = {}
    n = len(used)
    for idx, node in enumerate(used):
        ang = 2 * math.pi * idx / n - math.pi / 2
        pos[node] = (cx + R * math.cos(ang), cy + R * math.sin(ang))

    img = Image.new("RGB", (W, H), (255, 255, 255))
    d = ImageDraw.Draw(img)
    d.text((20, 16), "Graphe de co-occurrence des entités", fill=(20, 20, 20), font=ft)
    mxw = max(w for _, _, w in edges) or 1
    for a, b, w in edges:
        xa, ya = pos[a]
        xb, yb = pos[b]
        d.line([xa, ya, xb, yb], fill=(170, 185, 200), width=max(1, int(1 + 4 * w / mxw)))
    palette = [(52, 152, 219), (46, 204, 113), (231, 76, 60), (155, 89, 182),
               (241, 196, 15), (26, 188, 156), (230, 126, 34), (52, 73, 94),
               (233, 30, 99), (149, 165, 166), (26, 102, 204), (192, 57, 43)]
    for j, node in enumerate(used):
        x, y = pos[node]
        d.ellipse([x - 8, y - 8, x + 8, y + 8], fill=palette[j % len(palette)])
        label = sel[node]["entity_value"][:20]
        try:
            tw = d.textlength(label, font=f)
        except Exception:
            tw = len(label) * 7
        tx = (x - tw - 12) if x < cx else (x + 12)
        d.text((tx, y - 8), label, fill=(35, 35, 35), font=f)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _entity_minianalyses(cross_entities: list, use_ai: bool, top_n: int = 8) -> dict:
    """1 phrase IA par entité phare (un seul appel, JSON {entity_value: phrase})."""
    if not use_ai or not cross_entities:
        return {}
    items = [f"- {e['entity_value']} ({e['entity_type']}, {e['nb_flux']} flux)"
             for e in cross_entities[:top_n]]
    prompt = (
        "Pour chaque entité transversale ci-dessous (présente dans plusieurs flux de "
        "veille), rédige UNE phrase en français expliquant pourquoi elle est au cœur de "
        "l'actualité. Réponds UNIQUEMENT par un objet JSON {\"<entité>\": \"<phrase>\"}. "
        "N'invente aucun fait.\n\n" + "\n".join(items)
    )
    try:
        raw = (get_ai_client().ask(prompt, timeout=90, max_tokens=700) or "").strip()
    except Exception as exc:
        default_logger.warning(f"[cross-flux] Mini-analyses indisponibles : {exc}")
        return {}
    if _CJK_RE.search(raw):
        return {}
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    try:
        data = json.loads(m.group(0)) if m else json.loads(raw)
    except Exception:
        return {}
    return {str(k).strip().lower(): str(v).strip() for k, v in data.items() if str(v).strip()}


# ── Émergence / historique (#3, #18) ──────────────────────────────────────────

def _cross_history_path(project_root: Path) -> Path:
    return project_root / "data" / "cross_flux_history.json"


def _mark_emerging(project_root: Path, cross_entities: list, date_str: str) -> None:
    """Marque les entités cross-flux nouvellement apparues (in place : e['_new'])
    et met à jour l'historique data/cross_flux_history.json."""
    f = _cross_history_path(project_root)
    try:
        hist = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    except (OSError, json.JSONDecodeError):
        hist = {}
    seen = hist.get("seen", {}) if isinstance(hist, dict) else {}
    for e in cross_entities:
        e["_new"] = e["entity_key"] not in seen
        seen.setdefault(e["entity_key"], date_str)
    # purge des entités vues il y a > 90 jours
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y-%m-%d")
        seen = {k: v for k, v in seen.items() if v >= cutoff}
    except Exception:
        pass
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps({"seen": seen, "updated_at": date_str},
                                  ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(f)
    except OSError as exc:
        default_logger.warning(f"[cross-flux] Historique non sauvegardé : {exc}")


# ── Contradictions (#5, opt-in) ───────────────────────────────────────────────

def _detect_contradictions(cross_entities: list, enabled: bool, max_entities: int = 3) -> list:
    """Détecte des contradictions entre sources sur les entités phares (opt-in, coûteux)."""
    if not enabled:
        return []
    try:
        from utils.claim_extractor import extract_claims
        from utils.contradiction_engine import compare_claims_deterministic
    except Exception:
        return []
    found = []
    for e in cross_entities[:max_entities]:
        arts = [a for a in (e.get("_articles") or [])][:3]
        claim_sets = []
        for a in arts:
            try:
                claim_sets.append((a, extract_claims(a.get("résumé", a.get("Résumé", "")), a.get("Sources", ""))))
            except Exception:
                continue
        for i in range(len(claim_sets)):
            for j in range(i + 1, len(claim_sets)):
                for ca in claim_sets[i][1]:
                    for cb in claim_sets[j][1]:
                        res = compare_claims_deterministic(ca, cb)
                        if res:
                            found.append({"entity": e["entity_value"],
                                          "desc": res.get("description", ""),
                                          "src_a": claim_sets[i][0].get("Sources", ""),
                                          "src_b": claim_sets[j][0].get("Sources", "")})
    return found[:10]


def _link_entities_in_text(text: str, cross_entities: list) -> str:
    """Lie la 1re occurrence de chaque entité phare à son article représentatif (#8)."""
    if not text:
        return text
    pairs = [(e["entity_value"], (e.get("_representative") or {}).get("url", ""))
             for e in cross_entities if (e.get("_representative") or {}).get("url")]
    pairs.sort(key=lambda p: len(p[0]), reverse=True)
    for val, url in pairs:
        pat = re.compile(r"(?<!\[)(?<!\w)(" + re.escape(val) + r")(?!\w)(?!\]\()")
        text = pat.sub(lambda m: f"[{m.group(1)}]({url})", text, count=1)
    return text


def _top_entities_discord(cross_entities: list, n: int = 8) -> str:
    """Liste compacte des top entités cross-flux pour la notification Discord (#15)."""
    out = []
    for e in cross_entities[:n]:
        emoji = _TYPE_EMOJI.get(e["entity_type"], "•")
        trend = f" {e['_trend']}" if e.get("_trend") else ""
        new = " 🆕" if e.get("_new") else ""
        out.append(f"{emoji} **{e['entity_value']}** ({e['nb_flux']} flux){trend}{new}")
    return "\n".join(out)


def _export_atom_crossflux(project_root: Path, cross_entities: list) -> None:
    """Flux Atom des articles représentatifs des entités cross-flux (#16)."""
    try:
        from utils.exporters.atom_feed import generate_atom_feed
        arts = []
        for e in cross_entities[:30]:
            rep = e.get("_representative") or {}
            if rep.get("url"):
                arts.append({"Titre": rep.get("title") or e["entity_value"],
                             "URL": rep["url"], "Sources": rep.get("source", ""),
                             "Résumé": f"Entité transversale ({e['nb_flux']} flux, "
                                       f"{e['total_mentions']} mentions)."})
        if not arts:
            return
        xml = generate_atom_feed(arts, feed_title="WUDD.ai · Analyse croisée des flux")
        out_dir = project_root / "rapports" / "atom"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "cross_flux.xml").write_text(xml, encoding="utf-8")
        default_logger.info("[cross-flux] Flux Atom écrit : rapports/atom/cross_flux.xml")
    except Exception as exc:
        default_logger.warning(f"[cross-flux] Export Atom échoué : {exc}")


def _export_obsidian_crossflux(md_path: Path) -> None:
    """Copie le rapport cross-flux dans le vault Obsidian si disponible (#16)."""
    import os
    base = os.getenv("OBSIDIAN_DIR", "").strip() or ("/obsidian" if Path("/obsidian").is_dir() else "")
    if not base or not Path(base).is_dir():
        return
    try:
        dest = Path(base) / "Veille"
        dest.mkdir(parents=True, exist_ok=True)
        (dest / md_path.name).write_text(md_path.read_text(encoding="utf-8"), encoding="utf-8")
        default_logger.info(f"[cross-flux] Exporté vers Obsidian : {dest / md_path.name}")
    except OSError as exc:
        default_logger.warning(f"[cross-flux] Export Obsidian échoué : {exc}")


def build_cross_flux_markdown(
    date_str: str,
    days: int,
    flux_names: list[str],
    cross_entities: list[dict],
    flux_article_counts: dict[str, int] | None = None,
    project_root: Path | None = None,
    synthesis: str = "",
    flux_entities: dict | None = None,
    timeline: dict | None = None,
    minianalyses: dict | None = None,
    contradictions: list | None = None,
) -> str:
    """Génère le rapport Markdown de l'analyse croisée."""
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    counts = flux_article_counts or {}

    lines = [
        "---",
        f"title: \"Analyse croisée des flux — {date_str}\"",
        f"date: \"{date_str}\"",
        f"window_days: {days}",
        "tags: [cross-flux, entités, veille]",
        "---",
        "",
        f"# 🔀 Analyse croisée des flux — {date_str}",
        "",
        f"> Généré le {now_str} | Fenêtre : {days} jours",
        f"> Flux analysés : {len(flux_names)}",
        "",
        "## Flux inclus dans l'analyse",
        "",
    ]

    # N'inclure que les flux avec au moins 1 article
    sorted_flux_names = sorted(f for f in flux_names if counts.get(f, 0) > 0)
    flux_letter_map = _assign_flux_letters(sorted_flux_names)

    # Graphique top flux (lettres issues de la liste alphabétique)
    if counts:
        flux_chart = _build_flux_chart_block(counts, flux_letter_map, top_n=15)
        if flux_chart:
            lines.append(flux_chart)
            lines.append("")

    # Liste compacte : lettre — flux séparés par des virgules avec nombre d'articles
    flux_items = []
    for f in sorted_flux_names:
        nb = counts.get(f, 0)
        letter = flux_letter_map[f]
        flux_items.append(f"**{letter}** `{f}` ({nb} article(s))")
    lines.append(", ".join(flux_items))
    lines.append("")

    # Synthèse des éléments (IA) — en encadré, juste après les flux
    if synthesis.strip():
        quoted = "\n".join(("> " + l) if l.strip() else ">" for l in synthesis.strip().splitlines())
        lines += ["## 🧭 Synthèse des éléments", "", quoted, "", "---", ""]

    if not cross_entities:
        lines += [
            "## Résultat",
            "",
            "*Aucune entité commune détectée sur la période.*",
        ]
        return "\n".join(lines)

    timeline = timeline or {}
    minianalyses = minianalyses or {}

    def _ton_cell(e: dict) -> str:
        s = e.get("_sentiments") or {}
        pos, neg, neu = s.get("positif", 0), s.get("négatif", 0), s.get("neutre", 0)
        tot = pos + neg + neu
        if tot == 0:
            return "—"
        if pos and neg and min(pos, neg) / tot >= 0.25:
            return "⚖️ divergent"
        if pos >= neg and pos >= neu:
            return "🟢 positif"
        if neg >= pos and neg >= neu:
            return "🔴 négatif"
        return "⚪ neutre"

    def _ent_link(e: dict) -> str:
        rep = e.get("_representative") or {}
        val = e["entity_value"]
        return f"[**{val}**]({rep['url']})" if rep.get("url") else f"**{val}**"

    # Tendance + importance composite (#2, #6, #7), puis tri par importance
    for e in cross_entities:
        arrow, ratio = _entity_trend(timeline, e["entity_key"])
        e["_trend"] = arrow
        e["_importance"] = _composite_importance(e, ratio)
    cross_entities = sorted(cross_entities, key=lambda e: -e["_importance"])

    # #14 — sommaire
    lines += [
        "## 🧭 Sommaire",
        "",
        "- [Entités transversales](#entites-presentes-dans-plusieurs-flux)",
        "- [Entités à la une](#entites-a-la-une)",
        "- [Co-occurrences](#graphe-de-co-occurrence)",
        "- [Matrice entité × flux](#matrice-entite--flux)",
        "- [Flux proches](#flux-proches)",
        "",
        "---",
        "",
    ]

    lines += [
        "## Entités présentes dans plusieurs flux",
        "",
        f"*{len(cross_entities)} entité(s) détectée(s) dans ≥ 2 flux — triées par importance*",
        "",
        "| Entité | Type | Flux | Mentions | Tendance | Ton | Crédib. | Flux principaux |",
        "|--------|------|------|----------|----------|-----|---------|-----------------|",
    ]
    for e in cross_entities[:20]:
        flux_str = " / ".join(f"{fd['flux']} ({fd['mentions']})" for fd in e["flux_details"][:3])
        emoji = _TYPE_EMOJI.get(e["entity_type"], "")
        new_badge = " 🆕" if e.get("_new") else ""
        cred = f"{e['_credibility']:.0f}" if e.get("_credibility") is not None else "—"
        lines.append(
            f"| {_ent_link(e)}{new_badge} | {emoji} {e['entity_type']} | {e['nb_flux']} "
            f"| {e['total_mentions']} | {e.get('_trend') or '—'} | {_ton_cell(e)} | {cred} | {flux_str} |"
        )
    lines.append("")

    # #9 — signaux faibles : entités émergentes ou en forte hausse, peu mentionnées
    weak = [e for e in cross_entities
            if (e.get("_new") or e.get("_trend") == "📈") and e["total_mentions"] <= 8]
    if weak:
        lines += ["### 📡 Signaux faibles", ""]
        for e in weak[:8]:
            tag = "🆕 nouvelle" if e.get("_new") else "📈 en hausse"
            lines.append(f"- {_ent_link(e)} ({e['entity_type']}) — {tag}, {e['nb_flux']} flux")
        lines.append("")

    # #1 — graphe de co-occurrence
    cooc_block = _cooccurrence_mermaid(cross_entities, top_n=12)
    if cooc_block:
        lines += ["## Graphe de co-occurrence", "",
                  "*Entités transversales apparaissant ensemble dans les mêmes articles.*",
                  "", cooc_block, ""]

    # Entités à la une (détail + mini-analyse IA + ton + sources divergentes)
    lines += ["## Entités à la une", ""]
    for e in cross_entities[:5]:
        emoji = _TYPE_EMOJI.get(e["entity_type"], "")
        lines.append(f"### {emoji} {e['entity_value']} ({e['entity_type']}){' 🆕' if e.get('_new') else ''}")
        mini = minianalyses.get(e["entity_value"].lower())
        if mini:
            lines.append(f"*{mini}*\n")
        cred = f" · crédibilité {e['_credibility']:.0f}/100" if e.get("_credibility") is not None else ""
        lines.append(f"Présente dans **{e['nb_flux']} flux** · {e['total_mentions']} mentions "
                     f"{e.get('_trend') or ''}{cred}\n")
        # divergence de ton (#4)
        if e.get("_pos_src") and e.get("_neg_src"):
            lines.append(f"⚖️ **Traitement divergent** — 🟢 {', '.join(e['_pos_src'])} · "
                         f"🔴 {', '.join(e['_neg_src'])}\n")
        for fd in e["flux_details"][:6]:
            lines.append(f"- **{fd['flux']}** : {fd['mentions']} mention(s)")
        rep = e.get("_representative") or {}
        if rep.get("url"):
            lines.append(f"\n[🔗 Article représentatif]({rep['url']})")
        lines.append("")

    # #12 — matrice entité × flux (top entités × top flux)
    matrix_flux = [f for f, _ in sorted(counts.items(), key=lambda x: -x[1])[:6]]
    if matrix_flux:
        lines += ["## Matrice entité × flux", "",
                  "| Entité | " + " | ".join(f.replace("rss:", "") for f in matrix_flux) + " |",
                  "|--------|" + "|".join(["---"] * len(matrix_flux)) + "|"]
        for e in cross_entities[:10]:
            per = {fd["flux"]: fd["mentions"] for fd in e["flux_details"]}
            row = " | ".join(str(per.get(f, "·")) for f in matrix_flux)
            lines.append(f"| **{e['entity_value']}** | {row} |")
        lines.append("")

    # #13 — flux proches (partage d'entités)
    if flux_entities:
        sim = _flux_similarity(flux_entities)
        if sim:
            lines += ["## Flux proches", "",
                      "*Flux partageant le plus d'entités (entités communes · similarité).*", ""]
            for a, b, inter, jac in sim:
                lines.append(f"- `{a.replace('rss:', '')}` ↔ `{b.replace('rss:', '')}` — "
                             f"{inter} entités communes ({jac})")
            lines.append("")

    # #5 — contradictions entre sources (opt-in)
    if contradictions:
        lines += ["## ⚠️ Contradictions détectées", ""]
        for c in contradictions:
            lines.append(f"- **{c['entity']}** — {c['desc']} ({c['src_a']} vs {c['src_b']})")
        lines.append("")

    # Mindmap des mots-clés de veille (avant le pied de page)
    # N'inclure que les mots-clés qui ont des articles dans la période analysée
    root = project_root or _PROJECT_ROOT
    active_stems: set[str] | None = None
    if counts:
        active_stems = {
            k[4:]  # strip "rss:"
            for k, v in counts.items()
            if k.startswith("rss:") and v > 0
        } or None  # None si vide = afficher tous (fallback)
    triggers = collect_trigger_terms_by_flux(root, days=days)
    kw_table = _build_keyword_table_block(
        root, active_stems=active_stems, counts=counts, triggers=triggers
    )
    if kw_table:
        lines += [
            "",
            "## Mots-clés de veille",
            "",
            f"> *« Articles détectés » : nombre d'articles collectés par mot-clé sur les {days} derniers jours. "
            f"Le nombre entre parenthèses après chaque terme OU/ET indique combien de fois ce terme a "
            f"effectivement déclenché la détection d'un article (champ `terme_declencheur`).*",
            "",
            kw_table,
            "",
        ]

    lines += ["---", f"*Rapport généré par WUDD.ai — {now_str}*"]

    return "\n".join(lines)


# ── Point d'entrée ────────────────────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(
        description="Analyse croisée des flux WUDD.ai"
    )
    parser.add_argument(
        "--days", type=int, default=30,
        help="Fenêtre temporelle en jours (défaut: 30)"
    )
    parser.add_argument(
        "--min-flux", type=int, default=2,
        help="Nombre minimal de flux pour qu'une entité soit signalée (défaut: 2)"
    )
    parser.add_argument(
        "--top", type=int, default=30,
        help="Nombre d'entités à conserver dans le rapport (défaut: 30)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Affiche le résultat sans sauvegarder"
    )
    parser.add_argument(
        "--no-ai", action="store_true",
        help="Désactive la synthèse IA"
    )
    parser.add_argument(
        "--no-discord", action="store_true",
        help="N'envoie pas la notification Discord"
    )
    parser.add_argument(
        "--contradictions", action="store_true",
        help="Détecte les contradictions entre sources (coûteux : appels IA)"
    )
    parser.add_argument("--no-atom", action="store_true", help="N'écrit pas le flux Atom")
    parser.add_argument("--no-obsidian", action="store_true", help="N'exporte pas vers Obsidian")
    return parser.parse_args()


def main():
    args = parse_args()
    project_root = _PROJECT_ROOT
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    print_console(f"=== Analyse croisée des flux WUDD.ai ({args.days}j) ===")

    flux_entities = collect_entities_by_flux(project_root, days=args.days)
    flux_names = list(flux_entities.keys())
    print_console(f"  → {len(flux_names)} flux analysé(s)")

    if len(flux_names) < 2:
        print_console(
            "Moins de 2 flux disponibles. L'analyse croisée nécessite au moins 2 flux.",
            "warning"
        )

    cross_entities = compute_cross_flux(
        flux_entities,
        min_flux=args.min_flux,
        top_n=args.top,
    )
    print_console(
        f"  → {len(cross_entities)} entité(s) présente(s) dans ≥ {args.min_flux} flux"
    )

    flux_article_counts = collect_article_counts_by_flux(project_root, days=args.days)
    print_console(f"  → {sum(flux_article_counts.values())} article(s) comptabilisé(s) au total")

    # Enrichissement (#1,#4,#6,#7,#11) + tendances (#2) + émergence (#3,#18)
    _enrich_cross_entities(project_root, cross_entities, args.days)
    _mark_emerging(project_root, cross_entities, date_str)
    timeline = _load_entity_timeline(project_root)

    # Mini-analyses (#10) + contradictions (#5, opt-in) — sautées en dry-run
    minianalyses, contradictions = {}, []
    if not args.dry_run and not args.no_ai:
        minianalyses = _entity_minianalyses(cross_entities, use_ai=True)
    if not args.dry_run and getattr(args, "contradictions", False):
        contradictions = _detect_contradictions(cross_entities, enabled=True)
        if contradictions:
            print_console(f"  → {len(contradictions)} contradiction(s) détectée(s)")

    # Synthèse IA des éléments (puis liaison des entités citées #8)
    synthesis = ""
    if not args.dry_run and not args.no_ai:
        synthesis = _generate_cross_flux_synthesis(
            cross_entities, flux_article_counts, args.days, use_ai=True
        )
        if synthesis:
            synthesis = _link_entities_in_text(synthesis, cross_entities)
            print_console("  → synthèse IA générée")

    # JSON : on retire les champs internes « _… » (volumineux)
    output_data = {
        "generated_at":   datetime.now(timezone.utc).isoformat(),
        "window_days":    args.days,
        "min_flux":       args.min_flux,
        "flux_count":     len(flux_names),
        "flux_list":      sorted(flux_names),
        "cross_entities": [{k: v for k, v in e.items() if not k.startswith("_")}
                           for e in cross_entities],
    }

    report_md = build_cross_flux_markdown(
        date_str=date_str, days=args.days, flux_names=flux_names,
        cross_entities=cross_entities, flux_article_counts=flux_article_counts,
        project_root=project_root, synthesis=synthesis,
        flux_entities=flux_entities, timeline=timeline,
        minianalyses=minianalyses, contradictions=contradictions,
    )

    if args.dry_run:
        print_console("[DRY-RUN] Résultats non sauvegardés.")
        print(json.dumps(output_data, ensure_ascii=False, indent=2))
        return

    _OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    _OUTPUT_JSON.write_text(json.dumps(output_data, ensure_ascii=False, indent=2), encoding="utf-8")
    print_console(f"Rapport JSON sauvegardé : {_OUTPUT_JSON}")

    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    md_path = _OUTPUT_DIR / f"cross_flux_{date_str}.md"
    md_path.write_text(report_md, encoding="utf-8")
    print_console(f"Rapport Markdown sauvegardé : {md_path}")
    cleanup_old_dated_reports(md_path)

    # Exports (#16)
    if not args.no_atom:
        _export_atom_crossflux(project_root, cross_entities)
    if not args.no_obsidian:
        _export_obsidian_crossflux(md_path)

    # Notification Discord (#15) : synthèse + top entités + 2 images (flux + co-occurrence)
    if not args.no_discord and (synthesis or cross_entities or flux_article_counts):
        chart_png = _render_flux_chart_png(flux_article_counts, top_n=10)
        cooc_png = _render_cooc_png(cross_entities, top_n=12)
        images = []
        if cooc_png:
            images.append(("cooccurrence.png", cooc_png))
        if chart_png:
            images.append(("flux.png", chart_png))
        parts = [synthesis] if synthesis else []
        top_ent = _top_entities_discord(cross_entities)
        if top_ent:
            parts.append("**Entités transversales**\n" + top_ent)
        if not chart_png:
            bars = _flux_bar_chart_text(flux_article_counts, top_n=10)
            if bars:
                parts.append("**Top flux (articles)**\n```\n" + bars + "\n```")
        description = "\n\n".join(parts)
        try:
            send_text_discord(
                title=f"🔀 Analyse croisée des flux — {date_str}",
                description=description,
                footer=f"{len(cross_entities)} entités multi-flux · {len(flux_names)} flux · WUDD.ai",
                images=images,
            )
        except Exception as exc:
            print_console(f"Notification Discord échouée : {exc}", level="warning")


if __name__ == "__main__":
    main()
