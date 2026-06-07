"""tests/test_api_v1.py — Tests du blueprint /api/v1 (sources + keywords).

Couvre :
  - GET/POST/PATCH/DELETE /api/v1/sources
  - GET/POST/PATCH/DELETE /api/v1/keywords
  - GET /api/v1/keywords/<id>/articles
  - Auth bearer via WUDD_API_TOKEN
  - Filtres include_inactive, tag, days
  - Soft delete vs hard delete
"""

from __future__ import annotations

import json
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def api_paths(tmp_path, monkeypatch):
    """Configure les chemins du blueprint api_v1 sur un tmp_path isolé."""
    import viewer.routes.api_v1 as mod

    opml = tmp_path / "WUDD.opml"
    keywords = tmp_path / "keyword-to-search.json"
    rss_dir = tmp_path / "articles-from-rss"
    rss_dir.mkdir()

    # OPML initial minimal
    root = ET.Element("opml", version="2.0")
    head = ET.SubElement(root, "head")
    ET.SubElement(head, "title").text = "WUDD.ai"
    ET.SubElement(root, "body")
    ET.ElementTree(root).write(opml, encoding="UTF-8", xml_declaration=True)

    # Keywords vide
    keywords.write_text("[]", encoding="utf-8")

    monkeypatch.setattr(mod, "_OPML_PATH", opml)
    monkeypatch.setattr(mod, "_KEYWORDS_PATH", keywords)
    monkeypatch.setattr(mod, "_RSS_ARTICLES_DIR", rss_dir)
    # Empêcher la résolution réseau du titre
    monkeypatch.setattr(mod, "_resolve_feed_title", lambda url: f"Titre auto {url[:20]}")

    # Désactiver le token (testé séparément)
    monkeypatch.delenv("WUDD_API_TOKEN", raising=False)

    return {"opml": opml, "keywords": keywords, "rss_dir": rss_dir}


@pytest.fixture
def client(api_paths, monkeypatch):
    """Client Flask pour interroger /api/v1."""
    from viewer.app import app as flask_app

    # viewer.app exécute load_dotenv() au moment de l'import, ce qui réinjecte
    # WUDD_API_TOKEN depuis .env après le delenv de api_paths. On le retire ici,
    # une fois l'import effectué, pour garantir une API ouverte par défaut.
    monkeypatch.delenv("WUDD_API_TOKEN", raising=False)

    flask_app.config["TESTING"] = True
    with flask_app.test_client() as c:
        yield c


def _post(client, url, body, headers=None):
    return client.post(url, data=json.dumps(body), content_type="application/json", headers=headers or {})


def _patch(client, url, body, headers=None):
    return client.patch(url, data=json.dumps(body), content_type="application/json", headers=headers or {})


# ── Sources ───────────────────────────────────────────────────────────────────


