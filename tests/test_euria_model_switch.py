"""Tests ciblés pour le changement de modèle EurIA et les endpoints viewer associés."""

import importlib
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

from utils.api_client import EURIA_DEFAULT_MODEL, EurIAClient


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _import_viewer_app(monkeypatch):
    monkeypatch.setenv("WUDD_SKIP_STARTUP_REBUILD", "1")
    sys.modules.pop("viewer.app", None)
    return importlib.import_module("viewer.app")


def _mock_response(payload=None, lines=None):
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = payload or {}
    resp.iter_lines.return_value = lines or []
    return resp


def test_euria_default_model_is_qwen35():
    client = EurIAClient(url="https://api.example.com/v1/chat/completions", bearer="token")
    assert client.model == EURIA_DEFAULT_MODEL


def test_euria_ask_retries_on_reasoning_only_response():
    client = EurIAClient(url="https://api.example.com/v1/chat/completions", bearer="token")
    first = _mock_response({
        "choices": [{"message": {"content": None, "reasoning": "analyse partielle"}}]
    })
    second = _mock_response({
        "choices": [{"message": {"content": "Réponse finale"}}]
    })

    with patch("utils.api_client.requests.post", side_effect=[first, second]) as post_mock:
        result = client.ask("Bonjour", max_attempts=2, timeout=1)

    assert result == "Réponse finale"
    assert post_mock.call_count == 2
    second_payload = post_mock.call_args_list[1].kwargs["json"]
    assert second_payload["model"] == EURIA_DEFAULT_MODEL
    assert second_payload["messages"][0]["role"] == "system"


def test_euria_stream_falls_back_when_stream_has_reasoning_only():
    client = EurIAClient(url="https://api.example.com/v1/chat/completions", bearer="token")
    stream_resp = _mock_response(lines=[
        b'data: {"choices":[{"delta":{"reasoning":"analyse"},"finish_reason":null}]}',
        b"data: [DONE]",
    ])

    with patch("utils.api_client.requests.post", return_value=stream_resp), \
         patch.object(client, "_complete_messages", return_value="Texte final SSE"):
        chunks = list(client.stream(prompt="Bonjour", timeout=1))

    joined = "".join(chunks)
    assert "Texte final SSE" in joined
    assert "data: [DONE]" in joined


def test_ai_check_returns_active_euria_model(monkeypatch):
    monkeypatch.setenv("URL", "https://api.example.com/v1/chat/completions")
    monkeypatch.setenv("bearer", "token")
    monkeypatch.setenv("AI_PROVIDER", "euria")
    app_module = _import_viewer_app(monkeypatch)
    app_module.app.config["TESTING"] = True

    with app_module.app.test_client() as client, \
         patch("utils.api_client.EurIAClient.ask", return_value="OK"):
        resp = client.post("/api/ai-check", json={"provider": "euria"})

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert data["active_model"] == EURIA_DEFAULT_MODEL


def test_keyword_suggest_endpoint_uses_euria_client(monkeypatch):
    monkeypatch.setenv("URL", "https://api.example.com/v1/chat/completions")
    monkeypatch.setenv("bearer", "token")
    monkeypatch.setenv("AI_PROVIDER", "euria")
    app_module = _import_viewer_app(monkeypatch)
    app_module.app.config["TESTING"] = True

    with app_module.app.test_client() as client, \
         patch("utils.api_client.EurIAClient.ask", return_value='{"ou": ["OpenAI"], "et": ["IA"]}'):
        resp = client.post("/api/keywords/suggest", json={"keyword": "OpenAI"})

    assert resp.status_code == 200
    assert resp.get_json() == {"ou": ["OpenAI"], "et": ["IA"]}


def test_chat_stream_endpoint_uses_euria_stream(monkeypatch):
    monkeypatch.setenv("URL", "https://api.example.com/v1/chat/completions")
    monkeypatch.setenv("bearer", "token")
    monkeypatch.setenv("AI_PROVIDER", "euria")
    app_module = _import_viewer_app(monkeypatch)
    app_module.app.config["TESTING"] = True

    sse_chunks = iter([
        'data: {"choices":[{"delta":{"content":"Bonjour"},"finish_reason":null}]}\n\n',
        "data: [DONE]\n\n",
    ])

    with app_module.app.test_client() as client, \
         patch("utils.api_client.EurIAClient.stream", autospec=True, return_value=sse_chunks) as stream_mock:
        resp = client.post(
            "/api/chat/stream",
            json={
                "provider": "euria",
                "messages": [{"role": "user", "content": "Salut"}],
                "web_search": True,
            },
        )

    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Bonjour" in body
    assert "[DONE]" in body
    _, kwargs = stream_mock.call_args
    assert kwargs["messages"][0]["role"] == "system"
    assert kwargs["messages"][1]["content"] == "Salut"
    assert kwargs["enable_web_search"] is True