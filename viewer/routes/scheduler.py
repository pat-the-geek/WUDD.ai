"""
viewer/routes/scheduler.py — Blueprint Flask pour le scheduler et les scripts.

Routes :
  GET /api/scheduler
  GET /api/scripts/keyword-rss/status
  GET /api/scripts/keyword-rss/stream
"""
import datetime
import json
import os
import subprocess

from flask import Blueprint, jsonify, request, Response, stream_with_context
from pathlib import Path

from viewer.helpers import (
    PROJECT_ROOT, latest_mtime, next_cron_occurrence, cron_label
)
from viewer.state import _rss_job

scheduler_bp = Blueprint("scheduler", __name__)


@scheduler_bp.route("/api/scheduler")
def api_scheduler():
    now = datetime.datetime.now()
    tasks = []

    # Lire l'état du flux_watcher pour afficher le flux en cours de traitement
    flux_watcher_state_file = PROJECT_ROOT / "data" / "flux_watcher_state.json"
    flux_watcher_detail = None
    flux_watcher_last_run = None
    if flux_watcher_state_file.exists():
        try:
            _fw_state = json.loads(flux_watcher_state_file.read_text(encoding="utf-8"))
            last_idx   = _fw_state.get("last_feed_idx", 0)
            feed_count = _fw_state.get("feed_count", 0)
            last_title = _fw_state.get("last_feed_title", "")
            added      = _fw_state.get("articles_added", 0)
            next_idx   = (last_idx + 1) % feed_count if feed_count > 0 else 0
            flux_watcher_detail = (
                f"Dernier flux : [{last_idx + 1}/{feed_count}] {last_title}"
                f" (+{added} articles) — Prochain : #{next_idx + 1}"
            )
            _fw_last = _fw_state.get("last_run")
            if _fw_last:
                try:
                    flux_watcher_last_run = datetime.datetime.fromisoformat(_fw_last).replace(tzinfo=None)
                except Exception:
                    pass
        except Exception:
            pass

    # Tâches cron fixes (issues de archives/crontab)
    # Catégories : "Surveillance en continu" | "Enrichissement nocturne" | "Rapports & digests" | "Pipeline mensuel"
    fixed = [
        # ── Surveillance en continu ──────────────────────────────────────────────
        {
            "name": "Veille RSS temps-réel (round-robin)",
            "script": "flux_watcher.py → entity_timeline.py → cross_flux_analysis.py → enrich_reading_time.py",
            "cron": "*/5 * * * *",
            "category": "Surveillance en continu",
            "data_dir": None,
            "log_file": PROJECT_ROOT / "rapports" / "cron_flux_watcher.log",
            "extra_last_run": flux_watcher_last_run,
            "detail": flux_watcher_detail,
        },
        {
            "name": "Surveillance sources web (sitemap)",
            "script": "web_watcher.py",
            "cron": "0 */2 * * *",
            "category": "Surveillance en continu",
            "data_dir": None,
            "log_file": PROJECT_ROOT / "rapports" / "cron_web_watcher.log",
        },
        {
            "name": "Extraction mots-clés RSS",
            "script": "get-keyword-from-rss.py",
            "cron": "0 6-22/2 * * *",
            "category": "Surveillance en continu",
            "data_dir": PROJECT_ROOT / "data" / "articles-from-rss",
        },
        {
            "name": "Vérification santé cron",
            "script": "check_cron_health.py",
            "cron": "*/10 * * * *",
            "category": "Surveillance en continu",
            "data_dir": None,
            "log_file": PROJECT_ROOT / "rapports" / "cron_health.log",
        },
        # ── Enrichissement nocturne ──────────────────────────────────────────────
        {
            "name": "Backup des données",
            "script": "backup_data.py",
            "cron": "0 1 * * *",
            "category": "Enrichissement nocturne",
            "data_dir": None,
            "log_file": PROJECT_ROOT / "rapports" / "cron_backup.log",
        },
        {
            "name": "Enrichissement NER (entités)",
            "script": "enrich_entities.py",
            "cron": "0 2 * * *",
            "category": "Enrichissement nocturne",
            "data_dir": None,
            "log_file": PROJECT_ROOT / "rapports" / "cron_enrich_entities.log",
        },
        {
            "name": "Enrichissement images",
            "script": "enrich_images.py",
            "cron": "30 2 * * *",
            "category": "Enrichissement nocturne",
            "data_dir": None,
            "log_file": PROJECT_ROOT / "rapports" / "cron_enrich_images.log",
        },
        {
            "name": "Enrichissement sentiment",
            "script": "enrich_sentiment.py",
            "cron": "0 3 * * *",
            "category": "Enrichissement nocturne",
            "data_dir": None,
            "log_file": PROJECT_ROOT / "rapports" / "cron_sentiment.log",
        },
        {
            "name": "Réparation résumés en erreur",
            "script": "repair_failed_summaries.py",
            "cron": "0 4 * * 0",
            "category": "Enrichissement nocturne",
            "data_dir": None,
            "log_file": PROJECT_ROOT / "rapports" / "cron_repair.log",
        },
        # ── Rapports & digests ───────────────────────────────────────────────────
        {
            "name": "Collecte multi-flux",
            "script": "scheduler_articles.py",
            "cron": "0 6 * * 1",
            "category": "Rapports & digests",
            "data_dir": PROJECT_ROOT / "data" / "articles",
        },
        {
            "name": "Briefing exécutif hebdomadaire",
            "script": "generate_briefing.py --period weekly",
            "cron": "30 6 * * 1",
            "category": "Rapports & digests",
            "data_dir": None,
            "log_file": PROJECT_ROOT / "rapports" / "cron_briefing.log",
        },
        {
            "name": "Détection tendances & alertes",
            "script": "trend_detector.py",
            "cron": "0 7 * * *",
            "category": "Rapports & digests",
            "data_dir": None,
            "log_file": PROJECT_ROOT / "rapports" / "cron_trends.log",
        },
        {
            "name": "Morning Digest quotidien",
            "script": "generate_morning_digest.py --ai",
            "cron": "30 7 * * *",
            "category": "Rapports & digests",
            "data_dir": None,
            "log_file": PROJECT_ROOT / "rapports" / "cron_morning_digest.log",
        },
        {
            "name": "Notes de lecture quotidiennes",
            "script": "generate_reading_notes.py",
            "cron": "0 8 * * *",
            "category": "Rapports & digests",
            "data_dir": None,
            "log_file": PROJECT_ROOT / "rapports" / "cron_reading_notes.log",
        },
        {
            "name": "Rapport Top 10 entités 48h",
            "script": "generate_48h_report.py",
            "cron": "0 23 * * *",
            "category": "Rapports & digests",
            "data_dir": None,
            "log_file": PROJECT_ROOT / "rapports" / "cron_48h_report.log",
        },
        # ── Pipeline mensuel ─────────────────────────────────────────────────────
        {
            "name": "Radar thématique",
            "script": "radar_wudd.py",
            "cron": "0 5 28-31 * *",
            "category": "Pipeline mensuel",
            "data_dir": None,
            "log_file": PROJECT_ROOT / "rapports" / "cron_radar.log",
        },
        {
            "name": "Conversion articles RSS → Markdown",
            "script": "articles_rss_to_markdown.py",
            "cron": "30 5 28-31 * *",
            "category": "Pipeline mensuel",
            "data_dir": None,
            "log_file": PROJECT_ROOT / "rapports" / "cron_rss_markdown.log",
        },
        {
            "name": "Rapports mensuels par mot-clé",
            "script": "generate_keyword_reports.py",
            "cron": "0 6 28-31 * *",
            "category": "Pipeline mensuel",
            "data_dir": None,
            "log_file": PROJECT_ROOT / "rapports" / "cron_keyword_reports.log",
        },
    ]
    for t in fixed:
        if t.get("extra_last_run"):
            last_run = t["extra_last_run"]
        elif t.get("data_dir"):
            last_run = latest_mtime(t["data_dir"])
        elif t.get("log_file") and t["log_file"].exists():
            last_run = datetime.datetime.fromtimestamp(t["log_file"].stat().st_mtime)
        else:
            last_run = None
        next_run = next_cron_occurrence(t["cron"], now)
        tasks.append({
            "name": t["name"],
            "script": t["script"],
            "cron": t["cron"],
            "label": cron_label(t["cron"]),
            "category": t.get("category", "Surveillance en continu"),
            "last_run": last_run.isoformat() if last_run else None,
            "next_run": next_run.isoformat() if next_run else None,
            "flux": None,
            "detail": t.get("detail"),
        })

    # Tâches par flux (flux_json_sources.json)
    for fname in ("flux_json_sources.json", "flux_json_sources.example.json"):
        flux_file = PROJECT_ROOT / "config" / fname
        if flux_file.exists():
            try:
                flux_list = json.loads(flux_file.read_text(encoding="utf-8"))
                for flux in flux_list:
                    title = flux.get("title", "Flux inconnu")
                    # Support format plat (cron) et format imbriqué (scheduler.cron)
                    cron = (flux.get("cron")
                            or flux.get("scheduler", {}).get("cron", "0 6 * * 1"))
                    flux_dir = PROJECT_ROOT / "data" / "articles" / title.strip().replace(" ", "-").replace("\u00a0", "-")
                    last_run = latest_mtime(flux_dir)
                    next_run = next_cron_occurrence(cron, now)
                    tasks.append({
                        "name": f"Flux : {title}",
                        "script": "Get_data_from_JSONFile_AskSummary_v2.py",
                        "cron": cron,
                        "label": cron_label(cron),
                        "last_run": last_run.isoformat() if last_run else None,
                        "next_run": next_run.isoformat() if next_run else None,
                        "flux": title,
                    })
            except (json.JSONDecodeError, KeyError, TypeError):
                pass
            break  # Utiliser uniquement le premier fichier de config existant

    return jsonify({"tasks": tasks, "now": now.isoformat()})


