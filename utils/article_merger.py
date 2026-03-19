"""utils/article_merger.py — Fusion d'articles similaires pour WUDD.ai.

Deux fonctions publiques principales :

  find_similar(article, project_root, days=7, threshold=0.35)
      Recherche dans le corpus les articles traitant du même sujet.
      Retourne une liste triée par score décroissant.

  execute_merge(source_article, source_file_path, secondary_articles_with_meta,
                project_root, synthesis=None)
      Fusionne les articles sélectionnés :
        1. Archive les secondaires dans {dir}/merged/{fichier}-merged.json
        2. Supprime les URLs secondaires de TOUS les fichiers JSON du corpus
        3. Insère l'article fusionné dans le fichier de la source principale
        4. Met à jour tous les fichiers 48-heures.json détectés
        5. Ajoute une mention de fusion dans les notes Obsidian des secondaires
"""

import hashlib
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from .date_utils import parse_article_date
from .deduplication import _normalize, _tokenize, _bigrams
from .logging import default_logger

# ── Pondération des types d'entités ──────────────────────────────────────────

_ENTITY_WEIGHTS: dict[str, float] = {
    "PERSON":      1.5,
    "EVENT":       1.4,
    "ORG":         1.3,
    "PRODUCT":     1.2,
    "LAW":         0.9,
    "NORP":        0.9,
    "GPE":         0.8,
    "WORK_OF_ART": 0.8,
    "LOC":         0.7,
    "MONEY":       0.5,
    "FAC":         0.6,
    "LANGUAGE":    0.4,
    "QUANTITY":    0.3,
    "PERCENT":     0.3,
    "DATE":        0.3,
    "TIME":        0.2,
    "CARDINAL":    0.2,
    "ORDINAL":     0.2,
}

_SIMILARITY_THRESHOLD = 0.35
_WINDOW_DAYS = 7

# Répertoires à exclure lors du scan des fichiers JSON
_EXCLUDED_DIRS = frozenset({"cache", ".git", "__pycache__"})

# Noms de fichiers d'index à ne pas scanner comme articles
_INDEX_FILES = frozenset({"article_index.json", "entity_index.json",
                           "quota_state.json", "web_watcher_state.json",
                           "alertes.json", "entity_timeline.json"})


# ── Fonctions de similarité ───────────────────────────────────────────────────

def _get_entity_set(article: dict) -> dict[str, frozenset]:
    """Retourne les entités d'un article par type (frozenset de valeurs normalisées)."""
    result: dict[str, frozenset] = {}
    for etype, values in (article.get("entities") or {}).items():
        if isinstance(values, list):
            normalized = frozenset(_normalize(v) for v in values if v)
            if normalized:
                result[etype] = normalized
    return result


def _jaccard_entities_weighted(a: dict, b: dict) -> float:
    """Jaccard pondéré sur les entités nommées de deux articles.

    Retourne 0.0 si l'un des deux articles n'a pas d'entités.
    """
    ents_a = _get_entity_set(a)
    ents_b = _get_entity_set(b)
    if not ents_a or not ents_b:
        return 0.0

    all_types = set(ents_a) | set(ents_b)
    intersection_w = 0.0
    union_w = 0.0

    for etype in all_types:
        w = _ENTITY_WEIGHTS.get(etype, 0.5)
        set_a = ents_a.get(etype, frozenset())
        set_b = ents_b.get(etype, frozenset())
        inter = len(set_a & set_b)
        union = len(set_a | set_b)
        if union > 0:
            intersection_w += w * inter
            union_w += w * union

    return intersection_w / union_w if union_w > 0 else 0.0


def _jaccard_bigrams_text(text_a: str, text_b: str) -> float:
    """Jaccard sur bigrammes de mots pour deux textes (résumés)."""
    if not text_a or not text_b:
        return 0.0
    bg_a = _bigrams(_tokenize(_normalize(text_a)))
    bg_b = _bigrams(_tokenize(_normalize(text_b)))
    if not bg_a or not bg_b:
        return 0.0
    inter = len(bg_a & bg_b)
    union = len(bg_a | bg_b)
    return inter / union if union > 0 else 0.0


