"""tests/test_mcp_api_v1_tools.py — Tests des tools MCP sources + keywords.

Couvre les tools enregistrés via tool_registry.py qui wrappent /api/v1.
Utilise un FakeViewerClient qui simule les réponses du blueprint.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastmcp import FastMCP

from mcp_server.config import MCPConfig
from mcp_server.tool_registry import register_tools


class _FakeAPIv1Client:
    """Simule /api/v1/sources et /api/v1/keywords en mémoire."""

    heavy_timeout = 30

    def __init__(self):
        self._sources: dict[str, dict] = {}
        self._keywords: dict[str, dict] = {}
        self.last_call: dict | None = None

    def build_url(self, path: str) -> str:
        return f"http://viewer:5050{path}"

    def get(self, path: str, params=None, **_kwargs):
        self.last_call = {"method": "GET", "path": path, "params": params}
        if path == "/api/v1/sources":
            items = list(self._sources.values())
            if not (params and params.get("include_inactive") == "1"):
                items = [i for i in items if i["actif"]]
            if params and params.get("tag"):
                tag = params["tag"].lower()
                items = [
                    i for i in items if tag in [t.lower() for t in i["tags"]]
                ]
            return {"items": items, "total": len(items)}
        if path == "/api/v1/keywords":
            items = list(self._keywords.values())
            if params and params.get("tag"):
                tag = params["tag"].lower()
                items = [
                    i for i in items if tag in [t.lower() for t in i["tags"]]
                ]
            return {"items": items, "total": len(items)}
        if path.startswith("/api/v1/keywords/") and path.endswith("/articles"):
            kw_id = path.split("/")[4]
            if kw_id not in self._keywords:
                raise AssertionError(f"Keyword introuvable: {kw_id}")
            return {"expression": self._keywords[kw_id]["expression"], "items": [], "total": 0}
        raise AssertionError(f"GET inattendu: {path}")

    def post(self, path: str, json_body=None, **_kwargs):
        self.last_call = {"method": "POST", "path": path, "body": json_body}
        if path == "/api/v1/sources":
            sid = f"src{len(self._sources):04d}"
            entry = {
                "id": sid,
                "url": json_body["url"],
                "nom": json_body.get("nom") or "auto",
                "tags": json_body.get("tags", []),
                "actif": json_body.get("actif", True),
                "bypass_quota": json_body.get("bypass_quota", False),
                "html_url": json_body.get("html_url", ""),
            }
            self._sources[sid] = entry
            return entry
        if path == "/api/v1/keywords":
            kid = f"kw{len(self._keywords):04d}"
            entry = {
                "id": kid,
                "expression": json_body["expression"],
                "tags": json_body.get("tags", []),
                "seuil_alerte": json_body.get("seuil_alerte"),
                "ou": json_body.get("ou", []),
                "et": json_body.get("et", []),
            }
            self._keywords[kid] = entry
            return entry
        raise AssertionError(f"POST inattendu: {path}")

    def patch(self, path: str, json_body=None, **_kwargs):
        self.last_call = {"method": "PATCH", "path": path, "body": json_body}
        if path.startswith("/api/v1/sources/"):
            sid = path.rsplit("/", 1)[-1]
            if sid not in self._sources:
                raise AssertionError(f"Source introuvable: {sid}")
            self._sources[sid].update({k: v for k, v in json_body.items() if v is not None or k == "tags"})
            return self._sources[sid]
        if path.startswith("/api/v1/keywords/"):
            kid = path.rsplit("/", 1)[-1]
            if kid not in self._keywords:
                raise AssertionError(f"Keyword introuvable: {kid}")
            self._keywords[kid].update(json_body)
            return self._keywords[kid]
        raise AssertionError(f"PATCH inattendu: {path}")

    def delete(self, path: str, params=None, **_kwargs):
        self.last_call = {"method": "DELETE", "path": path, "params": params}
        if path.startswith("/api/v1/sources/"):
            sid = path.rsplit("/", 1)[-1]
            if params and params.get("hard") == "1":
                self._sources.pop(sid, None)
                return {"ok": True, "id": sid, "mode": "hard"}
            if sid in self._sources:
                self._sources[sid]["actif"] = False
                return self._sources[sid]
            return {"ok": False}
        if path.startswith("/api/v1/keywords/"):
            kid = path.rsplit("/", 1)[-1]
            if kid in self._keywords:
                expr = self._keywords.pop(kid)["expression"]
                return {"ok": True, "id": kid, "expression": expr}
            return {"ok": False}
        raise AssertionError(f"DELETE inattendu: {path}")


def _make_server(client: _FakeAPIv1Client, enable_write_tools: bool = True) -> FastMCP:
    server = FastMCP("test-api-v1")
    config = MCPConfig(
        project_root=Path.cwd(),
        host="127.0.0.1",
        port=8765,
        token="secret-token",
        viewer_base_url="http://viewer:5050",
        viewer_api_token="",
        enable_write_tools=enable_write_tools,
        request_timeout=10,
        heavy_request_timeout=30,
        log_level="INFO",
        streamable_http_path="/mcp",
    )
    register_tools(server, client, config)
    return server


# ── Sources ───────────────────────────────────────────────────────────────────


def test_list_sources_initially_empty():
    server = _make_server(_FakeAPIv1Client())
    result = asyncio.run(server.call_tool("list_sources"))
    assert result.structured_content["ok"] is True
    assert result.structured_content["data"]["items"] == []


def test_add_source_then_list():
    client = _FakeAPIv1Client()
    server = _make_server(client)
    asyncio.run(
        server.call_tool(
            "add_source",
            {"url": "https://lemonde.fr/rss", "nom": "Le Monde", "tags": ["presse"]},
        )
    )
    result = asyncio.run(server.call_tool("list_sources"))
    items = result.structured_content["data"]["items"]
    assert len(items) == 1
    assert items[0]["nom"] == "Le Monde"
    assert items[0]["tags"] == ["presse"]


def test_add_source_rejects_invalid_url():
    server = _make_server(_FakeAPIv1Client())
    result = asyncio.run(server.call_tool("add_source", {"url": "not-a-url"}))
    payload = result.structured_content
    assert payload["ok"] is False
    assert payload["error"]["code"] == "BAD_REQUEST"


def test_add_source_blocked_when_write_disabled():
    server = _make_server(_FakeAPIv1Client(), enable_write_tools=False)
    result = asyncio.run(
        server.call_tool("add_source", {"url": "https://x.com/rss"})
    )
    payload = result.structured_content
    assert payload["ok"] is False
    assert payload["error"]["code"] == "FORBIDDEN"


def test_toggle_source_flips_state():
    client = _FakeAPIv1Client()
    server = _make_server(client)
    added = asyncio.run(
        server.call_tool("add_source", {"url": "https://x.com/rss"})
    ).structured_content["data"]
    sid = added["id"]

    # Toggle sans paramètre → bascule actif → inactif
    r1 = asyncio.run(server.call_tool("toggle_source", {"source_id": sid}))
    assert r1.structured_content["data"]["actif"] is False
    # Toggle à nouveau → réactive
    r2 = asyncio.run(server.call_tool("toggle_source", {"source_id": sid}))
    assert r2.structured_content["data"]["actif"] is True


def test_update_source_changes_tags():
    client = _FakeAPIv1Client()
    server = _make_server(client)
    added = asyncio.run(
        server.call_tool("add_source", {"url": "https://x.com/rss"})
    ).structured_content["data"]
    r = asyncio.run(
        server.call_tool(
            "update_source",
            {"source_id": added["id"], "tags": ["nouveau"], "nom": "Nouveau nom"},
        )
    )
    payload = r.structured_content
    assert payload["ok"] is True
    assert payload["data"]["tags"] == ["nouveau"]
    assert payload["data"]["nom"] == "Nouveau nom"


def test_delete_source_soft_by_default():
    client = _FakeAPIv1Client()
    server = _make_server(client)
    added = asyncio.run(
        server.call_tool("add_source", {"url": "https://x.com/rss"})
    ).structured_content["data"]
    r = asyncio.run(server.call_tool("delete_source", {"source_id": added["id"]}))
    payload = r.structured_content
    assert payload["ok"] is True
    assert payload["data"]["action"] == "deactivated"


def test_delete_source_hard():
    client = _FakeAPIv1Client()
    server = _make_server(client)
    added = asyncio.run(
        server.call_tool("add_source", {"url": "https://x.com/rss"})
    ).structured_content["data"]
    r = asyncio.run(
        server.call_tool("delete_source", {"source_id": added["id"], "hard": True})
    )
    assert r.structured_content["data"]["action"] == "deleted"
    assert client.last_call["params"] == {"hard": "1"}


# ── Keywords ──────────────────────────────────────────────────────────────────


def test_add_keyword_minimal():
    client = _FakeAPIv1Client()
    server = _make_server(client)
    r = asyncio.run(
        server.call_tool("add_keyword", {"expression": "transformation digitale"})
    )
    payload = r.structured_content
    assert payload["ok"] is True
    assert payload["data"]["expression"] == "transformation digitale"


def test_add_keyword_with_seuil_and_synonyms():
    client = _FakeAPIv1Client()
    server = _make_server(client)
    r = asyncio.run(
        server.call_tool(
            "add_keyword",
            {
                "expression": "gouvernance des modèles",
                "tags": ["IA"],
                "seuil_alerte": 3,
                "ou": ["model governance"],
                "et": ["IA"],
            },
        )
    )
    data = r.structured_content["data"]
    assert data["seuil_alerte"] == 3
    assert data["ou"] == ["model governance"]


def test_add_keyword_requires_expression():
    server = _make_server(_FakeAPIv1Client())
    r = asyncio.run(server.call_tool("add_keyword", {}))
    assert r.structured_content["ok"] is False
    assert r.structured_content["error"]["code"] == "BAD_REQUEST"


def test_update_keyword_changes_seuil():
    client = _FakeAPIv1Client()
    server = _make_server(client)
    added = asyncio.run(
        server.call_tool("add_keyword", {"expression": "x"})
    ).structured_content["data"]
    r = asyncio.run(
        server.call_tool(
            "update_keyword", {"keyword_id": added["id"], "seuil_alerte": 7}
        )
    )
    assert r.structured_content["data"]["seuil_alerte"] == 7


def test_delete_keyword():
    client = _FakeAPIv1Client()
    server = _make_server(client)
    added = asyncio.run(
        server.call_tool("add_keyword", {"expression": "x"})
    ).structured_content["data"]
    r = asyncio.run(server.call_tool("delete_keyword", {"keyword_id": added["id"]}))
    assert r.structured_content["data"]["action"] == "deleted"


def test_get_keyword_articles_calls_correct_endpoint():
    client = _FakeAPIv1Client()
    server = _make_server(client)
    added = asyncio.run(
        server.call_tool("add_keyword", {"expression": "[Art]"})
    ).structured_content["data"]
    r = asyncio.run(
        server.call_tool(
            "get_keyword_articles", {"keyword_id": added["id"], "days": 30}
        )
    )
    payload = r.structured_content
    assert payload["ok"] is True
    assert client.last_call["path"] == f"/api/v1/keywords/{added['id']}/articles"
    assert client.last_call["params"] == {"days": 30}


def test_write_tools_disabled_blocks_keyword_add():
    server = _make_server(_FakeAPIv1Client(), enable_write_tools=False)
    r = asyncio.run(server.call_tool("add_keyword", {"expression": "x"}))
    assert r.structured_content["ok"] is False
    assert r.structured_content["error"]["code"] == "FORBIDDEN"
