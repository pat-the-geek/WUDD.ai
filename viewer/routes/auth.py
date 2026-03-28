"""
viewer/routes/auth.py — Blueprint Flask pour le contrôle d'accès.

Routes :
  GET  /api/auth/status    → {protected, authenticated, ip_allowed}
  POST /api/auth/login     → {ok, error?}
  POST /api/auth/logout    → {ok}

Variables d'environnement :
  ACCESS_PASSWORD   — si défini, un mot de passe est exigé pour accéder au viewer
  ALLOWED_IPS       — liste d'adresses IP autorisées (séparées par des virgules)
                       Ces IPs peuvent accéder sans mot de passe
"""
import hmac
import os

from flask import Blueprint, jsonify, request, session

auth_bp = Blueprint("auth", __name__)


def _get_password() -> str:
    """Retourne le mot de passe configuré (ou chaîne vide si aucun)."""
    return os.environ.get("ACCESS_PASSWORD", "").strip()


def _get_allowed_ips() -> list[str]:
    """Retourne la liste des IPs autorisées configurées."""
    raw = os.environ.get("ALLOWED_IPS", "").strip()
    if not raw:
        return []
    return [ip.strip() for ip in raw.split(",") if ip.strip()]


def _get_trusted_proxies() -> list[str]:
    """Retourne la liste des proxies de confiance (qui peuvent définir X-Forwarded-For)."""
    raw = os.environ.get("TRUSTED_PROXIES", "").strip()
    if not raw:
        return []
    return [ip.strip() for ip in raw.split(",") if ip.strip()]


def _get_client_ip() -> str:
    """Retourne l'IP du client.

    X-Forwarded-For n'est utilisé que si la requête provient d'un proxy de
    confiance défini dans TRUSTED_PROXIES, afin d'éviter le spoofing d'IP.
    """
    remote_addr = request.remote_addr or ""
    trusted_proxies = _get_trusted_proxies()

    if trusted_proxies and remote_addr in trusted_proxies:
        forwarded = request.headers.get("X-Forwarded-For", "")
        if forwarded:
            return forwarded.split(",")[0].strip()

    return remote_addr


def is_access_protected() -> bool:
    """Retourne True si l'accès est protégé par mot de passe ou whitelist IP."""
    return bool(_get_password() or _get_allowed_ips())


def is_request_allowed() -> bool:
    """Retourne True si la requête courante est autorisée (sans vérifier le path)."""
    password = _get_password()
    allowed_ips = _get_allowed_ips()

    # Aucune protection configurée → accès libre
    if not password and not allowed_ips:
        return True

    # IP dans la whitelist → accès autorisé
    client_ip = _get_client_ip()
    if allowed_ips and client_ip in allowed_ips:
        return True

    # Session authentifiée → accès autorisé
    if session.get("authenticated"):
        return True

    return False


@auth_bp.route("/api/auth/status", methods=["GET"])
def auth_status():
    """Retourne le statut d'authentification de la session courante."""
    password = _get_password()
    allowed_ips = _get_allowed_ips()
    client_ip = _get_client_ip()
    ip_allowed = bool(allowed_ips and client_ip in allowed_ips)

    return jsonify({
        "protected": is_access_protected(),
        "authenticated": bool(session.get("authenticated")),
        "ip_allowed": ip_allowed,
    })


@auth_bp.route("/api/auth/login", methods=["POST"])
def auth_login():
    """Authentifie l'utilisateur avec le mot de passe fourni."""
    password = _get_password()

    if not password:
        # Pas de protection configurée → toujours OK
        session["authenticated"] = True
        session.permanent = True
        return jsonify({"ok": True})

    data = request.get_json(force=True, silent=True) or {}
    provided = str(data.get("password", ""))

    # Comparaison en temps constant pour éviter les timing attacks
    if hmac.compare_digest(provided, password):
        session["authenticated"] = True
        session.permanent = True
        return jsonify({"ok": True})

    return jsonify({"ok": False, "error": "Mot de passe incorrect"}), 401


@auth_bp.route("/api/auth/logout", methods=["POST"])
def auth_logout():
    """Déconnecte l'utilisateur en effaçant sa session."""
    session.clear()
    return jsonify({"ok": True})
