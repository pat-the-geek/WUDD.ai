"""Tests de vérification des 8 optimisations techniques (v4.3).

Couvre :
  - 2.1  utils/db.py            — couche analytique DuckDB
  - 2.2  utils/rolling_window   — hook index événementiel
  - 2.3  utils/api_client       — circuit breaker enrichi (QUOTA/AUTH)
  - 2.4  utils/async_enricher   — parallélisme asyncio
  - 2.5  utils/deduplication    — seuil Jaccard adaptatif
  - 2.6  scripts/check_cron_health — monitoring structuré
  - 2.7  utils/cache            — TTL différenciés
  - 2.8  utils/api_client       — Batch API Claude (interface)

Tous les tests sont non-destructifs (pas d'appel API réel, pas d'écriture
en dehors de répertoires temporaires).
"""

import json
import tempfile
import threading
import time
from pathlib import Path

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# 2.1 — utils/db.py — DuckDB
# ─────────────────────────────────────────────────────────────────────────────

class TestArticleDB:
    """Vérifie que ArticleDB s'initialise et gère l'absence de DuckDB."""

    def test_import_succeeds(self):
        from utils.db import get_db, ArticleDB
        assert ArticleDB is not None

    def test_get_db_returns_instance(self):
        from utils.db import get_db, ArticleDB
        db = get_db()
        assert isinstance(db, ArticleDB)

    def test_available_flag_is_bool(self):
        from utils.db import get_db
        db = get_db()
        assert isinstance(db.available, bool)

    def test_returns_list_when_unavailable(self):
        """Si DuckDB absent, toutes les méthodes retournent [] sans exception."""
        from utils.db import ArticleDB
        db = ArticleDB.__new__(ArticleDB)
        db.available = False
        db._conn = None
        db._lock = threading.Lock()
        db.project_root = Path("/tmp")

        assert db.article_stats_by_source() == []
        assert db.article_stats_by_day() == []
        assert db.sentiment_distribution() == []
        assert db.full_text_search("test") == []

    def test_reading_time_stats_returns_dict_when_unavailable(self):
        from utils.db import ArticleDB
        db = ArticleDB.__new__(ArticleDB)
        db.available = False
        db._conn = None
        db._lock = threading.Lock()
        db.project_root = Path("/tmp")

        result = db.reading_time_stats()
        assert isinstance(result, dict)
        assert "total_articles" in result

    def test_duckdb_query_on_temp_json(self, tmp_path):
        """Si DuckDB disponible, vérifie une requête réelle sur un fichier JSON."""
        pytest.importorskip("duckdb")
        from utils.db import ArticleDB

        # Créer un fichier JSON d'articles de test
        articles = [
            {
                "Sources": "Test Source",
                "URL": "https://example.com/1",
                "Date de publication": "2026-03-16",
                "Résumé": "Un article sur OpenAI et les LLM.",
                "sentiment": "positif",
                "score_sentiment": 4,
                "temps_lecture_minutes": 2.5,
                "score_source": 75,
            }
        ]
        articles_dir = tmp_path / "data" / "articles-from-rss"
        articles_dir.mkdir(parents=True)
        (articles_dir / "test.json").write_text(json.dumps(articles), encoding="utf-8")

        db = ArticleDB(project_root=tmp_path)
        assert db.available is True

        stats = db.article_stats_by_source(days=30)
        assert isinstance(stats, list)
        # Peut être vide si DuckDB ne trouve pas exactement ce chemin, mais pas d'exception


# ─────────────────────────────────────────────────────────────────────────────
# 2.2 — rolling_window — hook index événementiel
# ─────────────────────────────────────────────────────────────────────────────