def _temporal_bonus(date_a: str, date_b: str) -> float:
    """Bonus temporel selon la proximité des dates de publication."""
    dt_a = parse_article_date(date_a)
    dt_b = parse_article_date(date_b)
    if dt_a is None or dt_b is None:
        return 0.0
    delta_days = abs((dt_a - dt_b).total_seconds()) / 86400
    if delta_days <= 2:
        return 1.0
    if delta_days <= 7:
        return 0.5
    return 0.0


def _compute_similarity(article_a: dict, article_b: dict) -> dict:
    """Calcule le score composite de similarité entre deux articles.

    Returns:
        dict avec score (composite), score_entites, score_bigrammes, score_temporel
    """
    score_entities = _jaccard_entities_weighted(article_a, article_b)
    score_bigrams = _jaccard_bigrams_text(
        article_a.get("Résumé") or "",
        article_b.get("Résumé") or "",
    )
    temporal = _temporal_bonus(
        article_a.get("Date de publication", ""),
        article_b.get("Date de publication", ""),
    )
    composite = 0.40 * score_entities + 0.35 * score_bigrams + 0.15 * temporal
    return {
        "score":           round(composite, 3),
        "score_entites":   round(score_entities, 3),
        "score_bigrammes": round(score_bigrams, 3),
        "score_temporel":  round(temporal, 3),
    }


def _is_within_window(date_a: str, date_b: str, days: int) -> bool:
    """Vérifie si deux dates sont dans une fenêtre de N jours."""
    dt_a = parse_article_date(date_a)
    dt_b = parse_article_date(date_b)
    if dt_a is None or dt_b is None:
        return False
    return abs((dt_a - dt_b).total_seconds()) <= days * 86400


def _write_atomic(path: Path, data) -> None:
    """Écriture atomique via fichier temporaire."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=4), encoding="utf-8")
    tmp.replace(path)


def _iter_article_files(project_root: Path):
    """Génère tous les fichiers JSON d'articles sous data/ (hors index et exclusions)."""
    data_dir = project_root / "data"
    if not data_dir.exists():
        return
    for json_file in data_dir.rglob("*.json"):
        parts = json_file.relative_to(project_root).parts
        if any(p in _EXCLUDED_DIRS for p in parts):
            continue
        if json_file.name in _INDEX_FILES:
            continue
        # Exclure les archives de fusion elles-mêmes
        if "merged" in parts:
            continue
        yield json_file


# ── Recherche d'articles similaires ──────────────────────────────────────────

def find_similar(
    article: dict,
    project_root: Path,
    days: int = _WINDOW_DAYS,
    threshold: float = _SIMILARITY_THRESHOLD,
) -> list[dict]:
    """Recherche les articles du corpus similaires à `article`.

    Algorithme en 3 passes :
      Passe 1 — Filtre temporel : ±days jours autour de la date de l'article source
      Passe 2 — Filtre entités  : score_entités ≥ 0.10 (si les deux ont des entités)
      Passe 3 — Score composite : ≥ threshold

    Returns:
        Liste de dicts triés par score décroissant :
          {score, score_entites, score_bigrammes, score_temporel, article, file_path}
    """
    source_url = (article.get("URL") or "").strip()
    source_date = article.get("Date de publication", "")
    has_source_entities = bool(article.get("entities"))

    seen_urls: set[str] = {source_url}  # éviter de se comparer à soi-même
    candidates: list[dict] = []

    for json_file in _iter_article_files(project_root):
        try:
            content = json.loads(json_file.read_text(encoding="utf-8"))
            if not isinstance(content, list):
                continue
        except Exception:
            continue

        for candidate in content:
            if not isinstance(candidate, dict):
                continue
            cand_url = (candidate.get("URL") or "").strip()
            if not cand_url or cand_url in seen_urls:
                continue

            # Passe 1 : filtre temporel
            if not _is_within_window(source_date, candidate.get("Date de publication", ""), days):
                continue

            # Passe 2 : filtre entités rapide
            if has_source_entities and candidate.get("entities"):
                if _jaccard_entities_weighted(article, candidate) < 0.10:
                    continue

            # Passe 3 : score composite
            scores = _compute_similarity(article, candidate)
            if scores["score"] >= threshold:
                seen_urls.add(cand_url)
                candidates.append({
                    **scores,
                    "article":   candidate,
                    "file_path": str(json_file.relative_to(project_root)),
                })

    candidates.sort(key=lambda x: x["score"], reverse=True)
    default_logger.info(
        f"article_merger : {len(candidates)} candidat(s) trouvé(s) pour {source_url[:60]}"
    )
    return candidates


