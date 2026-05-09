"""Authentification Bearer pour le serveur MCP WUDD.ai."""

from __future__ import annotations

import hmac

from fastmcp.server.auth import AccessToken, AuthProvider

from .errors import UnauthorizedError


def validate_bearer_token(auth_header: str | None, expected_token: str) -> None:
    """Valide un header Authorization de type Bearer."""
    if not auth_header:
        raise UnauthorizedError()
    prefix = "Bearer "
    if not auth_header.startswith(prefix):
        raise UnauthorizedError()
    token = auth_header[len(prefix) :].strip()
    if not token or not hmac.compare_digest(token, expected_token):
        raise UnauthorizedError()


class StaticTokenAuthProvider(AuthProvider):
    """Auth provider FastMCP basé sur un token statique."""

    def __init__(self, expected_token: str):
        super().__init__()
        self.expected_token = expected_token

    async def verify_token(self, token: str) -> AccessToken | None:
        if not token or not hmac.compare_digest(token, self.expected_token):
            return None
        return AccessToken(
            token=token,
            client_id="wudd-mcp-client",
            scopes=["mcp"],
            claims={"sub": "wudd-mcp-client"},
        )
