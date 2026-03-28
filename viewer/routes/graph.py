"""
viewer/routes/graph.py — Blueprint Flask pour le graphe de connaissances.

Routes :
  GET /api/graph/knowledge — flux SSE de nœuds (entités + articles) et arêtes
"""
import json
import unicodedata

from flask import Blueprint, request, Response, stream_with_context, jsonify
from pathlib import Path

from viewer.helpers import PROJECT_ROOT
from utils.article_index import get_article_index
from utils.entity_index import EntityIndex

graph_bp = Blueprint("graph", __name__)


@graph_bp.route("/api/graph/article")
def api_graph_article():
    """Retourne l'article complet (toutes les clés) depuis son fichier JSON.

    Paramètres GET :
      file_path — chemin relatif depuis la racine du projet (ex: data/articles/…/articles…json)
      url       — URL de l'article pour le retrouver dans le tableau
    """
    file_path = request.args.get("file_path", "").strip()
    url       = request.args.get("url",       "").strip()
    if not file_path or not url:
        return jsonify({"error": "file_path et url sont requis"}), 400

    # Sécurité : interdire les traversées de répertoire
    try:
        full = (PROJECT_ROOT / file_path).resolve()
        full.relative_to(PROJECT_ROOT.resolve())
    except (ValueError, Exception):
        return jsonify({"error": "Chemin invalide"}), 400

    if not full.exists():
        return jsonify({"error": "Fichier introuvable"}), 404

    try:
        articles = json.loads(full.read_text(encoding="utf-8"))
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

    if not isinstance(articles, list):
        return jsonify({"error": "Format inattendu"}), 500

    for article in articles:
        if article.get("URL") == url:
            return jsonify(article)

    return jsonify({"error": "Article non trouvé"}), 404


# Longueur maximale du résumé envoyé au client (évite des payloads trop lourds)
_MAX_RESUME_LENGTH = 300

# Nombre max d'articles par défaut (limité pour la lisibilité)
_DEFAULT_MAX_ARTICLES = 200
_HARD_MAX_ARTICLES    = 500
_ALL_MAX_ARTICLES     = 10_000   # plafond de sécurité mode "tout charger"
_HARD_MAX_ENTITIES    = 500

# Répertoires à scanner en mode "tout charger"
_ARTICLE_DIRS = ["data/articles", "data/articles-from-rss"]


def _norm_text(value: str) -> str:
    """Normalise un texte pour recherche tolérante aux accents/casse."""
    if not isinstance(value, str):
        return ""
    normalized = unicodedata.normalize("NFKD", value.lower())
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


