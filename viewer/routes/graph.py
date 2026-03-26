"""
viewer/routes/graph.py — Blueprint Flask pour le graphe de connaissances.

Routes :
  GET /api/graph/knowledge — flux SSE de nœuds (entités + articles) et arêtes
"""
import json

from flask import Blueprint, request, Response, stream_with_context
from pathlib import Path

from viewer.helpers import PROJECT_ROOT
from utils.article_index import get_article_index

graph_bp = Blueprint("graph", __name__)

# Longueur maximale du résumé envoyé au client (évite des payloads trop lourds)
_MAX_RESUME_LENGTH = 300

# Nombre max d'articles par défaut (limité pour la lisibilité)
_DEFAULT_MAX_ARTICLES = 200
_HARD_MAX_ARTICLES = 500


@graph_bp.route("/api/graph/knowledge")
def api_graph_knowledge():
    """Flux SSE de nœuds (entités + articles) et arêtes pour le graphe de connaissances.

    Chaque événement SSE est un objet JSON avec un champ ``type`` :
      - ``node`` (kind="article") : un article avec url, source, date, resume
      - ``node`` (kind="entity") : une entité nommée avec ner_type et value
      - ``edge``                  : liaison entre une entité et un article
      - ``done``                  : fin du flux, avec compteurs

    Paramètres GET :
      date_from  — date de début au format YYYY-MM-DD (incluse)
      date_to    — date de fin   au format YYYY-MM-DD (incluse)
      search     — texte de recherche plein-texte (url, source, date, résumé, entités)
      max_nodes  — nombre max d'articles à charger (défaut 200, max 500)
    """
    date_from  = request.args.get("date_from",  "").strip()
    date_to    = request.args.get("date_to",    "").strip()
    search     = request.args.get("search",     "").strip().lower()
    try:
        max_articles = min(int(request.args.get("max_articles", _DEFAULT_MAX_ARTICLES)),
                           _HARD_MAX_ARTICLES)
    except (ValueError, TypeError):
        max_articles = _DEFAULT_MAX_ARTICLES

    def generate():
        seen_entities: dict[str, str] = {}  # "TYPE:valeur" → identifiant du nœud
        total_nodes   = 0
        total_edges   = 0

        # ── 1. Chargement des métadonnées via article_index ──────────────────
        try:
            aidx  = get_article_index(PROJECT_ROOT)
            metas = aidx.get_articles()
        except Exception:
            metas = []

        # ── 2. Filtrage par date ─────────────────────────────────────────────
        filtered: list[dict] = []
        for meta in metas:
            date_iso = meta.get("date_iso") or meta.get("date", "")
            day = date_iso[:10] if date_iso else ""
            if date_from and day and day < date_from:
                continue
            if date_to and day and day > date_to:
                continue
            filtered.append(meta)

        # Tri par date décroissante, limitation
        filtered.sort(key=lambda m: m.get("date_iso", ""), reverse=True)
        filtered = filtered[:max_articles]

        # ── 3. Regroupement par fichier pour limiter les I/O ─────────────────
        by_file: dict[str, list[tuple[int, dict]]] = {}
        for meta in filtered:
            f   = meta.get("file", "")
            idx = meta.get("idx", -1)
            if f and idx >= 0:
                by_file.setdefault(f, []).append((idx, meta))

        # ── 4. Lecture des fichiers et streaming des nœuds/arêtes ────────────
        for file_path, meta_list in by_file.items():
            full_path = PROJECT_ROOT / file_path
            if not full_path.exists():
                continue
            try:
                articles = json.loads(full_path.read_text(encoding="utf-8"))
            except Exception:
                continue

            for idx, meta in meta_list:
                if idx >= len(articles):
                    continue

                article  = articles[idx]
                url      = article.get("URL", meta.get("url", ""))
                if not url:
                    continue

                source   = article.get("Sources",              meta.get("source", ""))
                date     = article.get("Date de publication",  meta.get("date", ""))
                resume   = article.get("Résumé", "")
                entities = article.get("entities", {})

                # ── Filtre plein-texte ───────────────────────────────────────
                if search:
                    blob = f"{url} {source} {date} {resume} {json.dumps(entities)}".lower()
                    if search not in blob:
                        continue

                # ── Nœud article ─────────────────────────────────────────────
                article_id = f"article:{url}"
                yield (
                    "data: "
                    + json.dumps(
                        {
                            "type":   "node",
                            "kind":   "article",
                            "id":     article_id,
                            "url":    url,
                            "source": source,
                            "date":   date,
                            "resume": resume[:_MAX_RESUME_LENGTH] if resume else "",
                        },
                        ensure_ascii=False,
                    )
                    + "\n\n"
                )
                total_nodes += 1

                # ── Nœuds entités + arêtes ────────────────────────────────────
                if not isinstance(entities, dict):
                    continue

                for ner_type, values in entities.items():
                    if not isinstance(values, list):
                        continue
                    for value in values:
                        if not isinstance(value, str) or not value.strip():
                            continue

                        entity_key = f"{ner_type}:{value}"
                        if entity_key not in seen_entities:
                            entity_id = f"entity:{entity_key}"
                            seen_entities[entity_key] = entity_id
                            yield (
                                "data: "
                                + json.dumps(
                                    {
                                        "type":     "node",
                                        "kind":     "entity",
                                        "id":       entity_id,
                                        "ner_type": ner_type,
                                        "value":    value,
                                    },
                                    ensure_ascii=False,
                                )
                                + "\n\n"
                            )
                            total_nodes += 1

                        # Arête entité → article
                        yield (
                            "data: "
                            + json.dumps(
                                {
                                    "type":   "edge",
                                    "source": seen_entities[entity_key],
                                    "target": article_id,
                                },
                                ensure_ascii=False,
                            )
                            + "\n\n"
                        )
                        total_edges += 1

        # ── 5. Événement de fin ───────────────────────────────────────────────
        yield (
            "data: "
            + json.dumps(
                {
                    "type":        "done",
                    "total_nodes": total_nodes,
                    "total_edges": total_edges,
                },
                ensure_ascii=False,
            )
            + "\n\n"
        )

    return Response(
        stream_with_context(generate()),
        content_type="text/event-stream",
        headers={
            "Cache-Control":    "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
