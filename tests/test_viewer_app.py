"""Tests d'intégration pour le viewer Flask.

Couvre les routes critiques GET et quelques POST avec Flask test client.
Les routes qui appellent l'IA (SSE streaming, synthèses) sont exclues car
elles nécessitent des connexions réseau actives.

Structure :
  - TestRuntimeInfo        : GET /api/runtime-info
  - TestFilesRoutes        : GET /api/files, GET /api/content, GET /api/search
  - TestQuotaRoutes        : GET/POST /api/quota/config, GET /api/quota/stats, POST /api/quota/reset
  - TestSettingsRoutes     : GET /api/keywords, GET /api/ai-providers, GET /api/env
  - TestAnalyticsRoutes    : GET /api/alerts, GET /api/sources/bias, GET /api/articles/top
  - TestEntityRoutes       : GET /api/entities/dashboard, GET /api/entities/timeline
  - TestValidation         : POST avec body manquant/invalide → 400
"""

import importlib
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ─────────────────────────────────────────────────────────────────────────────
# Fixture : application Flask de test
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def app(tmp_path_factory):
    """Crée une instance Flask de test isolée."""
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setenv("WUDD_SKIP_STARTUP_REBUILD", "1")

    # Éviter la pollution des modules déjà chargés
    for mod in list(sys.modules.keys()):
        if "viewer.app" in mod:
            del sys.modules[mod]

    import viewer.app as app_module
    flask_app = app_module.app
    flask_app.config["TESTING"] = True
    flask_app.config["ACTIVE_VIEWER_PORT"] = 5059

    yield flask_app
    monkeypatch.undo()


@pytest.fixture()
def client(app):
    with app.test_client() as c:
        yield c


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/runtime-info
# ─────────────────────────────────────────────────────────────────────────────

class TestRuntimeInfo:
    def test_returns_200(self, client):
        resp = client.get("/api/runtime-info")
        assert resp.status_code == 200

    def test_contains_viewer_port(self, client):
        data = client.get("/api/runtime-info").get_json()
        assert "viewer_port" in data

    def test_contains_project_root(self, client):
        data = client.get("/api/runtime-info").get_json()
        assert "project_root" in data


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/files
# ─────────────────────────────────────────────────────────────────────────────

class TestFilesRoutes:
    def test_api_files_returns_list(self, client):
        resp = client.get("/api/files")
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, list)

    def test_api_content_without_path_returns_400(self, client):
        resp = client.get("/api/content")
        assert resp.status_code == 400

    def test_api_content_with_invalid_path_returns_400_or_404(self, client):
        resp = client.get("/api/content?path=../../../etc/passwd")
        assert resp.status_code in (400, 403, 404)

    def test_api_search_returns_results(self, client):
        resp = client.get("/api/search?q=test")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "results" in data or isinstance(data, list)

    def test_api_search_empty_query_ok(self, client):
        resp = client.get("/api/search?q=")
        # Soit 200 (résultat vide) soit 400 (q requis)
        assert resp.status_code in (200, 400)

    def test_api_download_without_path_returns_400(self, client):
        resp = client.get("/api/download")
        assert resp.status_code == 400

    def test_api_delete_without_path_returns_400(self, client):
        resp = client.delete("/api/files")
        assert resp.status_code in (400, 415, 422)


# ─────────────────────────────────────────────────────────────────────────────
# GET/POST /api/quota/*
# ─────────────────────────────────────────────────────────────────────────────

class TestQuotaRoutes:
    def test_get_quota_config_returns_200(self, client):
        resp = client.get("/api/quota/config")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "enabled" in data
        assert "global_daily_limit" in data

    def test_get_quota_stats_returns_200(self, client):
        resp = client.get("/api/quota/stats")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "global" in data

    def test_post_quota_reset_returns_200(self, client):
        resp = client.post("/api/quota/reset")
        assert resp.status_code == 200

    def test_post_quota_config_with_valid_body(self, client):
        payload = {"global_daily_limit": 200, "enabled": True}
        resp = client.post(
            "/api/quota/config",
            json=payload,
            content_type="application/json",
        )
        assert resp.status_code == 200

    def test_post_quota_config_without_body_returns_400(self, client):
        resp = client.post(
            "/api/quota/config",
            data="",
            content_type="application/json",
        )
        assert resp.status_code == 400


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/keywords, /api/ai-providers, /api/env
# ─────────────────────────────────────────────────────────────────────────────

