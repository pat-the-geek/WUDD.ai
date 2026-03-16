"""
viewer/routes/files.py — Blueprint Flask pour la gestion des fichiers.

Routes :
  GET/DELETE /api/files
  GET/POST   /api/content
  GET        /api/stream-content
  GET        /api/download
  GET        /api/search
  POST       /api/article/refresh-resume
  GET        /api/article/full-report
"""
import json
import os
import re
import time

from flask import Blueprint, jsonify, request, abort, send_file, Response, stream_with_context
from pathlib import Path

from viewer.helpers import safe_path, collect_files, PROJECT_ROOT
from viewer.state import _invalidate_bias_cache

files_bp = Blueprint("files", __name__)


@files_bp.route("/api/files")
def api_files():
    # Double scan pour compenser les listings incomplets de virtiofs
    # (Docker Desktop / macOS) : rglob() peut retourner un résultat partiel
    # si le cache kernel est rafraîchi entre les deux appels.
    files1 = collect_files()
    time.sleep(0.20)
    files2 = collect_files()
    # Union des deux passes — chaque chemin vu dans l'une ou l'autre est retenu ;
    # la seconde passe écrase les métadonnées de la première si les deux la voient.
    by_path = {f["path"]: f for f in files1}
    by_path.update({f["path"]: f for f in files2})
    files = sorted(by_path.values(), key=lambda x: x["modified"], reverse=True)
    return jsonify(files)


@files_bp.route("/api/content")
def api_content():
    path = request.args.get("path", "")
    if not path:
        abort(400)
    f = safe_path(path)
    return jsonify({"path": path, "content": f.read_text(encoding="utf-8", errors="replace")})


@files_bp.route("/api/stream-content")
def api_stream_content():
    """Diffuse le contenu d'un fichier en streaming pour une meilleure réactivité."""
    path = request.args.get("path", "")
    if not path:
        abort(400)
    f = safe_path(path)
    file_size = f.stat().st_size

    def generate():
        with open(f, "rb") as fh:
            while True:
                chunk = fh.read(16384)  # 16 Ko par chunk
                if not chunk:
                    break
                yield chunk

    return Response(
        stream_with_context(generate()),
        mimetype="text/plain; charset=utf-8",
        headers={
            "X-File-Size": str(file_size),
            "Cache-Control": "no-cache",
        },
    )


@files_bp.route("/api/content", methods=["POST"])
def api_save_content():
    data = request.get_json(force=True)
    if not data or "path" not in data or "content" not in data:
        abort(400, "Champs 'path' et 'content' requis")
    rel = data["path"]
    # Restriction : uniquement data/ et config/ sont modifiables
    if not (rel.startswith("data/") or rel.startswith("config/")):
        abort(403, "Modification non autorisée hors de data/ et config/")
    target = (PROJECT_ROOT / rel).resolve()
    if not str(target).startswith(str(PROJECT_ROOT) + "/"):
        abort(403, "Accès refusé")
    if not target.exists():
        abort(404, "Fichier non trouvé")
    # Validation JSON si extension .json
    content = data["content"]
    if target.suffix == ".json":
        try:
            json.loads(content)
        except json.JSONDecodeError as e:
            abort(400, f"JSON invalide : {e}")
    try:
        target.write_text(content, encoding="utf-8")
    except OSError as e:
        abort(500, f"Erreur d'écriture : {e}")
    # Invalider le cache biais si un fichier JSON de data/ est modifié
    if rel.startswith("data/") and target.suffix == ".json":
        _invalidate_bias_cache()
    return jsonify({"ok": True})


