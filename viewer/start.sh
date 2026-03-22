#!/bin/bash
# Démarre le viewer WUDD.ai en mode développement (Flask + Vite dev server).
# Usage : bash viewer/start.sh  (depuis la racine du projet)
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Vérification des dépendances
command -v node >/dev/null || { echo "Erreur : node requis (https://nodejs.org)"; exit 1; }
command -v npm  >/dev/null || { echo "Erreur : npm requis"; exit 1; }

# Résolution du Python : privilégier le venv à la racine du projet
VENV_PYTHON="$SCRIPT_DIR/../.venv/bin/python3"
if [ -f "$VENV_PYTHON" ]; then
    PYTHON="$VENV_PYTHON"
else
    command -v python3 >/dev/null || { echo "Erreur : python3 requis"; exit 1; }
    PYTHON="python3"
fi

# Vérification que Flask et requests sont disponibles
"$PYTHON" -c "import flask, requests" 2>/dev/null || {
    echo "Erreur : Flask ou requests manquant pour $PYTHON"
    echo "Installez les dépendances : pip install -r requirements.txt"
    exit 1
}

# Installation des dépendances npm si nécessaire
if [ ! -d node_modules ]; then
    echo "Installation des dépendances npm..."
    npm install
fi

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║        WUDD.ai Viewer — Dev mode         ║"
echo "╠══════════════════════════════════════════╣"
echo "║  Backend Flask  →  http://localhost:5050  ║"
echo "║  Frontend Vite  →  http://localhost:5173  ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# Démarrer Flask en arrière-plan
"$PYTHON" app.py &
FLASK_PID=$!

# Démarrer Vite en avant-plan
npm run dev

# Arrêter Flask à la fermeture
kill $FLASK_PID 2>/dev/null || true