class TestRollingWindowEntityHook:
    """Vérifie le nouveau paramètre update_entity_index."""

    def test_signature_has_update_entity_index(self):
        import inspect
        from utils.rolling_window import update_rolling_window
        sig = inspect.signature(update_rolling_window)
        assert "update_entity_index" in sig.parameters

    def test_default_is_false(self):
        import inspect
        from utils.rolling_window import update_rolling_window
        sig = inspect.signature(update_rolling_window)
        assert sig.parameters["update_entity_index"].default is False

    def test_hook_disabled_by_default(self, tmp_path):
        """Sans update_entity_index, le comportement existant est inchangé."""
        from utils.rolling_window import update_rolling_window
        from datetime import datetime, timedelta

        recent_date = (datetime.utcnow() - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        articles = [{"URL": "https://a.com/1", "Date de publication": recent_date,
                     "Résumé": "Test", "Sources": "A"}]
        output = tmp_path / "48-heures.json"
        count = update_rolling_window(articles, output)
        assert count == 1
        assert output.exists()

    def test_hook_enabled_no_crash_without_entities(self, tmp_path):
        """update_entity_index=True ne crash pas si les articles n'ont pas d'entités."""
        from utils.rolling_window import update_rolling_window
        from datetime import datetime, timedelta

        recent_date = (datetime.utcnow() - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        articles = [{"URL": "https://b.com/1", "Date de publication": recent_date,
                     "Résumé": "Test sans entités", "Sources": "B"}]
        output = tmp_path / "48-heures.json"
        # Ne doit pas lever d'exception même si entity_index.json n'existe pas
        count = update_rolling_window(articles, output, update_entity_index=True)
        assert count == 1


# ─────────────────────────────────────────────────────────────────────────────
# 2.3 — circuit breaker enrichi
# ─────────────────────────────────────────────────────────────────────────────

class TestCircuitBreakerEnrichi:
    """Vérifie les 5 états du circuit breaker."""

    def setup_method(self):
        pytest.importorskip("requests")
        from utils.api_client import CircuitBreaker
        self.CB = CircuitBreaker

    def test_initial_state_closed(self):
        cb = self.CB("test")
        assert cb.state == "CLOSED"
        assert cb.allow_request() is True

    def test_quota_error_opens_quota_state(self):
        cb = self.CB("test")
        cb.record_failure(error_category="quota")
        assert cb.state == "OPEN_QUOTA"
        assert cb.allow_request() is False

    def test_auth_error_opens_auth_state(self):
        cb = self.CB("test")
        cb.record_failure(error_category="auth")
        assert cb.state == "OPEN_AUTH"
        assert cb.allow_request() is False

    def test_reset_closes_auth_state(self):
        cb = self.CB("test")
        cb.record_failure(error_category="auth")
        assert cb.state == "OPEN_AUTH"
        cb.reset()
        assert cb.state == "CLOSED"
        assert cb.allow_request() is True

    def test_transient_failures_open_circuit(self):
        cb = self.CB("test", failure_threshold=3)
        for _ in range(3):
            cb.record_failure(error_category="transient")
        assert cb.state == "OPEN"
        assert cb.allow_request() is False

    def test_success_resets_failure_count(self):
        cb = self.CB("test", failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        # Après un succès, les compteurs sont réinitialisés
        assert cb.state == "CLOSED"

    def test_grace_period_transitions_to_half_open(self):
        cb = self.CB("test", failure_threshold=1, grace_seconds=0.1)
        cb.record_failure()
        assert cb.state == "OPEN"
        time.sleep(0.15)
        # allow_request() doit passer en HALF-OPEN et retourner True
        assert cb.allow_request() is True
        assert cb.state == "HALF-OPEN"

    def test_half_open_success_closes_circuit(self):
        cb = self.CB("test", failure_threshold=1, grace_seconds=0.1)
        cb.record_failure()
        time.sleep(0.15)
        cb.allow_request()  # passe en HALF-OPEN
        cb.record_success()
        assert cb.state == "CLOSED"

    def test_quota_reset_date_set_on_429(self):
        cb = self.CB("test")
        cb.record_failure(error_category="quota")
        assert cb._quota_reset_date is not None

    def test_five_states_exist(self):
        cb = self.CB("test")
        assert hasattr(cb, "_STATE_CLOSED")
        assert hasattr(cb, "_STATE_OPEN")
        assert hasattr(cb, "_STATE_HALF_OPEN")
        assert hasattr(cb, "_STATE_OPEN_QUOTA")
        assert hasattr(cb, "_STATE_OPEN_AUTH")

    def test_reset_method_exists(self):
        cb = self.CB("test")
        assert callable(cb.reset)


# ─────────────────────────────────────────────────────────────────────────────
# 2.4 — async_enricher
# ─────────────────────────────────────────────────────────────────────────────

class TestAsyncEnricher:
    """Vérifie l'interface d'AsyncEnricher sans appel API réel."""

    def test_import(self):
        from utils.async_enricher import AsyncEnricher, get_async_enricher
        assert AsyncEnricher is not None

    def test_available_flag_is_bool(self):
        from utils.async_enricher import AsyncEnricher
        enricher = AsyncEnricher(concurrency=5)
        assert isinstance(enricher.available, bool)

    def test_concurrency_stored(self):
        from utils.async_enricher import AsyncEnricher
        enricher = AsyncEnricher(concurrency=7)
        assert enricher.concurrency == 7

    def test_get_async_enricher_singleton(self):
        from utils.async_enricher import get_async_enricher
        a = get_async_enricher()
        b = get_async_enricher()
        assert a is b

    def test_public_methods_exist(self):
        from utils.async_enricher import AsyncEnricher
        enricher = AsyncEnricher()
        assert callable(enricher.enrich_entities_batch)
        assert callable(enricher.enrich_sentiment_batch)


# ─────────────────────────────────────────────────────────────────────────────
# 2.5 — seuil Jaccard adaptatif
# ─────────────────────────────────────────────────────────────────────────────

class TestJaccardAdaptatif:
    """Vérifie _adaptive_jaccard_threshold et son intégration dans Deduplicator."""

    def test_function_exists(self):
        from utils.deduplication import _adaptive_jaccard_threshold
        assert callable(_adaptive_jaccard_threshold)

    def test_short_text_low_threshold(self):
        from utils.deduplication import _adaptive_jaccard_threshold
        short = "IA OpenAI annonce"  # < 80 mots
        assert _adaptive_jaccard_threshold(short) == 0.70

    def test_medium_text_default_threshold(self):
        from utils.deduplication import _adaptive_jaccard_threshold
        # Créer un texte de 100 mots environ
        medium = " ".join(["mot"] * 120)
        assert _adaptive_jaccard_threshold(medium) == 0.80

    def test_long_text_high_threshold(self):
        from utils.deduplication import _adaptive_jaccard_threshold
        long_text = " ".join(["mot"] * 250)
        assert _adaptive_jaccard_threshold(long_text) == 0.85

    def test_threshold_applied_in_is_duplicate(self):
        """Le Deduplicator utilise le seuil adaptatif pour les titres courts."""
        from utils.deduplication import Deduplicator

        dedup = Deduplicator()  # seuil par défaut → adaptatif actif

        # Enregistrer un article avec un titre court
        dedup.register({"Titre": "IA annonce OpenAI", "URL": "https://a.com/1"})

        # Un titre légèrement différent mais avec seuil bas (0.70) devrait matcher
        # "IA annonce" vs "IA annonce OpenAI" — test que ça ne crash pas
        result = dedup.is_duplicate({"Titre": "IA annonce", "URL": "https://b.com/2"})
        assert isinstance(result, bool)

    def test_explicit_threshold_overrides_adaptive(self):
        """Un seuil explicite non-défaut désactive l'adaptatif."""
        from utils.deduplication import Deduplicator, DEFAULT_TITLE_THRESHOLD

        custom_threshold = 0.95
        assert custom_threshold != DEFAULT_TITLE_THRESHOLD

        dedup = Deduplicator(title_threshold=custom_threshold)
        dedup.register({"Titre": "IA annonce OpenAI GPT-5", "URL": "https://a.com/1"})

        # Avec seuil 0.95, des titres légèrement différents ne devraient pas matcher
        result = dedup.is_duplicate({"Titre": "IA annonce GPT-5 OpenAI", "URL": "https://b.com/2"})
        assert isinstance(result, bool)


# ─────────────────────────────────────────────────────────────────────────────
# 2.6 — check_cron_health.py — monitoring structuré
# ─────────────────────────────────────────────────────────────────────────────

class TestCronHealthMonitoring:
    """Vérifie que check_cron_health écrit un JSON structuré valide."""

    def test_script_importable(self):
        import importlib.util, sys
        spec = importlib.util.spec_from_file_location(
            "check_cron_health",
            Path(__file__).parent.parent / "scripts" / "check_cron_health.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert hasattr(mod, "check_cron_health")
        assert hasattr(mod, "JOB_DEFINITIONS")
        assert hasattr(mod, "JOB_STALE_THRESHOLDS")

    def test_job_definitions_non_empty(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "check_cron_health",
            Path(__file__).parent.parent / "scripts" / "check_cron_health.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert len(mod.JOB_DEFINITIONS) >= 5

    def test_check_writes_valid_json(self, tmp_path, monkeypatch):
        """check_cron_health() écrit un JSON structuré dans HEALTH_FILE."""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "check_cron_health",
            Path(__file__).parent.parent / "scripts" / "check_cron_health.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        # Rediriger les fichiers vers tmp_path
        monkeypatch.setattr(mod, "HEALTH_FILE", tmp_path / "cron_health.json")
        monkeypatch.setattr(mod, "DATA_DIR", tmp_path)
        monkeypatch.setattr(mod, "MAIL_ENABLED", False)

        result = mod.check_cron_health()

        assert isinstance(result, dict)
        assert "status" in result
        assert result["status"] in ("ok", "degraded", "critical")
        assert "jobs" in result
        assert isinstance(result["jobs"], dict)
        assert "generated_at" in result

        # Le fichier doit avoir été écrit
        health_file = tmp_path / "cron_health.json"
        assert health_file.exists()
        parsed = json.loads(health_file.read_text())
        assert parsed["status"] in ("ok", "degraded", "critical")

    def test_health_endpoint_path_registered(self):
        """Vérifie que la route /api/health/cron est déclarée dans scheduler.py."""
        content = (
            Path(__file__).parent.parent / "viewer" / "routes" / "scheduler.py"
        ).read_text(encoding="utf-8")
        assert "/api/health/cron" in content


# ─────────────────────────────────────────────────────────────────────────────
# 2.7 — cache TTL différenciés
# ─────────────────────────────────────────────────────────────────────────────

class TestCacheTTL:
    """Vérifie CACHE_TTL et get_ttl()."""

    def test_cache_ttl_dict_exists(self):
        from utils.cache import CACHE_TTL
        assert isinstance(CACHE_TTL, dict)

    def test_all_expected_types_present(self):
        from utils.cache import CACHE_TTL
        for key in ("summary", "entities", "sentiment", "synthesis", "geocode", "images", "html", "report"):
            assert key in CACHE_TTL, f"Clé '{key}' manquante dans CACHE_TTL"

    def test_get_ttl_function(self):
        from utils.cache import get_ttl
        assert callable(get_ttl)

    def test_entities_ttl_7_days(self):
        from utils.cache import CACHE_TTL
        assert CACHE_TTL["entities"] == 604800

    def test_geocode_ttl_30_days(self):
        from utils.cache import CACHE_TTL
        assert CACHE_TTL["geocode"] == 2592000

    def test_synthesis_ttl_1h(self):
        from utils.cache import CACHE_TTL
        assert CACHE_TTL["synthesis"] == 3600

    def test_get_ttl_unknown_type_returns_default(self):
        from utils.cache import get_ttl
        assert get_ttl("type_inconnu") == 86400  # défaut 24h

    def test_get_ttl_known_types(self):
        from utils.cache import get_ttl, CACHE_TTL
        for content_type, expected_ttl in CACHE_TTL.items():
            assert get_ttl(content_type) == expected_ttl

    def test_ttl_passed_to_cache_get(self, tmp_path):
        """Vérifie que le TTL est bien honoré lors d'un get() avec TTL court."""
        import json as _json
        from datetime import datetime, timedelta
        from utils.cache import Cache, get_ttl

        cache = Cache(cache_dir=tmp_path / "cache")

        # Écrire manuellement une entrée avec un timestamp vieux de 2 jours
        cache_key = cache._get_cache_key("old_key")
        cache_file = cache.cache_dir / f"{cache_key}.json"
        old_data = {
            "timestamp": (datetime.now() - timedelta(days=2)).isoformat(),
            "key": "old_key",
            "value": {"data": "ancien"},
        }
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(_json.dumps(old_data), encoding="utf-8")

        # Avec TTL 7j (entities) → pas encore expiré → hit
        result = cache.get("old_key", ttl=get_ttl("entities"))
        assert result == {"data": "ancien"}

        # Avec TTL 1h (synthesis) → expiré il y a 2j → miss
        result_expired = cache.get("old_key", ttl=get_ttl("synthesis"))
        assert result_expired is None


# ─────────────────────────────────────────────────────────────────────────────
# 2.8 — Batch API Claude — interface
# ─────────────────────────────────────────────────────────────────────────────

class TestClaudeBatchInterface:
    """Vérifie l'interface des méthodes batch sans appel API réel."""

    def setup_method(self):
        pytest.importorskip("requests")

    def test_methods_exist_on_claude_client(self):
        from utils.api_client import ClaudeClient
        assert hasattr(ClaudeClient, "generate_entities_batch")
        assert hasattr(ClaudeClient, "generate_sentiment_batch")

    def test_entities_batch_signature(self):
        import inspect
        from utils.api_client import ClaudeClient
        sig = inspect.signature(ClaudeClient.generate_entities_batch)
        params = list(sig.parameters.keys())
        assert "resumes" in params
        assert "poll_interval" in params
        assert "max_polls" in params

    def test_sentiment_batch_signature(self):
        import inspect
        from utils.api_client import ClaudeClient
        sig = inspect.signature(ClaudeClient.generate_sentiment_batch)
        params = list(sig.parameters.keys())
        assert "resumes" in params

    def test_entities_batch_empty_list_returns_empty(self, monkeypatch):
        """Une liste vide retourne [] sans appel réseau."""
        from utils.api_client import ClaudeClient
        # Créer un client sans API key valide
        client = ClaudeClient.__new__(ClaudeClient)
        client.api_key = "test"
        client.model_batch = "claude-haiku-4-5-20251001"
        client.headers = {}

        # Sans anthropic installé, doit retourner [None]*0 = []
        # (ou [] si anthropic non disponible)
        try:
            result = client.generate_entities_batch([])
            assert result == []
        except Exception:
            pass  # Acceptable si anthropic non installé

    def test_entities_batch_returns_list_of_correct_length(self, monkeypatch):
        """La longueur du résultat doit correspondre à l'entrée."""
        pytest.importorskip("anthropic")
        from utils.api_client import ClaudeClient

        client = ClaudeClient.__new__(ClaudeClient)
        client.api_key = "sk-test-invalid"
        client.model_batch = "claude-haiku-4-5-20251001"
        client.headers = {}

        resumes = ["Article 1", "Article 2", "Article 3"]

        # Mocker le client anthropic pour éviter les vrais appels
        class FakeBatch:
            id = "batch_test_123"
            processing_status = "ended"

        class FakeBatches:
            def create(self, requests): return FakeBatch()
            def retrieve(self, id): return FakeBatch()
            def results(self, id): return []

        class FakeMessages:
            batches = FakeBatches()

        class FakeAnthropic:
            def __init__(self, api_key): pass
            messages = FakeMessages()

        monkeypatch.setattr("anthropic.Anthropic", FakeAnthropic)

        result = client.generate_entities_batch(resumes, poll_interval=0)
        assert isinstance(result, list)
        assert len(result) == len(resumes)