class TestSettingsRoutes:
    def test_get_keywords_returns_list(self, client):
        resp = client.get("/api/keywords")
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, list)

    def test_get_ai_providers_returns_200(self, client):
        resp = client.get("/api/ai-providers")
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, dict) or isinstance(data, list)

    def test_get_env_does_not_expose_bearer(self, client):
        """Sécurité : la clé bearer ne doit jamais apparaître en clair."""
        resp = client.get("/api/env")
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "bearer" not in body.lower() or "***" in body or "****" in body

    def test_get_flux_sources_returns_200(self, client):
        resp = client.get("/api/flux-sources")
        assert resp.status_code == 200

    def test_get_rss_feeds_returns_200(self, client):
        resp = client.get("/api/rss-feeds")
        assert resp.status_code == 200

    def test_get_web_sources_returns_200(self, client):
        resp = client.get("/api/web-sources")
        assert resp.status_code == 200

    def test_get_ollama_status_returns_200_or_503(self, client):
        resp = client.get("/api/ollama/status")
        assert resp.status_code in (200, 503)


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/alerts, /api/sources/bias, /api/articles/top
# ─────────────────────────────────────────────────────────────────────────────

class TestAnalyticsRoutes:
    def test_get_alerts_returns_200(self, client):
        resp = client.get("/api/alerts")
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, list) or isinstance(data, dict)

    def test_get_articles_top_returns_200(self, client):
        resp = client.get("/api/articles/top")
        assert resp.status_code == 200

    def test_get_articles_top_uses_precomputed_snapshot_when_available(self, client):
        fake_articles = [{"URL": "https://example.com/1", "score_pertinence": 88.0}]
        with patch("utils.scoring.load_precomputed_top_articles", return_value=fake_articles), \
             patch("utils.scoring.get_scoring_engine") as mock_engine:
            resp = client.get("/api/articles/top?n=1&hours=48")

        assert resp.status_code == 200
        assert resp.get_json()[0]["URL"] == "https://example.com/1"
        mock_engine.assert_not_called()

    def test_get_sources_bias_returns_200(self, client):
        resp = client.get("/api/sources/bias")
        assert resp.status_code == 200

    def test_get_sources_credibility_returns_200(self, client):
        resp = client.get("/api/sources/credibility")
        assert resp.status_code == 200

    def test_get_cross_flux_returns_200(self, client):
        resp = client.get("/api/cross-flux")
        assert resp.status_code == 200

    def test_get_data_quality_returns_200(self, client):
        resp = client.get("/api/data-quality")
        assert resp.status_code == 200


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/entities/*
# ─────────────────────────────────────────────────────────────────────────────

class TestEntityRoutes:
    def test_get_entity_dashboard_returns_200(self, client):
        resp = client.get("/api/entities/dashboard")
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, dict) or isinstance(data, list)

    def test_get_entity_timeline_returns_200(self, client):
        resp = client.get("/api/entities/timeline")
        assert resp.status_code == 200

    def test_get_entity_timeline_uses_param_specific_cache_file(self, client, tmp_path):
        cache_file = tmp_path / "entity_timeline_90d_top30.json"
        cache_file.write_text(
            json.dumps(
                {
                    "generated_at": "2026-05-09T10:00:00Z",
                    "window_days": 90,
                    "top_entities": [{"key": "ORG:OpenAI", "type": "ORG", "value": "OpenAI", "total": 3}],
                    "timeline": {"ORG:OpenAI": {"2026-05-09": 3}},
                }
            ),
            encoding="utf-8",
        )

        with patch("viewer.routes.entities._timeline_cache_file", return_value=cache_file):
            resp = client.get("/api/entities/timeline?days=90&top=30")

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["window_days"] == 90

    def test_get_entity_timeline_supports_match_mode_and_all_types(self, client):
        with patch("scripts.entity_timeline.collect_timeline", return_value={"ALL:Trump": {"2026-05-09": 3}}) as mock_collect, \
             patch("scripts.entity_timeline.build_top_entities", return_value=[{"key": "ALL:Trump", "type": "ALL", "value": "Trump", "total": 3}]), \
             patch("scripts.entity_timeline.fill_missing_dates", return_value={"ALL:Trump": {"2026-05-09": 3}}), \
             patch("viewer.routes.entities.resolve_entity_matches", return_value=[{"type": "PERSON", "value": "Donald Trump", "count": 2}]):
            resp = client.get("/api/entities/timeline?days=30&entity=Trump&type=PERSON&match_mode=aggregate&all_types=1")

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["query"]["match_mode"] == "aggregate"
        assert data["query"]["all_types"] is True
        mock_collect.assert_called_once_with(
            PROJECT_ROOT,
            days=30,
            entity_filter="Trump",
            type_filter="PERSON",
            match_mode="aggregate",
            all_types=True,
            include_structural=False,
        )

    def test_get_entity_timeline_rejects_invalid_match_mode(self, client):
        resp = client.get("/api/entities/timeline?days=30&entity=Trump&type=PERSON&match_mode=exact")

        assert resp.status_code == 400
        data = resp.get_json()
        assert "match_mode invalide" in data["error"]
        assert "strict" in data["allowed_match_modes"]

    def test_get_entity_timeline_supports_structural_opt_in(self, client):
        with patch("scripts.entity_timeline.collect_timeline", return_value={"DATE:2026": {"2026-05-09": 2}}), \
             patch("scripts.entity_timeline.fill_missing_dates", return_value={"DATE:2026": {"2026-05-09": 2}}), \
             patch("scripts.entity_timeline.build_top_entities", return_value=[
                 {"key": "DATE:2026", "type": "DATE", "value": "2026", "total": 2}
             ]), \
             patch("viewer.routes.entities.resolve_entity_matches", return_value=[]):
            resp = client.get("/api/entities/timeline?days=30&type=DATE&include_structural=1&regenerate=1")

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["query"]["include_structural"] is True
        assert data["advanced_options"]["include_structural"]["default"] is False
        assert data["top_entities"][0]["type"] == "DATE"

    def test_get_entity_timeline_aggregate_uses_filled_series_for_total(self, client):
        build_results = [
            [{"key": "PERSON:Trump", "type": "PERSON", "value": "Trump", "total": 877}],
            [{"key": "PERSON:Trump", "type": "PERSON", "value": "Trump", "total": 121}],
        ]
        with patch("scripts.entity_timeline.collect_timeline", return_value={"PERSON:Trump": {"2026-05-09": 121}}), \
             patch("scripts.entity_timeline.fill_missing_dates", return_value={"PERSON:Trump": {"2026-05-09": 121}}), \
             patch("scripts.entity_timeline.build_top_entities", side_effect=build_results), \
             patch("viewer.routes.entities.resolve_entity_matches", return_value=[{"type": "PERSON", "value": "Donald Trump", "count": 2}]):
            resp = client.get("/api/entities/timeline?days=30&entity=Trump&type=PERSON&match_mode=aggregate")

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["top_entities"][0]["total"] == 121

    def test_get_entity_search_empty_returns_400_or_200(self, client):
        resp = client.get("/api/entities/search")
        # Query param 'q' ou 'entity' requis selon l'implémentation
        assert resp.status_code in (200, 400)

    def test_get_entity_search_uses_fast_index_search_when_available(self, client):
        mock_idx = MagicMock()
        mock_idx.search_values.return_value = [
            {
                "type": "ORG",
                "unique_count": 1,
                "mention_count": 2,
                "top": [{"value": "OpenAI", "count": 2}],
            }
        ]

        with patch("viewer.routes.entities.get_entity_index", return_value=mock_idx):
            resp = client.get("/api/entities/search?q=OpenAI")

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["by_type"][0]["top"][0]["value"] == "OpenAI"
        assert data["query"]["original"] == "OpenAI"
        assert data["query"]["include_structural"] is False
        mock_idx.search_values.assert_called_once_with("OpenAI", include_structural=False)

    def test_get_entity_search_supports_structural_opt_in(self, client):
        mock_idx = MagicMock()
        mock_idx.search_values.return_value = [
            {
                "type": "MONEY",
                "unique_count": 1,
                "mention_count": 2,
                "top": [{"value": "30 milliards de dollars", "count": 2}],
            }
        ]

        with patch("viewer.routes.entities.get_entity_index", return_value=mock_idx):
            resp = client.get("/api/entities/search?q=milliards&include_structural=1")

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["query"]["include_structural"] is True
        assert data["by_type"][0]["type"] == "MONEY"
        mock_idx.search_values.assert_called_once_with("milliards", include_structural=True)

    def test_get_entity_search_returns_expanded_query_metadata(self, client):
        with patch(
            "viewer.routes.entities._build_search_query_info",
            return_value={
                "original": "nLPD",
                "expanded_terms": ["nLPD", "protection des données"],
                "short_query": True,
            },
        ), patch("viewer.routes.entities.get_entity_index") as mock_idx:
            mock_idx.return_value.search_values.return_value = []
            resp = client.get("/api/entities/search?q=nLPD")

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["query"]["expanded_terms"][1] == "protection des données"

    def test_get_entity_cooccurrences_handles_low_volume_entity(self, client):
        mock_idx = MagicMock()
        mock_idx.load_articles.return_value = [
            {
                "entities": {
                    "ORG": ["AI Act", "Commission européenne"],
                    "GPE": ["Union européenne"],
                }
            }
        ]
        mock_idx.get_canonical_refs.side_effect = lambda etype, value: [{"file": "x", "idx": 0, "date": "2026-05-09"}]

        with patch("viewer.routes.entities.get_entity_index", return_value=mock_idx):
            resp = client.get("/api/entities/cooccurrences?type=ORG&value=AI%20Act")

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["nodes"][0]["type"] == "LAW"
        assert data["nodes"][0]["value"] == "AI Act"

    def test_get_entity_cooccurrences_falls_back_to_search_counts_for_structural_nodes(self, client):
        mock_idx = MagicMock()
        mock_idx.load_articles.return_value = [
            {
                "entities": {
                    "ORG": ["OpenAI", "Microsoft"],
                    "DATE": ["2026"],
                }
            }
        ]

        mock_idx.get_canonical_ref_count.return_value = 0

        def _canonical_refs(etype, value):
            if etype == "DATE":
                return []
            return [{"file": "x", "idx": 0, "date": "2026-05-09"}]

        mock_idx.get_canonical_refs.side_effect = _canonical_refs
        mock_idx.search_values.return_value = [
            {
                "type": "DATE",
                "unique_count": 1,
                "mention_count": 689,
                "top": [{"value": "2026", "count": 689}],
            }
        ]

        with patch("viewer.routes.entities.get_entity_index", return_value=mock_idx):
            resp = client.get("/api/entities/cooccurrences?type=ORG&value=OpenAI")

        assert resp.status_code == 200
        data = resp.get_json()
        date_node = next(node for node in data["nodes"] if node["type"] == "DATE" and node["value"] == "2026")
        assert date_node["total_count"] == 689
        assert data["meta"]["total_count_scope"].startswith("Couverture corpus")

    def test_get_entity_cooccurrences_uses_direct_canonical_count_when_available(self, client):
        mock_idx = MagicMock()
        mock_idx.load_articles.return_value = [
            {
                "entities": {
                    "ORG": ["OpenAI", "Microsoft"],
                    "DATE": ["2026"],
                }
            }
        ]

        def _canonical_count(etype, value):
            if etype == "DATE" and value == "2026":
                return 689
            return 12

        mock_idx.get_canonical_ref_count.side_effect = _canonical_count
        mock_idx.search_values.return_value = []

        with patch("viewer.routes.entities.get_entity_index", return_value=mock_idx):
            resp = client.get("/api/entities/cooccurrences?type=ORG&value=OpenAI")

        assert resp.status_code == 200
        data = resp.get_json()
        date_node = next(node for node in data["nodes"] if node["type"] == "DATE" and node["value"] == "2026")
        assert date_node["total_count"] == 689

    def test_get_entity_dashboard_supports_structural_opt_in(self, client):
        from viewer.routes import entities as entities_module

        entities_module._dashboard_cache.clear()
        mock_idx = MagicMock()
        mock_idx.get_all_entries.return_value = {
            "MONEY:30 milliards de dollars": [{"file": "x", "idx": 0, "date": "2026-05-09"}],
            "ORG:OpenAI": [{"file": "x", "idx": 1, "date": "2026-05-09"}],
        }
        mock_aidx = MagicMock()
        mock_aidx.stats.return_value = {"total_files": 1, "total": 2, "with_entities": 2}

        with patch("viewer.routes.entities.get_entity_index", return_value=mock_idx), \
             patch("viewer.routes.entities.get_article_index", return_value=mock_aidx), \
             patch("viewer.routes.entities.get_entity_canonicalizer") as mock_canonicalizer, \
             patch("utils.db.get_db") as mock_db:
            mock_canonicalizer.return_value.is_noise.return_value = False
            mock_db.return_value.available = False
            resp = client.get("/api/entities/dashboard?include_structural=1")

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["include_structural"] is True
        assert {item["type"] for item in data["by_type"]} == {"MONEY", "ORG"}
        mock_idx.get_all_entries.assert_called_once_with(include_structural=True)

    def test_get_entity_dashboard_exposes_sentiment_sample_coverage(self, client):
        from viewer.routes import entities as entities_module

        entities_module._dashboard_cache.clear()
        mock_idx = MagicMock()
        mock_idx.get_all_entries.return_value = {
            "ORG:OpenAI": [{"file": "x", "idx": 1, "date": "2026-05-09"}],
        }
        mock_aidx = MagicMock()
        mock_aidx.stats.return_value = {"total_files": 1, "total": 2, "with_entities": 2}
        mock_db = MagicMock()
        mock_db.available = True
        mock_db.reading_time_stats.return_value = {
            "avg_minutes": 2.0,
            "median_minutes": 2.0,
            "total_articles": 100,
        }
        mock_db.sentiment_distribution.return_value = [
            {"sentiment": "neutre", "count": 20, "pct": 50.0},
            {"sentiment": "positif", "count": 20, "pct": 50.0},
        ]
        mock_db.enrichment_coverage.return_value = {
            "total_articles": 100,
            "with_entities": 60,
            "with_sentiment": 25,
            "with_score_source": 70,
            "editorial_ready": 18,
            "ok_status": 12,
        }
        mock_db.article_stats_by_source.return_value = [{"source": "OpenAI", "article_count": 4}]

        with patch("viewer.routes.entities.get_entity_index", return_value=mock_idx), \
             patch("viewer.routes.entities.get_article_index", return_value=mock_aidx), \
             patch("viewer.routes.entities.get_entity_canonicalizer") as mock_canonicalizer, \
             patch("utils.db.get_db", return_value=mock_db):
            mock_canonicalizer.return_value.is_noise.return_value = False
            resp = client.get("/api/entities/dashboard?include_structural=1")

        assert resp.status_code == 200
        data = resp.get_json()
        meta = data["duckdb_stats"]["sentiment_7j_meta"]
        assert meta["sample_size"] == 40
        assert meta["coverage_pct_of_reading_time_7j"] == 40.0
        assert "sentiment non vide" in meta["basis"]
        enrichment = data["duckdb_stats"]["enrichment_7j"]
        assert enrichment["enrichissement_pct"] == 12.0
        assert enrichment["sentiment_coverage_pct"] == 25.0
        assert "complétude du pipeline" in enrichment["basis"]

    def test_get_watched_entities_returns_200(self, client):
        resp = client.get("/api/watched-entities")
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, list) or isinstance(data, dict)

    def test_get_entity_articles_supports_aggregate_matching(self, client, tmp_path):
        from viewer.routes import entities as entities_module

        source_file = tmp_path / "articles.json"
        source_file.write_text(
            json.dumps(
                [
                    {"URL": "https://example.com/a", "Date de publication": "2026-05-09", "Résumé": "Donald Trump."},
                    {"URL": "https://example.com/b", "Date de publication": "2026-05-08", "Résumé": "Trump Administration."},
                ]
            ),
            encoding="utf-8",
        )
        entities_module._entity_articles_cache.clear()

        with patch.object(entities_module, "PROJECT_ROOT", tmp_path), \
             patch("viewer.routes.entities.resolve_entity_matches", return_value=[
                 {"type": "PERSON", "value": "Donald Trump", "count": 2},
                 {"type": "ORG", "value": "Trump Administration", "count": 1},
             ]), \
             patch("viewer.routes.entities.load_match_refs", return_value=[
                 {"file": "articles.json", "idx": 0, "date": "2026-05-09"},
                 {"file": "articles.json", "idx": 1, "date": "2026-05-08"},
             ]):
            resp = client.get("/api/entities/articles?type=PERSON&value=Trump&match_mode=aggregate&all_types=1")

        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) == 2
        assert data[0]["URL"] == "https://example.com/a"

    def test_get_entity_articles_rejects_invalid_match_mode(self, client):
        resp = client.get("/api/entities/articles?type=PERSON&value=Trump&match_mode=full")

        assert resp.status_code == 400
        data = resp.get_json()
        assert "match_mode invalide" in data["error"]

    def test_get_entity_articles_rejects_invalid_sort_by(self, client):
        resp = client.get("/api/entities/articles?type=PERSON&value=Trump&sort_by=quality")

        assert resp.status_code == 400
        data = resp.get_json()
        assert "sort_by invalide" in data["error"]
        assert "relevance" in data["allowed_sort_by"]

    def test_get_entity_articles_sorts_by_score_source_and_keeps_compact_scoring_fields(self, client, tmp_path):
        from viewer.routes import entities as entities_module

        source_file = tmp_path / "articles.json"
        source_file.write_text(
            json.dumps(
                [
                    {
                        "URL": "https://example.com/a",
                        "Date de publication": "2026-05-08",
                        "Résumé": "Article A",
                        "Titre": "Titre A",
                        "score_source": 55,
                        "score_ton": 3,
                        "sentiment": "neutre",
                        "enrichissement_statut": "ok",
                    },
                    {
                        "URL": "https://example.com/b",
                        "Date de publication": "2026-05-09",
                        "Résumé": "Article B",
                        "Titre": "Titre B",
                        "score_source": 82,
                        "score_ton": 5,
                        "sentiment": "positif",
                        "enrichissement_statut": "ok",
                    },
                ]
            ),
            encoding="utf-8",
        )
        entities_module._entity_articles_cache.clear()

        with patch.object(entities_module, "PROJECT_ROOT", tmp_path), \
             patch("viewer.routes.entities.resolve_entity_matches", return_value=[
                 {"type": "ORG", "value": "AI Act", "count": 2},
             ]), \
             patch("viewer.routes.entities.load_match_refs", return_value=[
                 {"file": "articles.json", "idx": 0, "date": "2026-05-08"},
                 {"file": "articles.json", "idx": 1, "date": "2026-05-09"},
             ]):
            resp = client.get(
                "/api/entities/articles?type=ORG&value=AI%20Act&compact=1&sort_by=score_source"
            )

        assert resp.status_code == 200
        data = resp.get_json()
        assert [item["URL"] for item in data] == ["https://example.com/b", "https://example.com/a"]
        assert data[0]["score_source"] == 82
        assert data[0]["enrichissement_statut"] == "ok"
        assert "Titre" not in data[0]

    def test_watched_entities_post_canonicalizes_entity(self, client, tmp_path):
        from viewer.routes import entities as entities_module

        watched_file = tmp_path / "watched_entities.json"
        entities_module._watched_cache.clear()
        mock_idx = MagicMock()
        mock_idx.get_canonical_refs.return_value = [{"date": "2026-05-09"}]

        with patch.object(entities_module, "_WATCHED_FILE", watched_file), \
             patch("viewer.routes.entities.get_entity_index", return_value=mock_idx):
            post_resp = client.post(
                "/api/watched-entities",
                json={"type": "ORG", "value": "AI Act", "notes": "Veille"},
                content_type="application/json",
            )
            get_resp = client.get("/api/watched-entities")

        assert post_resp.status_code == 200
        assert post_resp.get_json()["type"] == "LAW"
        assert get_resp.status_code == 200
        watched = get_resp.get_json()
        assert watched[0]["type"] == "LAW"
        assert watched[0]["value"] == "AI Act"
        assert watched[0]["mentions_7d"] == 1
        mock_idx.get_canonical_refs.assert_called_with("LAW", "AI Act")

    def test_watched_entities_counts_date_only_yesterday_in_24h_window(self, client, tmp_path):
        from datetime import datetime, timedelta, timezone
        from viewer.routes import entities as entities_module

        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
        watched_file = tmp_path / "watched_entities.json"
        watched_file.write_text(
            json.dumps([{"type": "ORG", "value": "OpenAI"}], ensure_ascii=False),
            encoding="utf-8",
        )
        entities_module._watched_cache.clear()
        mock_idx = MagicMock()
        mock_idx.get_canonical_refs.return_value = [{"date": yesterday}]

        with patch.object(entities_module, "_WATCHED_FILE", watched_file), \
             patch("viewer.routes.entities.get_entity_index", return_value=mock_idx):
            resp = client.get("/api/watched-entities")

        assert resp.status_code == 200
        watched = resp.get_json()
        assert watched[0]["mentions_24h"] == 1
        assert watched[0]["mentions_7d"] == 1

    def test_watched_entities_delete_uses_canonical_entity(self, client, tmp_path):
        from viewer.routes import entities as entities_module

        watched_file = tmp_path / "watched_entities.json"
        watched_file.write_text(
            json.dumps([{"type": "LAW", "value": "AI Act", "added_at": "2026-05-09T00:00:00+00:00", "notes": ""}]),
            encoding="utf-8",
        )
        entities_module._watched_cache.clear()

        with patch.object(entities_module, "_WATCHED_FILE", watched_file):
            resp = client.delete("/api/watched-entities?type=ORG&value=AI%20Act")

        assert resp.status_code == 200
        payload = resp.get_json()
        assert payload["removed"] is True
        assert payload["type"] == "LAW"
        assert json.loads(watched_file.read_text(encoding="utf-8")) == []

    def test_get_annotations_returns_200(self, client):
        resp = client.get("/api/annotations")
        assert resp.status_code == 200

    def test_get_entity_export_returns_200(self, client):
        resp = client.get("/api/entities/export")
        assert resp.status_code == 200

    def test_post_invalidate_entity_dashboard_returns_200(self, client):
        resp = client.post("/api/entities/dashboard/invalidate")
        assert resp.status_code == 200


# ─────────────────────────────────────────────────────────────────────────────
# Validation : POST avec body manquant ou invalide → 400
# ─────────────────────────────────────────────────────────────────────────────

class TestValidationPOST:
    """Vérifie que les endpoints POST protégés par require_json_body() rejettent
    les requêtes sans body ou avec Content-Type incorrect."""

    def _post_no_body(self, client, url):
        return client.post(url, data="")

    def _post_wrong_ct(self, client, url):
        return client.post(url, data='{"key":"value"}', content_type="text/plain")

    def _post_invalid_json(self, client, url):
        return client.post(url, data="invalide{{{", content_type="application/json")

    def test_keywords_post_requires_json(self, client):
        resp = self._post_wrong_ct(client, "/api/keywords")
        assert resp.status_code in (400, 415)

    def test_rss_check_post_invalid_json_returns_400(self, client):
        resp = self._post_invalid_json(client, "/api/rss-feeds/check")
        assert resp.status_code == 400

    def test_watched_entities_post_requires_json(self, client):
        resp = self._post_wrong_ct(client, "/api/watched-entities")
        assert resp.status_code in (400, 415)

    def test_annotations_post_requires_json(self, client):
        resp = self._post_wrong_ct(client, "/api/annotations")
        assert resp.status_code in (400, 415)

    def test_quota_config_post_invalid_json_returns_400(self, client):
        resp = self._post_invalid_json(client, "/api/quota/config")
        assert resp.status_code == 400


# ─────────────────────────────────────────────────────────────────────────────
# Sécurité : path traversal
# ─────────────────────────────────────────────────────────────────────────────

class TestPathTraversalSecurity:
    @pytest.mark.parametrize("path", [
        "../../../etc/passwd",
        "..%2F..%2F..%2Fetc%2Fpasswd",
        "/etc/passwd",
        "../../../../.env",
    ])
    def test_content_rejects_traversal(self, client, path):
        resp = client.get(f"/api/content?path={path}")
        assert resp.status_code in (400, 403, 404)

    @pytest.mark.parametrize("path", [
        "../../../etc/passwd",
        "/etc/shadow",
    ])
    def test_download_rejects_traversal(self, client, path):
        resp = client.get(f"/api/download?path={path}")
        assert resp.status_code in (400, 403, 404)