# ── Helpers de fusion ─────────────────────────────────────────────────────────

def _merge_entities(articles: list[dict]) -> dict:
    """Union déduplicatée des entités de plusieurs articles."""
    merged: dict[str, list[str]] = {}
    for article in articles:
        for etype, values in (article.get("entities") or {}).items():
            if not isinstance(values, list):
                continue
            existing = merged.setdefault(etype, [])
            for v in values:
                if v and v not in existing:
                    existing.append(v)
    return merged


def _select_primary(articles: list[dict]) -> dict:
    """Sélectionne la source principale parmi les articles à fusionner.

    Critères (par priorité décroissante) :
      1. score_source (crédibilité source) le plus élevé
      2. Complétude (résumé long + images + entités)
      3. Date de publication la plus récente
    """
    def _rank(a: dict) -> tuple:
        cred = a.get("score_source") or 50
        completeness = (
            (1 if len(a.get("Résumé") or "") > 100 else 0)
            + (1 if a.get("Images") else 0)
            + (1 if a.get("entities") else 0)
        )
        dt = parse_article_date(a.get("Date de publication", ""))
        ts = dt.timestamp() if dt else 0
        return (cred, completeness, ts)

    return max(articles, key=_rank)


def _get_obsidian_note_name(article: dict) -> str:
    """Extrait le nom (sans extension) de la note Obsidian de l'article."""
    for rapport in (article.get("rapports") or []):
        if rapport.get("cible") == "obsidian":
            fichier = rapport.get("fichier") or ""
            if fichier:
                return Path(fichier).stem
    # Fallback : titre normalisé
    titre = article.get("Titre") or article.get("Sources") or "article-fusionné"
    return re.sub(r"[^\w\s-]", "", titre)[:60].strip()


def _update_obsidian_note(rapport: dict, merged_note_name: str) -> bool:
    """Ajoute une mention de fusion en tête de la note Obsidian d'un article secondaire.

    Returns True si la note a été modifiée.
    """
    chemin = rapport.get("chemin") or ""
    fichier = rapport.get("fichier") or ""
    if not chemin or not fichier:
        return False

    note_path = Path(chemin) / fichier
    if not note_path.exists():
        return False

    try:
        content = note_path.read_text(encoding="utf-8")
        if "fusionné dans" in content:
            return False  # mention déjà présente

        today = datetime.now().strftime("%d/%m/%Y")
        mention = (
            f"> [!note] Article fusionné\n"
            f"> Fusionné dans [[{merged_note_name}]] le {today}.\n\n"
        )
        note_path.write_text(mention + content, encoding="utf-8")
        return True
    except Exception as e:
        default_logger.warning(f"article_merger : impossible de modifier {note_path} — {e}")
        return False


