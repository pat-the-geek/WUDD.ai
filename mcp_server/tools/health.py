"""Tools de santé pour le serveur MCP."""

from __future__ import annotations

import time

from mcp_server import __version__

from ..config import MCPConfig
from ..responses import from_exception, success, viewer_meta
from ..viewer_client import ViewerClient

_ENDPOINT = "/api/runtime-info"


def tool_wudd_health(client: ViewerClient, config: MCPConfig) -> dict:
    started_at = time.perf_counter()
    try:
        runtime = client.get(_ENDPOINT)
        data = {
            "mcp_version": __version__,
            "viewer_reachable": True,
            "viewer": runtime,
            "write_tools_enabled": config.enable_write_tools,
            "transport": "streamable-http",
            "path": config.streamable_http_path,
        }
        return success("wudd_health", data, meta=viewer_meta(_ENDPOINT, started_at))
    except Exception as exc:
        return from_exception("wudd_health", _ENDPOINT, started_at, exc)
