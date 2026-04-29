"""
viewer/routes/quota.py — Blueprint Flask pour la gestion des quotas.

Routes :
  GET/POST /api/quota/config
  GET      /api/quota/stats
  POST     /api/quota/reset
"""
from flask import Blueprint, jsonify, request, abort

quota_bp = Blueprint("quota", __name__)


@quota_bp.route("/api/quota/config", methods=["GET"])
def api_get_quota_config():
    """Retourne la configuration des quotas (config/quota.json)."""
    from utils.quota import get_quota_manager, DEFAULT_CONFIG
    mgr = get_quota_manager()
    # Retourner la config avec les valeurs par défaut en fallback
    cfg = {**DEFAULT_CONFIG, **mgr._config}
    return jsonify(cfg)


@quota_bp.route("/api/quota/config", methods=["POST"])
def api_save_quota_config():
    """Sauvegarde la configuration des quotas."""
    from utils.quota import get_quota_manager
    data = request.get_json(force=True)
    if not isinstance(data, dict):
        abort(400, "Format invalide : objet attendu")
    # Validation basique des types
    for int_key in ("global_daily_limit", "per_keyword_daily_limit", "per_source_daily_limit",
                    "per_entity_daily_limit", "per_run_limit", "global_source_daily_limit",
                    "summary_max_lines"):
        if int_key in data:
            try:
                data[int_key] = max(0, int(data[int_key]))
            except (ValueError, TypeError):
                abort(400, f"Valeur invalide pour {int_key}")
    # Validation de la liste des types d'entités ignorés
    if "ignored_entity_types" in data:
        if not isinstance(data["ignored_entity_types"], list):
            abort(400, "ignored_entity_types doit être une liste")
        data["ignored_entity_types"] = [str(t).upper() for t in data["ignored_entity_types"]]
    get_quota_manager().save_config(data)
    # Invalider le singleton Config pour que summary_max_lines soit rechargé
    try:
        from utils.config import get_config as _get_config
        _get_config(force_reload=True)
    except Exception:
        pass
    return jsonify({"ok": True})


@quota_bp.route("/api/quota/stats", methods=["GET"])
def api_get_quota_stats():
    """Retourne les statistiques de consommation du jour."""
    from utils.quota import get_quota_manager
    top_keywords = request.args.get("top_keywords", default=25, type=int)
    top_sources = request.args.get("top_sources", default=5, type=int)
    top_entities = request.args.get("top_entities", default=20, type=int)
    top_global_sources = request.args.get("top_global_sources", default=20, type=int)
    return jsonify(
        get_quota_manager().get_stats(
            top_keywords=top_keywords,
            top_sources_per_keyword=top_sources,
            top_entities=top_entities,
            top_global_sources=top_global_sources,
        )
    )


@quota_bp.route("/api/quota/reset", methods=["POST"])
def api_reset_quota():
    """Réinitialise les compteurs de quota du jour."""
    from utils.quota import get_quota_manager
    get_quota_manager().reset_day()
    return jsonify({"ok": True})