@graph_bp.route("/api/graph/knowledge")
def api_graph_knowledge():
    """Flux SSE de nœuds (entités + articles) et arêtes pour le graphe de connaissances.

    Chaque événement SSE est un objet JSON avec un champ ``type`` :
      - ``node`` (kind="article") : un article avec url, source, date, resume
      - ``node`` (kind="entity") : une entité nommée avec ner_type et value
      - ``edge``                  : liaison entre une entité et un article
      - ``done``                  : fin du flux, avec compteurs

    Paramètres GET :
      date_from    — date de début au format YYYY-MM-DD (incluse)
      date_to      — date de fin   au format YYYY-MM-DD (incluse)
      search       — texte de recherche plein-texte (url, source, date, résumé, entités)
      max_articles — nombre max d'articles à charger (défaut 200, max 500)
      all          — "true" pour charger tous les fichiers sans filtre de date (max 10 000)
    """
    date_from   = request.args.get("date_from",  "").strip()
    date_to     = request.args.get("date_to",    "").strip()
    mode        = request.args.get("mode", "articles").strip().lower()
    keyword     = _norm_text(request.args.get("keyword", "").strip())  # recherche dans noms d'entités
    article_query = _norm_text(request.args.get("article_query", "").strip())  # filtre titre + résumé
    entity_types_raw = request.args.get("entity_types", "").strip()
    entity_types = {t.strip().upper() for t in entity_types_raw.split(",") if t.strip()} if entity_types_raw else set()
    selected_entities_raw = request.args.get("selected_entities", "").strip()
    selected_entities: set[str] = set()
    if selected_entities_raw:
        try:
            raw_items = json.loads(selected_entities_raw)
            if isinstance(raw_items, list):
                for item in raw_items:
                    if isinstance(item, str) and item.strip():
                        normalized = item.strip()
                        if normalized.startswith("entity:"):
                            normalized = normalized[len("entity:"):]
                        selected_entities.add(normalized)
        except Exception:
            for item in selected_entities_raw.split("|"):
                normalized = item.strip()
                if normalized.startswith("entity:"):
                    normalized = normalized[len("entity:"):]
                if normalized:
                    selected_entities.add(normalized)
    load_all    = request.args.get("all", "").lower() in ("true", "1", "yes")
    try:
        max_articles = min(int(request.args.get("max_articles", _DEFAULT_MAX_ARTICLES)),
                           _HARD_MAX_ARTICLES)
    except (ValueError, TypeError):
        max_articles = _DEFAULT_MAX_ARTICLES

    if mode == "entities":
        return Response(
            stream_with_context(_generate_matching_entities(keyword)),
            content_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    if load_all:
        return Response(
            stream_with_context(_generate_all(keyword, entity_types, selected_entities, article_query)),
            content_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    def generate():
        # ── Sans entité sélectionnée → graphe vide ─────────────────────────
        if not selected_entities:
            yield (
                "data: "
                + json.dumps(
                    {"type": "done", "total_nodes": 0, "total_edges": 0, "filtered_total": 0},
                    ensure_ascii=False,
                )
                + "\n\n"
            )
            return

        seen_entities: dict[str, str] = {}  # "TYPE:valeur" → identifiant du nœud
        total_nodes   = 0
        total_edges   = 0

        # ── 1. Chargement des métadonnées via article_index ──────────────────
        try:
            aidx  = get_article_index(PROJECT_ROOT)
            metas = aidx.get_articles()
        except Exception:
            metas = []

        # Tri par date décroissante pour un ordre stable
        metas.sort(key=lambda m: m.get("date_iso", ""), reverse=True)

        # ── 2. Regroupement par fichier (scan complet des correspondances) ───
        by_file: dict[str, list[tuple[int, dict]]] = {}
        for meta in metas:
            f   = meta.get("file", "")
            idx = meta.get("idx", -1)
            if f and idx >= 0:
                by_file.setdefault(f, []).append((idx, meta))

        # Candidats retenus par entités sélectionnées (avant règle <20)
        candidates: list[dict] = []

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
                titre    = article.get("Titre", "")
                resume   = article.get("Résumé", "")
                entities = article.get("entities", {})

                # Filtre texte article : titre + résumé
                if article_query:
                    text_blob = _norm_text(f"{titre} {resume}")
                    if article_query not in text_blob:
                        continue

                article_entities: list[tuple[str, str]] = []
                if isinstance(entities, dict):
                    for ner_type, values in entities.items():
                        if not isinstance(values, list):
                            continue
                        for value in values:
                            if isinstance(value, str) and value.strip():
                                article_entities.append((ner_type, value.strip()))

                article_entity_keys = {f"{ner_type}:{value}" for ner_type, value in article_entities}
                if not (article_entity_keys & selected_entities):
                    continue

                matched_entities: list[tuple[str, str]] = []
                for ner_type, value in article_entities:
                    key = f"{ner_type}:{value}"
                    if key in selected_entities or (entity_types and ner_type.upper() in entity_types):
                        matched_entities.append((ner_type, value))

                if not matched_entities:
                    continue

                candidates.append(
                    {
                        "file_path": file_path,
                        "meta": meta,
                        "url": url,
                        "source": source,
                        "date": date,
                        "title": titre,
                        "resume": resume,
                        "matched_entities": matched_entities,
                    }
                )

        # ── 3. Règle métier : < 20 => tout afficher, sinon plage de dates ───
        matched_total = len(candidates)
        date_limited = matched_total >= 20

        if date_limited:
            filtered_candidates: list[dict] = []
            for cand in candidates:
                meta = cand.get("meta", {})
                date_iso = meta.get("date_iso") or meta.get("date", "")
                day = date_iso[:10] if date_iso else ""
                if date_from and day and day < date_from:
                    continue
                if date_to and day and day > date_to:
                    continue
                filtered_candidates.append(cand)
        else:
            filtered_candidates = candidates

        filtered_candidates.sort(
            key=lambda c: (c.get("meta", {}) or {}).get("date_iso", ""),
            reverse=True,
        )
        filtered_total = len(filtered_candidates)
        filtered_candidates = filtered_candidates[:max_articles]

        # ── 4. Streaming des nœuds/arêtes ────────────────────────────────────
        for cand in filtered_candidates:
            file_path = cand["file_path"]
            url = cand["url"]
            source = cand["source"]
            date = cand["date"]
            resume = cand["resume"]
            matched_entities = cand["matched_entities"]

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
                        "file":   file_path,
                    },
                    ensure_ascii=False,
                )
                + "\n\n"
            )
            total_nodes += 1

            for ner_type, value in matched_entities:
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
                    "type":          "done",
                    "total_nodes":   total_nodes,
                    "total_edges":   total_edges,
                    "filtered_total": filtered_total,
                    "matched_total": matched_total,
                    "date_limited": date_limited,
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