class TestSources:
    def test_list_empty(self, client):
        r = client.get("/api/v1/sources")
        assert r.status_code == 200
        assert r.get_json() == {"items": [], "total": 0}

    def test_create_minimal(self, client):
        r = _post(client, "/api/v1/sources", {"url": "https://example.com/feed.xml"})
        assert r.status_code == 201
        payload = r.get_json()
        assert payload["url"] == "https://example.com/feed.xml"
        assert payload["actif"] is True
        assert payload["nom"].startswith("Titre auto")
        assert len(payload["id"]) == 12

    def test_create_with_all_fields(self, client):
        body = {
            "url": "https://lemonde.fr/rss/une.xml",
            "nom": "Le Monde",
            "tags": ["presse", "généraliste"],
            "actif": True,
            "bypass_quota": True,
            "html_url": "https://lemonde.fr",
        }
        r = _post(client, "/api/v1/sources", body)
        assert r.status_code == 201
        p = r.get_json()
        assert p["nom"] == "Le Monde"
        assert p["tags"] == ["presse", "généraliste"]
        assert p["bypass_quota"] is True
        assert p["html_url"] == "https://lemonde.fr"

    def test_create_duplicate(self, client):
        body = {"url": "https://example.com/feed.xml"}
        _post(client, "/api/v1/sources", body)
        r = _post(client, "/api/v1/sources", body)
        assert r.status_code == 409
        assert "id" in r.get_json()

    def test_create_invalid_url(self, client):
        r = _post(client, "/api/v1/sources", {"url": "not-a-url"})
        assert r.status_code == 400

    def test_create_missing_url(self, client):
        r = _post(client, "/api/v1/sources", {})
        assert r.status_code == 400

    def test_list_filters_tags(self, client):
        _post(client, "/api/v1/sources", {"url": "https://a.com/rss", "tags": ["tech"]})
        _post(client, "/api/v1/sources", {"url": "https://b.com/rss", "tags": ["culture"]})
        r = client.get("/api/v1/sources?tag=tech")
        items = r.get_json()["items"]
        assert len(items) == 1
        assert "tech" in items[0]["tags"]

    def test_patch_updates_fields(self, client):
        created = _post(client, "/api/v1/sources", {"url": "https://x.com/rss"}).get_json()
        r = _patch(
            client,
            f"/api/v1/sources/{created['id']}",
            {"nom": "Nouveau", "tags": ["a", "b"]},
        )
        assert r.status_code == 200
        p = r.get_json()
        assert p["nom"] == "Nouveau"
        assert p["tags"] == ["a", "b"]

    def test_patch_unknown_id(self, client):
        r = _patch(client, "/api/v1/sources/deadbeef0000", {"nom": "x"})
        assert r.status_code == 404

    def test_soft_delete_default(self, client):
        created = _post(client, "/api/v1/sources", {"url": "https://x.com/rss"}).get_json()
        r = client.delete(f"/api/v1/sources/{created['id']}")
        assert r.status_code == 200
        assert r.get_json()["actif"] is False
        # Par défaut, la source désactivée disparaît de la liste
        listed = client.get("/api/v1/sources").get_json()["items"]
        assert listed == []
        # include_inactive=1 la fait réapparaître
        all_items = client.get("/api/v1/sources?include_inactive=1").get_json()["items"]
        assert len(all_items) == 1 and all_items[0]["actif"] is False

    def test_hard_delete_removes_entry(self, client, api_paths):
        created = _post(client, "/api/v1/sources", {"url": "https://x.com/rss"}).get_json()
        r = client.delete(f"/api/v1/sources/{created['id']}?hard=1")
        assert r.status_code == 200
        assert r.get_json()["mode"] == "hard"
        all_items = client.get("/api/v1/sources?include_inactive=1").get_json()["items"]
        assert all_items == []

    def test_reactivate_via_patch(self, client):
        created = _post(client, "/api/v1/sources", {"url": "https://x.com/rss"}).get_json()
        client.delete(f"/api/v1/sources/{created['id']}")
        r = _patch(client, f"/api/v1/sources/{created['id']}", {"actif": True})
        assert r.status_code == 200
        assert r.get_json()["actif"] is True


# ── Keywords ──────────────────────────────────────────────────────────────────


