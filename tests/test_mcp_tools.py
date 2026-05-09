"""Tests ciblés sur les tools MCP enregistrés."""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastmcp import FastMCP

from mcp_server.config import MCPConfig
from mcp_server.tool_registry import register_tools


class _FakeViewerClient:
    heavy_timeout = 30

    def __init__(self):
        self.last_get = None

    def build_url(self, path: str) -> str:
        return f"http://viewer:5050{path}"

    def get(self, path: str, params=None, **_kwargs):
        self.last_get = {"path": path, "params": params}
        if path == "/api/runtime-info":
            return {"viewer_port": 5050, "project_root": "/app"}
        if path == "/api/entities/search":
            return {"by_type": [{"type": "ORG", "top": [{"value": "OpenAI", "count": 3}]}]}
        if path == "/api/entities/articles":
            return [{"URL": "https://example.com", "Résumé": "Article"}]
        if path == "/api/entities/timeline":
            return {"timeline": {}, "top_entities": [], "window_days": params.get("days", 30)}
        if path == "/api/search":
            return [{"path": "data/articles/demo.json", "matches": [{"line": 1, "text": "OpenAI"}]}]
        if path == "/api/watched-entities":
            return [{"type": "ORG", "value": "OpenAI", "mentions_24h": 2, "mentions_7d": 8}]
        if path == "/api/content":
            return {"path": params["path"], "content": "demo"}
        raise AssertionError(f"Unexpected GET path: {path}")

    def post(self, path: str, json_body=None, **_kwargs):
        if path == "/api/watched-entities":
            if json_body and json_body.get("value") == "AI Act":
                return {"ok": True, "action": "added", "type": "LAW", "value": "AI Act"}
            return {"ok": True, "action": "added"}
        if path == "/api/annotations":
            return {"ok": True, "url": json_body["url"], "annotation": {"tags": json_body.get("tags", [])}}
        raise AssertionError(f"Unexpected POST path: {path}")

    def delete(self, path: str, params=None, **_kwargs):
        if path == "/api/watched-entities":
            return {"ok": True, "removed": True}
        if path == "/api/annotations":
            return {"ok": True, "removed": True}
        raise AssertionError(f"Unexpected DELETE path: {path}")


def _make_server(enable_write_tools: bool = True, client: _FakeViewerClient | None = None) -> FastMCP:
    server = FastMCP("test-mcp")
    config = MCPConfig(
        project_root=Path.cwd(),
        host="127.0.0.1",
        port=8765,
        token="secret-token",
        viewer_base_url="http://viewer:5050",
        enable_write_tools=enable_write_tools,
        request_timeout=10,
        heavy_request_timeout=30,
        log_level="INFO",
        streamable_http_path="/mcp",
    )
    register_tools(server, client or _FakeViewerClient(), config)
    return server


def test_wudd_health_tool_returns_contract_payload():
    server = _make_server()
    result = asyncio.run(server.call_tool("wudd_health"))

    assert result.structured_content["ok"] is True
    assert result.structured_content["tool"] == "wudd_health"
    assert result.structured_content["data"]["viewer_reachable"] is True


def test_search_entities_tool_returns_grouped_results():
    server = _make_server()
    result = asyncio.run(server.call_tool("search_entities", {"q": "OpenAI"}))

    payload = result.structured_content
    assert payload["ok"] is True
    assert payload["data"]["by_type"][0]["type"] == "ORG"


def test_watch_entity_tool_returns_added_action():
    server = _make_server()
    result = asyncio.run(
        server.call_tool(
            "watch_entity",
            {"type": "ORG", "value": "NVIDIA", "notes": "Veille"},
        )
    )

    payload = result.structured_content
    assert payload["ok"] is True
    assert payload["data"]["action"] == "added"
    assert payload["data"]["value"] == "NVIDIA"


def test_watch_entity_tool_preserves_canonical_payload():
    server = _make_server()
    result = asyncio.run(
        server.call_tool(
            "watch_entity",
            {"type": "ORG", "value": "AI Act", "notes": "Veille juridique"},
        )
    )

    payload = result.structured_content
    assert payload["ok"] is True
    assert payload["data"]["type"] == "LAW"
    assert payload["data"]["value"] == "AI Act"


def test_get_entity_timeline_tool_forwards_match_mode_and_all_types():
    client = _FakeViewerClient()
    server = _make_server(client=client)
    result = asyncio.run(
        server.call_tool(
            "get_entity_timeline",
            {
                "days": 30,
                "entity": "Trump",
                "type": "PERSON",
                "match_mode": "aggregate",
                "all_types": True,
            },
        )
    )

    payload = result.structured_content
    assert payload["ok"] is True
    assert client.last_get["path"] == "/api/entities/timeline"
    assert client.last_get["params"]["match_mode"] == "aggregate"
    assert client.last_get["params"]["all_types"] == "1"


def test_create_annotation_tool_respects_write_toggle():
    server = _make_server(enable_write_tools=False)
    result = asyncio.run(
        server.call_tool(
            "create_annotation",
            {"url": "https://example.com/article", "tags": ["ia"]},
        )
    )

    payload = result.structured_content
    assert payload["ok"] is False
    assert payload["error"]["code"] == "FORBIDDEN"


def test_export_dataset_returns_download_url():
    server = _make_server()
    result = asyncio.run(
        server.call_tool(
            "export_dataset",
            {"format": "csv", "path": "data/articles/demo.json"},
        )
    )

    payload = result.structured_content
    assert payload["ok"] is True
    assert payload["data"]["download_url"].endswith("/api/export/csv?path=data%2Farticles%2Fdemo.json")
