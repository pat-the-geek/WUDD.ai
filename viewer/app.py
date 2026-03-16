"""
WUDD.ai Viewer — Flask backend
Sert l'API de navigation de fichiers et le frontend React compilé.
"""

import threading
from pathlib import Path

# Charge les variables d'environnement depuis .env (si disponible)
try:
    from dotenv import load_dotenv as _load_dotenv
    _load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)
except ImportError:
    pass

# La racine du projet est le dossier parent de viewer/
# resolve() AVANT parent.parent : __file__ peut être un chemin relatif
# ('app.py') quand Flask est lancé via `python3 app.py` depuis viewer/,
# auquel que (Path('app.py').parent.parent).resolve() → cwd au lieu de la racine.
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Ajouter la racine au sys.path pour que `from utils.X import Y` fonctionne
# quel que soit le répertoire courant au démarrage (cron, Docker, CLI…)
import sys as _sys
if str(PROJECT_ROOT) not in _sys.path:
    _sys.path.insert(0, str(PROJECT_ROOT))

from flask import Flask, send_from_directory

from utils.article_index import get_article_index
from utils.entity_index import get_entity_index

app = Flask(__name__)

# ── Enregistrement des blueprints ─────────────────────────────────────────────
from viewer.routes.files     import files_bp
from viewer.routes.entities  import entities_bp
from viewer.routes.analytics import analytics_bp
from viewer.routes.export    import export_bp
from viewer.routes.quota     import quota_bp
from viewer.routes.settings  import settings_bp
from viewer.routes.scheduler import scheduler_bp

app.register_blueprint(files_bp)
app.register_blueprint(entities_bp)
app.register_blueprint(analytics_bp)
app.register_blueprint(export_bp)
app.register_blueprint(quota_bp)
app.register_blueprint(settings_bp)
app.register_blueprint(scheduler_bp)


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

            need_article = a_stats.get("count", 0) == 0 or _is_index_stale(
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
                    f"[startup] article_index OK ({a_stats.get('count', 0)} articles, "
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
        except Exception as exc:
            print(f"[startup] Erreur rebuild index : {exc}", flush=True)

    t = threading.Thread(target=_rebuild, daemon=True, name="startup-index-rebuild")
    t.start()


# Lancer la vérification des indexes dès le chargement du module
_startup_index_rebuild()


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
    print(f"WUDD.ai Viewer — racine projet : {PROJECT_ROOT}")
    print("API disponible sur http://localhost:5050/api/files")
    app.run(host="0.0.0.0", port=5050, debug=False, threaded=True)