@scheduler_bp.route("/api/scripts/keyword-rss/status")
def keyword_rss_status():
    """Retourne l'état courant du script get-keyword-from-rss.py.

    Combine trois sources :
    1. _rss_job   — suivi du process lancé via le viewer
    2. ps aux     — détection d'un process externe (cron)
    3. rss_progress.json — fichier de progression écrit par le script lui-même
    """
    # ── 1. Process suivi par le viewer ────────────────────────────────────────
    with _rss_job["lock"]:
        proc = _rss_job.get("process")
        viewer_running = proc is not None and proc.poll() is None
        viewer_pid     = proc.pid if viewer_running and proc else None
        last_run       = _rss_job.get("last_run")
        last_rc        = _rss_job.get("last_returncode")

    # ── 2. Détection d'un process externe (cron / terminal) ──────────────────
    external_pid = None
    try:
        out = subprocess.check_output(
            ["pgrep", "-f", "get-keyword-from-rss"],
            text=True, stderr=subprocess.DEVNULL
        ).strip()
        pids = [int(p) for p in out.splitlines() if p.strip().isdigit()]
        # Exclure le PID du viewer lui-même et de son process enfant (si lancé via viewer)
        for p in pids:
            if viewer_pid and p == viewer_pid:
                continue
            external_pid = p
            break
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    running = viewer_running or (external_pid is not None)
    pid     = viewer_pid or external_pid

    # ── 3. Fichier de progression écrit par le script ─────────────────────────
    progress = None
    progress_file = PROJECT_ROOT / "data" / "rss_progress.json"
    if progress_file.exists():
        try:
            progress = json.loads(progress_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    # Réconcilier avec rss_progress.json
    if progress:
        if progress.get("started_at") and not progress.get("finished_at") and not running:
            try:
                mtime = progress_file.stat().st_mtime
                age_s = datetime.datetime.now().timestamp() - mtime
                if age_s < 180:  # fichier modifié il y a moins de 3 minutes
                    running = True
            except Exception:
                pass
        elif progress.get("finished_at") and not running:
            last_run = last_run or progress.get("finished_at")
            last_rc  = last_rc if last_rc is not None else progress.get("returncode")

    # ── 4. Comptage des fichiers et articles dans articles-from-rss ──────────
    articles_dir = PROJECT_ROOT / "data" / "articles-from-rss"
    file_count    = 0
    article_count = 0
    if articles_dir.exists():
        for f in articles_dir.glob("*.json"):
            file_count += 1
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    article_count += len(data)
            except Exception:
                pass

    result = {
        "running":          running,
        "pid":              pid,
        "last_run":         last_run,
        "last_returncode":  last_rc,
        "file_count":       file_count,
        "article_count":    article_count,
        "progress":         progress,
    }
    return jsonify(result)


@scheduler_bp.route("/api/scripts/keyword-rss/stream")
def stream_keyword_rss():
    """Lance get-keyword-from-rss.py et stream la sortie via SSE."""
    script = PROJECT_ROOT / "scripts" / "get-keyword-from-rss.py"
    if not script.exists():
        return jsonify({"error": f"Script introuvable : {script}"}), 404

    def generate():
        with _rss_job["lock"]:
            proc = _rss_job["process"]
            if proc is not None and proc.poll() is None:
                yield f'data: {json.dumps({"log": f"⚠ Script déjà en cours (PID {proc.pid})"})}\n\n'
                return
            env = {**os.environ, "PYTHONUNBUFFERED": "1"}
            try:
                proc = subprocess.Popen(
                    ["python3", str(script)],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    cwd=str(PROJECT_ROOT),
                    env=env,
                )
                _rss_job["process"] = proc
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
        with _rss_job["lock"]:
            _rss_job["last_run"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
            _rss_job["last_returncode"] = rc
        msg = f"✓ Terminé (code : {rc})" if rc == 0 else f"✗ Erreur (code : {rc})"
        yield f'data: {json.dumps({"done": True, "returncode": rc, "log": msg})}\n\n'

    return Response(
        stream_with_context(generate()),
        content_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
