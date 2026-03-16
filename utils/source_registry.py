"""Registre des sources surveillées — WUDD.ai.

Collecte l'ensemble des noms de sources actives depuis :
  1. data/WUDD.opml          — flux RSS (attribut ``title``/``text`` des <outline>)
  2. config/web_sources.json — sources web sans RSS (champ ``title``, sources actives uniquement)
  3. data/articles/          — champ ``"Sources"`` des articles existants
  4. data/articles-from-rss/ — champ ``"Sources"`` des articles keyword existants

Les sources des articles existants sont la source la plus fiable car elles
reflètent le nom exact tel qu'il apparaît dans le pipeline de collecte.

Usage :
    from utils.source_registry import collect_sources

    sources = collect_sources(project_root)   # set[str]
    for name in sorted(sources):
        print(name)
"""

import json
import xml.etree.ElementTree as ET
from pathlib import Path

from .logging import default_logger


# ── Parseurs par source ────────────────────────────────────────────────────────

def _sources_from_opml(opml_path: Path) -> set[str]:
    """Extrait les titres des flux RSS depuis un fichier OPML.

    Utilise l'attribut ``title`` en priorité (standard OPML), puis ``text``
    comme fallback (variante courante).
    """
    sources: set[str] = set()
    if not opml_path.exists():
        default_logger.debug(f"[source_registry] OPML introuvable : {opml_path}")
        return sources
    try:
        tree = ET.parse(opml_path)
        root = tree.getroot()
        for outline in root.findall(".//outline[@type='rss']"):
            title = (
                outline.get("title")
                or outline.get("text")
                or ""
            ).strip()
            if title:
                sources.add(title)
        default_logger.debug(
            f"[source_registry] OPML : {len(sources)} flux trouvés"
        )
    except Exception as exc:
        default_logger.warning(f"[source_registry] Erreur lecture OPML : {exc}")
    return sources


def _sources_from_web_config(config_path: Path) -> set[str]:
    """Extrait les titres des sources web depuis web_sources.json.

    Ignore les entrées avec ``"actif": false``.
    """
    sources: set[str] = set()
    if not config_path.exists():
        default_logger.debug(
            f"[source_registry] web_sources.json introuvable : {config_path}"
        )
        return sources
    try:
        entries = json.loads(config_path.read_text(encoding="utf-8"))
        if not isinstance(entries, list):
            return sources
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            if not entry.get("actif", True):
                continue
            title = (entry.get("title") or entry.get("name") or "").strip()
            if title:
                sources.add(title)
        default_logger.debug(
            f"[source_registry] web_sources.json : {len(sources)} sources actives"
        )
    except Exception as exc:
        default_logger.warning(
            f"[source_registry] Erreur lecture web_sources.json : {exc}"
        )
    return sources


def _sources_from_articles(data_dirs: list[Path]) -> set[str]:
    """Collecte les valeurs du champ ``"Sources"`` dans les articles existants.

    Parcourt tous les fichiers JSON (hors cache) dans les répertoires fournis.
    Ce scan est limité à 20 articles par fichier pour rester performant.
    """
    sources: set[str] = set()
    for data_dir in data_dirs:
        if not data_dir.exists():
            continue
        for json_file in data_dir.rglob("*.json"):
            if "cache" in json_file.parts:
                continue
            try:
                articles = json.loads(
                    json_file.read_text(encoding="utf-8", errors="replace")
                )
                if not isinstance(articles, list):
                    continue
                for article in articles[:20]:
                    if not isinstance(article, dict):
                        continue
                    source = (
                        article.get("Sources") or article.get("source") or ""
                    ).strip()
                    if source:
                        sources.add(source)
            except Exception:
                continue
    default_logger.debug(
        f"[source_registry] Articles existants : {len(sources)} sources vues"
    )
    return sources


# ── Point d'entrée public ─────────────────────────────────────────────────────

def collect_sources(project_root: Path) -> set[str]:
    """Collecte l'ensemble des sources surveillées depuis toutes les configurations.

    Args:
        project_root : racine du projet WUDD.ai

    Returns:
        Ensemble de noms de sources (str), dédupliqués, longueur ≥ 2 caractères.
    """
    all_sources: set[str] = set()

    # 1. Flux RSS depuis OPML
    all_sources |= _sources_from_opml(project_root / "data" / "WUDD.opml")

    # 2. Sources web sans RSS
    all_sources |= _sources_from_web_config(
        project_root / "config" / "web_sources.json"
    )

    # 3. Sources vues dans les articles existants (valeur réelle du pipeline)
    all_sources |= _sources_from_articles([
        project_root / "data" / "articles",
        project_root / "data" / "articles-from-rss",
    ])

    # Éliminer les chaînes vides ou trop courtes
    all_sources = {s for s in all_sources if len(s) >= 2}

    default_logger.info(
        f"[source_registry] {len(all_sources)} sources uniques collectées "
        f"(OPML + web_sources + articles)"
    )
    return all_sources
