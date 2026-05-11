"""Tests ciblés pour /api/entities/articles (validation query params et alias limit)."""

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture(scope="module")
def app():
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setenv("WUDD_SKIP_STARTUP_REBUILD", "1")

    for mod in list(sys.modules.keys()):
        if "viewer.app" in mod:
            del sys.modules[mod]

    import viewer.app as app_module

    flask_app = app_module.app
    flask_app.config["TESTING"] = True
    yield flask_app
    monkeypatch.undo()


@pytest.fixture()
def client(app):
    with app.test_client() as c:
        yield c


def test_entities_articles_accepts_limit_alias(client, tmp_path):
    from viewer.routes import entities as entities_module

    source_file = tmp_path / "articles.json"
    source_file.write_text(
        json.dumps(
            [
                {"URL": "https://example.com/a", "Date de publication": "2026-05-09", "Résumé": "A"},
                {"URL": "https://example.com/b", "Date de publication": "2026-05-08", "Résumé": "B"},
            ]
        ),
        encoding="utf-8",
    )
    entities_module._entity_articles_cache.clear()

    with patch.object(entities_module, "PROJECT_ROOT", tmp_path), \
         patch("viewer.routes.entities.resolve_entity_matches", return_value=[
             {"type": "PERSON", "value": "Sam Altman", "count": 2},
         ]), \
         patch("viewer.routes.entities.load_match_refs", return_value=[
             {"file": "articles.json", "idx": 0, "date": "2026-05-09"},
             {"file": "articles.json", "idx": 1, "date": "2026-05-08"},
         ]):
        resp = client.get("/api/entities/articles?type=PERSON&value=Sam%20Altman&limit=1")

    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data) == 1
    assert data[0]["URL"] == "https://example.com/a"


def test_entities_articles_rejects_unknown_query_param(client):
    resp = client.get("/api/entities/articles?type=PERSON&value=Trump&foo=bar")

    assert resp.status_code == 400
    data = resp.get_json()
    assert "foo" in data["unknown_params"]
    assert "allowed_params" in data
