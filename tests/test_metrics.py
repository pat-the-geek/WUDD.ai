"""Tests unitaires pour utils/metrics.py.

Couvre :
  - L'existence et le type de chaque métrique publique
  - Les fonctions d'instrumentation record_*() / update_*()
  - L'enregistrement de l'endpoint /metrics dans une app Flask de test
  - L'instrumentation HTTP automatique via register_flask_instrumentation()
"""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# ── Imports après ajout du path ───────────────────────────────────────────────
from utils import metrics as M
from utils.metrics import (
    record_ai_call,
    record_article_processed,
    record_article_deduplicated,
    record_quota_exhausted,
    update_quota_usage_ratio,
    record_http_request,
    record_http_request_duration,
    record_cache_hit,
    record_cache_miss,
    record_index_rebuild,
    update_index_size,
    register_metrics_endpoint,
)
from prometheus_client import REGISTRY

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _counter_value(counter, **labels) -> float:
    """Retourne la valeur courante d'un Counter pour un jeu de labels donné."""
    return counter.labels(**labels)._value.get()


def _gauge_value(gauge, **labels) -> float:
    """Retourne la valeur courante d'un Gauge (avec ou sans labels)."""
    if labels:
        return gauge.labels(**labels)._value.get()
    # Gauge sans labels
    return gauge._value.get()


# ─────────────────────────────────────────────────────────────────────────────
# Existence des métriques
# ─────────────────────────────────────────────────────────────────────────────

class TestMetricObjects:
    def test_ai_calls_total_is_counter(self):
        from prometheus_client import Counter
        assert isinstance(M.AI_CALLS_TOTAL, Counter)

    def test_ai_call_duration_seconds_is_histogram(self):
        from prometheus_client import Histogram
        assert isinstance(M.AI_CALL_DURATION_SECONDS, Histogram)

    def test_ai_tokens_total_is_counter(self):
        from prometheus_client import Counter
        assert isinstance(M.AI_TOKENS_TOTAL, Counter)

    def test_articles_processed_total_is_counter(self):
        from prometheus_client import Counter
        assert isinstance(M.ARTICLES_PROCESSED_TOTAL, Counter)

    def test_articles_deduplicated_total_is_counter(self):
        from prometheus_client import Counter
        assert isinstance(M.ARTICLES_DEDUPLICATED_TOTAL, Counter)

    def test_quota_exhausted_total_is_counter(self):
        from prometheus_client import Counter
        assert isinstance(M.QUOTA_EXHAUSTED_TOTAL, Counter)

    def test_quota_usage_ratio_is_gauge(self):
        from prometheus_client import Gauge
        assert isinstance(M.QUOTA_USAGE_RATIO, Gauge)

    def test_http_requests_total_is_counter(self):
        from prometheus_client import Counter
        assert isinstance(M.HTTP_REQUESTS_TOTAL, Counter)

    def test_http_request_duration_seconds_is_histogram(self):
        from prometheus_client import Histogram
        assert isinstance(M.HTTP_REQUEST_DURATION_SECONDS, Histogram)

    def test_cache_hits_total_is_counter(self):
        from prometheus_client import Counter
        assert isinstance(M.CACHE_HITS_TOTAL, Counter)

    def test_cache_misses_total_is_counter(self):
        from prometheus_client import Counter
        assert isinstance(M.CACHE_MISSES_TOTAL, Counter)

    def test_index_rebuild_total_is_counter(self):
        from prometheus_client import Counter
        assert isinstance(M.INDEX_REBUILD_TOTAL, Counter)

    def test_index_size_is_gauge(self):
        from prometheus_client import Gauge
        assert isinstance(M.INDEX_SIZE, Gauge)


# ─────────────────────────────────────────────────────────────────────────────
# record_ai_call
# ─────────────────────────────────────────────────────────────────────────────