def _generate_matching_entities(keyword: str):
    """Retourne uniquement les nœuds entités correspondant au mot-clé."""
    seen: set[str] = set()
    total_nodes = 0

    if not keyword:
        yield (
            "data: "
            + json.dumps({"type": "done", "total_nodes": 0, "total_edges": 0}, ensure_ascii=False)
            + "\n\n"
        )
        return

    json_files: list[Path] = []
    for dir_name in _ARTICLE_DIRS:
        d = PROJECT_ROOT / dir_name
        if d.exists():
            json_files.extend(sorted(d.rglob("*.json")))

    for json_path in json_files:
        name = json_path.name
        if name in (
            "article_index.json", "entity_index.json", "quota_state.json", "alertes.json",
            "entity_timeline.json", "synthesis_cache.json", "web_watcher_state.json", "entity_reports_index.json",
        ):
            continue
        if "cache" in json_path.parts:
            continue

        try:
            articles = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception:
            continue

        if not isinstance(articles, list):
            continue

        for article in articles:
            if not isinstance(article, dict):
                continue
            entities = article.get("entities", {})
            if not isinstance(entities, dict):
                continue

            for ner_type, values in entities.items():
                if not isinstance(values, list):
                    continue
                for value in values:
                    if not isinstance(value, str):
                        continue
                    val = value.strip()
                    if not val:
                        continue
                    if keyword not in _norm_text(val):
                        continue
                    key = f"{ner_type}:{val}"
                    if key in seen:
                        continue
                    seen.add(key)
                    yield (
                        "data: "
                        + json.dumps(
                            {
                                "type": "node",
                                "kind": "entity",
                                "id": f"entity:{key}",
                                "ner_type": ner_type,
                                "value": val,
                            },
                            ensure_ascii=False,
                        )
                        + "\n\n"
                    )
                    total_nodes += 1
                    if total_nodes >= _HARD_MAX_ENTITIES:
                        break
                if total_nodes >= _HARD_MAX_ENTITIES:
                    break
            if total_nodes >= _HARD_MAX_ENTITIES:
                break
        if total_nodes >= _HARD_MAX_ENTITIES:
            break

    yield (
        "data: "
        + json.dumps(
            {
                "type": "done",
                "total_nodes": total_nodes,
                "total_edges": 0,
                "filtered_total": 0,
            },
            ensure_ascii=False,
        )
        + "\n\n"
    )