@files_bp.route("/api/search")
def api_search():
    """Recherche textuelle avec filtres optionnels.

    Paramètres :
      q          : texte à chercher (min 2 chars)
      type       : "json" ou "markdown" (filtre type de fichier)
      sentiment  : "positif", "neutre", "négatif" (filtre sur articles JSON)
      source     : nom de source (filtre partiel, insensible à la casse)
      date_from  : YYYY-MM-DD (articles publiés à partir de cette date)
      date_to    : YYYY-MM-DD (articles publiés jusqu'à cette date)
    """
    q = request.args.get("q", "").strip()
    if len(q) < 2:
        return jsonify([])

    filter_type      = request.args.get("type", "").strip().lower()
    filter_sentiment = request.args.get("sentiment", "").strip().lower()
    filter_source    = request.args.get("source", "").strip().lower()
    filter_from      = request.args.get("date_from", "").strip()
    filter_to        = request.args.get("date_to", "").strip()

    has_article_filters = bool(filter_sentiment or filter_source or filter_from or filter_to)

    pattern = re.compile(re.escape(q), re.IGNORECASE)
    results = []

    for info in collect_files():
        # Filtre par type de fichier
        if filter_type and info["type"] != filter_type:
            continue

        f = PROJECT_ROOT / info["path"]

        # Pour les filtres article, on parse le JSON et applique les filtres
        if has_article_filters and info["type"] == "json":
            try:
                articles = json.loads(f.read_text(encoding="utf-8", errors="replace"))
                if not isinstance(articles, list):
                    continue
            except (json.JSONDecodeError, OSError):
                continue

            # Filtrer les articles selon les critères
            filtered = []
            for art in articles:
                if filter_sentiment and art.get("sentiment", "").lower() != filter_sentiment:
                    continue
                if filter_source:
                    src = art.get("Sources", "").lower()
                    if filter_source not in src:
                        continue
                date_str = art.get("Date de publication", "")[:10]
                if filter_from and date_str and date_str < filter_from:
                    continue
                if filter_to and date_str and date_str > filter_to:
                    continue
                # Vérifier si la requête textuelle matche
                resume = art.get("Résumé", "") or ""
                if pattern.search(resume) or pattern.search(art.get("URL", "") or "") or pattern.search(art.get("Sources", "") or ""):
                    filtered.append(art)

            if not filtered:
                continue

            matches = [
                {"line": 0, "text": f"{art.get('Sources','')} · {art.get('Date de publication','')[:10]} — {(art.get('Résumé','') or '')[:150]}"}
                for art in filtered[:5]
            ]
            results.append({**info, "matches": matches, "article_count": len(filtered)})

        else:
            # Recherche ligne par ligne (fichiers Markdown ou JSON sans filtres article)
            try:
                lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
                matches = [
                    {"line": i + 1, "text": line.strip()[:200]}
                    for i, line in enumerate(lines)
                    if pattern.search(line)
                ]
                if matches:
                    results.append({**info, "matches": matches[:5]})
            except OSError:
                continue

    return jsonify(results)


@files_bp.route("/api/download")
def api_download():
    path = request.args.get("path", "")
    if not path:
        abort(400)
    f = safe_path(path)
    return send_file(f, as_attachment=True, download_name=f.name)


@files_bp.route("/api/files", methods=["DELETE"])
def api_delete_file():
    """Supprime un fichier de data/ ou rapports/ (avec validation de sécurité)."""
    rel = request.args.get("path", "").strip()
    if not rel:
        abort(400, "Paramètre path requis")
    if not (rel.startswith("data/") or rel.startswith("rapports/")):
        abort(403, "Suppression non autorisée hors de data/ et rapports/")
    target = (PROJECT_ROOT / rel).resolve()
    if not str(target).startswith(str(PROJECT_ROOT) + "/"):
        abort(403, "Accès refusé")
    if not target.exists():
        abort(404, "Fichier non trouvé")
    try:
        target.unlink()
    except OSError as exc:
        abort(500, f"Erreur de suppression : {exc}")
    # Invalider le cache biais si un fichier JSON de data/ est supprimé
    if rel.startswith("data/") and target.suffix == ".json":
        _invalidate_bias_cache()
    return jsonify({"ok": True, "deleted": rel})