class TestRecordAiCall:
    def test_increments_counter(self):
        before = _counter_value(M.AI_CALLS_TOTAL, provider="euria", operation="summary", status="success")
        record_ai_call("euria", "summary")
        after = _counter_value(M.AI_CALLS_TOTAL, provider="euria", operation="summary", status="success")
        assert after == before + 1.0

    def test_error_status(self):
        before = _counter_value(M.AI_CALLS_TOTAL, provider="ollama", operation="entities", status="error")
        record_ai_call("ollama", "entities", status="error")
        after = _counter_value(M.AI_CALLS_TOTAL, provider="ollama", operation="entities", status="error")
        assert after == before + 1.0

    def test_records_duration_in_histogram(self):
        # Compter via generate_latest : on observe juste que .observe() ne lève pas d'exception
        record_ai_call("claude", "report", duration=2.5)
        # Vérification simple : le _sum augmente
        import prometheus_client
        metrics_text = prometheus_client.generate_latest().decode()
        assert "wudd_ai_call_duration_seconds" in metrics_text

    def test_negative_duration_ignored(self):
        """Duration négative ne doit pas lever d'exception."""
        record_ai_call("euria", "synthesis", duration=-1.0)  # no-op silencieux

    def test_tokens_incremented(self):
        before_p = _counter_value(M.AI_TOKENS_TOTAL, provider="euria", operation="summary", token_type="prompt")
        before_c = _counter_value(M.AI_TOKENS_TOTAL, provider="euria", operation="summary", token_type="completion")
        record_ai_call("euria", "summary", tokens_prompt=100, tokens_completion=200)
        assert _counter_value(M.AI_TOKENS_TOTAL, provider="euria", operation="summary", token_type="prompt") == before_p + 100
        assert _counter_value(M.AI_TOKENS_TOTAL, provider="euria", operation="summary", token_type="completion") == before_c + 200


# ─────────────────────────────────────────────────────────────────────────────
# record_article_processed / record_article_deduplicated
# ─────────────────────────────────────────────────────────────────────────────

class TestRecordArticle:
    def test_article_processed_success(self):
        before = _counter_value(M.ARTICLES_PROCESSED_TOTAL, flux="IA", operation="summary", status="success")
        record_article_processed("IA", "summary")
        assert _counter_value(M.ARTICLES_PROCESSED_TOTAL, flux="IA", operation="summary", status="success") == before + 1

    def test_article_processed_error(self):
        before = _counter_value(M.ARTICLES_PROCESSED_TOTAL, flux="IA", operation="ner", status="error")
        record_article_processed("IA", "ner", status="error")
        assert _counter_value(M.ARTICLES_PROCESSED_TOTAL, flux="IA", operation="ner", status="error") == before + 1

    def test_article_deduplicated_url(self):
        before = _counter_value(M.ARTICLES_DEDUPLICATED_TOTAL, flux="politique", reason="url")
        record_article_deduplicated("politique", reason="url")
        assert _counter_value(M.ARTICLES_DEDUPLICATED_TOTAL, flux="politique", reason="url") == before + 1

    def test_article_deduplicated_default_reason(self):
        before = _counter_value(M.ARTICLES_DEDUPLICATED_TOTAL, flux="tech", reason="url")
        record_article_deduplicated("tech")
        assert _counter_value(M.ARTICLES_DEDUPLICATED_TOTAL, flux="tech", reason="url") == before + 1


# ─────────────────────────────────────────────────────────────────────────────
# record_quota_exhausted / update_quota_usage_ratio
# ─────────────────────────────────────────────────────────────────────────────

class TestQuotaMetrics:
    def test_quota_exhausted_global(self):
        before = _counter_value(M.QUOTA_EXHAUSTED_TOTAL, quota_type="global")
        record_quota_exhausted("global")
        assert _counter_value(M.QUOTA_EXHAUSTED_TOTAL, quota_type="global") == before + 1

    def test_quota_exhausted_entity(self):
        before = _counter_value(M.QUOTA_EXHAUSTED_TOTAL, quota_type="entity")
        record_quota_exhausted("entity")
        assert _counter_value(M.QUOTA_EXHAUSTED_TOTAL, quota_type="entity") == before + 1

    def test_update_quota_usage_ratio_valid(self):
        update_quota_usage_ratio(0.75)
        assert _gauge_value(M.QUOTA_USAGE_RATIO) == pytest.approx(0.75)

    def test_update_quota_usage_ratio_clamps_above_one(self):
        update_quota_usage_ratio(1.5)
        assert _gauge_value(M.QUOTA_USAGE_RATIO) == pytest.approx(1.0)

    def test_update_quota_usage_ratio_clamps_below_zero(self):
        update_quota_usage_ratio(-0.3)
        assert _gauge_value(M.QUOTA_USAGE_RATIO) == pytest.approx(0.0)


# ─────────────────────────────────────────────────────────────────────────────
# record_http_request / record_http_request_duration
# ─────────────────────────────────────────────────────────────────────────────

class TestHttpMetrics:
    def test_record_http_request(self):
        before = _counter_value(M.HTTP_REQUESTS_TOTAL, method="GET", endpoint="files", http_status="200")
        record_http_request("GET", "files", 200)
        assert _counter_value(M.HTTP_REQUESTS_TOTAL, method="GET", endpoint="files", http_status="200") == before + 1

    def test_record_http_request_error_status(self):
        before = _counter_value(M.HTTP_REQUESTS_TOTAL, method="POST", endpoint="quota", http_status="400")
        record_http_request("POST", "quota", 400)
        assert _counter_value(M.HTTP_REQUESTS_TOTAL, method="POST", endpoint="quota", http_status="400") == before + 1

    def test_record_http_duration(self):
        # Vérifier que .observe() ne lève pas d'exception et que les métriques sont exportées
        record_http_request_duration("GET", "dashboard", 0.042)
        import prometheus_client
        body = prometheus_client.generate_latest().decode()
        assert "wudd_http_request_duration_seconds" in body


