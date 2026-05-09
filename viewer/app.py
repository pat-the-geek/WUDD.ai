"""
WUDD.ai Viewer — Flask backend
Sert l'API de navigation de fichiers et le frontend React compilé.
"""

import os
import socket
import subprocess
import threading
import _strptime  # Pré-charge strptime avant les threads de warm-up.
from pathlib import Path


def _resolve_project_root() -> Path:
    """Résout la racine du dépôt principal, même depuis un worktree git."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            capture_output=True, text=True,
            cwd=Path(__file__).parent,
        )
        if result.returncode == 0:
            git_common = result.stdout.strip()
            git_common_path = Path(git_common)
            if not git_common_path.is_absolute():
                git_common_path = (Path(__file__).parent / git_common_path).resolve()
            return git_common_path.parent
    except Exception:
        pass
    return Path(__file__).resolve().parent.parent


# La racine du projet est toujours celle du dépôt principal (pas d'un worktree)
PROJECT_ROOT = _resolve_project_root()

# Ajouter la racine au sys.path pour que `from utils.X import Y` fonctionne
# quel que soit le répertoire courant au démarrage (cron, Docker, CLI…)
import sys as _sys
if str(PROJECT_ROOT) not in _sys.path:
    _sys.path.insert(0, str(PROJECT_ROOT))

# Charge les variables d'environnement depuis .env (si disponible)
try:
    from dotenv import load_dotenv as _load_dotenv
    _load_dotenv(PROJECT_ROOT / ".env", override=False)
except ImportError:
    pass

from flask import Flask, jsonify, send_from_directory
from utils.metrics import register_metrics_endpoint, register_flask_instrumentation
from utils.openapi import register_openapi_endpoints

_DEFAULT_VIEWER_PORT = 5050

from utils.article_index import get_article_index
from utils.entity_index import get_entity_index

app = Flask(__name__)
app.config["ACTIVE_VIEWER_PORT"] = _DEFAULT_VIEWER_PORT
_startup_rebuild_lock = threading.Lock()
_startup_rebuild_started = False


def _port_is_free(host: str, port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind((host, port))
        return True
    except OSError:
        return False


def _resolve_viewer_port(default_port: int = _DEFAULT_VIEWER_PORT, attempts: int = 10) -> int:
    explicit_port = os.getenv("WUDD_VIEWER_PORT") or os.getenv("PORT")
    if explicit_port:
        try:
            return int(explicit_port)
        except ValueError:
            print(f"[startup] Port invalide ignoré : {explicit_port}", flush=True)

    for port in range(default_port, default_port + attempts):
        if _port_is_free("127.0.0.1", port):
            if port != default_port:
                print(
                    f"[startup] Port {default_port} occupé, bascule automatique sur {port}.",
                    flush=True,
                )
            return port

    raise RuntimeError(
        f"Aucun port libre trouvé entre {default_port} et {default_port + attempts - 1}."
    )

# ── Enregistrement des blueprints ─────────────────────────────────────────────
from viewer.routes.files           import files_bp
from viewer.routes.entities        import entities_bp
from viewer.routes.analytics       import analytics_bp
from viewer.routes.export          import export_bp
from viewer.routes.quota           import quota_bp
from viewer.routes.settings        import settings_bp
from viewer.routes.scheduler       import scheduler_bp
from viewer.routes.contradictions  import contradictions_bp
from viewer.routes.merge           import merge_bp
from viewer.routes.rss_direct      import rss_direct_bp
from viewer.routes.self_learning   import self_learning_bp
from viewer.routes.graph           import graph_bp
from viewer.routes.youtube         import youtube_bp
from viewer.routes.gallery         import gallery_bp
from viewer.routes.auth            import auth_bp

app.register_blueprint(files_bp)
app.register_blueprint(entities_bp)
app.register_blueprint(analytics_bp)
app.register_blueprint(export_bp)
app.register_blueprint(quota_bp)
app.register_blueprint(settings_bp)
app.register_blueprint(scheduler_bp)
app.register_blueprint(contradictions_bp)
app.register_blueprint(merge_bp)
app.register_blueprint(rss_direct_bp)
app.register_blueprint(self_learning_bp)
app.register_blueprint(graph_bp)
app.register_blueprint(youtube_bp)
app.register_blueprint(gallery_bp)
app.register_blueprint(auth_bp)

# ── Métriques Prometheus ──────────────────────────────────────────────────────
register_metrics_endpoint(app)
register_flask_instrumentation(app)

# ── OpenAPI / Swagger UI ──────────────────────────────────────────────────────
register_openapi_endpoints(app)


# ── Rebuild des indexes au démarrage ─────────────────────────────────────────
_INDEX_STALE_HOURS = 24  # Reconstruire si l'index a plus de N heures


def _is_index_stale(generated_at: str) -> bool:
    """Retourne True si generated_at est vide ou daté de plus de _INDEX_STALE_HOURS."""
    if not generated_at:
        return True
    try:
        import datetime as _dt
        ts = _dt.datetime.strptime(generated_at, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=_dt.timezone.utc
        )
        age_h = (_dt.datetime.now(_dt.timezone.utc) - ts).total_seconds() / 3600
        return age_h > _INDEX_STALE_HOURS
    except Exception:
        return True


def _startup_index_rebuild() -> None:
    """Lance en arrière-plan une reconstruction des indexes si nécessaire."""
    def _rebuild():
        try:
            aidx = get_article_index(PROJECT_ROOT)
            eidx = get_entity_index(PROJECT_ROOT)

            a_stats = aidx.stats()
            e_stats = eidx.stats()

            need_article = a_stats.get("total", 0) == 0 or _is_index_stale(
                a_stats.get("generated_at", "")
            )
            need_entity = e_stats.get("entities", 0) == 0 or _is_index_stale(
                e_stats.get("generated_at", "")
            )

            if need_article:
                print("[startup] Reconstruction article_index en cours…", flush=True)
                n = aidx.rebuild()
                print(f"[startup] article_index : {n} articles indexés.", flush=True)
            else:
                print(
                    f"[startup] article_index OK ({a_stats.get('total', 0)} articles, "
                    f"généré le {a_stats.get('generated_at', '?')[:10]})",
                    flush=True,
                )

            if need_entity:
                print("[startup] Reconstruction entity_index en cours…", flush=True)
                n = eidx.rebuild()
                print(f"[startup] entity_index : {n} références indexées.", flush=True)
            else:
                print(
                    f"[startup] entity_index OK ({e_stats.get('entities', 0)} entités, "
                    f"généré le {e_stats.get('generated_at', '?')[:10]})",
                    flush=True,
                )

            try:
                from utils.scoring import get_scoring_engine, precompute_top_articles

                print("[startup] Warm-up scoring engine…", flush=True)
                engine = get_scoring_engine(PROJECT_ROOT)
                snapshot_counts = precompute_top_articles(PROJECT_ROOT, engine=engine, top_n=50)
                rendered = ", ".join(
                    f"{hours}h={count}" for hours, count in sorted(snapshot_counts.items())
                )
                print(f"[startup] top_articles pré-calculés : {rendered}", flush=True)
            except Exception as exc:
                print(f"[startup] Erreur warm-up scoring : {exc}", flush=True)
        except Exception as exc:
            print(f"[startup] Erreur rebuild index : {exc}", flush=True)

    t = threading.Thread(target=_rebuild, daemon=True, name="startup-index-rebuild")
    t.start()


def _ensure_startup_index_rebuild() -> None:
    """Déclenche le warm-up une seule fois, après le fork des workers."""
    global _startup_rebuild_started
    if os.getenv("WUDD_SKIP_STARTUP_REBUILD") == "1":
        return
    if _startup_rebuild_started:
        return
    with _startup_rebuild_lock:
        if _startup_rebuild_started:
            return
        _startup_index_rebuild()
        _startup_rebuild_started = True


@app.before_request
def _lazy_startup_rebuild():
    _ensure_startup_index_rebuild()


@app.route("/api/runtime-info")
def runtime_info():
    return jsonify({
        "viewer_port": app.config.get("ACTIVE_VIEWER_PORT", _DEFAULT_VIEWER_PORT),
        "default_viewer_port": _DEFAULT_VIEWER_PORT,
        "project_root": str(PROJECT_ROOT),
    })


# ── SPA fallback — toutes les routes non-API renvoient index.html ─────────────

@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve_app(path):
    dist = Path(__file__).parent / "dist"
    if not dist.exists():
        return (
            "<h1>Frontend non compilé</h1>"
            "<p>Exécutez <code>npm run build</code> dans le dossier <code>viewer/</code></p>",
            503,
        )
    target = dist / path
    if path and target.exists() and target.is_file():
        return send_from_directory(str(dist), path)
    # SPA fallback : toutes les routes renvoient index.html (sans cache)
    response = send_from_directory(str(dist), "index.html")
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


if __name__ == "__main__":
    port = _resolve_viewer_port()
    app.config["ACTIVE_VIEWER_PORT"] = port
    _ensure_startup_index_rebuild()
    print(f"WUDD.ai Viewer — racine projet : {PROJECT_ROOT}")
    print(f"API disponible sur http://localhost:{port}/api/files")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
