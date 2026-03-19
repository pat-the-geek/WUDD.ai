"""
viewer/routes/merge.py — Blueprint Flask pour la fusion d'articles similaires.

Routes :
  POST /api/articles/merge/search   — recherche les articles similaires à un article donné
  POST /api/articles/merge/execute  — exécute la fusion des articles sélectionnés
"""
import json

from flask import Blueprint, jsonify, request, abort
from viewer.helpers import PROJECT_ROOT, safe_path
from viewer.state import _invalidate_bias_cache

merge_bp = Blueprint("merge", __name__)


@merge_bp.route("/api/articles/merge/search", methods=["POST"])
def api_merge_search():
    """Recherche les articles similaires à un article donné.

    Body JSON :
        file_path   (str)   chemin relatif du fichier contenant l'article source
        article_url (str)   URL de l'article source
        days        (int)   fenêtre temporelle en jours (défaut : 7)
        threshold   (float) seuil de score composite (défaut : 0.35)

    Returns :
        { candidates: [{url, source, titre, date, resume_extrait, score,
                        score_entites, score_bigrammes, has_obsidian, file_path}],
          source_url: str }
    """
    data = request.get_json(force=True, silent=True) or {}
    file_path   = data.get("file_path", "").strip()
    article_url = data.get("article_url", "").strip()
    days        = int(data.get("days", 7))
    threshold   = float(data.get("threshold", 0.35))

    if not file_path or not article_url:
        abort(400, "file_path et article_url sont requis")

    # Charger l'article source depuis son fichier
    try:
        fpath    = safe_path(file_path)
        articles = json.loads(fpath.read_text(encoding="utf-8"))
        if not isinstance(articles, list):
            abort(400, "Le fichier ne contient pas un tableau JSON valide")
    except Exception as e:
        abort(400, f"Erreur lecture fichier : {e}")

    source_article = next(
        (a for a in articles if (a.get("URL") or "").strip() == article_url),
        None,
    )
    if source_article is None:
        abort(404, "Article non trouvé dans le fichier spécifié")

    try:
        from utils.article_merger import find_similar
        candidates = find_similar(
            source_article, PROJECT_ROOT, days=days, threshold=threshold
        )
    except Exception as e:
        abort(500, f"Erreur lors de la recherche : {e}")

    results = [
        {
            "url":            c["article"].get("URL", ""),
            "source":         c["article"].get("Sources", ""),
            "titre":          c["article"].get("Titre", ""),
            "date":           c["article"].get("Date de publication", ""),
            "resume_extrait": (c["article"].get("Résumé") or "")[:300],
            "score":          c["score"],
            "score_entites":  c["score_entites"],
            "score_bigrammes":c["score_bigrammes"],
            "has_obsidian":   any(
                r.get("cible") == "obsidian"
                for r in (c["article"].get("rapports") or [])
            ),
            "file_path":      c["file_path"],
        }
        for c in candidates
    ]
    return jsonify({"candidates": results, "source_url": article_url})


@merge_bp.route("/api/articles/merge/execute", methods=["POST"])
def api_merge_execute():
    """Exécute la fusion des articles sélectionnés.

    Body JSON :
        source_url        (str)  URL de l'article depuis lequel la recherche a été lancée
        source_file_path  (str)  chemin relatif du fichier source
        selected          (list) [{url, file_path, score}] — articles secondaires à fusionner
        synthesis         (str)  résumé synthétisé par l'IA (optionnel)

    Returns :
        { ok, primary_source, secondaries_count, archive_path, obsidian_updated }
    """
    data             = request.get_json(force=True, silent=True) or {}
    source_url       = data.get("source_url", "").strip()
    source_file_path = data.get("source_file_path", "").strip()
    selected         = data.get("selected", [])
    synthesis        = data.get("synthesis") or None

    if not source_url or not source_file_path or not selected:
        abort(400, "source_url, source_file_path et selected sont requis")

    # Charger l'article source
    try:
        fpath    = safe_path(source_file_path)
        articles = json.loads(fpath.read_text(encoding="utf-8"))
        source_article = next(
            (a for a in articles if (a.get("URL") or "").strip() == source_url),
            None,
        )
        if source_article is None:
            abort(404, "Article source introuvable dans le fichier")
    except Exception as e:
        abort(400, f"Erreur chargement article source : {e}")

    # Charger chaque article secondaire depuis son fichier
    secondary_articles_with_meta: list[dict] = []
    for item in selected:
        url   = (item.get("url") or "").strip()
        fp    = (item.get("file_path") or "").strip()
        score = float(item.get("score") or 0)
        if not url or not fp:
            continue
        try:
            sfpath   = safe_path(fp)
            sarticles = json.loads(sfpath.read_text(encoding="utf-8"))
            article  = next(
                (a for a in sarticles if (a.get("URL") or "").strip() == url),
                None,
            )
            if article:
                secondary_articles_with_meta.append({
                    "article":   article,
                    "file_path": fp,
                    "score":     score,
                })
        except Exception:
            continue  # article introuvable — ignorer silencieusement

    if not secondary_articles_with_meta:
        abort(400, "Aucun article secondaire valide trouvé parmi les sélections")

    try:
        from utils.article_merger import execute_merge
        result = execute_merge(
            source_article=source_article,
            source_file_path=source_file_path,
            secondary_articles_with_meta=secondary_articles_with_meta,
            project_root=PROJECT_ROOT,
            synthesis=synthesis,
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        abort(500, f"Erreur lors de la fusion : {e}")

    # Invalider le cache analytique (biais éditorial, etc.)
    try:
        _invalidate_bias_cache()
    except Exception:
        pass

    return jsonify({
        "ok":               True,
        "primary_source":   result["primary_source"],
        "secondaries_count":result["secondaries_count"],
        "archive_path":     result["archive_path"],
        "obsidian_updated": result["obsidian_updated"],
    })
