"""scripts/check_cron_health.py — Sonde de santé des jobs cron WUDD.ai.

Optimisation 2.6 : refactoring complet pour écrire un fichier structuré
data/cron_health.json avec l'état détaillé de chaque job, exposé via
l'endpoint /api/health/cron du viewer Flask.

Exécution : toutes les 10 minutes (cron Docker)
Sortie     : data/cron_health.json + alertes par email/webhook si échec
"""

import json
import os
import smtplib
import time
from datetime import datetime, timedelta
from email.message import EmailMessage
from pathlib import Path

# ── Configuration ─────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
RAPPORTS_DIR = PROJECT_ROOT / "rapports"
HEALTH_FILE = DATA_DIR / "cron_health.json"

# Paramètres email (optionnel — laisser vide pour désactiver)
MAIL_ENABLED = bool(os.getenv("CRON_ALERT_MAIL"))
MAIL_TO = os.getenv("CRON_ALERT_MAIL", "")
MAIL_FROM = os.getenv("CRON_ALERT_FROM", "cron-bot@example.com")
MAIL_SERVER = os.getenv("CRON_ALERT_SMTP", "smtp.example.com")
MAIL_PORT = int(os.getenv("CRON_ALERT_PORT", "587"))
MAIL_USER = os.getenv("CRON_ALERT_USER", "")
MAIL_PASS = os.getenv("CRON_ALERT_PASS", "")

# Seuils d'alerte : nombre maximal de minutes depuis la dernière exécution
# avant de déclencher une alerte par job
JOB_STALE_THRESHOLDS: dict[str, int] = {
    "flux_watcher":           10,   # toutes les 5 min → alerte si > 10 min
    "get_keyword_from_rss":   150,  # toutes les 2h (06-22h) → alerte si > 150 min
    "web_watcher":            130,  # toutes les 2h → alerte si > 130 min
    "check_cron_health":      15,   # toutes les 10 min → alerte si > 15 min
    "backup_data":            1500, # quotidien 01:00 → alerte si > 25h
    "enrich_entities":        1500, # quotidien 02:00
    "enrich_images":          1500,
    "enrich_sentiment":       1500,
    "repair_failed_summaries": 10100, # hebdo dim 04:00 → alerte si > 7j+3h
    "trend_detector":         1500,
    "generate_morning_digest": 1500,
    "generate_48h_report":    1500,
}

# Définition des jobs à surveiller : (nom, fichier_log ou répertoire_données)
JOB_DEFINITIONS: list[dict] = [
    {
        "name": "flux_watcher",
        "label": "Veille RSS temps-réel",
        "log": RAPPORTS_DIR / "cron_flux_watcher.log",
        "state_file": DATA_DIR / "flux_watcher_state.json",
        "state_key": "last_run",
    },
    {
        "name": "get_keyword_from_rss",
        "label": "Extraction mots-clés RSS",
        "log": None,
        "state_file": DATA_DIR / "rss_progress.json",
        "state_key": "finished_at",
    },
    {
        "name": "web_watcher",
        "label": "Surveillance sources web",
        "log": RAPPORTS_DIR / "cron_web_watcher.log",
        "state_file": DATA_DIR / "web_watcher_state.json",
        "state_key": None,  # utiliser mtime du state_file
    },
    {
        "name": "backup_data",
        "label": "Backup données",
        "log": RAPPORTS_DIR / "cron_backup.log",
        "state_file": None,
        "state_key": None,
    },
    {
        "name": "enrich_entities",
        "label": "Enrichissement NER",
        "log": RAPPORTS_DIR / "cron_enrich_entities.log",
        "state_file": None,
        "state_key": None,
    },
    {
        "name": "enrich_images",
        "label": "Enrichissement images",
        "log": RAPPORTS_DIR / "cron_enrich_images.log",
        "state_file": None,
        "state_key": None,
    },
    {
        "name": "enrich_sentiment",
        "label": "Enrichissement sentiment",
        "log": RAPPORTS_DIR / "cron_sentiment.log",
        "state_file": None,
        "state_key": None,
    },
    {
        "name": "repair_failed_summaries",
        "label": "Réparation résumés",
        "log": RAPPORTS_DIR / "cron_repair.log",
        "state_file": None,
        "state_key": None,
    },
    {
        "name": "trend_detector",
        "label": "Détection tendances",
        "log": RAPPORTS_DIR / "cron_trends.log",
        "state_file": DATA_DIR / "alertes.json",
        "state_key": None,  # mtime de alertes.json
    },
    {
        "name": "generate_morning_digest",
        "label": "Morning Digest",
        "log": RAPPORTS_DIR / "cron_morning_digest.log",
        "state_file": None,
        "state_key": None,
    },
    {
        "name": "generate_48h_report",
        "label": "Rapport 48h",
        "log": RAPPORTS_DIR / "cron_48h_report.log",
        "state_file": None,
        "state_key": None,
    },
]


# ── Fonctions utilitaires ─────────────────────────────────────────────────────

def _last_run_from_log(log_path: Path) -> datetime | None:
    """Retourne la date de dernière modification d'un fichier log."""
    if log_path and log_path.exists():
        try:
            return datetime.fromtimestamp(log_path.stat().st_mtime)
        except OSError:
            return None
    return None


