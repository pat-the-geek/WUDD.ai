#!/bin/bash
# deploy_local.sh — Déploiement manuel (même séquence que le workflow CI)
# Usage : bash deploy_local.sh
set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║        WUDD.ai — Déploiement local                  ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

# 1 — Git pull
echo "▶ [1/3] Git pull..."
git -C "$PROJECT_DIR" pull --ff-only

# 2 — Docker
echo ""
echo "▶ [2/3] Build & redémarrage Docker..."
docker compose -f "$PROJECT_DIR/docker-compose.yml" up -d --build

# 3 — Tests
echo ""
echo "▶ [3/3] Exécution des tests dans le conteneur Docker..."
VIEWER_SERVICE="analyse-actualites-viewer"

# Exécuter via docker compose pour éviter les erreurs si le nom du conteneur change.
docker compose -f "$PROJECT_DIR/docker-compose.yml" exec -T "$VIEWER_SERVICE" pytest tests/ -v --tb=short

echo ""
echo "✅ Déploiement terminé avec succès."
