"""Tests des enveloppes de réponse MCP."""

from __future__ import annotations

import time

from mcp_server.responses import failure, success, truncate_text, viewer_meta


def test_success_payload_shape():
    payload = success("demo_tool", {"value": 1}, warnings=["fallback_used"], meta={"endpoint": "/x"})

    assert payload == {
        "ok": True,
        "tool": "demo_tool",
        "data": {"value": 1},
        "warnings": ["fallback_used"],
        "meta": {"endpoint": "/x"},
    }


def test_failure_payload_shape():
    payload = failure(
        "demo_tool",
        "BAD_REQUEST",
        "Paramètre invalide",
        details={"field": "q"},
        meta={"endpoint": "/y"},
    )

    assert payload["ok"] is False
    assert payload["tool"] == "demo_tool"
    assert payload["error"]["code"] == "BAD_REQUEST"
    assert payload["error"]["details"] == {"field": "q"}


def test_viewer_meta_contains_expected_fields():
    started_at = time.perf_counter()
    meta = viewer_meta("/api/test", started_at)

    assert meta["source"] == "viewer-api"
    assert meta["endpoint"] == "/api/test"
    assert isinstance(meta["request_id"], str)
    assert meta["duration_ms"] >= 0


def test_truncate_text_flags_long_content():
    text, truncated = truncate_text("a" * 250_000)

    assert truncated is True
    assert len(text) == 200_000