class TestKeywords:
    def test_list_empty(self, client):
        r = client.get("/api/v1/keywords")
        assert r.status_code == 200
        assert r.get_json() == {"items": [], "total": 0}

    def test_create_minimal(self, client):
        r = _post(client, "/api/v1/keywords", {"expression": "transformation digitale"})
        assert r.status_code == 201
        p = r.get_json()
        assert p["expression"] == "transformation digitale"
        assert p["tags"] == []
        assert p["ou"] == []
        assert p["et"] == []

    def test_create_with_synonyms_and_seuil(self, client):
        body = {
            "expression": "gouvernance des modèles",
            "tags": ["réglementation"],
            "seuil_alerte": 3,
            "ou": ["AI governance", "model governance"],
            "et": ["IA", "modèle"],
        }
        r = _post(client, "/api/v1/keywords", body)
        assert r.status_code == 201
        p = r.get_json()
        assert p["seuil_alerte"] == 3
        assert p["ou"] == ["AI governance", "model governance"]
        assert p["et"] == ["IA", "modèle"]
        assert p["tags"] == ["réglementation"]

    def test_create_duplicate(self, client):
        _post(client, "/api/v1/keywords", {"expression": "test"})
        r = _post(client, "/api/v1/keywords", {"expression": "test"})
        assert r.status_code == 409

    def test_create_missing_expression(self, client):
        r = _post(client, "/api/v1/keywords", {})
        assert r.status_code == 400

    def test_patch(self, client):
        created = _post(client, "/api/v1/keywords", {"expression": "kw1"}).get_json()
        r = _patch(client, f"/api/v1/keywords/{created['id']}", {"seuil_alerte": 5, "tags": ["x"]})
        assert r.status_code == 200
        p = r.get_json()
        assert p["seuil_alerte"] == 5
        assert p["tags"] == ["x"]

    def test_delete(self, client):
        created = _post(client, "/api/v1/keywords", {"expression": "todelete"}).get_json()
        r = client.delete(f"/api/v1/keywords/{created['id']}")
        assert r.status_code == 200
        assert client.get("/api/v1/keywords").get_json()["total"] == 0

    def test_delete_unknown(self, client):
        r = client.delete("/api/v1/keywords/000000000000")
        assert r.status_code == 404

    def test_keyword_articles_empty(self, client):
        created = _post(client, "/api/v1/keywords", {"expression": "[Art]"}).get_json()
        r = client.get(f"/api/v1/keywords/{created['id']}/articles")
        assert r.status_code == 200
        assert r.get_json()["items"] == []

    def test_keyword_articles_finds_file(self, client, api_paths):
        # Crée un mot-clé et un fichier matching
        created = _post(client, "/api/v1/keywords", {"expression": "[Art]"}).get_json()
        articles_file = api_paths["rss_dir"] / "Art.json"
        articles_file.write_text(
            json.dumps([
                {"URL": "https://x.com/1", "Date de publication": "01/05/2026", "Résumé": "a"},
                {"URL": "https://x.com/2", "Date de publication": "01/01/2020", "Résumé": "b"},
            ], ensure_ascii=False),
            encoding="utf-8",
        )
        r = client.get(f"/api/v1/keywords/{created['id']}/articles")
        assert r.status_code == 200
        assert r.get_json()["total"] == 2

    def test_keyword_articles_days_filter(self, client, api_paths):
        created = _post(client, "/api/v1/keywords", {"expression": "[Art]"}).get_json()
        from datetime import datetime, timedelta

        recent = datetime.now().strftime("%d/%m/%Y")
        old = (datetime.now() - timedelta(days=400)).strftime("%d/%m/%Y")
        (api_paths["rss_dir"] / "Art.json").write_text(
            json.dumps([
                {"URL": "https://x.com/r", "Date de publication": recent},
                {"URL": "https://x.com/o", "Date de publication": old},
            ], ensure_ascii=False),
            encoding="utf-8",
        )
        r = client.get(f"/api/v1/keywords/{created['id']}/articles?days=30")
        items = r.get_json()["items"]
        assert len(items) == 1
        assert items[0]["URL"] == "https://x.com/r"


# ── Auth ──────────────────────────────────────────────────────────────────────


class TestAuth:
    def test_no_token_no_auth(self, client):
        # WUDD_API_TOKEN absent → ouvert
        r = client.get("/api/v1/sources")
        assert r.status_code == 200

    def test_token_required_when_set(self, api_paths, monkeypatch):
        monkeypatch.setenv("WUDD_API_TOKEN", "secret-xyz")
        from viewer.app import app as flask_app

        flask_app.config["TESTING"] = True
        with flask_app.test_client() as c:
            r = c.get("/api/v1/sources")
            assert r.status_code == 401
            r = c.get("/api/v1/sources", headers={"Authorization": "Bearer wrong"})
            assert r.status_code == 401
            r = c.get("/api/v1/sources", headers={"Authorization": "Bearer secret-xyz"})
            assert r.status_code == 200