def _archive_articles(
    secondary_meta: list[dict],
    merged_article: dict,
    primary_file: Path,
    project_root: Path,
) -> Path:
    """Archive les articles secondaires dans {dir}/merged/{stem}-merged.json.

    Le fichier archive est cumulatif : chaque fusion ajoute une entrée dans
    le tableau `fusions` sans écraser les précédentes.

    Returns:
        Chemin absolu du fichier archive.
    """
    archive_dir = primary_file.parent / "merged"
    archive_dir.mkdir(parents=True, exist_ok=True)
    archive_path = archive_dir / (primary_file.stem + "-merged.json")

    # Charger l'archive existante ou initialiser
    if archive_path.exists():
        try:
            data = json.loads(archive_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError
        except Exception:
            data = {"fichier_source": primary_file.name, "fusions": []}
    else:
        data = {"fichier_source": primary_file.name, "fusions": []}

    # ID unique de fusion
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    fusion_id = f"fus_{ts}_{hashlib.md5((merged_article.get('URL') or '').encode()).hexdigest()[:6]}"

    entry = {
        "id_fusion":            fusion_id,
        "date_fusion":          datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "url_article_fusionné": merged_article.get("URL", ""),
        "articles_archivés": [
            {
                **item["article"],
                "_archive": {
                    "raison":           f"fusionné dans {merged_article.get('URL', '')}",
                    "score_similarité": item.get("score", 0),
                    "fichier_source":   item.get("file_path", ""),
                },
            }
            for item in secondary_meta
        ],
    }

    data.setdefault("fusions", []).append(entry)
    data["dernière_modification"] = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

    _write_atomic(archive_path, data)
    default_logger.info(f"article_merger : archive écrite → {archive_path.relative_to(project_root)}")
    return archive_path


def _remove_urls_from_all_files(urls_to_remove: set[str], project_root: Path) -> int:
    """Supprime toutes les occurrences des URLs données dans tous les fichiers JSON du corpus.

    Returns:
        Nombre de fichiers modifiés.
    """
    modified = 0
    for json_file in _iter_article_files(project_root):
        try:
            articles = json.loads(json_file.read_text(encoding="utf-8"))
            if not isinstance(articles, list):
                continue
            before = len(articles)
            filtered = [a for a in articles if (a.get("URL") or "") not in urls_to_remove]
            if len(filtered) < before:
                _write_atomic(json_file, filtered)
                modified += 1
                default_logger.debug(
                    f"article_merger : {before - len(filtered)} supprimé(s) dans {json_file.name}"
                )
        except Exception as e:
            default_logger.warning(f"article_merger : erreur lecture {json_file} — {e}")
    return modified


def _insert_merged_into_primary(merged_article: dict, primary_file: Path) -> None:
    """Insère l'article fusionné en tête du fichier source principal."""
    try:
        articles = json.loads(primary_file.read_text(encoding="utf-8"))
        if not isinstance(articles, list):
            articles = []
    except Exception:
        articles = []

    merged_url = merged_article.get("URL") or ""
    # Retirer l'éventuel doublon (la source principale a déjà été supprimée, mais par sécurité)
    articles = [a for a in articles if (a.get("URL") or "") != merged_url]
    articles.insert(0, merged_article)
    _write_atomic(primary_file, articles)


def _update_all_48h_files(
    project_root: Path,
    secondary_urls: set[str],
    merged_article: dict,
) -> None:
    """Met à jour tous les fichiers 48-heures.json : supprime les secondaires, insère le fusionné."""
    cutoff = datetime.utcnow() - timedelta(hours=48)
    merged_url = merged_article.get("URL") or ""

    dt_merged = parse_article_date(merged_article.get("Date de publication", ""))
    in_window = dt_merged is not None and dt_merged > cutoff

    for h48_file in (project_root / "data").rglob("48-heures.json"):
        try:
            articles = json.loads(h48_file.read_text(encoding="utf-8"))
            if not isinstance(articles, list):
                continue

            filtered = [
                a for a in articles
                if (a.get("URL") or "") not in secondary_urls
                and (a.get("URL") or "") != merged_url
            ]

            if in_window:
                filtered.insert(0, merged_article)

            # Tri date décroissante
            def _key(a: dict):
                dt = parse_article_date(a.get("Date de publication", ""))
                return dt if dt else datetime.min

            filtered.sort(key=_key, reverse=True)
            _write_atomic(h48_file, filtered)
            default_logger.debug(f"article_merger : 48-heures.json mis à jour → {h48_file}")
        except Exception as e:
            default_logger.warning(f"article_merger : erreur mise à jour {h48_file} — {e}")


# ── Point d'entrée principal ──────────────────────────────────────────────────

def execute_merge(
    source_article: dict,
    source_file_path: str,
    secondary_articles_with_meta: list[dict],
    project_root: Path,
    synthesis: Optional[str] = None,
) -> dict:
    """Fusionne les articles sélectionnés de façon atomique et traçable.

    Séquence d'opérations (dans cet ordre) :
      1. Sélectionner la source principale (meilleure crédibilité/complétude)
      2. Construire l'article fusionné (entités union, résumé synthétisé ou source principale)
      3. Archiver les secondaires dans merged/{fichier}-merged.json  ← avant toute suppression
      4. Supprimer les URLs secondaires de TOUS les fichiers JSON du corpus
      5. Insérer l'article fusionné dans le fichier de la source principale
      6. Mettre à jour tous les fichiers 48-heures.json
      7. Mettre à jour les notes Obsidian des articles secondaires

    Args:
        source_article              : l'article depuis lequel la recherche a été lancée
        source_file_path            : chemin relatif (depuis project_root) du fichier source
        secondary_articles_with_meta: liste de dicts {article, file_path, score}
        project_root                : racine du projet
        synthesis                   : résumé synthétisé par l'IA (optionnel)

    Returns:
        dict {merged_article, archive_path, obsidian_updated, primary_source, secondaries_count}
    """
    all_articles = [source_article] + [m["article"] for m in secondary_articles_with_meta]

    # ── 1. Sélectionner la source principale ─────────────────────────────────
    primary = _select_primary(all_articles)
    primary_url = (primary.get("URL") or "").strip()
    secondaries = [a for a in all_articles if (a.get("URL") or "").strip() != primary_url]
    secondary_urls = {(a.get("URL") or "").strip() for a in secondaries}

    # Métadonnées complètes des secondaires (pour l'archive)
    all_meta = secondary_articles_with_meta.copy()
    if (source_article.get("URL") or "").strip() != primary_url:
        # La source de lancement est secondaire — l'ajouter aux métadonnées
        already = any(
            (m["article"].get("URL") or "") == (source_article.get("URL") or "")
            for m in all_meta
        )
        if not already:
            all_meta.append({
                "article":   source_article,
                "file_path": source_file_path,
                "score":     1.0,
            })
    secondary_meta = [
        m for m in all_meta
        if (m["article"].get("URL") or "").strip() != primary_url
    ]

    # Trouver le fichier de la source principale
    primary_file = project_root / source_file_path  # défaut si non trouvé dans meta
    for m in secondary_articles_with_meta:
        if (m["article"].get("URL") or "").strip() == primary_url:
            primary_file = project_root / m["file_path"]
            break

    # ── 2. Construire l'article fusionné ─────────────────────────────────────
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    fusion_id = f"fus_{ts}_{hashlib.md5(primary_url.encode()).hexdigest()[:6]}"
    archive_rel = str(
        (primary_file.parent / "merged" / (primary_file.stem + "-merged.json"))
        .relative_to(project_root)
    )

    merged_article: dict = {
        **primary,  # hérite de tous les champs de la source principale
        "entities": _merge_entities(all_articles),
    }
    if synthesis:
        merged_article["Résumé"] = synthesis

    merged_article["_fusion"] = {
        "est_article_fusionné": True,
        "id_fusion":            fusion_id,
        "date_fusion":          datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "archive":              archive_rel,
        "source_principale": {
            "Sources":             primary.get("Sources"),
            "URL":                 primary.get("URL"),
            "Date de publication": primary.get("Date de publication"),
        },
        "sources_secondaires": [
            {
                "Sources":             a.get("Sources"),
                "URL":                 a.get("URL"),
                "Date de publication": a.get("Date de publication"),
                "score_similarité":    next(
                    (m["score"] for m in secondary_meta
                     if (m["article"].get("URL") or "") == (a.get("URL") or "")),
                    0,
                ),
                "rapports": a.get("rapports", []),
            }
            for a in secondaries
        ],
        "articles_supprimés": len(secondaries),
    }

    # ── 3. Archiver avant toute suppression ───────────────────────────────────
    archive_path = _archive_articles(secondary_meta, merged_article, primary_file, project_root)

    # ── 4. Supprimer les URLs secondaires de tous les fichiers JSON ───────────
    _remove_urls_from_all_files(secondary_urls | {primary_url}, project_root)

    # ── 5. Insérer l'article fusionné dans le fichier source principal ────────
    _insert_merged_into_primary(merged_article, primary_file)

    # ── 6. Mettre à jour les fichiers 48-heures.json ──────────────────────────
    _update_all_48h_files(project_root, secondary_urls, merged_article)

    # ── 7. Mettre à jour les notes Obsidian des articles secondaires ──────────
    merged_note_name = _get_obsidian_note_name(primary)
    obsidian_updated: list[str] = []
    for sec in secondaries:
        for rapport in (sec.get("rapports") or []):
            if rapport.get("cible") == "obsidian":
                if _update_obsidian_note(rapport, merged_note_name):
                    obsidian_updated.append(rapport.get("fichier", ""))

    default_logger.info(
        f"article_merger : fusion terminée — source principale : {primary.get('Sources')} "
        f"| {len(secondaries)} secondaire(s) archivé(s)"
    )

    return {
        "merged_article":    merged_article,
        "archive_path":      str(archive_path.relative_to(project_root)),
        "obsidian_updated":  obsidian_updated,
        "primary_source":    primary.get("Sources"),
        "secondaries_count": len(secondaries),
    }