def _last_run_from_state(state_file: Path, key: str | None) -> datetime | None:
    """Retourne la date depuis un fichier d'état JSON."""
    if not state_file or not state_file.exists():
        return None
    try:
        data = json.loads(state_file.read_text(encoding="utf-8"))
        if key and isinstance(data, dict):
            raw = data.get(key)
            if raw:
                return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).replace(tzinfo=None)
        # Fallback : mtime du fichier
        return datetime.fromtimestamp(state_file.stat().st_mtime)
    except Exception:
        return None


def _check_log_errors(log_path: Path, last_n_lines: int = 30) -> list[str]:
    """Retourne les lignes d'erreur dans les N dernières lignes d'un log."""
    if not log_path or not log_path.exists():
        return []
    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        recent = lines[-last_n_lines:]
        return [
            l.strip() for l in recent
            if any(kw in l for kw in ("Traceback", "Error", "Exception", "ERREUR", "ALERTE"))
        ]
    except Exception:
        return []


def send_mail(subject: str, body: str) -> None:
    """Envoie une alerte par email si MAIL_ENABLED est True."""
    if not MAIL_ENABLED or not MAIL_TO:
        return
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = MAIL_FROM
    msg["To"] = MAIL_TO
    msg.set_content(body)
    try:
        with smtplib.SMTP(MAIL_SERVER, MAIL_PORT) as server:
            server.starttls()
            if MAIL_USER:
                server.login(MAIL_USER, MAIL_PASS)
            server.send_message(msg)
    except Exception as e:
        print(f"[ERREUR] Envoi mail échoué : {e}")


# ── Vérification principale ───────────────────────────────────────────────────

def check_cron_health() -> dict:
    """Vérifie l'état de santé de tous les jobs cron et écrit cron_health.json.

    Returns:
        Dictionnaire complet de santé (aussi écrit dans data/cron_health.json).
    """
    now = datetime.utcnow()
    health: dict = {
        "generated_at": now.isoformat() + "Z",
        "status": "ok",  # "ok" | "degraded" | "critical"
        "jobs": {},
        "alerts": [],
    }

    degraded_jobs = []

    for job_def in JOB_DEFINITIONS:
        name = job_def["name"]
        label = job_def["label"]
        log_path: Path | None = job_def.get("log")
        state_file: Path | None = job_def.get("state_file")
        state_key: str | None = job_def.get("state_key")

        # Déterminer la date de dernière exécution
        last_run: datetime | None = None
        if state_file and state_key:
            last_run = _last_run_from_state(state_file, state_key)
        elif state_file:
            last_run = _last_run_from_state(state_file, None)
        if not last_run and log_path:
            last_run = _last_run_from_log(log_path)

        # Calculer l'âge en minutes
        age_minutes: float | None = None
        if last_run:
            age_minutes = (now - last_run).total_seconds() / 60

        # Vérifier les erreurs dans le log
        log_errors = _check_log_errors(log_path) if log_path else []

        # Déterminer le statut du job
        stale_threshold = JOB_STALE_THRESHOLDS.get(name, 1500)
        is_stale = age_minutes is not None and age_minutes > stale_threshold
        has_errors = len(log_errors) > 0

        if is_stale or has_errors:
            job_status = "warning"
            degraded_jobs.append(name)
        else:
            job_status = "ok"

        health["jobs"][name] = {
            "label": label,
            "status": job_status,
            "last_run": last_run.isoformat() + "Z" if last_run else None,
            "age_minutes": round(age_minutes, 1) if age_minutes is not None else None,
            "stale_threshold_minutes": stale_threshold,
            "is_stale": is_stale,
            "recent_errors": log_errors[:3],  # max 3 erreurs pour ne pas surcharger le JSON
        }

        # Affichage console
        age_str = f"{age_minutes:.0f}min" if age_minutes is not None else "inconnu"
        if job_status == "ok":
            print(f"[OK]      {label:<40} — dernière exécution : {age_str}")
        else:
            reasons = []
            if is_stale:
                reasons.append(f"inactif depuis {age_str} > {stale_threshold}min")
            if has_errors:
                reasons.append(f"{len(log_errors)} erreur(s) dans le log")
            print(f"[ALERTE]  {label:<40} — {', '.join(reasons)}")

    # Déterminer le statut global
    if len(degraded_jobs) == 0:
        health["status"] = "ok"
    elif len(degraded_jobs) <= 2:
        health["status"] = "degraded"
    else:
        health["status"] = "critical"

    if degraded_jobs:
        health["alerts"] = [
            f"Jobs dégradés : {', '.join(degraded_jobs)}"
        ]
        send_mail(
            f"[WUDD.ai] Alerte santé cron — {len(degraded_jobs)} job(s) dégradé(s)",
            f"Jobs en alerte :\n" + "\n".join(f"  - {j}" for j in degraded_jobs)
            + f"\n\nVérifier : {HEALTH_FILE}"
        )

    # Écriture atomique de data/cron_health.json
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = HEALTH_FILE.with_suffix(".tmp")
    try:
        tmp.write_text(
            json.dumps(health, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        tmp.replace(HEALTH_FILE)
        print(f"[INFO] cron_health.json mis à jour ({health['status'].upper()}) — {HEALTH_FILE}")
    except OSError as e:
        print(f"[ERREUR] Écriture cron_health.json échouée : {e}")

    return health


if __name__ == "__main__":
    result = check_cron_health()
    status = result.get("status", "inconnu")
    jobs = result.get("jobs", {})
    ok_count = sum(1 for j in jobs.values() if j["status"] == "ok")
    print(f"\nRésumé : {ok_count}/{len(jobs)} jobs OK — statut global : {status.upper()}")
