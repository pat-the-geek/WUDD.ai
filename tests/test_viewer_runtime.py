"""Tests ciblés pour le runtime Flask du viewer."""

import importlib
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _import_viewer_app(monkeypatch):
    monkeypatch.setenv("WUDD_SKIP_STARTUP_REBUILD", "1")
    sys.modules.pop("viewer.app", None)
    return importlib.import_module("viewer.app")


def test_runtime_info_endpoint(monkeypatch):
    app_module = _import_viewer_app(monkeypatch)
    app_module.app.config["TESTING"] = True
    app_module.app.config["ACTIVE_VIEWER_PORT"] = 5057

    with app_module.app.test_client() as client:
        resp = client.get("/api/runtime-info")

    assert resp.status_code == 200
    assert resp.get_json() == {
        "viewer_port": 5057,
        "default_viewer_port": 5050,
        "project_root": str(app_module.PROJECT_ROOT),
    }


def test_resolve_viewer_port_skips_busy_default(monkeypatch):
    app_module = _import_viewer_app(monkeypatch)

    monkeypatch.delenv("WUDD_VIEWER_PORT", raising=False)
    monkeypatch.delenv("PORT", raising=False)

    def fake_port_is_free(_host, port):
        return port >= 5052

    monkeypatch.setattr(app_module, "_port_is_free", fake_port_is_free)

    resolved = app_module._resolve_viewer_port(default_port=5050, attempts=5)

    assert resolved == 5052


def test_resolve_viewer_port_prefers_explicit_env(monkeypatch):
    app_module = _import_viewer_app(monkeypatch)

    monkeypatch.setenv("WUDD_VIEWER_PORT", "5099")
    monkeypatch.setattr(app_module, "_port_is_free", lambda *_args: False)

    resolved = app_module._resolve_viewer_port(default_port=5050, attempts=3)

    assert resolved == 5099