def _generate_all(keyword: str = "", entity_types: set = None, selected_entities: set = None, article_query: str = ""):
    """Générateur SSE qui scanne TOUS les fichiers JSON d'articles sans filtre de date.

    Parcourt récursivement _ARTICLE_DIRS, lit chaque fichier JSON valide et
    émet les nœuds/arêtes pour les articles dont les entités correspondent au critère.
    Plafond de sécurité : _ALL_MAX_ARTICLES articles.
    """
    if entity_types is None:
        entity_types = set()
    if selected_entities is None:
        selected_entities = set()
    seen_entities: dict[str, str] = {}
    total_nodes  = 0
    total_edges  = 0
    total_files  = 0
    article_count = 0

    # Collecte tous les fichiers JSON à traiter
    json_files: list[Path] = []
    for dir_name in _ARTICLE_DIRS:
        d = PROJECT_ROOT / dir_name
        if d.exists():
            json_files.extend(sorted(d.rglob("*.json")))

    for json_path in json_files:
        # Ignore les fichiers d'état/index/cache
        name = json_path.name
        if name in ("article_index.json", "entity_index.json",
                    "quota_state.json", "alertes.json",
                    "entity_timeline.json", "synthesis_cache.json",
                    "web_watcher_state.json", "entity_reports_index.json"):
            continue
        # Ignore les sous-dossiers cache
        if "cache" in json_path.parts:
            continue

        try:
            articles = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception:
            continue

        if not isinstance(articles, list):
            continue

        total_files += 1

        for article in articles:
            if not isinstance(article, dict):
                continue
            if article_count >= _ALL_MAX_ARTICLES:
                break

            url      = article.get("URL", article.get("url", ""))
            if not url:
                continue

            source   = article.get("Sources",             article.get("source", ""))
            date     = article.get("Date de publication", article.get("date", ""))
            titre    = article.get("Titre", article.get("title", ""))
            resume   = article.get("Résumé", article.get("resume", ""))
            entities = article.get("entities", {})

            # Filtre texte article : titre + résumé
            if article_query:
                text_blob = _norm_text(f"{titre} {resume}")
                if article_query not in text_blob:
                    continue

            # Entités de l'article
            article_entities: list[tuple[str, str]] = []
            if isinstance(entities, dict):
                for ner_type, values in entities.items():
                    if not isinstance(values, list):
                        continue
                    for value in values:
                        if not isinstance(value, str) or not value.strip():
                            continue
                        article_entities.append((ner_type, value.strip()))

            # Conserver uniquement les articles qui contiennent au moins une entité sélectionnée
            article_entity_keys = {f"{ner_type}:{value}" for ner_type, value in article_entities}
            if selected_entities and not (article_entity_keys & selected_entities):
                continue

            # Entités à afficher : sélectionnées + types actifs
            matched_entities: list[tuple[str, str]] = []
            for ner_type, value in article_entities:
                key = f"{ner_type}:{value}"
                if key in selected_entities or (entity_types and ner_type.upper() in entity_types):
                    matched_entities.append((ner_type, value))

            if selected_entities and not matched_entities:
                continue

            article_id = f"article:{url}"
            # Chemin relatif pour le frontend (depuis PROJECT_ROOT)
            rel_path = str(json_path.relative_to(PROJECT_ROOT))
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
                        "file":   rel_path,
                    },
                    ensure_ascii=False,
                )
                + "\n\n"
            )
            total_nodes   += 1
            article_count += 1

            # Entités filtrées uniquement
            entities_to_stream = matched_entities if (keyword or entity_types) else []
            if not (keyword or entity_types) and isinstance(entities, dict):
                for ner_type, values in entities.items():
                    if isinstance(values, list):
                        for value in values:
                            if isinstance(value, str) and value.strip():
                                entities_to_stream.append((ner_type, value))

            for ner_type, value in entities_to_stream:
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

        if article_count >= _ALL_MAX_ARTICLES:
            break

    yield (
        "data: "
        + json.dumps(
            {
                "type":        "done",
                "total_nodes": total_nodes,
                "total_edges": total_edges,
                "total_files": total_files,
            },
            ensure_ascii=False,
        )
        + "\n\n"
    )


# ── Nombre max d'entités L2 co-occurrentes retournées ──────────────────────
_MAX_L2_ENTITIES  = 150  # nœuds L2 max au total
_MAX_CO_PER_ENTITY = 10  # co-occurrences max par entité source


