"""viewer/routes/auth.py — Authentification JWT pour WUDD.ai Viewer.

L'authentification est OPTIONNELLE : si AUTH_ENABLED=false dans .env
(ou si config/users.json ne contient aucun utilisateur activé), toutes
les routes sont accessibles sans token.

Pour activer l'auth :
  1. Mettre AUTH_ENABLED=true dans .env
  2. Générer un secret : python3 -c "import secrets; print(secrets.token_hex(32))"
     → mettre dans JWT_SECRET dans .env
  3. Créer un utilisateur dans config/users.json avec password_hash non vide
     python3 -c "import hashlib; print(hashlib.sha256(b'monmdp').hexdigest())"

Routes :
  POST /api/auth/login   — authentification, retourne JWT
  POST /api/auth/refresh — rafraîchit un token valide
  GET  /api/auth/me      — info utilisateur courant
  POST /api/auth/logout  — invalide le token (client-side only)
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
from functools import wraps
from pathlib import Path

from flask import Blueprint, jsonify, request, g

auth_bp = Blueprint("auth", __name__)

PROJECT_ROOT = Path(__file__).parent.parent.parent.resolve()
_USERS_PATH = PROJECT_ROOT / "config" / "users.json"


def _get_jwt_secret() -> str:
    return os.getenv("JWT_SECRET", "wudd-ai-dev-secret-NOT-FOR-PRODUCTION")


def _is_auth_enabled() -> bool:
    """Retourne True si l'authentification est activée."""
    env_val = os.getenv("AUTH_ENABLED", "false").lower()
    if env_val not in ("true", "1", "yes"):
        return False
    # Vérifier qu'il y a au moins un utilisateur activé avec un hash
    users = _load_users()
    return any(u.get("enabled", False) and u.get("password_hash") for u in users)


def _load_users() -> list[dict]:
    if not _USERS_PATH.exists():
        return []
    try:
        data = json.loads(_USERS_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def _generate_token(username: str, role: str) -> str:
    try:
        import jwt
    except ImportError:
        raise RuntimeError("PyJWT non installé — ajouter PyJWT>=2.8.0 dans requirements.txt")

    payload = {
        "sub": username,
        "role": role,
        "iat": datetime.datetime.now(datetime.timezone.utc),
        "exp": datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=24),
    }
    return jwt.encode(payload, _get_jwt_secret(), algorithm="HS256")


def _decode_token(token: str) -> dict | None:
    try:
        import jwt
        return jwt.decode(token, _get_jwt_secret(), algorithms=["HS256"])
    except Exception:
        return None


def require_auth(f):
    """Décorateur : exige un token JWT valide si l'auth est activée."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not _is_auth_enabled():
            return f(*args, **kwargs)
        # Lire le token depuis le header Authorization: Bearer <token>
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"error": "Token manquant", "auth_required": True}), 401
        token = auth_header[7:]
        payload = _decode_token(token)
        if payload is None:
            return jsonify({"error": "Token invalide ou expiré", "auth_required": True}), 401
        g.current_user = payload
        return f(*args, **kwargs)
    return decorated


@auth_bp.route("/api/auth/login", methods=["POST"])
def api_auth_login():
    """Authentification : retourne un JWT si les credentials sont valides.

    Body JSON : { "username": "...", "password": "..." }
    """
    data = request.get_json(silent=True) or {}
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", ""))

    if not username or not password:
        return jsonify({"error": "username et password obligatoires"}), 400

    users = _load_users()
    user = next((u for u in users if u.get("username") == username and u.get("enabled", False)), None)
    if user is None:
        return jsonify({"error": "Utilisateur introuvable ou désactivé"}), 401

    expected_hash = user.get("password_hash", "")
    if not expected_hash or _hash_password(password) != expected_hash:
        return jsonify({"error": "Mot de passe incorrect"}), 401

    try:
        token = _generate_token(username, user.get("role", "viewer"))
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 500

    return jsonify({
        "token": token,
        "username": username,
        "role": user.get("role", "viewer"),
        "expires_in": 86400,
    })


@auth_bp.route("/api/auth/refresh", methods=["POST"])
def api_auth_refresh():
    """Rafraîchit un token valide (sliding window)."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return jsonify({"error": "Token manquant"}), 401
    payload = _decode_token(auth_header[7:])
    if payload is None:
        return jsonify({"error": "Token invalide ou expiré"}), 401

    try:
        token = _generate_token(payload["sub"], payload.get("role", "viewer"))
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 500

    return jsonify({"token": token, "expires_in": 86400})


@auth_bp.route("/api/auth/me", methods=["GET"])
def api_auth_me():
    """Retourne les infos de l'utilisateur courant."""
    if not _is_auth_enabled():
        return jsonify({"auth_enabled": False, "username": None})

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return jsonify({"auth_enabled": True, "username": None})

    payload = _decode_token(auth_header[7:])
    if payload is None:
        return jsonify({"auth_enabled": True, "username": None, "expired": True})

    return jsonify({
        "auth_enabled": True,
        "username": payload.get("sub"),
        "role": payload.get("role", "viewer"),
    })


@auth_bp.route("/api/auth/logout", methods=["POST"])
def api_auth_logout():
    """Logout côté serveur (stateless — le client supprime juste le token)."""
    return jsonify({"ok": True, "message": "Supprimez le token côté client"})


@auth_bp.route("/api/auth/status", methods=["GET"])
def api_auth_status():
    """Retourne si l'auth est activée (utilisé par le frontend pour afficher la page login)."""
    return jsonify({"auth_enabled": _is_auth_enabled()})
