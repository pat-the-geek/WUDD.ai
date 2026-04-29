#!/bin/sh
# Entrypoint multi-role :
# - viewer : lance uniquement Gunicorn (foreground)
# - worker : lance uniquement cron (foreground)
# - all    : compat legacy (viewer en arrière-plan + cron en foreground)
set -e

RUN_ROLE="${RUN_ROLE:-all}"

# ── 1. Vérifier la présence de .env (monté via bind-volume par docker-compose) ─
# Le fichier .env est monté en lecture/écriture depuis l'hôte (./.env:/app/.env).
# Les scripts cron utilisent load_dotenv(/app/.env) pour lire leurs variables.
# Les modifications faites via l'UI Flask persistent automatiquement sur l'hôte.
if [ ! -f /app/.env ]; then
    echo "Avertissement : /app/.env absent — copie depuis .env.example"
    cp /app/.env.example /app/.env
fi
echo "/app/.env chargé ($(wc -l < /app/.env) lignes)."

# ── 2. Initialisation du rôle worker (crontab + sync sources) ─────────────────
if [ "$RUN_ROLE" = "worker" ] || [ "$RUN_ROLE" = "all" ]; then
    # Le fichier archives/crontab utilise le format /etc/cron.d/ (avec champ utilisateur)
    # Il doit donc être copié dans /etc/cron.d/ et NON installé via 'crontab'
    if [ -f /app/archives/crontab ]; then
        cp /app/archives/crontab /etc/cron.d/app-crontab
        chmod 644 /etc/cron.d/app-crontab
        chown root:root /etc/cron.d/app-crontab
        echo "Crontab personnalisée installée dans /etc/cron.d/app-crontab :"
        cat /etc/cron.d/app-crontab
    else
        echo "Aucune crontab personnalisée trouvée."
    fi

    # Ajoute dans sources_credibility.json les sources absentes détectées.
    echo "Synchronisation du registre des sources..."
    python3 /app/scripts/enrich_source_credibility.py --sync-only \
        >> /app/rapports/sync_sources.log 2>&1 \
        && echo "Registre sources synchronisé." \
        || echo "Avertissement : synchronisation sources partiellement échouée (voir /app/rapports/sync_sources.log)."
fi

# ── 3. Configuration Gunicorn (viewer) ───────────────────────────────────────
VIEWER_PORT="${WUDD_VIEWER_PORT:-5050}"
GUNI_WORKERS="${WUDD_GUNICORN_WORKERS:-2}"
GUNI_THREADS="${WUDD_GUNICORN_THREADS:-4}"
GUNI_TIMEOUT="${WUDD_GUNICORN_TIMEOUT:-120}"

mkdir -p /app/rapports

if [ "$RUN_ROLE" = "viewer" ]; then
    echo "Démarrage du viewer WUDD.ai (Gunicorn) sur le port ${VIEWER_PORT}..."
    echo "Gunicorn config: workers=${GUNI_WORKERS}, threads=${GUNI_THREADS}, timeout=${GUNI_TIMEOUT}s"
    exec gunicorn \
        --bind "0.0.0.0:${VIEWER_PORT}" \
        --workers "${GUNI_WORKERS}" \
        --threads "${GUNI_THREADS}" \
        --timeout "${GUNI_TIMEOUT}" \
        --preload \
        --access-logfile - \
        --error-logfile - \
        --capture-output \
        viewer.app:app
fi

if [ "$RUN_ROLE" = "worker" ]; then
    echo "Démarrage du worker cron (sans viewer)..."
    exec cron -f
fi

if [ "$RUN_ROLE" = "all" ]; then
    echo "Démarrage du viewer WUDD.ai (Gunicorn) sur le port ${VIEWER_PORT}..."
    echo "Gunicorn config: workers=${GUNI_WORKERS}, threads=${GUNI_THREADS}, timeout=${GUNI_TIMEOUT}s"
    gunicorn \
        --bind "0.0.0.0:${VIEWER_PORT}" \
        --workers "${GUNI_WORKERS}" \
        --threads "${GUNI_THREADS}" \
        --timeout "${GUNI_TIMEOUT}" \
        --preload \
        --access-logfile - \
        --error-logfile - \
        --capture-output \
        viewer.app:app >> /app/rapports/viewer.log 2>&1 &
    VIEWER_PID=$!
    echo "Viewer démarré (PID : $VIEWER_PID) — http://localhost:${VIEWER_PORT}"
    echo "Démarrage du worker cron (mode all)..."
    exec cron -f
fi

echo "RUN_ROLE invalide: ${RUN_ROLE}. Valeurs attendues: viewer|worker|all"
exit 1
