"""Tests du client Viewer utilisé par le serveur MCP."""

from __future__ import annotations

from dataclasses import dataclass

import pytest
import requests

from mcp_server.errors import NotFoundError, UpstreamUnavailableError
from mcp_server.viewer_client import ViewerClient


@dataclass
class _FakeResponse:
    status_code: int
    payload: object
    headers: dict[str, str]
    text: str = ""

    def json(self):
        return self.payload


def test_viewer_client_get_returns_json(monkeypatch):
    client = ViewerClient("http://viewer:5050", timeout=5)

    def fake_request(**_kwargs):
        return _FakeResponse(
            status_code=200,
            payload={"ok": True},
            headers={"Content-Type": "application/json"},
        )

    monkeypatch.setattr(client.session, "request", fake_request)

    assert client.get("/api/runtime-info") == {"ok": True}


def test_viewer_client_maps_404(monkeypatch):
    client = ViewerClient("http://viewer:5050", timeout=5)

    def fake_request(**_kwargs):
        return _FakeResponse(
            status_code=404,
            payload={"error": "Introuvable"},
            headers={"Content-Type": "application/json"},
        )

    monkeypatch.setattr(client.session, "request", fake_request)

    with pytest.raises(NotFoundError):
        client.get("/api/missing")


def test_viewer_client_maps_timeout(monkeypatch):
    client = ViewerClient("http://viewer:5050", timeout=5)

    def fake_request(**_kwargs):
        raise requests.Timeout("boom")

    monkeypatch.setattr(client.session, "request", fake_request)

    with pytest.raises(UpstreamUnavailableError):
        client.get("/api/runtime-info")


def test_viewer_client_retries_get_once_on_timeout(monkeypatch):
    client = ViewerClient("http://viewer:5050", timeout=5)
    calls = {"count": 0}

    def fake_request(**_kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise requests.Timeout("boom")
        return _FakeResponse(
            status_code=200,
            payload={"ok": True},
            headers={"Content-Type": "application/json"},
        )

    monkeypatch.setattr(client.session, "request", fake_request)

    assert client.get("/api/runtime-info") == {"ok": True}
    assert calls["count"] == 2


def test_viewer_client_does_not_retry_post_on_timeout(monkeypatch):
    client = ViewerClient("http://viewer:5050", timeout=5)
    calls = {"count": 0}

    def fake_request(**_kwargs):
        calls["count"] += 1
        raise requests.Timeout("boom")

    monkeypatch.setattr(client.session, "request", fake_request)

    with pytest.raises(UpstreamUnavailableError):
        client.post("/api/annotations", json_body={"url": "https://example.com"})
    assert calls["count"] == 1


def test_viewer_client_supports_timeout_override(monkeypatch):
    client = ViewerClient("http://viewer:5050", timeout=5, heavy_timeout=30)
    captured: dict[str, object] = {}

    def fake_request(**kwargs):
        captured.update(kwargs)
        return _FakeResponse(
            status_code=200,
            payload={"ok": True},
            headers={"Content-Type": "application/json"},
        )

    monkeypatch.setattr(client.session, "request", fake_request)

    client.get("/api/entities/timeline", timeout=client.heavy_timeout)

    assert captured["timeout"] == 30
