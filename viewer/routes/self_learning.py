"""
viewer/routes/self_learning.py — API REST pour le système auto-apprenant

Endpoints :
  POST /api/engagement            Enregistre un signal d'engagement
  GET  /api/engagement/stats      Statistiques d'engagement

  GET  /api/quality/stats         Statistiques de qualité des articles
  POST /api/quality/update        Recalcule les scores de qualité (async)

  POST /api/contradiction/feedback  Enregistre un retour sur contradiction
  GET  /api/contradiction/stats     Statistiques du feedback contradictions
  POST /api/contradiction/calibrate Calibre les seuils (dry-run ou réel)

  GET  /api/self-learning/status   Résumé de l'état du système auto-apprenant
"""

import threading
from pathlib import Path

from flask import Blueprint, jsonify, request

self_learning_bp = Blueprint("self_learning", __name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


# ── Engagement ────────────────────────────────────────────────────────────────

@self_learning_bp.route("/api/engagement", methods=["POST"])
def record_engagement():
    """Enregistre un signal d'engagement implicite.

    Body JSON :
      {
        "signal_type"  : "article_opened",      (obligatoire)
        "url"          : "https://...",          (optionnel)
        "source"       : "Le Monde",             (optionnel)
        "keyword"      : "intelligence-artificielle", (optionnel)
        "entities"     : ["Emmanuel Macron"],    (optionnel)
        "alert_entity" : "PERSON:Jean Dupont"    (optionnel, pour alert_dismissed)
      }
    """
    data = request.get_json(silent=True) or {}
    signal_type = data.get("signal_type")

    if not signal_type:
        return jsonify({"error": "signal_type requis"}), 400

    try:
        from utils.engagement_tracker import get_engagement_tracker, SIGNAL_WEIGHTS
        if signal_type not in SIGNAL_WEIGHTS:
            return jsonify({"error": f"signal_type inconnu : {signal_type}"}), 400

        tracker = get_engagement_tracker()
        tracker.record(
            signal_type=signal_type,
            url=data.get("url"),
            source=data.get("source"),
            keyword=data.get("keyword"),
            entities=data.get("entities"),
            alert_entity=data.get("alert_entity"),
        )

        # Si alerte ignorée → notifier aussi le calibrateur
        if signal_type == "alert_dismissed" and data.get("alert_entity"):
            try:
                from utils.alert_calibrator import mark_dismissed
                mark_dismissed(data["alert_entity"])
            except Exception:
                pass

        return jsonify({"ok": True, "signal": signal_type}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@self_learning_bp.route("/api/engagement/stats", methods=["GET"])
def engagement_stats():
    """Retourne les statistiques d'engagement."""
    try:
        from utils.engagement_tracker import get_engagement_tracker
        tracker = get_engagement_tracker()
        return jsonify(tracker.get_stats()), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Qualité ───────────────────────────────────────────────────────────────────

@self_learning_bp.route("/api/quality/stats", methods=["GET"])
def quality_stats():
    """Retourne les statistiques de qualité des articles depuis l'index."""
    try:
        from utils.quality_monitor import get_quality_stats
        stats = get_quality_stats(project_root=_PROJECT_ROOT)
        return jsonify(stats), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@self_learning_bp.route("/api/quality/update", methods=["POST"])
def quality_update():
    """Recalcule les scores de qualité (s'exécute en arrière-plan).

    Body JSON : { "dry_run": false }
    """
    data = request.get_json(silent=True) or {}
    dry_run = bool(data.get("dry_run", False))

    def _run():
        from utils.quality_monitor import update_quality_scores
        update_quality_scores(project_root=_PROJECT_ROOT, dry_run=dry_run)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return jsonify({"ok": True, "message": "Mise à jour des scores de qualité lancée en arrière-plan"}), 202


# ── Contradiction feedback ────────────────────────────────────────────────────

@self_learning_bp.route("/api/contradiction/feedback", methods=["POST"])
def contradiction_feedback():
    """Enregistre un retour utilisateur sur une contradiction.

    Body JSON :
      {
        "contradiction_type" : "CHIFFRE",
        "action"             : "confirmed",    // ou "rejected"
        "description"        : "...",
        "confidence"         : 0.72,
        "article_url"        : "https://..."
      }
    """
    data = request.get_json(silent=True) or {}
    ctype  = data.get("contradiction_type", "AUTRE")
    action = data.get("action")

    if action not in ("confirmed", "rejected"):
        return jsonify({"error": "action doit être 'confirmed' ou 'rejected'"}), 400

    try:
        from utils.contradiction_feedback import get_contradiction_feedback
        fb = get_contradiction_feedback()
        fb.record(
            contradiction_type=ctype,
            action=action,
            description=data.get("description"),
            confidence=data.get("confidence"),
            article_url=data.get("article_url"),
        )
        return jsonify({"ok": True, "action": action, "type": ctype}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@self_learning_bp.route("/api/contradiction/stats", methods=["GET"])
def contradiction_stats():
    """Retourne les statistiques du feedback contradictions."""
    try:
        from utils.contradiction_feedback import get_contradiction_feedback
        fb = get_contradiction_feedback()
        return jsonify(fb.get_stats()), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@self_learning_bp.route("/api/contradiction/calibrate", methods=["POST"])
def contradiction_calibrate():
    """Lance une calibration des seuils de confiance.

    Body JSON : { "dry_run": true }
    """
    data = request.get_json(silent=True) or {}
    dry_run = bool(data.get("dry_run", True))

    try:
        from utils.contradiction_feedback import get_contradiction_feedback
        fb = get_contradiction_feedback()
        result = fb.calibrate(dry_run=dry_run)
        return jsonify(result), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Tableau de bord global ────────────────────────────────────────────────────

@self_learning_bp.route("/api/self-learning/status", methods=["GET"])
def self_learning_status():
    """Retourne l'état global du système auto-apprenant."""
    status: dict = {}

    # Engagement
    try:
        from utils.engagement_tracker import get_engagement_tracker
        stats = get_engagement_tracker().get_stats()
        status["engagement"] = {
            "total_articles_tracked": stats["total_articles_tracked"],
            "total_signals_today": stats.get("daily_activity", {}).get(
                __import__("datetime").date.today().isoformat(), {}
            ).get("signals", 0),
            "updated_at": stats.get("updated_at", ""),
        }
    except Exception:
        status["engagement"] = {"error": "indisponible"}

    # Poids de scoring
    try:
        from utils.scoring_optimizer import load_weights
        status["scoring_weights"] = load_weights()
    except Exception:
        status["scoring_weights"] = {"error": "indisponible"}

    # Qualité
    try:
        from utils.quality_monitor import get_quality_stats
        q = get_quality_stats(project_root=_PROJECT_ROOT)
        status["quality"] = {
            "avg_score":     q.get("avg_score", 0),
            "pct_complete":  q.get("pct_complete", 0),
            "repair_needed": q.get("repair_needed", 0),
        }
    except Exception:
        status["quality"] = {"error": "indisponible"}

    # Feedback contradictions
    try:
        from utils.contradiction_feedback import get_contradiction_feedback
        cf = get_contradiction_feedback().get_stats()
        status["contradiction_feedback"] = {
            "total_feedback": cf["total_feedback"],
            "global_precision": cf.get("global_precision"),
        }
    except Exception:
        status["contradiction_feedback"] = {"error": "indisponible"}

    # Historique quota
    history_dir = _PROJECT_ROOT / "data" / "quota_history"
    status["quota_history_days"] = len(list(history_dir.glob("*.json"))) if history_dir.exists() else 0

    return jsonify(status), 200
