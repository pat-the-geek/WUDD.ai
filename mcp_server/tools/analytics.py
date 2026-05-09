"""Tools analytiques MCP."""

from __future__ import annotations

import time
from typing import Any

from ..errors import BadRequestError
from ..responses import from_exception, success, viewer_meta
from ..viewer_client import ViewerClient


def tool_get_alerts(
    client: ViewerClient,
    *,
    niveau: str | None = None,
    alert_type: str | None = None,
) -> dict:
    started_at = time.perf_counter()
    endpoint = "/api/alerts"
    try:
        params: dict[str, Any] = {}
        if niveau:
            normalized_level = niveau.strip()
            if normalized_level not in {"critique", "élevé", "modéré"}:
                raise BadRequestError("niveau doit valoir critique, élevé ou modéré")
            params["niveau"] = normalized_level
        if alert_type:
            normalized_type = alert_type.strip().lower()
            if normalized_type not in {"silence", "tendance"}:
                raise BadRequestError("type doit valoir silence ou tendance")
            params["type"] = normalized_type
        data = client.get(endpoint, params=params or None)
        return success("get_alerts", data, meta=viewer_meta(endpoint, started_at))
    except Exception as exc:
        return from_exception("get_alerts", endpoint, started_at, exc)


def tool_get_top_articles(
    client: ViewerClient,
    *,
    n: int = 10,
    hours: int = 48,
) -> dict:
    started_at = time.perf_counter()
    endpoint = "/api/articles/top"
    try:
        top_n = max(1, min(int(n), 50))
        window_hours = max(0, int(hours))
        data = client.get(endpoint, params={"n": top_n, "hours": window_hours})
        return success(
            "get_top_articles",
            data,
            meta=viewer_meta(endpoint, started_at),
        )
    except Exception as exc:
        return from_exception("get_top_articles", endpoint, started_at, exc)


def tool_get_data_quality(client: ViewerClient, *, dir_name: str = "all") -> dict:
    started_at = time.perf_counter()
    endpoint = "/api/data-quality"
    try:
        normalized_dir = (dir_name or "all").strip().lower()
        if normalized_dir not in {"articles", "rss", "all"}:
            raise BadRequestError("dir doit valoir articles, rss ou all")
        data = client.get(endpoint, params={"dir": normalized_dir})
        return success("get_data_quality", data, meta=viewer_meta(endpoint, started_at))
    except Exception as exc:
        return from_exception("get_data_quality", endpoint, started_at, exc)


def tool_get_cross_flux_analysis(
    client: ViewerClient,
    *,
    days: int = 30,
    min_flux: int = 2,
    top: int = 30,
) -> dict:
    started_at = time.perf_counter()
    endpoint = "/api/cross-flux"
    try:
        params = {
            "days": max(1, min(int(days), 365)),
            "min_flux": max(1, int(min_flux)),
            "top": max(1, min(int(top), 100)),
        }
        data = client.get(endpoint, params=params)
        return success(
            "get_cross_flux_analysis",
            data,
            meta=viewer_meta(endpoint, started_at),
        )
    except Exception as exc:
        return from_exception("get_cross_flux_analysis", endpoint, started_at, exc)
