"""Tools entités MCP."""

from __future__ import annotations

import time
from typing import Any

from ..errors import BadRequestError
from ..responses import from_exception, success, viewer_meta
from ..viewer_client import ViewerClient
from utils.entity_matching import normalize_match_mode


def tool_search_entities(
    client: ViewerClient,
    *,
    q: str | None = None,
    include_structural: bool = False,
) -> dict:
    started_at = time.perf_counter()
    endpoint = "/api/entities/search"
    try:
        query = (q or "").strip()
        if len(query) < 2:
            raise BadRequestError("Le paramètre q doit contenir au moins 2 caractères")
        params = {"q": query}
        if include_structural:
            params["include_structural"] = "1"
        data = client.get(endpoint, params=params, timeout=client.heavy_timeout)
        return success("search_entities", data, meta=viewer_meta(endpoint, started_at))
    except Exception as exc:
        return from_exception("search_entities", endpoint, started_at, exc)


def tool_get_entity_dashboard(
    client: ViewerClient,
    *,
    include_structural: bool = False,
) -> dict:
    started_at = time.perf_counter()
    endpoint = "/api/entities/dashboard"
    try:
        params = {"include_structural": "1"} if include_structural else None
        data = client.get(endpoint, params=params)
        return success(
            "get_entity_dashboard",
            data,
            meta=viewer_meta(endpoint, started_at),
        )
    except Exception as exc:
        return from_exception("get_entity_dashboard", endpoint, started_at, exc)


def tool_get_entity_articles(
    client: ViewerClient,
    *,
    entity_type: str | None = None,
    value: str | None = None,
    max_articles: int = 100,
    compact: bool = True,
    match_mode: str | None = None,
    all_types: bool = False,
) -> dict:
    started_at = time.perf_counter()
    endpoint = "/api/entities/articles"
    warnings: list[str] = []
    try:
        normalized_type = (entity_type or "").strip().upper()
        entity_value = (value or "").strip()
        if not entity_value or (not normalized_type and not all_types):
            raise BadRequestError("Le paramètre value est requis, et type sauf si all_types=true")
        normalized_match_mode = None
        if match_mode is not None and str(match_mode).strip():
            try:
                normalized_match_mode = normalize_match_mode(str(match_mode), default="canonical")
            except ValueError as exc:
                raise BadRequestError(str(exc)) from exc
        capped_max = max(1, min(int(max_articles), 200))
        if capped_max != int(max_articles):
            warnings.append("large_result_capped")
        params = {"value": entity_value, "max_articles": capped_max, "compact": "1" if compact else "0"}
        if normalized_type:
            params["type"] = normalized_type
        if normalized_match_mode:
            params["match_mode"] = normalized_match_mode
        if all_types:
            params["all_types"] = "1"
        data = client.get(endpoint, params=params, timeout=client.heavy_timeout)
        return success(
            "get_entity_articles",
            data,
            warnings=warnings,
            meta=viewer_meta(endpoint, started_at),
        )
    except Exception as exc:
        return from_exception("get_entity_articles", endpoint, started_at, exc)


def tool_get_entity_timeline(
    client: ViewerClient,
    *,
    days: int = 30,
    top: int = 30,
    entity: str | None = None,
    entity_type: str | None = None,
    match_mode: str | None = None,
    all_types: bool = False,
) -> dict:
    started_at = time.perf_counter()
    endpoint = "/api/entities/timeline"
    try:
        params: dict[str, Any] = {
            "days": max(1, min(int(days), 365)),
            "top": max(1, min(int(top), 100)),
        }
        normalized_match_mode = None
        if match_mode is not None and str(match_mode).strip():
            try:
                normalized_match_mode = normalize_match_mode(
                    str(match_mode),
                    default="contains",
                )
            except ValueError as exc:
                raise BadRequestError(str(exc)) from exc
        if entity:
            params["entity"] = entity.strip()
        if entity_type:
            params["type"] = entity_type.strip().upper()
        if normalized_match_mode:
            params["match_mode"] = normalized_match_mode
        if all_types:
            params["all_types"] = "1"
        data = client.get(endpoint, params=params, timeout=client.heavy_timeout)
        return success(
            "get_entity_timeline",
            data,
            meta=viewer_meta(endpoint, started_at),
        )
    except Exception as exc:
        return from_exception("get_entity_timeline", endpoint, started_at, exc)


def tool_get_entity_cooccurrences(
    client: ViewerClient,
    *,
    entity_type: str | None = None,
    value: str | None = None,
    limit: int = 40,
    depth: int = 1,
    limit_l2: int = 4,
    days: int = 0,
) -> dict:
    started_at = time.perf_counter()
    endpoint = "/api/entities/cooccurrences"
    try:
        normalized_type = (entity_type or "").strip().upper()
        entity_value = (value or "").strip()
        if not normalized_type or not entity_value:
            raise BadRequestError("Les paramètres type et value sont requis")
        graph_depth = int(depth)
        if graph_depth not in {1, 2}:
            raise BadRequestError("depth doit valoir 1 ou 2")
        params = {
            "type": normalized_type,
            "value": entity_value,
            "limit": max(1, min(int(limit), 100)),
            "depth": graph_depth,
            "limit_l2": max(1, min(int(limit_l2), 15)),
            "days": max(0, min(int(days), 365)),
        }
        data = client.get(endpoint, params=params, timeout=client.heavy_timeout)
        return success(
            "get_entity_cooccurrences",
            data,
            meta=viewer_meta(endpoint, started_at),
        )
    except Exception as exc:
        return from_exception("get_entity_cooccurrences", endpoint, started_at, exc)