@files_bp.route("/api/article/refresh-resume", methods=["POST"])
def api_article_refresh_resume():
    """Régénère le résumé d'un article via l'IA choisie et met à jour le fichier JSON.

    Body JSON :
      file_path   (str) — chemin relatif du fichier JSON dans PROJECT_ROOT
      article_url (str) — URL de l'article à rafraîchir
      provider    (str) — 'euria', 'claude', ou 'auto' (utilise AI_PROVIDER depuis .env)
    Retourne : { ok: bool, resume: str }
    """
    body = request.get_json(force=True, silent=True) or {}
    rel_path = (body.get("file_path") or "").strip()
    article_url = (body.get("article_url") or "").strip()
    provider = (body.get("provider") or "auto").strip().lower()

    if not rel_path or not article_url:
        return jsonify({"error": "file_path et article_url sont requis"}), 400

    # Validation du chemin — uniquement data/ et articles-from-rss/
    if not (rel_path.startswith("data/") or rel_path.startswith("samples/")):
        return jsonify({"error": "Chemin non autorisé"}), 403

    target = (PROJECT_ROOT / rel_path).resolve()
    if not str(target).startswith(str(PROJECT_ROOT) + "/"):
        return jsonify({"error": "Accès refusé"}), 403
    if not target.exists():
        return jsonify({"error": "Fichier non trouvé"}), 404

    try:
        articles = json.loads(target.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        return jsonify({"error": f"Lecture impossible : {e}"}), 500

    # Trouver l'article par URL
    article = next((a for a in articles if a.get("URL") == article_url), None)
    if article is None:
        return jsonify({"error": "Article non trouvé dans le fichier"}), 404

    # Récupérer le texte source : tenter de re-fetcher l'article original depuis son URL,
    # fallback sur le résumé existant (re-résumer un résumé dégrade la qualité mais reste utile).
    source_text = ""
    original_url = article.get("URL", "").strip()
    if original_url:
        try:
            import requests as _req
            from bs4 import BeautifulSoup as _BS
            resp = _req.get(original_url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
            resp.raise_for_status()
            soup = _BS(resp.text, "html.parser")
            for tag in soup(["script", "style", "nav", "footer", "header"]):
                tag.decompose()
            source_text = " ".join(soup.get_text(separator=" ").split())[:15000]
        except Exception:
            pass  # fallback ci-dessous
    if not source_text.strip():
        source_text = article.get("Résumé") or article.get("Titre") or ""
    if not source_text.strip():
        return jsonify({"error": "Aucun texte source disponible pour générer un résumé"}), 400

    # Sélectionner le client IA
    try:
        from utils.api_client import EurIAClient, ClaudeClient
        if provider == "auto":
            provider = os.environ.get("AI_PROVIDER", "euria").strip().lower()

        if provider == "claude":
            api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
            if not api_key:
                return jsonify({"error": "ANTHROPIC_API_KEY non configurée"}), 400
            client = ClaudeClient(api_key=api_key)
        else:
            url_env = os.environ.get("URL", "").strip()
            bearer = os.environ.get("bearer", "").strip()
            if not url_env or not bearer:
                return jsonify({"error": "URL ou bearer non configuré"}), 400
            client = EurIAClient(url=url_env, bearer=bearer)

        new_resume = client.generate_summary(source_text)
    except Exception as exc:
        return jsonify({"error": f"Erreur IA : {exc}"}), 500

    # Mettre à jour le fichier JSON
    article["Résumé"] = new_resume
    try:
        tmp = target.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(articles, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(target)
    except OSError as e:
        return jsonify({"error": f"Erreur écriture : {e}"}), 500

    return jsonify({"ok": True, "resume": new_resume})


@files_bp.route("/api/article/full-report")
def api_article_full_report():
    """Génère en streaming un rapport complet approfondi sur un article.

    Paramètres GET :
      url        — URL de l'article source (fetch HTML + extraction texte)
      titre      — Titre de l'article
      sources    — Source / média
      date       — Date de publication
      resume     — Résumé existant (fallback si URL inaccessible ou derrière paywall)
      entities   — JSON dict {TYPE: [valeur, …]}
      sentiment  — Sentiment (positif/neutre/négatif)
      ton        — Ton éditorial
      image_url  — URL de l'image principale de l'article

    Retourne un flux SSE (text/event-stream) identique au format EurIA / OpenAI.
    """
    import requests as _req
    from bs4 import BeautifulSoup as _BS

    url         = request.args.get("url",        "").strip()
    titre       = request.args.get("titre",      "").strip()
    sources     = request.args.get("sources",    "").strip()
    date        = request.args.get("date",       "").strip()
    resume_ex   = request.args.get("resume",     "").strip()
    entities_js = request.args.get("entities",   "{}").strip()
    sentiment   = request.args.get("sentiment",  "").strip()
    ton         = request.args.get("ton",        "").strip()
    image_url   = request.args.get("image_url",  "").strip()

    try:
        entities = json.loads(entities_js)
    except (json.JSONDecodeError, ValueError):
        entities = {}

    if not url and not resume_ex:
        return jsonify({"error": "url ou resume requis"}), 400

    # ── 1. Fetch article content from URL ─────────────────────────────────────
    source_text = ""
    url_ok = False
    if url:
        try:
            resp = _req.get(
                url, timeout=15,
                headers={"User-Agent": "Mozilla/5.0 (compatible; WUDD-bot/1.0)"},
            )
            resp.raise_for_status()
            soup = _BS(resp.text, "html.parser")
            for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
                tag.decompose()
            source_text = " ".join(soup.get_text(separator=" ").split())[:20000]
            url_ok = bool(source_text.strip())
        except Exception:
            pass  # fallback on resume below

    if not source_text.strip():
        source_text = resume_ex
    if not source_text.strip():
        return jsonify({"error": "Aucun texte source disponible (URL inaccessible et résumé absent)"}), 400

    # ── 2. Entity context for the prompt ─────────────────────────────────────
    entity_lines = []
    for etype, vals in entities.items():
        if isinstance(vals, list) and vals:
            entity_lines.append(f"  - {etype} : {', '.join(str(v) for v in vals[:10])}")
    entity_context = "\n".join(entity_lines) if entity_lines else "  Aucune entité extraite."

    # ── 3. Metadata string ────────────────────────────────────────────────────
    meta_parts = []
    if titre:     meta_parts.append(f"Titre : {titre}")
    if sources:   meta_parts.append(f"Source : {sources}")
    if date:      meta_parts.append(f"Date : {date}")
    if sentiment: meta_parts.append(f"Sentiment : {sentiment}")
    if ton:       meta_parts.append(f"Ton éditorial : {ton}")
    meta_str = "\n".join(meta_parts) or "(non renseigné)"

    source_label = "texte complet de l'article" if url_ok else "résumé de l'article"
    image_md = f"![Image principale]({image_url})\n\n" if image_url else ""
    source_link = f"[{url}]({url})" if url else "(non disponible)"

    # ── 4. Prompt ─────────────────────────────────────────────────────────────
    prompt = (
        f"Tu es un analyste en intelligence médiatique. "
        f"À partir du {source_label} ci-dessous, génère un **rapport approfondi en Markdown** en français.\n\n"
        f"## Métadonnées\n{meta_str}\n\n"
        f"## Entités nommées détectées\n{entity_context}\n\n"
        f"## {source_label.capitalize()}\n{source_text}\n\n"
        "---\n\n"
        "Génère un rapport complet en Markdown français avec ces sections dans l'ordre :\n"
        f"1. Titre H1{(' + ' + image_md.strip()) if image_url else ''} + métadonnées (source · date) + accroche\n"
        "2. ## Contexte et enjeux — 2-4 paragraphes, **entités en gras**\n"
        "3. ## Analyse détaillée — sous-sections H3, **entités en gras**, faits et chiffres\n"
        "4. ## Acteurs impliqués — tableau | Entité | Type | Rôle |\n"
        "5. ## Diagrammes (si données disponibles) — Mermaid timeline/graph/xychart. "
        "⚠️ Labels Mermaid : sans accents (e=é,a=à,c=ç,u=ù), espaces entre guillemets [\"label\"]\n"
        "6. ## Points clés — 4-7 bullets + conclusion\n"
        f"7. ## Source — {source_link}\n\n"
        "Règles : Markdown uniquement, pas de balises <think>, développe chaque section au maximum."
    )

    # ── 5. Stream via EurIA or Claude ─────────────────────────────────────────
    provider = os.environ.get("AI_PROVIDER", "euria").strip().lower()

    if provider == "claude":
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            return jsonify({"error": "ANTHROPIC_API_KEY manquante dans .env (AI_PROVIDER=claude)"}), 503
        from utils.api_client import ClaudeClient as _CC
        _claude = _CC(api_key=api_key)

        def generate():
            yield from _claude.stream(prompt=prompt, max_tokens=16000, timeout=300)

    else:
        api_url = os.environ.get("URL", "")
        bearer  = os.environ.get("bearer", "")
        if not api_url or not bearer:
            return jsonify({"error": "URL ou bearer manquant dans .env (AI_PROVIDER=euria)"}), 503
        payload = {
            "messages":        [{"role": "user", "content": prompt}],
            "model":           "qwen3",
            "stream":          True,
            "max_tokens":      16000,
            "enable_thinking": False,
        }
        api_headers = {
            "Authorization": f"Bearer {bearer}",
            "Content-Type":  "application/json",
        }

        def generate():
            try:
                r = _req.post(
                    api_url, json=payload, headers=api_headers,
                    stream=True, timeout=300,
                )
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
