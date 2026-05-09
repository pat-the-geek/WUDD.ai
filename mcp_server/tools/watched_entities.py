"""Tools watchlist d'entités MCP."""

from __future__ import annotations

import time

from ..config import MCPConfig
from ..errors import BadRequestError, ForbiddenError
from ..responses import from_exception, success, viewer_meta
from ..viewer_client import ViewerClient

_ENDPOINT = "/api/watched-entities"


def tool_list_watched_entities(client: ViewerClient) -> dict:
    started_at = time.perf_counter()
    try:
        data = client.get(_ENDPOINT)
        return success(
            "list_watched_entities",
            data,
            meta=viewer_meta(_ENDPOINT, started_at),
        )
    except Exception as exc:
        return from_exception("list_watched_entities", _ENDPOINT, started_at, exc)


def tool_watch_entity(
    client: ViewerClient,
    config: MCPConfig,
    *,
    entity_type: str | None = None,
    value: str | None = None,
    notes: str | None = None,
) -> dict:
    started_at = time.perf_counter()
    try:
        if not config.enable_write_tools:
            raise ForbiddenError("Les tools d'écriture sont désactivés")
        normalized_type = (entity_type or "").strip().upper()
        entity_value = (value or "").strip()
        if not normalized_type or not entity_value:
            raise BadRequestError("Les paramètres type et value sont requis")
        body = {"type": normalized_type, "value": entity_value}
        if notes is not None:
            body["notes"] = str(notes)[:500]
        data = client.post(_ENDPOINT, json_body=body)
        if isinstance(data, dict):
            data.setdefault("type", normalized_type)
            data.setdefault("value", entity_value)
        return success("watch_entity", data, meta=viewer_meta(_ENDPOINT, started_at))
    except Exception as exc:
        return from_exception("watch_entity", _ENDPOINT, started_at, exc)


def tool_unwatch_entity(
    client: ViewerClient,
    config: MCPConfig,
    *,
    entity_type: str | None = None,
    value: str | None = None,
) -> dict:
    started_at = time.perf_counter()
    try:
        if not config.enable_write_tools:
            raise ForbiddenError("Les tools d'écriture sont désactivés")
        normalized_type = (entity_type or "").strip().upper()
        entity_value = (value or "").strip()
        if not normalized_type or not entity_value:
            raise BadRequestError("Les paramètres type et value sont requis")
        data = client.delete(
            _ENDPOINT,
            params={"type": normalized_type, "value": entity_value},
        )
        if isinstance(data, dict):
            data.setdefault("type", normalized_type)
            data.setdefault("value", entity_value)
        return success(
            "unwatch_entity",
            data,
            meta=viewer_meta(_ENDPOINT, started_at),
        )
    except Exception as exc:
        return from_exception("unwatch_entity", _ENDPOINT, started_at, exc)