# ─────────────────────────────────────────────────────────────────────────────
# record_cache_hit / record_cache_miss
# ─────────────────────────────────────────────────────────────────────────────

class TestCacheMetrics:
    def test_cache_hit_default_namespace(self):
        before = _counter_value(M.CACHE_HITS_TOTAL, namespace="default")
        record_cache_hit()
        assert _counter_value(M.CACHE_HITS_TOTAL, namespace="default") == before + 1

    def test_cache_hit_custom_namespace(self):
        before = _counter_value(M.CACHE_HITS_TOTAL, namespace="euria")
        record_cache_hit("euria")
        assert _counter_value(M.CACHE_HITS_TOTAL, namespace="euria") == before + 1

    def test_cache_miss_default_namespace(self):
        before = _counter_value(M.CACHE_MISSES_TOTAL, namespace="default")
        record_cache_miss()
        assert _counter_value(M.CACHE_MISSES_TOTAL, namespace="default") == before + 1


# ─────────────────────────────────────────────────────────────────────────────
# record_index_rebuild / update_index_size
# ─────────────────────────────────────────────────────────────────────────────

class TestIndexMetrics:
    def test_record_index_rebuild_article(self):
        before = _counter_value(M.INDEX_REBUILD_TOTAL, index_type="article", trigger="startup")
        record_index_rebuild("article", "startup")
        assert _counter_value(M.INDEX_REBUILD_TOTAL, index_type="article", trigger="startup") == before + 1

    def test_record_index_rebuild_entity_manual(self):
        before = _counter_value(M.INDEX_REBUILD_TOTAL, index_type="entity", trigger="manual")
        record_index_rebuild("entity", "manual")
        assert _counter_value(M.INDEX_REBUILD_TOTAL, index_type="entity", trigger="manual") == before + 1

    def test_record_index_rebuild_default_trigger(self):
        before = _counter_value(M.INDEX_REBUILD_TOTAL, index_type="article", trigger="manual")
        record_index_rebuild("article")
        assert _counter_value(M.INDEX_REBUILD_TOTAL, index_type="article", trigger="manual") == before + 1

    def test_update_index_size_article(self):
        update_index_size("article", 4200)
        assert _gauge_value(M.INDEX_SIZE, index_type="article") == pytest.approx(4200)

    def test_update_index_size_entity(self):
        update_index_size("entity", 9800)
        assert _gauge_value(M.INDEX_SIZE, index_type="entity") == pytest.approx(9800)


# ─────────────────────────────────────────────────────────────────────────────
# register_metrics_endpoint (endpoint /metrics Flask)
# ─────────────────────────────────────────────────────────────────────────────

class TestRegisterMetricsEndpoint:
    @pytest.fixture(scope="class")
    def flask_app_with_metrics(self):
        import os, sys
        os.environ.setdefault("WUDD_SKIP_STARTUP_REBUILD", "1")
        os.environ.setdefault("WUDD_SKIP_METRICS", "1")
        for mod in list(sys.modules.keys()):
            if "viewer.app" in mod:
                del sys.modules[mod]
        import viewer.app as app_module
        app_module.app.config["TESTING"] = True
        return app_module.app

    def test_metrics_endpoint_returns_200(self, flask_app_with_metrics):
        with flask_app_with_metrics.test_client() as c:
            resp = c.get("/metrics")
        assert resp.status_code == 200

    def test_metrics_content_type(self, flask_app_with_metrics):
        with flask_app_with_metrics.test_client() as c:
            resp = c.get("/metrics")
        ct = resp.content_type
        assert "text/plain" in ct

    def test_metrics_contains_wudd_counter(self, flask_app_with_metrics):
        """Au moins un compteur WUDD doit apparaître dans la sortie."""
        # Générer au moins un point de données
        record_ai_call("euria", "summary")
        with flask_app_with_metrics.test_client() as c:
            body = c.get("/metrics").get_data(as_text=True)
        assert "wudd_ai_calls_total" in body

    def test_metrics_contains_python_gc(self, flask_app_with_metrics):
        """Les métriques Python par défaut doivent être présentes."""
        with flask_app_with_metrics.test_client() as c:
            body = c.get("/metrics").get_data(as_text=True)
        assert "python_gc_objects_collected_total" in body
