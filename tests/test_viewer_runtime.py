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


def test_startup_warmup_skipped_by_env(monkeypatch):
    app_module = _import_viewer_app(monkeypatch)
    assert hasattr(app_module, "_startup_index_rebuild")
    assert app_module._startup_rebuild_started is False


def test_ensure_startup_index_rebuild_runs_once(monkeypatch):
    app_module = _import_viewer_app(monkeypatch)
    calls = {"count": 0}

    monkeypatch.delenv("WUDD_SKIP_STARTUP_REBUILD", raising=False)
    monkeypatch.setattr(
        app_module,
        "_startup_index_rebuild",
        lambda: calls.__setitem__("count", calls["count"] + 1),
    )

    class _FakeHandle:
        def fileno(self):
            return 42

    monkeypatch.setattr("builtins.open", lambda *_args, **_kwargs: _FakeHandle())
    monkeypatch.setattr(app_module.fcntl, "flock", lambda *_args, **_kwargs: None)

    app_module._startup_rebuild_started = False
    app_module._startup_rebuild_file_handle = None

    app_module._ensure_startup_index_rebuild()
    app_module._ensure_startup_index_rebuild()

    assert calls["count"] == 1
    assert app_module._startup_rebuild_started is True


def test_ensure_startup_index_rebuild_skips_when_lock_unavailable(monkeypatch):
    app_module = _import_viewer_app(monkeypatch)
    calls = {"count": 0}

    monkeypatch.delenv("WUDD_SKIP_STARTUP_REBUILD", raising=False)
    monkeypatch.setattr(
        app_module,
        "_startup_index_rebuild",
        lambda: calls.__setitem__("count", calls["count"] + 1),
    )
    app_module._startup_rebuild_started = False
    app_module._startup_rebuild_file_handle = None

    class _FakeHandle:
        def fileno(self):
            return 99

    monkeypatch.setattr("builtins.open", lambda *_args, **_kwargs: _FakeHandle())

    def fake_flock(_fd, _flags):
        raise OSError("busy")

    monkeypatch.setattr(app_module.fcntl, "flock", fake_flock)

    app_module._ensure_startup_index_rebuild()

    assert calls["count"] == 0
    assert app_module._startup_rebuild_started is True


def test_schedule_scoring_warmup_uses_timer_when_delayed(monkeypatch):
    app_module = _import_viewer_app(monkeypatch)
    scheduled = {}

    class _FakeTimer:
        def __init__(self, delay, target):
            scheduled["delay"] = delay
            scheduled["target"] = target
            self.daemon = False

        def start(self):
            scheduled["started"] = True

    monkeypatch.setattr(app_module.threading, "Timer", _FakeTimer)
    monkeypatch.setattr(app_module, "_run_scoring_warmup", lambda: scheduled.setdefault("ran", True))

    app_module._schedule_scoring_warmup(12)

    assert scheduled["delay"] == 12
    assert scheduled["target"] == app_module._run_scoring_warmup
    assert scheduled["started"] is True


def test_schedule_scoring_warmup_runs_immediately_when_delay_zero(monkeypatch):
    app_module = _import_viewer_app(monkeypatch)
    called = {"count": 0}

    monkeypatch.setattr(
        app_module,
        "_run_scoring_warmup",
        lambda: called.__setitem__("count", called["count"] + 1),
    )

    app_module._schedule_scoring_warmup(0)

    assert called["count"] == 1