@graph_bp.route("/api/graph/l2", methods=["POST"])
def api_graph_l2():
    """Retourne les co-occurrences L2 pour les entités secondaires du graphe.

    Pour chaque entité non-seed sur le graphe, cherche dans l'entity_index
    les articles qui la mentionnent MAIS qui ne sont PAS déjà sur le graphe,
    puis collecte les entités co-occurrentes de ces autres articles.

    Body JSON :
      entities      — array : entités non-seed du graphe (ex. ["ORG:OpenAI","GPE:France"])
      seed_entities — array : entités principales/seed (ex. ["PERSON:Sam Altman"])
      exclude_urls  — array : URLs des articles déjà sur le graphe
      date_from     — filtre date début (YYYY-MM-DD) optionnel
      date_to       — filtre date fin   (YYYY-MM-DD) optionnel
    """
    body = request.get_json(silent=True) or {}

    entity_keys = body.get("entities", [])
    if not isinstance(entity_keys, list) or not entity_keys:
        return jsonify({"nodes": [], "edges": []})

    # Entités seed (principales) à exclure des résultats
    seed_list = body.get("seed_entities", [])
    seed_keys: set[str] = set()
    if isinstance(seed_list, list):
        seed_keys = {k.strip() for k in seed_list if isinstance(k, str) and ":" in k}

    # URLs des articles déjà sur le graphe à exclure
    urls_list = body.get("exclude_urls", [])
    exclude_urls: set[str] = set()
    if isinstance(urls_list, list):
        exclude_urls = {u.strip() for u in urls_list if isinstance(u, str)}

    # Entités non-seed à explorer (celles envoyées dans "entities")
    source_keys: set[str] = set()
    for k in entity_keys:
        if isinstance(k, str) and ":" in k:
            source_keys.add(k.strip())

    if not source_keys:
        return jsonify({"nodes": [], "edges": []})

    # Toutes les entités déjà sur le graphe = source + seed → à exclure des résultats
    all_graph_keys = source_keys | seed_keys

    eidx = EntityIndex(PROJECT_ROOT)

    # Pour chaque entité source, collecter les articles puis les co-entités
    co_count: dict[str, dict[str, int]] = {}
    co_info: dict[str, tuple[str, str]] = {}

    file_cache: dict[str, list] = {}

    for src_key in source_keys:
        if ":" not in src_key:
            continue
        ner_type, _, value = src_key.partition(":")
        if not value:
            continue

        refs = eidx.get_refs(ner_type, value)

        co_count[src_key] = {}

        for ref in refs:
            fpath = ref.get("file", "")
            idx = ref.get("idx", -1)
            if not fpath or idx < 0:
                continue

            # Charger le fichier JSON (avec cache)
            if fpath not in file_cache:
                full = PROJECT_ROOT / fpath
                if not full.exists():
                    file_cache[fpath] = []
                    continue
                try:
                    file_cache[fpath] = json.loads(full.read_text(encoding="utf-8"))
                except Exception:
                    file_cache[fpath] = []
                    continue

            articles = file_cache[fpath]
            if idx >= len(articles):
                continue

            article = articles[idx]

            # Exclure les articles déjà sur le graphe
            article_url = article.get("URL", "")
            if article_url and article_url in exclude_urls:
                continue

            entities = article.get("entities", {})
            if not isinstance(entities, dict):
                continue

            for co_type, values in entities.items():
                if not isinstance(values, list):
                    continue
                for v in values:
                    if not isinstance(v, str) or not v.strip():
                        continue
                    co_key = f"{co_type}:{v.strip()}"
                    # Ne pas compter les entités déjà sur le graphe (source + seed)
                    if co_key in all_graph_keys:
                        continue
                    co_count[src_key][co_key] = co_count[src_key].get(co_key, 0) + 1
                    if co_key not in co_info:
                        co_info[co_key] = (co_type, v.strip())

    # Sélectionner les top co-occurrences par entité source, puis global
    all_candidates: dict[str, int] = {}
    per_source_top: dict[str, list[str]] = {}
    for src_key, counts in co_count.items():
        top = sorted(counts.items(), key=lambda x: -x[1])[:_MAX_CO_PER_ENTITY]
        per_source_top[src_key] = [k for k, _ in top]
        for co_key, cnt in top:
            all_candidates[co_key] = all_candidates.get(co_key, 0) + cnt

    # Garder les _MAX_L2_ENTITIES entités les plus co-occurrentes globalement
    selected_l2 = set(
        k for k, _ in sorted(all_candidates.items(), key=lambda x: -x[1])[:_MAX_L2_ENTITIES]
    )

    # Construire les nœuds et arêtes
    nodes = []
    edges = []
    for co_key in selected_l2:
        info = co_info.get(co_key)
        if not info:
            continue
        ner_type, value = info
        nodes.append({
            "id": f"entity:{co_key}",
            "kind": "entity",
            "ner_type": ner_type,
            "value": value,
            "l2": True,
        })

    for src_key, top_keys in per_source_top.items():
        for co_key in top_keys:
            if co_key not in selected_l2:
                continue
            weight = co_count[src_key].get(co_key, 1)
            edges.append({
                "source": f"entity:{src_key}",
                "target": f"entity:{co_key}",
                "weight": weight,
            })

    return jsonify({"nodes": nodes, "edges": edges})
