"""
viewer/routes/contradictions.py — Blueprint Flask pour la détection de contradictions.

Routes :
  GET  /api/contradictions              → liste des contradictions sauvegardées
  GET  /api/contradictions/stream       → lance detect_contradictions.py --article <url> en SSE
"""

import json
import os
import subprocess

from flask import Blueprint, jsonify, request, Response, stream_with_context
from pathlib import Path

from viewer.helpers import PROJECT_ROOT

contradictions_bp = Blueprint("contradictions", __name__)


@contradictions_bp.route("/api/contradictions")
def list_contradictions():
    """Retourne les contradictions sauvegardées dans data/contradictions.json.

    Paramètres query optionnels :
      days  (int)  : filtre sur les N derniers jours
      type  (str)  : filtre par type (QUANTITATIVE, FACTUELLE_BINAIRE, etc.)
      limit (int)  : max résultats (défaut 100)
    """
    out_path = PROJECT_ROOT / "data" / "contradictions.json"
    if not out_path.exists():
        return jsonify({"contradictions": [], "total": 0})

    try:
        items = json.loads(out_path.read_text(encoding="utf-8"))
        if not isinstance(items, list):
            items = []
    except Exception:
        return jsonify({"contradictions": [], "total": 0})

    # Filtres
    days = request.args.get("days", type=int)
    ctype = request.args.get("type", "").strip()
    limit = request.args.get("limit", 100, type=int)

    if days:
        from datetime import datetime, timedelta
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        items = [c for c in items if c.get("detected_at", "") >= cutoff]

    if ctype:
        items = [c for c in items if c.get("type_contradiction") == ctype]

    return jsonify({"contradictions": items[:limit], "total": len(items)})


@contradictions_bp.route("/api/contradictions/stream")
def stream_contradiction_analysis():
    """Lance detect_contradictions.py pour un article et stream les logs via SSE.

    Paramètre query :
      url (str) : URL de l'article à analyser (obligatoire)
    """
    article_url = request.args.get("url", "").strip()
    if not article_url:
        return jsonify({"error": "Paramètre 'url' manquant"}), 400

    script = PROJECT_ROOT / "scripts" / "detect_contradictions.py"
    if not script.exists():
        return jsonify({"error": f"Script introuvable : {script}"}), 404

    def generate():
        env = {**os.environ, "PYTHONUNBUFFERED": "1"}
        try:
            proc = subprocess.Popen(
                ["python3", str(script), "--article", article_url],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                cwd=str(PROJECT_ROOT),
                env=env,
            )
        except Exception as exc:
            yield f'data: {json.dumps({"error": str(exc)})}\n\n'
            return

        yield f'data: {json.dumps({"log": f"▶ Démarré (PID {proc.pid})"})}\n\n'

        try:
            for line in proc.stdout:
                stripped = line.rstrip("\n")
                if stripped:
                    yield f'data: {json.dumps({"log": stripped})}\n\n'
        except Exception as exc:
            yield f'data: {json.dumps({"error": str(exc)})}\n\n'

        rc = proc.wait()
        done_msg = "✓ Analyse terminée" if rc == 0 else f"✗ Erreur (code : {rc})"
        yield f'data: {json.dumps({"done": True, "returncode": rc, "log": done_msg})}\n\n'

    return Response(
        stream_with_context(generate()),
        content_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
