"""Erreurs métier du serveur MCP WUDD.ai."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class MCPError(Exception):
    """Erreur métier normalisée pour les tools MCP."""

    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return self.message


class UnauthorizedError(MCPError):
    def __init__(self, message: str = "Token MCP absent ou invalide") -> None:
        super().__init__("UNAUTHORIZED", message)


class ForbiddenError(MCPError):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__("FORBIDDEN", message, details or {})


class BadRequestError(MCPError):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__("BAD_REQUEST", message, details or {})


class NotFoundError(MCPError):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__("NOT_FOUND", message, details or {})


class UpstreamError(MCPError):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__("UPSTREAM_ERROR", message, details or {})


class UpstreamUnavailableError(MCPError):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__("UPSTREAM_UNAVAILABLE", message, details or {})


class InternalError(MCPError):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__("INTERNAL_ERROR", message, details or {})
