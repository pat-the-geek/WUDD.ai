"""
viewer/routes/analytics.py — Blueprint Flask pour les analytiques et rapports.

Routes :
  GET  /api/articles/top
  GET  /api/alerts
  POST /api/alerts/run
  GET/POST /api/alerts/rules
  GET  /api/sources/bias
  GET  /api/sources/credibility
  GET  /api/synthesize-topic       (streaming SSE)
  GET  /api/cross-flux
  GET  /api/analytics/compare
  GET  /api/analytics/clusters
  POST /api/briefing/generate
  GET  /api/data-quality
"""
import datetime
import json
import os
import sys
import time as _time

from collections import defaultdict, Counter
from flask import Blueprint, jsonify, request, Response, stream_with_context
from pathlib import Path

from viewer.helpers import PROJECT_ROOT
from viewer.state import _bias_cache, _BIAS_CACHE_TTL
from utils.article_index import get_article_index
from utils.entity_index import get_entity_index

analytics_bp = Blueprint("analytics", __name__)


@analytics_bp.route("/api/articles/top")
def api_articles_top():
    """Retourne les N articles les mieux scorés sur une fenêtre temporelle.

    Paramètres :
      n     : nombre d'articles (défaut: 10, max: 50)
      hours : fenêtre en heures (défaut: 48, 0=sans filtre)
    """
    sys.path.insert(0, str(PROJECT_ROOT))
    try:
        from utils.scoring import ScoringEngine
        n = min(int(request.args.get("n", 10)), 50)
        hours = int(request.args.get("hours", 48))
        engine = ScoringEngine(PROJECT_ROOT)
        top = engine.get_top_articles(top_n=n, hours=hours)
        return jsonify(top)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@analytics_bp.route("/api/alerts")
def api_get_alerts():
    """Retourne les alertes de tendance (data/alertes.json).

    Paramètres :
      niveau : filtre par niveau ("critique", "élevé", "modéré")
    """
    alerts_file = PROJECT_ROOT / "data" / "alertes.json"
    if not alerts_file.exists():
        return jsonify([])
    try:
        alerts = json.loads(alerts_file.read_text(encoding="utf-8"))
        niveau = request.args.get("niveau", "").strip()
        if niveau:
            alerts = [a for a in alerts if a.get("niveau") == niveau]
        return jsonify(alerts)
    except (json.JSONDecodeError, OSError) as e:
        return jsonify({"error": str(e)}), 500


