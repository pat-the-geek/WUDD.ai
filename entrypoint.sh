#!/bin/sh
# Entrypoint : génère .env, installe la crontab, démarre le viewer Flask,
# puis lance cron en foreground.
set -e

# ── 1. Vérifier la présence de .env (monté via bind-volume par docker-compose) ─
# Le fichier .env est monté en lecture/écriture depuis l'hôte (./.env:/app/.env).
# Les scripts cron utilisent load_dotenv(/app/.env) pour lire leurs variables.
# Les modifications faites via l'UI Flask persistent automatiquement sur l'hôte.
if [ ! -f /app/.env ]; then
    echo "Avertissement : /app/.env absent — copie depuis .env.example"
    cp /app/.env.example /app/.env
fi
echo "/app/.env chargé ($(wc -l < /app/.env) lignes)."

# ── 2. Installer la crontab personnalisée ────────────────────────────────────
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

# ── 3. Synchroniser le registre des sources ──────────────────────────────────
# Ajoute dans sources_credibility.json les sources absentes détectées dans
# WUDD.opml, web_sources.json et les articles existants.
# Opération locale (< 10 s, aucun appel HTTP externe).
echo "Synchronisation du registre des sources..."
python3 /app/scripts/enrich_source_credibility.py --sync-only \
    >> /app/rapports/sync_sources.log 2>&1 \
    && echo "Registre sources synchronisé." \
    || echo "Avertissement : synchronisation sources partiellement échouée (voir /app/rapports/sync_sources.log)."

# ── 4. Démarrer le viewer Flask en arrière-plan ──────────────────────────────
echo "Démarrage du viewer WUDD.ai sur le port 5050..."
mkdir -p /app/rapports
python3 /app/viewer/app.py >> /app/rapports/viewer.log 2>&1 &
VIEWER_PID=$!
echo "Viewer démarré (PID : $VIEWER_PID) — http://localhost:5050"

# ── 5. Lancer cron en foreground ─────────────────────────────────────────────
exec cron -f
