"""Tools watchlist d'entités MCP."""

from __future__ import annotations

import time
from urllib.parse import quote

from ..config import MCPConfig
from ..errors import BadRequestError, ForbiddenError
from ..responses import from_exception, success, viewer_meta
from ..viewer_client import ViewerClient

_ENDPOINT = "/api/watched-entities"
_VERIFY_READ_DELAYS = (0.0, 0.05, 0.15)


def _watch_entry_present(client: ViewerClient, entity_type: str, value: str) -> bool:
    payload = client.get(_ENDPOINT)
    if not isinstance(payload, list):
        return False
    for item in payload:
        if not isinstance(item, dict):
            continue
        if (
            str(item.get("type") or "").strip().upper() == entity_type
            and str(item.get("value") or "").strip() == value
        ):
            return True
    return False


def _confirm_watch_persisted(client: ViewerClient, entity_type: str, value: str) -> tuple[bool, int]:
    reads = 0
    for delay in _VERIFY_READ_DELAYS:
        if delay > 0:
            time.sleep(delay)
        reads += 1
        try:
            if _watch_entry_present(client, entity_type, value):
                return True, reads
        except Exception:
            continue
    return False, reads


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
        post_attempts = 1
        if isinstance(data, dict):
            resolved_type = str(data.get("type") or normalized_type).strip().upper()
            resolved_value = str(data.get("value") or entity_value).strip()
            persisted, verification_reads = _confirm_watch_persisted(
                client,
                resolved_type,
                resolved_value,
            )
            if not persisted:
                retry_data = client.post(_ENDPOINT, json_body=body)
                post_attempts += 1
                if isinstance(retry_data, dict):
                    data = retry_data
                    resolved_type = str(data.get("type") or resolved_type).strip().upper()
                    resolved_value = str(data.get("value") or resolved_value).strip()
                retry_persisted, retry_reads = _confirm_watch_persisted(
                    client,
                    resolved_type,
                    resolved_value,
                )
                persisted = retry_persisted
                verification_reads += retry_reads
            data.setdefault("type", resolved_type)
            data.setdefault("value", resolved_value)
            data["persisted"] = bool(persisted)
            data["verification_reads"] = verification_reads
            data["post_attempts"] = post_attempts
            if not persisted:
                data["warning"] = (
                    "Écriture non confirmée par relecture immédiate; relancer list_watched_entities "
                    "ou watch_entity pour vérifier l'état final."
                )
        return success("watch_entity", data, meta=viewer_meta(_ENDPOINT, started_at))
    except Exception as exc:
        return from_exception("watch_entity", _ENDPOINT, started_at, exc)


def tool_get_watched_entity_articles(
    client: ViewerClient,
    *,
    entity_name: str | None = None,
    date: str | None = None,
    entity_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Articles du jour (ou d'une date donnée) mentionnant une entité.

    Mappe GET /api/watched-entities/{entity_name}/articles. Endpoint de
    lecture : l'entité n'a pas besoin d'être sur la watchlist.

    NOTE : la spec suggérait le nom `get_entity_articles`, mais ce nom est
    déjà pris par un tool existant qui cible un autre endpoint
    (/api/entities/articles, sans filtre date). Pour ne rien casser, ce
    nouvel outil est exposé sous `get_watched_entity_articles`.
    """
    started_at = time.perf_counter()
    name = (entity_name or "").strip()
    endpoint = f"/api/watched-entities/{quote(name, safe='')}/articles"
    try:
        if not name:
            raise BadRequestError("Le paramètre entity_name est requis")
        try:
            capped_limit = max(1, min(int(limit), 500))
        except (TypeError, ValueError):
            raise BadRequestError("limit doit être un entier")
        try:
            safe_offset = max(0, int(offset))
        except (TypeError, ValueError):
            raise BadRequestError("offset doit être un entier")
        params: dict[str, str | int] = {"limit": capped_limit, "offset": safe_offset}
        if date is not None and str(date).strip():
            params["date"] = str(date).strip()
        if entity_type is not None and str(entity_type).strip():
            params["type"] = str(entity_type).strip().upper()
        data = client.get(endpoint, params=params, timeout=client.heavy_timeout)
        return success(
            "get_watched_entity_articles",
            data,
            meta=viewer_meta(endpoint, started_at),
        )
    except Exception as exc:
        return from_exception(
            "get_watched_entity_articles", endpoint, started_at, exc
        )


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