@analytics_bp.route("/api/alerts/run", methods=["POST"])
def api_run_trend_detector():
    """Lance le détecteur de tendances et retourne les alertes générées."""
    import subprocess
    script = PROJECT_ROOT / "scripts" / "trend_detector.py"
    if not script.exists():
        return jsonify({"error": "Script trend_detector.py introuvable"}), 404

    data = request.get_json(force=True) or {}
    threshold = float(data.get("threshold", 2.0))
    top = int(data.get("top", 20))

    try:
        result = subprocess.run(
            [sys.executable, str(script), "--threshold", str(threshold), "--top", str(top)],
            capture_output=True, text=True, timeout=120, cwd=str(PROJECT_ROOT)
        )
        alerts_file = PROJECT_ROOT / "data" / "alertes.json"
        alerts = []
        if alerts_file.exists():
            try:
                alerts = json.loads(alerts_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        return jsonify({
            "ok": result.returncode == 0,
            "alerts": alerts,
            "stdout": result.stdout[-2000:] if result.stdout else "",
        })
    except subprocess.TimeoutExpired:
        return jsonify({"error": "Timeout (120s)"}), 504
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@analytics_bp.route("/api/sources/bias")
def api_sources_bias():
    """Agrège les données de sentiment par source pour détecter les biais éditoriaux.

    Résultat mis en cache en mémoire pendant 5 minutes pour éviter les rglob répétés.

    Returns :
      [{ source, article_count, sentiment_counts: {positif, neutre, négatif},
         avg_score_sentiment, avg_score_ton, ton_distribution: {...} }]
    """
    # ── Cache TTL 5 min ───────────────────────────────────────────────────────
    now_ts = _time.time()
    if _bias_cache["data"] is not None and (now_ts - _bias_cache["ts"]) < _BIAS_CACHE_TTL:
        return jsonify(_bias_cache["data"])

    data_dirs = [
        PROJECT_ROOT / "data" / "articles",
        PROJECT_ROOT / "data" / "articles-from-rss",
    ]

    sources: dict[str, dict] = defaultdict(lambda: {
        "article_count": 0,
        "sentiment_counts": {"positif": 0, "neutre": 0, "négatif": 0},
        "score_sentiment_sum": 0,
        "score_ton_sum": 0,
        "score_count": 0,
        "ton_distribution": {},
    })

    for data_dir in data_dirs:
        if not data_dir.exists():
            continue
        for json_file in data_dir.rglob("*.json"):
            if "cache" in str(json_file):
                continue
            try:
                articles = json.loads(json_file.read_text(encoding="utf-8", errors="replace"))
                if not isinstance(articles, list):
                    continue
            except (json.JSONDecodeError, OSError):
                continue
            for article in articles:
                source = article.get("Sources", "Inconnu").strip()
                if not source:
                    continue
                s = sources[source]
                s["article_count"] += 1
                sentiment = article.get("sentiment", "")
                if sentiment in ("positif", "neutre", "négatif"):
                    s["sentiment_counts"][sentiment] += 1
                score_s = article.get("score_sentiment")
                score_t = article.get("score_ton")
                if isinstance(score_s, (int, float)) and isinstance(score_t, (int, float)):
                    s["score_sentiment_sum"] += score_s
                    s["score_ton_sum"] += score_t
                    s["score_count"] += 1
                ton = article.get("ton_editorial", "")
                if ton:
                    s["ton_distribution"][ton] = s["ton_distribution"].get(ton, 0) + 1

    result = []
    for source, data in sources.items():
        count = data["score_count"]
        result.append({
            "source": source,
            "article_count": data["article_count"],
            "sentiment_counts": data["sentiment_counts"],
            "avg_score_sentiment": round(data["score_sentiment_sum"] / count, 2) if count else None,
            "avg_score_ton": round(data["score_ton_sum"] / count, 2) if count else None,
            "ton_distribution": data["ton_distribution"],
        })

    result.sort(key=lambda x: x["article_count"], reverse=True)
    _bias_cache["data"] = result
    _bias_cache["ts"] = now_ts
    return jsonify(result)


@analytics_bp.route("/api/sources/credibility")
def api_sources_credibility():
    """Score de crédibilité des sources.

    Query params :
      source : nom de la source à évaluer (retourne une seule entrée)
               Si absent, retourne toutes les sources de la base
    """
    try:
        from utils.source_credibility import CredibilityEngine
        engine = CredibilityEngine(PROJECT_ROOT)

        source_query = request.args.get("source") or None
        if source_query:
            meta = engine.get_metadata(source_query)
            meta["source"] = source_query
            meta["multiplier"] = engine.get_multiplier(source_query)
            return jsonify(meta)

        # Toutes les sources de la base
        all_sources = []
        for name, entry in engine._db.items():
            all_sources.append({
                "source":     name,
                "score":      entry.get("score", 50),
                "biais":      entry.get("biais", "inconnu"),
                "type":       entry.get("type", "inconnu"),
                "pays":       entry.get("pays", "inconnu"),
                "fiabilite":  entry.get("fiabilite", "non évalué"),
                "multiplier": engine.get_multiplier(name),
            })
        all_sources.sort(key=lambda x: -x["score"])
        return jsonify({"sources": all_sources, "total": len(all_sources)})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@analytics_bp.route("/api/synthesize-topic")
def api_synthesize_topic():
    """Synthèse comparative multi-sources en streaming SSE.

    Paramètres :
      entity_type  : type de l'entité (ex: "ORG")
      entity_value : valeur de l'entité (ex: "OpenAI")
      topic        : sujet libre (alternatif à entity_type+entity_value)
      n            : nombre d'articles à consolider (défaut: 15)
    """
    sys.path.insert(0, str(PROJECT_ROOT))

    entity_type = request.args.get("entity_type", "").strip()
    entity_value = request.args.get("entity_value", "").strip()
    topic = request.args.get("topic", "").strip()
    n = min(int(request.args.get("n", 15)), 30)

    if not topic and not entity_value:
        return jsonify({"error": "Paramètre topic ou entity_value requis"}), 400

    label = topic or entity_value

    # Collecte des articles pertinents
    matching_articles = []
    search_term = (entity_value or topic).lower()

    # Quand entité précise fournie, utiliser l'index (rapide)
    if entity_type and entity_value:
        try:
            eidx = get_entity_index(PROJECT_ROOT)
            matching_articles = eidx.load_articles(entity_type, entity_value)
        except Exception:
            matching_articles = []

    # Si non trouvé via index, ou si recherche par topic libre : fallback rglob
    if not matching_articles:
        for data_dir in [PROJECT_ROOT / "data" / "articles", PROJECT_ROOT / "data" / "articles-from-rss"]:
            if not data_dir.exists():
                continue
            for json_file in sorted(data_dir.rglob("*.json")):
                if "cache" in str(json_file):
                    continue
                try:
                    arts = json.loads(json_file.read_text(encoding="utf-8", errors="replace"))
                    if not isinstance(arts, list):
                        continue
                except (json.JSONDecodeError, OSError):
                    continue
                for article in arts:
                    resume = (article.get("Résumé") or "").lower()
                    entities = article.get("entities", {})
                    entity_match = False
                    if entity_type and entity_value:
                        values = entities.get(entity_type, []) if isinstance(entities, dict) else []
                        _ev_l = entity_value.lower()
                        entity_match = any(
                            isinstance(v, str) and v.lower() == _ev_l for v in values
                        )
                    text_match = search_term in resume
                    if entity_match or text_match:
                        matching_articles.append(article)

    # Déduplication par URL
    seen_urls = set()
    deduped = []
    for a in matching_articles:
        url = a.get("URL", "")
        if url and url in seen_urls:
            continue
        if url:
            seen_urls.add(url)
        deduped.append(a)

    # Tri par date décroissante
    deduped.sort(key=lambda a: a.get("Date de publication", ""), reverse=True)
    articles_to_use = deduped[:n]

    provider = os.environ.get("AI_PROVIDER", "euria").strip().lower()

    if provider == "claude":
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            return jsonify({"error": "ANTHROPIC_API_KEY manquante dans .env (AI_PROVIDER=claude)"}), 503
    else:
        api_url = os.environ.get("URL", "")
        bearer  = os.environ.get("bearer", "")
        if not api_url or not bearer:
            return jsonify({"error": "URL ou bearer manquant dans .env (AI_PROVIDER=euria)"}), 503

    if not articles_to_use:
        def empty_stream():
            msg = f"Aucun article trouvé pour « {label} »."
            yield f'data: {json.dumps({"choices":[{"delta":{"content": msg},"finish_reason":None}]})}\n\n'
            yield "data: [DONE]\n\n"
        return Response(stream_with_context(empty_stream()), content_type="text/event-stream",
                        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # Construire le prompt à partir des articles collectés
    sources_block = ""
    for i, a in enumerate(articles_to_use, 1):
        source = a.get("Sources", "Source inconnue")
        date   = a.get("Date de publication", "")
        resume = (a.get("Résumé") or "")[:600]
        sources_block += f"\n--- Article {i} ({source}, {date}) ---\n{resume}\n"

    prompt = (
        f"Tu es un analyste de presse. Voici {len(articles_to_use)} articles de sources différentes "
        f"traitant du sujet : **{label}**.\n\n"
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

    import requests as req

    if provider == "claude":
        from utils.api_client import ClaudeClient as _ClaudeClient
        _claude = _ClaudeClient(api_key=api_key)

        def generate_synthesis():
            yield from _claude.stream(prompt=prompt, timeout=120)

    else:
        payload = {
            "messages": [{"role": "user", "content": prompt}],
            "model": "qwen3",
            "stream": True,
        }
        api_headers = {
            "Authorization": f"Bearer {bearer}",
            "Content-Type": "application/json",
        }

        def generate_synthesis():
            try:
                r = req.post(api_url, json=payload, headers=api_headers, stream=True, timeout=120)
                r.raise_for_status()
                for line in r.iter_lines():
                    if line:
                        decoded = line.decode("utf-8")
                        if not decoded.startswith("data:"):
                            decoded = "data: " + decoded
                        yield decoded + "\n\n"
            except Exception as exc:
                yield f'data: {json.dumps({"error": str(exc)})}\n\n'

    return Response(
        stream_with_context(generate_synthesis()),
        content_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@analytics_bp.route("/api/alerts/rules", methods=["GET"])
def api_get_alert_rules():
    """Retourne la configuration des règles d'alertes."""
    rules_file = PROJECT_ROOT / "config" / "alert_rules.json"
    if not rules_file.exists():
        return jsonify({"error": "alert_rules.json introuvable"}), 404
    try:
        return jsonify(json.loads(rules_file.read_text(encoding="utf-8")))
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@analytics_bp.route("/api/alerts/rules", methods=["POST"])
def api_save_alert_rules():
    """Sauvegarde la configuration des règles d'alertes."""
    rules_file = PROJECT_ROOT / "config" / "alert_rules.json"
    try:
        data = request.get_json(force=True)
        if not isinstance(data, dict):
            return jsonify({"error": "Données invalides (dict attendu)"}), 400
        rules_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return jsonify({"status": "ok", "message": "Règles d'alertes sauvegardées"})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@analytics_bp.route("/api/cross-flux")
def api_cross_flux():
    """Analyse croisée des flux — entités communes.

    Query params :
      days     : fenêtre temporelle en jours (défaut 30)
      min_flux : nombre minimal de flux (défaut 2)
      top      : nombre d'entités (défaut 30)
    """
    try:
        days      = int(request.args.get("days", 30))
        min_flux  = int(request.args.get("min_flux", 2))
        top_n     = int(request.args.get("top", 30))

        # Essayer d'abord le fichier mis en cache
        cache_file = PROJECT_ROOT / "data" / "cross_flux_report.json"
        if cache_file.exists():
            import time as _t
            age_s = _t.time() - cache_file.stat().st_mtime
            if age_s < 3600:
                data = json.loads(cache_file.read_text(encoding="utf-8"))
                return jsonify(data)

        sys.path.insert(0, str(PROJECT_ROOT))
        from scripts.cross_flux_analysis import collect_entities_by_flux, compute_cross_flux

        flux_entities   = collect_entities_by_flux(PROJECT_ROOT, days=days)
        cross_entities  = compute_cross_flux(flux_entities, min_flux=min_flux, top_n=top_n)

        result = {
            "generated_at":   datetime.datetime.utcnow().isoformat() + "Z",
            "window_days":    days,
            "min_flux":       min_flux,
            "flux_count":     len(flux_entities),
            "flux_list":      sorted(flux_entities.keys()),
            "cross_entities": cross_entities,
        }

        # Mettre en cache
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")

        return jsonify(result)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@analytics_bp.route("/api/briefing/generate", methods=["POST"])
def api_generate_briefing():
    """Génère un briefing exécutif (sans synthèse IA, retourne le Markdown).

    Body JSON :
      period : "daily" (défaut) ou "weekly"
    """
    try:
        body    = request.get_json(force=True) or {}
        period  = body.get("period", "daily")
        if period not in ("daily", "weekly"):
            return jsonify({"error": "period doit être 'daily' ou 'weekly'"}), 400

        sys.path.insert(0, str(PROJECT_ROOT))
        from scripts.generate_briefing import (
            collect_articles, compute_top_entities, load_alerts,
            build_briefing_markdown, _PERIOD_HOURS,
        )
        from utils.scoring import ScoringEngine
        from datetime import timedelta

        hours = _PERIOD_HOURS[period]
        now   = datetime.datetime.utcnow()
        date_fin   = now.strftime("%Y-%m-%d")
        date_debut = (now - timedelta(hours=hours)).strftime("%Y-%m-%d")
        period_label = "hebdomadaire" if period == "weekly" else "quotidien"

        articles     = collect_articles(PROJECT_ROOT, hours=hours)
        engine       = ScoringEngine(PROJECT_ROOT)
        top_articles = engine.score_and_sort(articles, top_n=10)
        top_entities = compute_top_entities(articles, top_n=10)
        alerts       = load_alerts(PROJECT_ROOT)

        md = build_briefing_markdown(
            period_label=period_label,
            date_debut=date_debut,
            date_fin=date_fin,
            articles=articles,
            top_articles=top_articles,
            top_entities=top_entities,
            alerts=alerts,
        )
        return jsonify({
            "period":       period,
            "date_debut":   date_debut,
            "date_fin":     date_fin,
            "articles_count": len(articles),
            "markdown":     md,
        })
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@analytics_bp.route("/api/analytics/compare")
def api_analytics_compare():
    """Compare deux périodes temporelles.

    Paramètres :
      from1, to1 : première période (YYYY-MM-DD)
      from2, to2 : deuxième période (YYYY-MM-DD)
    """
    from1 = request.args.get("from1", "").strip()
    to1   = request.args.get("to1",   "").strip()
    from2 = request.args.get("from2", "").strip()
    to2   = request.args.get("to2",   "").strip()

    if not (from1 and to1 and from2 and to2):
        return jsonify({"error": "Paramètres from1, to1, from2, to2 requis"}), 400

    def _in_range(date_str: str, d_from: str, d_to: str) -> bool:
        d = date_str[:10] if date_str else ""
        return bool(d and d_from <= d <= d_to)

    def _stats(articles):
        if not articles:
            return {"count": 0, "sentiment": {}, "top_sources": [], "top_entities": []}
        sentiments = Counter(a.get("sentiment", "") for a in articles if a.get("sentiment"))
        sources = Counter(a.get("Sources", "") for a in articles if a.get("Sources"))
        entities: dict = defaultdict(Counter)
        for a in articles:
            ents = a.get("entities")
            if not isinstance(ents, dict):
                continue
            for etype, vals in ents.items():
                if isinstance(vals, list):
                    for v in vals:
                        if isinstance(v, str) and v.strip():
                            entities[etype][v.strip()] += 1
        top_entities = []
        for etype, counts in entities.items():
            for val, cnt in counts.most_common(5):
                top_entities.append({"type": etype, "value": val, "count": cnt})
        top_entities.sort(key=lambda x: x["count"], reverse=True)
        return {
            "count": len(articles),
            "sentiment": dict(sentiments),
            "top_sources": [{"source": s, "count": c} for s, c in sources.most_common(5)],
            "top_entities": top_entities[:20],
        }

    # Utiliser l'article_index pour charger uniquement les fichiers contenant
    # des articles dans les deux fenêtres temporelles (évite le scan rglob complet).
    try:
        from utils.article_index import get_article_index as _get_aidx
        _aidx = _get_aidx(PROJECT_ROOT)
        # Déterminer la fenêtre englobante pour une seule requête d'index
        date_min = min(from1, from2)
        date_max = max(to1, to2)
        # Charger les entrées d'index dans la plage globale
        all_entries = [
            e for e in _aidx._data.get("articles", [])
            if date_min <= e.get("date", "") <= date_max
        ] if (_aidx._load() or True) else []
        all_articles = _aidx.load_articles(all_entries)
        index_available = True
    except Exception:
        index_available = False
        all_articles = []

    if not index_available or not all_articles:
        # Fallback : scan complet
        for data_dir in [PROJECT_ROOT / "data" / "articles",
                         PROJECT_ROOT / "data" / "articles-from-rss"]:
            if not data_dir.exists():
                continue
            for json_file in data_dir.rglob("*.json"):
                if "cache" in str(json_file):
                    continue
                try:
                    arts = json.loads(json_file.read_text(encoding="utf-8", errors="replace"))
                    if isinstance(arts, list):
                        all_articles.extend(arts)
                except (json.JSONDecodeError, OSError):
                    continue

    # Déduplication par URL
    seen: set = set()
    deduped = []
    for a in all_articles:
        url = a.get("URL", "")
        if url and url in seen:
            continue
        if url:
            seen.add(url)
        deduped.append(a)

    p1 = [a for a in deduped if _in_range(a.get("Date de publication", ""), from1, to1)]
    p2 = [a for a in deduped if _in_range(a.get("Date de publication", ""), from2, to2)]

    return jsonify({
        "period1": {"from": from1, "to": to1, **_stats(p1)},
        "period2": {"from": from2, "to": to2, **_stats(p2)},
    })


@analytics_bp.route("/api/analytics/clusters")
def api_analytics_clusters():
    """Retourne les clusters thématiques des N derniers jours.

    Query params:
      days      : fenêtre temporelle en jours (défaut 7)
      min_size  : taille minimale d'un cluster (défaut 2)
    """
    days = max(1, min(int(request.args.get("days", 7)), 365))
    min_size = max(1, int(request.args.get("min_size", 2)))

    try:
        sys.path.insert(0, str(PROJECT_ROOT))
        from scripts.cluster_articles import load_articles, cluster_articles

        articles = load_articles(PROJECT_ROOT, days=days)
        clusters = cluster_articles(articles)
        clusters = [c for c in clusters if c["count"] >= min_size]

        return jsonify({
            "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "window_days": days,
            "total_articles": len(articles),
            "clusters": clusters,
        })
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@analytics_bp.route("/api/data-quality")
def api_data_quality():
    """Rapport de qualité des données WUDD.ai.

    Scanne data/articles/ et data/articles-from-rss/ et retourne pour chaque fichier :
      - total       : nombre d'articles
      - sans_resume : articles sans champ Résumé ou résumé vide
      - sans_entites: articles sans champ entities (et statut enrichissement)
      - sans_sentiment : articles sans sentiment
      - echec_api   : articles avec enrichissement_statut = "echec_api"
      - echec_parse : articles avec enrichissement_statut = "echec_parse"
      - sans_image  : articles sans Images ou Images vide
      - sans_date   : articles sans Date de publication

    Paramètres GET :
      dir  : "articles" (défaut) | "rss" | "all" — sous-répertoire à scanner
    """
    dir_filter = request.args.get("dir", "all").strip().lower()

    scan_dirs = []
    if dir_filter in ("articles", "all"):
        scan_dirs.append(PROJECT_ROOT / "data" / "articles")
    if dir_filter in ("rss", "all"):
        scan_dirs.append(PROJECT_ROOT / "data" / "articles-from-rss")

    results = []
    totals = defaultdict(int)

    for scan_dir in scan_dirs:
        if not scan_dir.exists():
            continue
        for json_file in sorted(scan_dir.rglob("*.json")):
            if "cache" in json_file.relative_to(scan_dir).parts:
                continue
            try:
                articles = json.loads(json_file.read_text(encoding="utf-8", errors="replace"))
            except (json.JSONDecodeError, OSError):
                continue
            if not isinstance(articles, list) or not articles:
                continue

            stats = {
                "total": len(articles),
                "sans_resume": 0,
                "sans_entites": 0,
                "sans_sentiment": 0,
                "echec_api": 0,
                "echec_parse": 0,
                "sans_image": 0,
                "sans_date": 0,
            }
            for a in articles:
                if not isinstance(a, dict):
                    continue
                resume = a.get("Résumé", "")
                if not resume or not str(resume).strip():
                    stats["sans_resume"] += 1
                if not a.get("entities"):
                    stats["sans_entites"] += 1
                if not a.get("sentiment"):
                    stats["sans_sentiment"] += 1
                statut = a.get("enrichissement_statut", "")
                if statut == "echec_api":
                    stats["echec_api"] += 1
                elif statut == "echec_parse":
                    stats["echec_parse"] += 1
                images = a.get("Images", [])
                if not images:
                    stats["sans_image"] += 1
                if not a.get("Date de publication", ""):
                    stats["sans_date"] += 1

            rel = str(json_file.relative_to(PROJECT_ROOT)).replace("\\", "/")
            # Score qualité 0–100 : pénalise les articles incomplets
            pct_ok = round(
                100 * (1 - (stats["sans_resume"] + stats["sans_entites"]) / (2 * stats["total"])),
                1,
            ) if stats["total"] > 0 else 100.0

            results.append({
                "file": rel,
                "quality_score": pct_ok,
                **stats,
            })
            for k, v in stats.items():
                totals[k] += v

    results.sort(key=lambda r: r.get("quality_score", 100))

    return jsonify({
        "files": results,
        "totals": dict(totals),
        "file_count": len(results),
    })
