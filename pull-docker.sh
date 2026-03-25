#!/bin/bash
# pull-docker.sh — Git pull + rebuild Docker (avec déverrouillage trousseau macOS)
# Usage : bash pull-docker.sh
set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║        WUDD.ai — Pull & Deploy                      ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

# 0 — Déverrouillage trousseau macOS (évite l'erreur "keychain cannot be accessed")
if [[ "$OSTYPE" == "darwin"* ]]; then
  echo "▶ [0/3] Déverrouillage du trousseau macOS..."
  security unlock-keychain ~/Library/Keychains/login.keychain-db
  echo "    ✓ Trousseau déverrouillé"
  echo ""
fi

# 1 — Git pull
echo "▶ [1/3] Git pull..."
git -C "$PROJECT_DIR" pull --ff-only
echo ""

# 2 — Docker build & restart
echo "▶ [2/3] Build & redémarrage Docker..."
docker compose -f "$PROJECT_DIR/docker-compose.yml" up -d --build
echo ""

# 3 — Statut conteneur
echo "▶ [3/3] Statut du conteneur..."
docker compose -f "$PROJECT_DIR/docker-compose.yml" ps

echo ""
echo "✅ Déploiement terminé — http://localhost:5050"
