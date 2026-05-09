"""Enveloppes de réponse du serveur MCP WUDD.ai."""

from __future__ import annotations

import time
from typing import Any
from uuid import uuid4

from .errors import InternalError, MCPError

MAX_TEXT_CHARS = 200_000


def viewer_meta(
    endpoint: str | None,
    started_at: float,
    *,
    cached: bool = False,
    source: str = "viewer-api",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "source": source,
        "endpoint": endpoint,
        "cached": cached,
        "request_id": str(uuid4()),
        "duration_ms": int((time.perf_counter() - started_at) * 1000),
    }
    if extra:
        meta.update(extra)
    return meta


def success(
    tool: str,
    data: Any,
    *,
    warnings: list[str] | None = None,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "ok": True,
        "tool": tool,
        "data": data,
        "warnings": warnings or [],
        "meta": meta or {},
    }


def failure(
    tool: str,
    code: str,
    message: str,
    *,
    details: dict[str, Any] | None = None,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ok": False,
        "tool": tool,
        "error": {
            "code": code,
            "message": message,
        },
        "meta": meta or {},
    }
    if details:
        payload["error"]["details"] = details
    return payload


def from_exception(
    tool: str,
    endpoint: str | None,
    started_at: float,
    exc: Exception,
) -> dict[str, Any]:
    err = exc if isinstance(exc, MCPError) else InternalError(str(exc))
    return failure(
        tool,
        err.code,
        err.message,
        details=err.details,
        meta=viewer_meta(endpoint, started_at),
    )


def truncate_text(text: str) -> tuple[str, bool]:
    if len(text) <= MAX_TEXT_CHARS:
        return text, False
    return text[:MAX_TEXT_CHARS], True
