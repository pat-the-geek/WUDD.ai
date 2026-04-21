# Dockerfile pour AnalyseActualités (multi-flux) + Viewer React/Flask

# ── Étape 1 : Compilation du frontend React ──────────────────────────────────
FROM node:24-slim AS react-builder

WORKDIR /viewer
COPY viewer/package*.json ./
RUN npm ci --silent
COPY viewer/ ./
RUN npm run build

# ── Étape 2 : Image Python principale ────────────────────────────────────────
FROM python:3.14-slim

# 1. Dépendances système minimales (inclut cron)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cron \
    && rm -rf /var/lib/apt/lists/*

# 2. Création des dossiers de travail
WORKDIR /app

# 3. Copie du code source et de la config
COPY scripts/ scripts/
COPY utils/ utils/
COPY config/ config/
COPY tests/ tests/

# Dépendances Python (fichier versionné à la racine)
COPY requirements.txt ./requirements.txt
COPY archives/crontab archives/crontab
COPY .env.example .env.example
COPY README.md ./README.md

# 4. Installation des dépendances Python principales
RUN pip install --no-cache-dir -r requirements.txt

# 5. Copie du viewer (backend Flask + frontend React compilé)
COPY viewer/app.py viewer/app.py
COPY viewer/helpers.py viewer/helpers.py
COPY viewer/state.py viewer/state.py
COPY viewer/routes/ viewer/routes/
COPY viewer/requirements.txt viewer/requirements.txt
COPY --from=react-builder /viewer/dist viewer/dist

# 6. Installation des dépendances Python du viewer
RUN pip install --no-cache-dir -r viewer/requirements.txt

# 7. Création des dossiers de données et rapports (volumes)
RUN mkdir -p data/articles data/articles-from-rss data/raw \
             rapports/markdown rapports/pdf samples archives

# 8. Variables d'environnement (timezone alignée sur le host)
ENV TZ=Europe/Paris
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone
ENV PYTHONUNBUFFERED=1

# 9. Port du viewer
EXPOSE 5050

# 10. Entrypoint : crontab + viewer Flask + cron
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]

# Pour lancer un traitement manuel, overridez la commande :
# docker run --rm -v $(pwd)/data:/app/data -v $(pwd)/rapports:/app/rapports <image> \
#   python3 scripts/Get_data_from_JSONFile_AskSummary_v2.py --flux <nom_flux> \
#   --date_debut ... --date_fin ...
