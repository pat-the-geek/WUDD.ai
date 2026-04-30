"""Tests unitaires pour utils/openapi.py.

Couvre :
  - generate_openapi_spec() : structure, version, paths, tags
  - _flask_rule_to_openapi_path() : conversion des règles Flask
  - register_openapi_endpoints() : endpoints /api/openapi.json et /api/docs
  - Sécurité : aucun secret dans la spec
"""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.openapi import (
    generate_openapi_spec,
    _flask_rule_to_openapi_path,
)


# ─────────────────────────────────────────────────────────────────────────────
# Fixture : application Flask de test
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def flask_app():
    import os
    os.environ.setdefault("WUDD_SKIP_STARTUP_REBUILD", "1")
    os.environ.setdefault("WUDD_SKIP_METRICS", "1")
    for mod in list(sys.modules.keys()):
        if "viewer.app" in mod:
            del sys.modules[mod]
    import viewer.app as app_module
    app_module.app.config["TESTING"] = True
    return app_module.app


@pytest.fixture(scope="module")
def spec(flask_app):
    return generate_openapi_spec(flask_app)


@pytest.fixture(scope="module")
def client(flask_app):
    with flask_app.test_client() as c:
        yield c


# ─────────────────────────────────────────────────────────────────────────────
# Conversion de règles Flask → chemins OpenAPI
# ─────────────────────────────────────────────────────────────────────────────

class TestFlaskRuleConversion:
    def test_simple_path_unchanged(self):
        assert _flask_rule_to_openapi_path("/api/files") == "/api/files"

    def test_int_param_converted(self):
        assert _flask_rule_to_openapi_path("/api/items/<int:id>") == "/api/items/{id}"

    def test_string_param_converted(self):
        assert _flask_rule_to_openapi_path("/api/files/<path:filename>") == "/api/files/{filename}"

    def test_bare_param_converted(self):
        assert _flask_rule_to_openapi_path("/api/entity/<name>") == "/api/entity/{name}"

    def test_multiple_params(self):
        result = _flask_rule_to_openapi_path("/api/<flux>/articles/<int:idx>")
        assert result == "/api/{flux}/articles/{idx}"


# ─────────────────────────────────────────────────────────────────────────────
# Structure de la spec OpenAPI
# ─────────────────────────────────────────────────────────────────────────────

class TestSpecStructure:
    def test_openapi_version_is_3(self, spec):
        assert spec["openapi"] == "3.0.3"

    def test_info_title(self, spec):
        assert "WUDD.ai" in spec["info"]["title"]

    def test_info_version_present(self, spec):
        assert "version" in spec["info"]

    def test_servers_present(self, spec):
        assert len(spec["servers"]) >= 1
        assert any("5050" in s["url"] for s in spec["servers"])

    def test_paths_present(self, spec):
        assert "paths" in spec
        assert len(spec["paths"]) > 0

    def test_tags_present(self, spec):
        assert "tags" in spec
        tag_names = [t["name"] for t in spec["tags"]]
        assert "Système" in tag_names
        assert "Entités" in tag_names
        assert "Quota" in tag_names

    def test_components_schemas_present(self, spec):
        assert "components" in spec
        assert "Article" in spec["components"]["schemas"]
        assert "ErrorResponse" in spec["components"]["schemas"]


# ─────────────────────────────────────────────────────────────────────────────
# Contenu des paths critiques
# ─────────────────────────────────────────────────────────────────────────────

class TestSpecPaths:
    def test_runtime_info_path_present(self, spec):
        assert "/api/runtime-info" in spec["paths"]

    def test_metrics_path_present(self, spec):
        assert "/metrics" in spec["paths"]

    def test_files_path_present(self, spec):
        assert "/api/files" in spec["paths"]

    def test_quota_config_get_and_post(self, spec):
        p = spec["paths"].get("/api/quota/config", {})
        assert "get" in p
        assert "post" in p

    def test_entities_dashboard_has_tags(self, spec):
        p = spec["paths"].get("/api/entities/dashboard", {})
        assert "get" in p
        tags = p["get"].get("tags", [])
        assert "Entités" in tags

    def test_alerts_path_has_summary(self, spec):
        p = spec["paths"].get("/api/alerts", {})
        assert "get" in p
        assert "summary" in p["get"]

    def test_all_operations_have_responses(self, spec):
        """Toutes les opérations doivent déclarer au moins une réponse."""
        for path, methods in spec["paths"].items():
            for method, op in methods.items():
                assert "responses" in op, f"Pas de 'responses' pour {method.upper()} {path}"

    def test_all_operations_have_operation_id(self, spec):
        """Chaque opération doit avoir un operationId unique."""
        op_ids = []
        for path, methods in spec["paths"].items():
            for method, op in methods.items():
                assert "operationId" in op, f"Pas d'operationId pour {method.upper()} {path}"
                op_ids.append(op["operationId"])
        assert len(op_ids) == len(set(op_ids)), "Doublons dans les operationId"

    def test_path_params_use_openapi_syntax(self, spec):
        """Aucun chemin ne doit contenir la syntaxe Flask <param>."""
        for path in spec["paths"]:
            assert "<" not in path, f"Syntaxe Flask non convertie dans le path : {path}"


# ─────────────────────────────────────────────────────────────────────────────
# Sécurité : aucun secret dans la spec
# ─────────────────────────────────────────────────────────────────────────────

class TestSpecSecurity:
    def test_no_bearer_token_in_spec(self, spec):
        import json
        spec_str = json.dumps(spec).lower()
        # "bearer" peut apparaître comme nom de variable dans la description, mais pas comme valeur
        assert "authorization: bearer" not in spec_str

    def test_no_password_fields(self, spec):
        import json
        spec_str = json.dumps(spec).lower()
        assert "password" not in spec_str


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints Flask : /api/openapi.json et /api/docs
# ─────────────────────────────────────────────────────────────────────────────

class TestOpenAPIEndpoints:
    def test_openapi_json_returns_200(self, client):
        resp = client.get("/api/openapi.json")
        assert resp.status_code == 200

    def test_openapi_json_content_type(self, client):
        resp = client.get("/api/openapi.json")
        assert "application/json" in resp.content_type

    def test_openapi_json_is_valid_spec(self, client):
        data = client.get("/api/openapi.json").get_json()
        assert data["openapi"] == "3.0.3"
        assert "paths" in data
        assert len(data["paths"]) > 0

    def test_docs_returns_200(self, client):
        resp = client.get("/api/docs")
        assert resp.status_code == 200

    def test_docs_content_type_html(self, client):
        resp = client.get("/api/docs")
        assert "text/html" in resp.content_type

    def test_docs_contains_swagger_ui(self, client):
        body = client.get("/api/docs").get_data(as_text=True)
        assert "swagger-ui" in body.lower()

    def test_docs_references_openapi_json(self, client):
        """La page Swagger UI doit pointer vers /api/openapi.json."""
        body = client.get("/api/docs").get_data(as_text=True)
        assert "/api/openapi.json" in body

    def test_openapi_json_cached_between_calls(self, client):
        """Deux appels successifs retournent la même spec (cache laziness)."""
        spec1 = client.get("/api/openapi.json").get_json()
        spec2 = client.get("/api/openapi.json").get_json()
        assert spec1["info"]["version"] == spec2["info"]["version"]
        assert len(spec1["paths"]) == len(spec2["paths"])
