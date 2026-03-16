"""
viewer/routes/entities.py — Blueprint Flask pour les entités nommées (NER).

Routes :
  GET  /api/search/entity
  GET  /api/entities/dashboard
  GET  /api/entities/articles
  GET  /api/entity-context
  GET  /api/entities/cooccurrences
  POST /api/entities/geocode
  POST /api/entities/images
  GET  /api/entities/info
  GET  /api/entities/timeline
  GET/POST/DELETE /api/annotations
  GET/POST/DELETE /api/watched-entities
"""
import datetime
import json
import os
import threading

from flask import Blueprint, jsonify, request, Response, stream_with_context
from pathlib import Path

from viewer.helpers import PROJECT_ROOT, _call_ai_blocking
from viewer.state import _annotations_lock
from utils.article_index import get_article_index
from utils.entity_index import get_entity_index

entities_bp = Blueprint("entities", __name__)

# ── Annotations manuelles ─────────────────────────────────────────────────────
# Stockées dans data/annotations.json (dict keyed par URL d'article)
# Jamais dans les fichiers articles — données sources préservées.

_ANNOTATIONS_FILE = PROJECT_ROOT / "data" / "annotations.json"


def _load_annotations() -> dict:
    """Charge le fichier annotations.json (crée s'il n'existe pas)."""
    if not _ANNOTATIONS_FILE.exists():
        return {}
    try:
        return json.loads(_ANNOTATIONS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_annotations(data: dict) -> None:
    """Sauvegarde atomique du fichier annotations.json."""
    _ANNOTATIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = _ANNOTATIONS_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(_ANNOTATIONS_FILE)


# ── Entités surveillées ───────────────────────────────────────────────────────
# Stockées dans data/watched_entities.json
# [{type, value, added_at, notes}]

_WATCHED_FILE = PROJECT_ROOT / "data" / "watched_entities.json"
_watched_lock = threading.Lock()


def _load_watched() -> list:
    if not _WATCHED_FILE.exists():
        return []
    try:
        return json.loads(_WATCHED_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_watched(data: list) -> None:
    _WATCHED_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = _WATCHED_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(_WATCHED_FILE)


@entities_bp.route("/api/search/entity")
def api_search_entity():
    """Recherche cross-fichiers d'une valeur d'entité nommée (via entity_index)."""
    q = request.args.get("q", "").strip()
    entity_type = request.args.get("type", "").strip()
    if len(q) < 2:
        return jsonify([])

    q_lower = q.lower()
    results = []

    try:
        eidx = get_entity_index(PROJECT_ROOT)
        all_entries = eidx.get_all_entries()  # { "TYPE:value": [{file, idx, date}, ...] }

        # Filtrer les clés qui contiennent q_lower (correspondance partielle)
        matching_keys = [
            k for k in all_entries
            if q_lower in k.split(":", 1)[-1].lower()
            and (not entity_type or k.startswith(entity_type + ":"))
        ]

        # Regrouper refs par fichier pour charger chaque fichier une seule fois
        files_to_idxs: dict[str, set[int]] = {}
        key_by_file_idx: dict[tuple, list[str]] = {}  # (file, idx) → matched types
        for k in matching_keys:
            etype = k.split(":", 1)[0]
            for ref in all_entries[k]:
                fpath = ref.get("file", "")
                idx = ref.get("idx", -1)
                if not fpath:
                    continue
                files_to_idxs.setdefault(fpath, set()).add(idx)
                key_by_file_idx.setdefault((fpath, idx), []).append(etype)

        seen_results: set[str] = set()
        for rel_path, idxs in files_to_idxs.items():
            try:
                articles = json.loads(
                    (PROJECT_ROOT / rel_path).read_text(encoding="utf-8", errors="replace")
                )
                if not isinstance(articles, list):
                    continue
            except (json.JSONDecodeError, OSError):
                continue
            for i, article in enumerate(articles):
                if i not in idxs:
                    continue
                url = article.get("URL", "")
                if url and url in seen_results:
                    continue
                if url:
                    seen_results.add(url)
                matched_types = key_by_file_idx.get((rel_path, i), [])
                resume = article.get("Résumé", "")
                idx_in_resume = resume.lower().find(q_lower)
                if idx_in_resume >= 0:
                    start = max(0, idx_in_resume - 80)
                    end = min(len(resume), idx_in_resume + len(q) + 80)
                    excerpt = (
                        ("…" if start > 0 else "")
                        + resume[start:end]
                        + ("…" if end < len(resume) else "")
                    )
                else:
                    excerpt = resume[:160] + ("…" if len(resume) > 160 else "")
                results.append({
                    "path": rel_path,
                    "name": Path(rel_path).name,
                    "source": article.get("Sources", ""),
                    "date": article.get("Date de publication", ""),
                    "url": url,
                    "excerpt": excerpt,
                    "types": matched_types,
                })
    except Exception:
        # Fallback rglob si l'index est indisponible
        data_dirs = [
            PROJECT_ROOT / "data" / "articles",
            PROJECT_ROOT / "data" / "articles-from-rss",
        ]
        for data_dir in data_dirs:
            if not data_dir.exists():
                continue
            for json_file in sorted(data_dir.rglob("*.json")):
                if "cache" in json_file.relative_to(data_dir).parts:
                    continue
                try:
                    articles = json.loads(json_file.read_text(encoding="utf-8", errors="replace"))
                    if not isinstance(articles, list):
                        continue
                except (json.JSONDecodeError, OSError):
                    continue
                for article in articles:
                    ents = article.get("entities")
                    if not ents or not isinstance(ents, dict):
                        continue
                    matched_types = []
                    for etype, values in ents.items():
                        if entity_type and etype != entity_type:
                            continue
                        if not isinstance(values, list):
                            continue
                        if any(q_lower in str(v).lower() for v in values):
                            matched_types.append(etype)
                    if not matched_types:
                        continue
                    resume = article.get("Résumé", "")
                    idx = resume.lower().find(q_lower)
                    if idx >= 0:
                        start = max(0, idx - 80)
                        end = min(len(resume), idx + len(q) + 80)
                        excerpt = (
                            ("…" if start > 0 else "")
                            + resume[start:end]
                            + ("…" if end < len(resume) else "")
                        )
                    else:
                        excerpt = resume[:160] + ("…" if len(resume) > 160 else "")
                    rel = json_file.relative_to(PROJECT_ROOT)
                    results.append({
                        "path": str(rel).replace("\\", "/"),
                        "name": json_file.name,
                        "source": article.get("Sources", ""),
                        "date": article.get("Date de publication", ""),
                        "url": article.get("URL", ""),
                        "excerpt": excerpt,
                        "types": matched_types,
                    })

    results.sort(key=lambda r: r["date"], reverse=True)
    return jsonify(results[:100])


@entities_bp.route("/api/entities/dashboard")
def api_entities_dashboard():
    """Agrège les entités de tous les fichiers JSON et retourne des stats globales (via entity_index)."""
    by_type: dict[str, dict[str, int]] = {}
    total_with_entities = 0

    try:
        eidx = get_entity_index(PROJECT_ROOT)
        all_entries = eidx.get_all_entries()  # { "TYPE:value": [{file, idx, date}, ...] }

        # Compter les mentions depuis l'index (O(k) sur les clés)
        for key, refs in all_entries.items():
            parts = key.split(":", 1)
            if len(parts) != 2:
                continue
            etype, value = parts[0], parts[1].strip()
            if not value:
                continue
            if etype not in by_type:
                by_type[etype] = {}
            by_type[etype][value] = by_type[etype].get(value, 0) + len(refs)

        # Totaux depuis l'article_index
        aidx = get_article_index(PROJECT_ROOT)
        astats = aidx.stats()
        total_files = len({ref.get("file", "") for refs in all_entries.values() for ref in refs if ref.get("file")})
        total_articles = astats.get("total", 0)
        # Approximation : articles avec entités = ceux que l'index entités a référencés
        seen_refs: set[tuple] = set()
        for refs in all_entries.values():
            for ref in refs:
                seen_refs.add((ref.get("file", ""), ref.get("idx", -1)))
        total_with_entities = len(seen_refs)

    except Exception:
        # Fallback rglob
        data_dirs = [
            PROJECT_ROOT / "data" / "articles",
            PROJECT_ROOT / "data" / "articles-from-rss",
        ]
        total_files = 0
        total_articles = 0
        total_with_entities = 0
        for data_dir in data_dirs:
            if not data_dir.exists():
                continue
            for json_file in sorted(data_dir.rglob("*.json")):
                if "cache" in json_file.relative_to(data_dir).parts:
                    continue
                try:
                    articles = json.loads(json_file.read_text(encoding="utf-8", errors="replace"))
                    if not isinstance(articles, list):
                        continue
                except (json.JSONDecodeError, OSError):
                    continue
                total_files += 1
                total_articles += len(articles)
                for article in articles:
                    ents = article.get("entities")
                    if not ents or not isinstance(ents, dict):
                        continue
                    has_ent = False
                    for etype, values in ents.items():
                        if not isinstance(values, list) or not values:
                            continue
                        has_ent = True
                        if etype not in by_type:
                            by_type[etype] = {}
                        for v in values:
                            if isinstance(v, str) and v.strip():
                                key = v.strip()
                                by_type[etype][key] = by_type[etype].get(key, 0) + 1
                    if has_ent:
                        total_with_entities += 1

    result_types = []
    for etype, value_counts in by_type.items():
        sorted_values = sorted(value_counts.items(), key=lambda x: x[1], reverse=True)
        result_types.append({
            "type": etype,
            "unique_count": len(sorted_values),
            "mention_count": sum(c for _, c in sorted_values),
            "top": [{"value": v, "count": c} for v, c in sorted_values[:50]],
        })
    result_types.sort(key=lambda x: x["mention_count"], reverse=True)

    return jsonify({
        "total_files": total_files,
        "total_articles": total_articles,
        "total_with_entities": total_with_entities,
        "by_type": result_types,
    })


@entities_bp.route("/api/entities/articles")
def api_entities_articles():
    """Retourne tous les articles contenant une entité donnée (type + valeur) via entity_index."""
    entity_type = request.args.get("type", "").strip()
    entity_value = request.args.get("value", "").strip()
    if not entity_type or not entity_value:
        return jsonify({"error": "Paramètres type et value requis"}), 400

    seen_urls: set = set()
    results = []

    try:
        eidx = get_entity_index(PROJECT_ROOT)
        articles_from_idx = eidx.load_articles(entity_type, entity_value)
        for article in articles_from_idx:
            url = (article.get("URL") or "").strip()
            resume_key = article.get("Résumé", "")[:150].strip()
            if (url and url in seen_urls) or (resume_key and resume_key in seen_urls):
                continue
            if url:
                seen_urls.add(url)
            if resume_key:
                seen_urls.add(resume_key)
            results.append(article)
    except Exception:
        # Fallback rglob
        for data_dir in [PROJECT_ROOT / "data" / "articles", PROJECT_ROOT / "data" / "articles-from-rss"]:
            if not data_dir.exists():
                continue
            for json_file in sorted(data_dir.rglob("*.json")):
                if "cache" in json_file.relative_to(data_dir).parts:
                    continue
                try:
                    articles = json.loads(json_file.read_text(encoding="utf-8", errors="replace"))
                    if not isinstance(articles, list):
                        continue
                except (json.JSONDecodeError, OSError):
                    continue
                for article in articles:
                    entities = article.get("entities", {})
                    if not isinstance(entities, dict):
                        continue
                    values = entities.get(entity_type, [])
                    ev_lower = entity_value.lower()
                    if not (isinstance(values, list) and any(
                        isinstance(v, str) and v.lower() == ev_lower for v in values
                    )):
                        continue
                    url = (article.get("URL") or "").strip()
                    resume_key = article.get("Résumé", "")[:150].strip()
                    if (url and url in seen_urls) or (resume_key and resume_key in seen_urls):
                        continue
                    if url:
                        seen_urls.add(url)
                    if resume_key:
                        seen_urls.add(resume_key)
                    results.append(article)

    results.sort(key=lambda a: a.get("Date de publication", ""), reverse=True)
    return jsonify(results)


@entities_bp.route("/api/entity-context")
def api_entity_context():
    """Construit le contexte complet d'une entité pour le Terminal IA.

    Retourne un flux SSE avec des événements de progression, puis un
    événement "done" contenant le contexte assemblé (articles, co-occurrences,
    calendrier, synthèse encyclopédique IA, analyse comparative RAG).

    Query params :
      type  — type NER (ex. "ORG", "PERSON", "GPE")
      value — valeur de l'entité (ex. "OpenAI", "Emmanuel Macron")
      n     — nombre max d'articles dans le contexte (défaut 20, max 50)
    """
    entity_type  = request.args.get("type",  "").strip()
    entity_value = request.args.get("value", "").strip()
    n_articles   = min(int(request.args.get("n", 20)), 50)

    if not entity_type or not entity_value:
        return jsonify({"error": "Paramètres type et value requis"}), 400

    def _evt(payload: dict) -> str:
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    def generate():  # noqa: C901
        from collections import Counter as _Counter, defaultdict as _defaultdict

        # ── Étape 1 : collecte via entity_index (évite le scan rglob) ──────
        yield _evt({"type": "progress", "step": "data",
                    "message": f"Collecte des articles pour « {entity_value} »…"})

        try:
            from utils.entity_index import get_entity_index as _get_eidx
            eidx = _get_eidx(PROJECT_ROOT)
            articles = eidx.load_articles(entity_type, entity_value)
        except Exception:
            # Fallback : scan complet si l'index n'est pas disponible
            articles = []
            seen_urls: set = set()
            for data_dir in [PROJECT_ROOT / "data" / "articles",
                             PROJECT_ROOT / "data" / "articles-from-rss"]:
                if not data_dir.exists():
                    continue
                for json_file in sorted(data_dir.rglob("*.json")):
                    if "cache" in json_file.relative_to(data_dir).parts:
                        continue
                    try:
                        arts = json.loads(json_file.read_text(encoding="utf-8", errors="replace"))
                        if not isinstance(arts, list):
                            continue
                    except (json.JSONDecodeError, OSError):
                        continue
                    for article in arts:
                        ents = article.get("entities", {})
                        if not isinstance(ents, dict):
                            continue
                        values = ents.get(entity_type, [])
                        _ev_lower = entity_value.lower()
                        if not (isinstance(values, list) and any(
                            isinstance(v, str) and v.lower() == _ev_lower for v in values
                        )):
                            continue
                        url = (article.get("URL") or "").strip()
                        if url and url in seen_urls:
                            continue
                        if url:
                            seen_urls.add(url)
                        articles.append(article)

        articles.sort(key=lambda a: a.get("Date de publication", ""), reverse=True)
        top_articles = articles[:n_articles]

        yield _evt({"type": "progress", "step": "data",
                    "message": f"{len(articles)} article(s) trouvé(s). Calcul des relations…"})

        # ── Calcul co-occurrences + calendrier en un seul passage ──────────
        cooc: _Counter = _Counter()
        monthly: dict[str, int] = _defaultdict(int)
        sentiments_tmp: _Counter = _Counter()
        sources_tmp: _Counter = _Counter()

        for article in articles:
            # Co-occurrences L1
            ents = article.get("entities", {})
            if isinstance(ents, dict):
                for etype, evals in ents.items():
                    if isinstance(evals, list):
                        for ev in evals:
                            if not (etype == entity_type and ev == entity_value):
                                cooc[(etype, ev)] += 1
            # Calendrier mensuel
            date_str = article.get("Date de publication", "")
            if date_str and len(date_str) >= 7:
                if "/" in date_str:
                    parts = date_str.split("/")
                    if len(parts) == 3:
                        monthly[f"{parts[2]}-{parts[1]}"] += 1
                elif "-" in date_str:
                    monthly[date_str[:7]] += 1
            # Sentiments & sources (évite un 2e passage plus bas)
            s = article.get("sentiment")
            if s:
                sentiments_tmp[s] += 1
            src = article.get("Sources")
            if src:
                sources_tmp[src] += 1

        top_cooc = cooc.most_common(15)

        # ── Étape 2 : synthèse IA (encyclopédie + RAG) avec cache ─────────
        yield _evt({"type": "progress", "step": "info",
                    "message": "Synthèse encyclopédique IA en cours…"})

        type_labels_fr = {
            "PERSON": "personne physique", "ORG": "organisation ou entreprise",
            "GPE": "lieu géopolitique", "LOC": "lieu géographique",
            "PRODUCT": "produit ou technologie", "EVENT": "événement",
        }
        label_fr = type_labels_fr.get(entity_type, entity_type.lower())

        info_text = ""
        rag_text = ""

        # Vérifier le cache avant tout appel IA
        try:
            from utils.synthesis_cache import get_synthesis_cache as _get_scache
            _scache = _get_scache(PROJECT_ROOT)
            _cached = _scache.get(entity_type, entity_value)
        except Exception:
            _cached = None
            _scache = None

        if _cached:
            info_text = _cached.get("info_text", "")
            rag_text  = _cached.get("rag_text", "")
            yield _evt({"type": "progress", "step": "info",
                        "message": "Synthèse chargée depuis le cache."})
        else:
            # Appel 1 : synthèse encyclopédique
            info_prompt = (
                f"Fournis une synthèse encyclopédique en français sur « {entity_value} » ({label_fr}).\n\n"
                "Structure ta réponse en Markdown avec des sections pertinentes "
                "(présentation, rôle, contexte, actualité récente, chiffres clés, "
                "liens avec d'autres acteurs…).\n"
                "Sois factuel et concis. Génère uniquement le contenu Markdown, "
                "sans balises <think>."
            )
            info_text = _call_ai_blocking(info_prompt, timeout=90, enable_web_search=True)

            # Appel 2 : analyse RAG multi-sources
            yield _evt({"type": "progress", "step": "rag",
                        "message": "Analyse comparative multi-sources (RAG)…"})

            if top_articles:
                sources_block = ""
                for i, a in enumerate(top_articles[:15], 1):
                    src    = a.get("Sources", "Source inconnue")
                    date   = a.get("Date de publication", "")
                    resume = (a.get("Résumé") or "")[:600]
                    sources_block += f"\n--- Article {i} ({src}, {date}) ---\n{resume}\n"

                rag_prompt = (
                    f"Tu es un analyste de presse. Voici {min(len(top_articles), 15)} articles "
                    f"de sources différentes traitant de : **{entity_value}**.\n\n"
                    "Génère une synthèse comparative structurée en Markdown comprenant :\n"
                    "1. **Résumé de la situation** (2-3 phrases)\n"
                    "2. **Points de convergence** entre les sources\n"
                    "3. **Points de divergence ou contradictions**\n"
                    "4. **Positionnement éditorial** : sources favorables, neutres ou critiques\n"
                    "5. **Éléments clés manquants**\n\n"
                    "Cite les sources (nom + date) à chaque point. Sois concis et factuel.\n"
                    "Génère uniquement le contenu Markdown, sans balises <think>.\n\n"
                    f"Articles :\n{sources_block}"
                )
                rag_text = _call_ai_blocking(rag_prompt, timeout=120)

            # Stocker dans le cache pour les prochaines requêtes
            if _scache and (info_text or rag_text):
                try:
                    _scache.set(entity_type, entity_value,
                                info_text=info_text, rag_text=rag_text)
                except Exception:
                    pass

        # ── Étape 4 : assemblage du contexte final ─────────────────────────
        yield _evt({"type": "progress", "step": "build",
                    "message": "Assemblage du contexte…"})

        type_labels = {
            "PERSON": "Personne", "ORG": "Organisation", "GPE": "Pays/Région",
            "LOC": "Lieu", "PRODUCT": "Produit", "EVENT": "Événement",
            "DATE": "Date", "MONEY": "Montant",
        }
        type_label = type_labels.get(entity_type, entity_type)

        ctx_lines: list[str] = [
            f"# Contexte entité : {entity_value} ({type_label})",
            f"Total articles trouvés : {len(articles)}",
            "",
        ]

        # Calendrier
        cal_lines = [f"  {m} : {c} article(s)"
                     for m, c in sorted(monthly.items(), reverse=True)[:12]]
        if cal_lines:
            ctx_lines.append("## Calendrier des mentions (derniers 12 mois)")
            ctx_lines.extend(cal_lines)
            ctx_lines.append("")

        # Co-occurrences
        if top_cooc:
            ctx_lines.append("## Entités co-occurrentes principales")
            for (etype, ev), count in top_cooc:
                lbl = type_labels.get(etype, etype)
                ctx_lines.append(f"  - {ev} ({lbl}) : {count} co-occurrence(s)")
            ctx_lines.append("")

        # Sentiments agrégés (calculés lors du passage co-occurrences)
        sentiments = sentiments_tmp
        sources_ctr = sources_tmp
        if sentiments:
            ctx_lines.append("## Tonalité éditoriale")
            for sent, cnt in sentiments.most_common():
                ctx_lines.append(f"  - {sent} : {cnt} article(s)")
            ctx_lines.append("")
        if sources_ctr:
            ctx_lines.append("## Sources principales")
            for src, cnt in sources_ctr.most_common(8):
                ctx_lines.append(f"  - {src} : {cnt} article(s)")
            ctx_lines.append("")

        # Synthèse encyclopédique IA
        if info_text:
            ctx_lines.append("## Synthèse encyclopédique (IA)")
            ctx_lines.append(info_text)
            ctx_lines.append("")

        # Analyse comparative RAG
        if rag_text:
            ctx_lines.append("## Analyse comparative multi-sources (RAG)")
            ctx_lines.append(rag_text)
            ctx_lines.append("")

        # Articles (résumés tronqués)
        if top_articles:
            ctx_lines.append(f"## Articles récents ({len(top_articles)} sur {len(articles)})")
            for i, art in enumerate(top_articles, 1):
                date   = art.get("Date de publication", "?")
                src    = art.get("Sources", "?")
                url    = art.get("URL", "")
                resume = (art.get("Résumé") or "").strip()
                if len(resume) > 500:
                    resume = resume[:500] + "…"
                header = f"### {i}. [{date}] {src}"
                if url:
                    header += f" — {url}"
                ctx_lines.append(header)
                if resume:
                    ctx_lines.append(resume)
                ctx_lines.append("")

        context_text = "\n".join(ctx_lines)

        yield _evt({
            "type":          "done",
            "entity_type":   entity_type,
            "entity_value":  entity_value,
            "article_count": len(articles),
            "has_info":      bool(info_text),
            "has_rag":       bool(rag_text),
            "context_text":  context_text,
        })

    return Response(
        stream_with_context(generate()),
        content_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@entities_bp.route("/api/entities/cooccurrences")
def api_entities_cooccurrences():
    """Retourne les entités co-occurrentes d'une entité donnée (via articles partagés).

    Paramètres :
      type, value  — entité centrale
      limit        — max d'entités niveau 1 (défaut 40)
      depth        — profondeur du graphe : 1 ou 2 (défaut 1)
      limit_l2     — max d'entités niveau 2 par nœud L1 (défaut 4)
    """
    entity_type = request.args.get("type", "").strip()
    entity_value = request.args.get("value", "").strip()
    depth = min(int(request.args.get("depth", 1)), 2)
    # Quand depth=2 on réduit L1 pour garder le graphe lisible
    limit_l1 = min(int(request.args.get("limit", 40)), 100)
    if depth >= 2:
        limit_l1 = min(limit_l1, 12)
    limit_l2 = min(int(request.args.get("limit_l2", 4)), 15)

    if not entity_type or not entity_value:
        return jsonify({"error": "Paramètres type et value requis"}), 400

    def node_id(t, v):
        return f"{t}:{v}"

    # ── Chargement unique de tous les articles ────────────────────────────────
    all_articles: list[dict] = []
    for data_dir in [PROJECT_ROOT / "data" / "articles", PROJECT_ROOT / "data" / "articles-from-rss"]:
        if not data_dir.exists():
            continue
        for json_file in sorted(data_dir.rglob("*.json")):
            if "cache" in json_file.relative_to(data_dir).parts:
                continue
            try:
                arts = json.loads(json_file.read_text(encoding="utf-8", errors="replace"))
                if isinstance(arts, list):
                    all_articles.extend(arts)
            except (json.JSONDecodeError, OSError):
                continue

    # ── Passe 1 : co-occurrences L1 ──────────────────────────────────────────
    entity_value_lower = entity_value.lower()
    cooc_l1: dict[tuple[str, str], int] = {}
    for article in all_articles:
        entities = article.get("entities", {})
        if not isinstance(entities, dict):
            continue
        values = entities.get(entity_type, [])
        # Comparaison insensible à la casse pour robustesse vis-à-vis de la normalisation
        if not isinstance(values, list) or not any(
            v.lower() == entity_value_lower for v in values if isinstance(v, str)
        ):
            continue
        for etype, evals in entities.items():
            if not isinstance(evals, list):
                continue
            for ev in evals:
                if etype == entity_type and ev.lower() == entity_value_lower:
                    continue
                key = (etype, ev)
                cooc_l1[key] = cooc_l1.get(key, 0) + 1

    sorted_l1 = sorted(cooc_l1.items(), key=lambda x: x[1], reverse=True)[:limit_l1]
    top_l1_set: set[tuple[str, str]] = {k for k, _ in sorted_l1}

    # ── Construction des nœuds / arêtes L1 ───────────────────────────────────
    nodes = [{"type": entity_type, "value": entity_value, "count": 0,
               "central": True, "level": 0}]
    edges = []

    for (etype, ev), count in sorted_l1:
        nodes.append({"type": etype, "value": ev, "count": count,
                       "central": False, "level": 1})
        edges.append({"source": node_id(entity_type, entity_value),
                       "target": node_id(etype, ev), "weight": count})

    # ── Passe 2 : co-occurrences L2 (optionnel) ──────────────────────────────
    if depth >= 2 and top_l1_set:
        # Pour chaque article, identifie les entités L1 présentes, puis
        # accumule leurs co-occurrences (→ candidats L2).
        cooc_l2: dict[tuple[tuple, tuple], int] = {}
        for article in all_articles:
            entities = article.get("entities", {})
            if not isinstance(entities, dict):
                continue
            # Entités L1 présentes dans cet article
            l1_here = set()
            for etype, evals in entities.items():
                if not isinstance(evals, list):
                    continue
                for ev in evals:
                    if (etype, ev) in top_l1_set:
                        l1_here.add((etype, ev))
            if not l1_here:
                continue
            # Co-occurrences entre chaque nœud L1 et les autres entités
            for l1_key in l1_here:
                for etype, evals in entities.items():
                    if not isinstance(evals, list):
                        continue
                    for ev in evals:
                        co_key = (etype, ev)
                        if co_key == l1_key:
                            continue
                        if etype == entity_type and ev.lower() == entity_value_lower:
                            continue  # évite l'arête de retour vers le centre
                        cooc_l2[(l1_key, co_key)] = cooc_l2.get((l1_key, co_key), 0) + 1

        # Regroupe par nœud L1
        l1_coocs: dict[tuple, list] = {}
        for (l1_key, co_key), count in cooc_l2.items():
            l1_coocs.setdefault(l1_key, []).append((co_key, count))

        existing: set[tuple[str, str]] = {(entity_type, entity_value)} | top_l1_set
        added_l2: set[tuple[str, str]] = set()

        for l1_key, coocs in l1_coocs.items():
            top_for_l1 = sorted(
                [x for x in coocs if x[0] not in existing],
                key=lambda x: x[1],
                reverse=True,
            )[:limit_l2]
            for (etype, ev), count in top_for_l1:
                l2_key = (etype, ev)
                if l2_key not in added_l2:
                    nodes.append({"type": etype, "value": ev, "count": count,
                                   "central": False, "level": 2})
                    added_l2.add(l2_key)
                    existing.add(l2_key)
                edges.append({"source": node_id(*l1_key),
                               "target": node_id(etype, ev),
                               "weight": count})

    return jsonify({"nodes": nodes, "edges": edges, "total_cooc": len(cooc_l1)})


@entities_bp.route("/api/entities/geocode", methods=["POST"])
def api_entities_geocode():
    """Géocode une liste d'entités via Wikipedia API avec cache JSON local."""
    import requests as req

    names = request.get_json(force=True) or []
    if not names or not isinstance(names, list):
        return jsonify({})

    cache_path = PROJECT_ROOT / "data" / "geocode_cache.json"
    cache = {}
    if cache_path.exists():
        try:
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            cache = {}

    to_fetch = [n for n in names if n not in cache]

    WIKIPEDIA_UA = (
        "WUDD.ai/2.1.0 (news monitoring tool; "
        "https://github.com/patrickostertag) python-requests"
    )

    BATCH = 50
    for i in range(0, len(to_fetch), BATCH):
        batch = to_fetch[i : i + BATCH]
        titles_str = "|".join(batch)
        fetched_coords: dict[str, dict] = {}

        for lang in ("fr", "en"):
            try:
                r = req.get(
                    f"https://{lang}.wikipedia.org/w/api.php",
                    params={
                        "action": "query",
                        "titles": titles_str,
                        "prop": "coordinates",
                        "format": "json",
                        "origin": "*",
                    },
                    headers={"User-Agent": WIKIPEDIA_UA},
                    timeout=10,
                )
                data = r.json()
                pages = data.get("query", {}).get("pages", {})
                # normalizations : associe les redirections aux noms originaux
                normalized = {
                    n["from"]: n["to"]
                    for n in data.get("query", {}).get("normalized", [])
                }
                for page in pages.values():
                    if "coordinates" not in page:
                        continue
                    title = page.get("title", "")
                    coords = {
                        "lat": page["coordinates"][0]["lat"],
                        "lon": page["coordinates"][0]["lon"],
                    }
                    fetched_coords[title] = coords
                    # mappe aussi la forme originale si redirigée
                    for orig, norm in normalized.items():
                        if norm == title:
                            fetched_coords[orig] = coords
            except Exception:
                continue

            if lang == "fr" and len(fetched_coords) >= len(batch):
                break  # tout trouvé en FR

        for name in batch:
            if name not in cache:
                cache[name] = fetched_coords.get(name)  # None si introuvable

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    return jsonify({n: cache.get(n) for n in names})


@entities_bp.route("/api/entities/images", methods=["POST"])
def api_entities_images():
    """Récupère les images Wikipedia d'une liste d'entités.

    Accepte [{name, type}] ou [str] (compat. ascendante).
    Stratégie :
      - PERSON               → Wikipedia pageimages (portrait)
      - ORG / PRODUCT        → Wikidata P154 (logo officiel) + fallback pageimages
      - autres / inconnus    → Wikipedia pageimages
    """
    import requests as req

    body = request.get_json(force=True) or []
    if not body or not isinstance(body, list):
        return jsonify({})

    # Normalise l'entrée en [{name, type}]
    entities: list[dict] = []
    for item in body:
        if isinstance(item, dict):
            entities.append({"name": item.get("name", "").strip(), "type": item.get("type", "").upper()})
        elif isinstance(item, str):
            entities.append({"name": item.strip(), "type": ""})
    entities = [e for e in entities if e["name"]]

    UA = "WUDD.ai/2.1.0 (news monitoring tool; https://github.com/patrickostertag) python-requests"
    THUMB = 200
    BATCH = 50

    cache_path = PROJECT_ROOT / "data" / "images_cache.json"
    cache: dict = {}
    if cache_path.exists():
        try:
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            cache = {}

    to_fetch = [e for e in entities if e["name"] not in cache]
    if not to_fetch:
        return jsonify({e["name"]: cache.get(e["name"]) for e in entities})

    # ── Séparer PERSON vs ORG/PRODUCT vs autres ──────────────────────────────
    person_names = [e["name"] for e in to_fetch if e["type"] == "PERSON"]
    logo_names   = [e["name"] for e in to_fetch if e["type"] in ("ORG", "PRODUCT")]
    other_names  = [e["name"] for e in to_fetch if e["type"] not in ("PERSON", "ORG", "PRODUCT")]

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _pageimages(names_batch: list[str]) -> dict[str, dict]:
        """Retourne {name: {url,width,height}} via Wikipedia pageimages."""
        result: dict[str, dict] = {}
        for i in range(0, len(names_batch), BATCH):
            batch = names_batch[i : i + BATCH]
            titles_str = "|".join(batch)
            for lang in ("fr", "en"):
                try:
                    r = req.get(
                        f"https://{lang}.wikipedia.org/w/api.php",
                        params={"action": "query", "titles": titles_str,
                                "prop": "pageimages", "pithumbsize": THUMB,
                                "pilicense": "any", "format": "json", "origin": "*"},
                        headers={"User-Agent": UA}, timeout=10,
                    )
                    pages = r.json().get("query", {})
                    normalized = {n["from"]: n["to"] for n in pages.get("normalized", [])}
                    for page in pages.get("pages", {}).values():
                        if "thumbnail" not in page:
                            continue
                        title = page["title"]
                        img = {"url": page["thumbnail"]["source"],
                               "width": page["thumbnail"].get("width", THUMB),
                               "height": page["thumbnail"].get("height", THUMB)}
                        result[title] = img
                        for orig, norm in normalized.items():
                            if norm == title:
                                result[orig] = img
                except Exception:
                    continue
                if lang == "fr" and len(result) >= len(batch):
                    break
        return result

    def _wikidata_logos(names_batch: list[str]) -> tuple[dict[str, str], set[str]]:
        """Retourne ({name: image_filename}, rejected) via Wikidata P154 puis P18."""
        logos: dict[str, str] = {}
        rejected: set[str] = set()
        P154 = "P154"
        P18  = "P18"

        HARD_WRONG = {
            "Q5", "Q202444", "Q101352", "Q11266439",
        }
        SOFT_WRONG = {
            "Q4167410", "Q50339617",
        }
        WRONG_TYPES = HARD_WRONG | SOFT_WRONG
        OK_TYPES = {
            "Q4830453", "Q783794", "Q891723", "Q43229", "Q167037",
            "Q7397", "Q166142", "Q9143", "Q9135", "Q7889",
            "Q18127206", "Q18662854", "Q1331793", "Q17155032",
            "Q3220391", "Q122759350", "Q6576792", "Q118140435",
        }

        def _filename(claim_value) -> str:
            if isinstance(claim_value, str):
                return claim_value
            return claim_value.get("value", "") if isinstance(claim_value, dict) else ""

        for i in range(0, len(names_batch), BATCH):
            batch = names_batch[i : i + BATCH]
            titles_str = "|".join(batch)
            for site in ("enwiki", "frwiki"):
                try:
                    r = req.get(
                        "https://www.wikidata.org/w/api.php",
                        params={"action": "wbgetentities", "sites": site,
                                "titles": titles_str, "props": "claims|sitelinks",
                                "format": "json", "origin": "*"},
                        headers={"User-Agent": UA}, timeout=10,
                    )
                    for eid, entity in r.json().get("entities", {}).items():
                        if eid.startswith("-"):
                            continue
                        wiki_title = entity.get("sitelinks", {}).get(site, {}).get("title", "")
                        claims = entity.get("claims", {})
                        p31_ids = {
                            claim["mainsnak"]["datavalue"]["value"]["id"]
                            for claim in claims.get("P31", [])
                            if claim["mainsnak"].get("datavalue")
                        }
                        for orig in batch:
                            if orig.lower() == wiki_title.lower() and orig not in logos and orig not in rejected:
                                if p31_ids & HARD_WRONG:
                                    rejected.add(orig)
                                elif p31_ids & SOFT_WRONG:
                                    break
                                elif P154 in claims:
                                    logos[orig] = _filename(claims[P154][0]["mainsnak"]["datavalue"]["value"])
                                elif P18 in claims and p31_ids & OK_TYPES:
                                    logos[orig] = _filename(claims[P18][0]["mainsnak"]["datavalue"]["value"])
                                elif p31_ids & OK_TYPES:
                                    pass
                                else:
                                    break
                                break
                except Exception:
                    continue
        return logos, rejected

    def _wikidata_p18_persons(names_batch: list[str]) -> dict[str, str]:
        """Retourne {name: image_filename} via Wikidata P18 pour les PERSON."""
        logos: dict[str, str] = {}
        P18 = "P18"
        for i in range(0, len(names_batch), BATCH):
            batch = names_batch[i : i + BATCH]
            titles_str = "|".join(batch)
            for site in ("enwiki", "frwiki"):
                try:
                    r = req.get(
                        "https://www.wikidata.org/w/api.php",
                        params={"action": "wbgetentities", "sites": site,
                                "titles": titles_str, "props": "claims|sitelinks",
                                "format": "json", "origin": "*"},
                        headers={"User-Agent": UA}, timeout=10,
                    )
                    for eid, entity in r.json().get("entities", {}).items():
                        if eid.startswith("-"):
                            continue
                        wiki_title = entity.get("sitelinks", {}).get(site, {}).get("title", "")
                        claims = entity.get("claims", {})
                        if P18 not in claims:
                            continue
                        for orig in batch:
                            if orig.lower() == wiki_title.lower() and orig not in logos:
                                val = claims[P18][0]["mainsnak"]["datavalue"]["value"]
                                fname = val if isinstance(val, str) else val.get("value", "")
                                if fname:
                                    logos[orig] = fname
                                break
                except Exception:
                    continue
        return logos

    def _resolve_logo_urls(filenames: list[str]) -> dict[str, str]:
        """Retourne {filename: url_miniature} depuis Wikimedia Commons."""
        urls: dict[str, str] = {}
        for i in range(0, len(filenames), BATCH):
            batch = filenames[i : i + BATCH]
            titles = "|".join(f"File:{f}" for f in batch)
            try:
                r = req.get(
                    "https://commons.wikimedia.org/w/api.php",
                    params={"action": "query", "titles": titles,
                            "prop": "imageinfo", "iiprop": "url",
                            "iiurlwidth": THUMB, "format": "json", "origin": "*"},
                    headers={"User-Agent": UA}, timeout=10,
                )
                for page in r.json().get("query", {}).get("pages", {}).values():
                    fname = page.get("title", "").removeprefix("File:")
                    info = page.get("imageinfo", [])
                    if info:
                        url = info[0].get("thumburl") or info[0].get("url")
                        if url:
                            urls[fname] = url
            except Exception:
                pass
        return urls

    SEARCH_WRONG = {
        "Q5", "Q202444", "Q101352", "Q4167410", "Q11266439", "Q50339617",
        "Q4086834", "Q35234", "Q12503", "Q8091", "Q1298765", "Q17451",
        "Q58481926", "Q8171", "Q58778", "Q82042", "Q16521", "Q89", "Q1364",
    }

    def _wikidata_type_ok(qid: str, strict: bool = False) -> bool:
        if not qid:
            return not strict
        try:
            r2 = req.get(
                "https://www.wikidata.org/w/api.php",
                params={"action": "wbgetentities", "ids": qid,
                        "props": "claims", "format": "json", "origin": "*"},
                headers={"User-Agent": UA}, timeout=5,
            )
            claims = r2.json().get("entities", {}).get(qid, {}).get("claims", {})
            p31_ids = {
                c["mainsnak"]["datavalue"]["value"]["id"]
                for c in claims.get("P31", [])
                if c["mainsnak"].get("datavalue")
            }
            if strict and not p31_ids:
                return False
            return not bool(p31_ids & SEARCH_WRONG)
        except Exception:
            return True

    def _search_pageimage_single(name: str, entity_type: str = "") -> tuple[str, dict | None]:
        """Fallback final : recherche Wikipedia generator=search avec validation de type."""
        langs = ("fr", "en")
        validate = entity_type in ("ORG", "PRODUCT")

        for lang in langs:
            try:
                r = req.get(
                    f"https://{lang}.wikipedia.org/w/api.php",
                    params={
                        "action": "query",
                        "generator": "search",
                        "gsrsearch": name,
                        "gsrlimit": 3,
                        "prop": "pageimages|pageprops",
                        "pithumbsize": THUMB,
                        "pilicense": "any",
                        "ppprop": "wikibase_item",
                        "format": "json",
                        "origin": "*",
                    },
                    headers={"User-Agent": UA},
                    timeout=8,
                )
                pages = r.json().get("query", {}).get("pages", {})
                for page in sorted(pages.values(), key=lambda p: p.get("index", 0)):
                    if validate:
                        qid = page.get("pageprops", {}).get("wikibase_item", "")
                        if not _wikidata_type_ok(qid, strict=True):
                            continue

                    thumb = page.get("thumbnail")
                    if thumb and thumb.get("source"):
                        return name, {
                            "url": thumb["source"],
                            "width": thumb.get("width", THUMB),
                            "height": thumb.get("height", THUMB),
                        }
            except Exception:
                continue
        return name, None

    # ── PERSON & autres : pageimages puis Wikidata P18 si rien trouvé ───────────
    pageimg = _pageimages(person_names + other_names)
    for name in person_names + other_names:
        if name not in cache:
            cache[name] = pageimg.get(name)

    # Fallback Wikidata P18 pour les PERSON sans image Wikipedia
    persons_no_img = [n for n in person_names if not cache.get(n)]
    if persons_no_img:
        p18_files = _wikidata_p18_persons(persons_no_img)
        if p18_files:
            p18_urls = _resolve_logo_urls(list(set(p18_files.values())))
            for name, fname in p18_files.items():
                if name not in cache or not cache[name]:
                    url = p18_urls.get(fname)
                    cache[name] = {"url": url, "width": THUMB, "height": THUMB} if url else None

    # ── ORG / PRODUCT : Wikidata P154/P18 → sinon _search_pageimage_single ──
    if logo_names:
        wikidata, rejected = _wikidata_logos(logo_names)
        resolved = _resolve_logo_urls(list(set(wikidata.values()))) if wikidata else {}
        for name in logo_names:
            if name not in cache:
                logo_file = wikidata.get(name)
                if logo_file and logo_file in resolved:
                    cache[name] = {"url": resolved[logo_file], "width": THUMB, "height": THUMB}
                elif name in rejected:
                    cache[name] = None

    # ── Fallback final : Wikipedia generator=search pour toutes les entités sans image ──
    SEARCH_LIMIT = 25
    _rejected = rejected if logo_names else set()
    _type_map = {e["name"]: e["type"] for e in to_fetch}
    null_entities = [
        name for name in (person_names + logo_names + other_names)
        if not cache.get(name) and name not in _rejected
    ][:SEARCH_LIMIT]
    if null_entities:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        with ThreadPoolExecutor(max_workers=6) as pool:
            futures = {
                pool.submit(_search_pageimage_single, name, _type_map.get(name, "")): name
                for name in null_entities
            }
            for future in as_completed(futures):
                try:
                    name, result = future.result()
                    if result and not cache.get(name):
                        cache[name] = result
                except Exception:
                    pass

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")

    return jsonify({e["name"]: cache.get(e["name"]) for e in entities})


@entities_bp.route("/api/entities/info")
def api_entities_info():
    """Génère en streaming une synthèse encyclopédique sur une entité (EurIA ou Claude)."""
    import requests as req

    entity_type  = request.args.get("type",  "").strip()
    entity_value = request.args.get("value", "").strip()
    if not entity_type or not entity_value:
        return jsonify({"error": "Paramètres type et value requis"}), 400

    provider = os.environ.get("AI_PROVIDER", "euria").strip().lower()

    type_labels = {
        "PERSON":      "personne physique",
        "ORG":         "organisation ou entreprise",
        "GPE":         "lieu géopolitique",
        "LOC":         "lieu géographique",
        "PRODUCT":     "produit ou technologie",
        "EVENT":       "événement",
        "WORK_OF_ART": "œuvre",
        "LAW":         "loi ou règlement",
        "NORP":        "groupe national, religieux ou politique",
        "FAC":         "site ou bâtiment",
    }
    label = type_labels.get(entity_type, entity_type.lower())

    prompt = (
        f"Fournis une synthèse encyclopédique en français sur « {entity_value} » ({label}).\n\n"
        "Structure ta réponse en Markdown avec des sections pertinentes "
        "(présentation, rôle, contexte, actualité récente, chiffres clés, liens avec d'autres acteurs…).\n"
        "Sois factuel et concis. Génère uniquement le contenu Markdown, sans balises <think>."
    )

    if provider == "claude":
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            return jsonify({"error": "ANTHROPIC_API_KEY manquante dans .env (AI_PROVIDER=claude)"}), 503
        from utils.api_client import ClaudeClient as _ClaudeClient
        _claude = _ClaudeClient(api_key=api_key)

        def generate():
            yield from _claude.stream(prompt=prompt, timeout=90)

    else:
        api_url = os.environ.get("URL", "")
        bearer  = os.environ.get("bearer", "")
        if not api_url or not bearer:
            return jsonify({"error": "URL ou bearer manquant dans .env (AI_PROVIDER=euria)"}), 503
        payload = {
            "messages": [{"role": "user", "content": prompt}],
            "model": "qwen3",
            "stream": True,
            "enable_web_search": True,
        }
        api_headers = {
            "Authorization": f"Bearer {bearer}",
            "Content-Type": "application/json",
        }

        def generate():
            try:
                r = req.post(api_url, json=payload, headers=api_headers, stream=True, timeout=90)
                r.raise_for_status()
                for line in r.iter_lines():
                    if line:
                        yield line.decode("utf-8") + "\n\n"
            except Exception as exc:
                yield f'data: {json.dumps({"error": str(exc)})}\n\n'

    return Response(
        stream_with_context(generate()),
        content_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@entities_bp.route("/api/entities/timeline")
def api_entities_timeline():
    """Série chronologique des mentions d'entités.

    Query params :
      days       : fenêtre temporelle en jours (défaut 30)
      top        : nombre d'entités (défaut 30)
      entity     : filtrer sur une valeur d'entité
      type       : filtrer sur un type d'entité (PERSON, ORG…)
      regenerate : si "1", force le recalcul (sinon utilise le cache JSON)
    """
    import time as _time
    import sys as _sys
    try:
        days       = int(request.args.get("days", 30))
        top_n      = int(request.args.get("top", 30))
        entity     = request.args.get("entity") or None
        etype      = request.args.get("type")   or None
        regenerate = request.args.get("regenerate") == "1"

        timeline_file = PROJECT_ROOT / "data" / "entity_timeline.json"

        # Utiliser le fichier mis en cache si présent et non périmé (< 1h)
        if not regenerate and timeline_file.exists() and not entity and not etype:
            age_s = _time.time() - timeline_file.stat().st_mtime
            if age_s < 3600:
                data = json.loads(timeline_file.read_text(encoding="utf-8"))
                return jsonify(data)

        _sys.path.insert(0, str(PROJECT_ROOT))
        from scripts.entity_timeline import collect_timeline, fill_missing_dates, build_top_entities

        raw = collect_timeline(PROJECT_ROOT, days=days, entity_filter=entity, type_filter=etype)
        top_entities = build_top_entities(raw, top_n=top_n)
        top_keys = {e["key"] for e in top_entities}
        filled = fill_missing_dates({k: v for k, v in raw.items() if k in top_keys}, days=days)

        result = {
            "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
            "window_days": days,
            "top_entities": top_entities,
            "timeline": filled,
        }

        # Sauvegarder le cache si requête sans filtre
        if not entity and not etype:
            timeline_file.parent.mkdir(parents=True, exist_ok=True)
            timeline_file.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")

        return jsonify(result)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@entities_bp.route("/api/annotations", methods=["GET"])
def api_annotations_get():
    """Retourne toutes les annotations (dict keyed par URL)."""
    with _annotations_lock:
        return jsonify(_load_annotations())


@entities_bp.route("/api/annotations", methods=["POST"])
def api_annotations_post():
    """Crée ou met à jour l'annotation d'un article.

    Body JSON attendu :
        url         (str, obligatoire) — URL de l'article
        is_important (bool, optionnel)
        is_read      (bool, optionnel)
        tags         (list[str], optionnel, max 20 items)
        notes        (str, optionnel, max 5000 chars)
    """
    body = request.get_json(force=True, silent=True) or {}
    url = (body.get("url") or "").strip()
    if not url:
        return jsonify({"error": "Le champ 'url' est obligatoire"}), 400

    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")

    with _annotations_lock:
        data = _load_annotations()
        existing = data.get(url, {})

        # Merge : on ne remplace que les champs explicitement fournis
        updated = dict(existing)
        if "is_important" in body:
            updated["is_important"] = bool(body["is_important"])
        if "is_read" in body:
            updated["is_read"] = bool(body["is_read"])
        if "tags" in body:
            tags = body["tags"]
            if not isinstance(tags, list):
                return jsonify({"error": "'tags' doit être une liste"}), 400
            tags = [str(t).strip() for t in tags if str(t).strip()][:20]
            updated["tags"] = tags
        if "notes" in body:
            notes = str(body["notes"])[:5000]
            updated["notes"] = notes

        updated["updated_at"] = now_iso
        if "created_at" not in updated:
            updated["created_at"] = now_iso

        data[url] = updated
        _save_annotations(data)

    return jsonify({"ok": True, "url": url, "annotation": updated})


@entities_bp.route("/api/annotations", methods=["DELETE"])
def api_annotations_delete():
    """Supprime l'annotation d'un article (paramètre ?url=...)."""
    url = (request.args.get("url") or "").strip()
    if not url:
        return jsonify({"error": "Paramètre 'url' obligatoire"}), 400

    with _annotations_lock:
        data = _load_annotations()
        if url not in data:
            return jsonify({"ok": True, "removed": False})
        del data[url]
        _save_annotations(data)

    return jsonify({"ok": True, "removed": True, "url": url})


@entities_bp.route("/api/watched-entities", methods=["GET"])
def api_watched_get():
    """Retourne les entités surveillées avec leur volume de mentions récentes."""
    with _watched_lock:
        watched = _load_watched()

    # Calcul rapide des mentions sur les 7 derniers jours
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    cutoff_7d = now - timedelta(days=7)
    cutoff_24h = now - timedelta(hours=24)

    counts_7d: dict[str, int] = {}
    counts_24h: dict[str, int] = {}

    for data_dir in [PROJECT_ROOT / "data" / "articles", PROJECT_ROOT / "data" / "articles-from-rss"]:
        if not data_dir.exists():
            continue
        for json_file in data_dir.rglob("*.json"):
            if "cache" in str(json_file):
                continue
            try:
                arts = json.loads(json_file.read_text(encoding="utf-8", errors="replace"))
                if not isinstance(arts, list):
                    continue
            except (json.JSONDecodeError, OSError):
                continue
            for art in arts:
                entities = art.get("entities", {})
                if not isinstance(entities, dict):
                    continue
                # Parse date
                date_str = art.get("Date de publication", "")
                art_dt = None
                for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d", "%d/%m/%Y"):
                    try:
                        art_dt = datetime.strptime(date_str[:19], fmt).replace(tzinfo=timezone.utc)
                        break
                    except ValueError:
                        continue
                if art_dt is None:
                    try:
                        from email.utils import parsedate_to_datetime
                        art_dt = parsedate_to_datetime(date_str).astimezone(timezone.utc)
                    except Exception:
                        pass

                for w in watched:
                    vals = entities.get(w["type"], [])
                    _wv_lower = w["value"].lower()
                    if isinstance(vals, list) and any(
                        isinstance(v, str) and v.lower() == _wv_lower for v in vals
                    ):
                        key = f"{w['type']}:{w['value']}"
                        if art_dt and art_dt >= cutoff_7d:
                            counts_7d[key] = counts_7d.get(key, 0) + 1
                        if art_dt and art_dt >= cutoff_24h:
                            counts_24h[key] = counts_24h.get(key, 0) + 1

    result = []
    for w in watched:
        key = f"{w['type']}:{w['value']}"
        result.append({**w, "mentions_7d": counts_7d.get(key, 0), "mentions_24h": counts_24h.get(key, 0)})

    return jsonify(result)


@entities_bp.route("/api/watched-entities", methods=["POST"])
def api_watched_post():
    """Ajoute ou met à jour une entité surveillée.

    Body JSON : { type: str, value: str, notes?: str }
    """
    body = request.get_json(force=True, silent=True) or {}
    etype = (body.get("type") or "").strip().upper()
    value = (body.get("value") or "").strip()
    if not etype or not value:
        return jsonify({"error": "Champs type et value requis"}), 400

    with _watched_lock:
        watched = _load_watched()
        # Mise à jour si déjà présent
        for w in watched:
            if w["type"] == etype and w["value"] == value:
                if "notes" in body:
                    w["notes"] = str(body["notes"])[:500]
                _save_watched(watched)
                return jsonify({"ok": True, "action": "updated"})
        # Ajout
        entry = {
            "type": etype,
            "value": value,
            "added_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
            "notes": str(body.get("notes", ""))[:500],
        }
        watched.append(entry)
        _save_watched(watched)

    return jsonify({"ok": True, "action": "added"})


@entities_bp.route("/api/watched-entities", methods=["DELETE"])
def api_watched_delete():
    """Retire une entité de la surveillance (paramètres ?type=...&value=...)."""
    etype = (request.args.get("type") or "").strip().upper()
    value = (request.args.get("value") or "").strip()
    if not etype or not value:
        return jsonify({"error": "Paramètres type et value requis"}), 400

    with _watched_lock:
        watched = _load_watched()
        before = len(watched)
        watched = [w for w in watched if not (w["type"] == etype and w["value"] == value)]
        _save_watched(watched)

    return jsonify({"ok": True, "removed": len(watched) < before})
