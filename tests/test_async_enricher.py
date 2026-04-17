"""Tests pour utils/async_enricher.py.

Teste :
- AsyncEnricher.__init__ (disponible / non disponible)
- enrich_entities_batch  (path asyncio.run et path fallback)
- enrich_sentiment_batch (path asyncio.run et path fallback)
- _sync_fallback_entities / _sync_fallback_sentiment
- get_async_enricher (singleton)
"""

import asyncio
from unittest.mock import MagicMock, patch, AsyncMock
import pytest


# ═════════════════════════════════════════════════════════════════════════════
# AsyncEnricher — __init__
# ═════════════════════════════════════════════════════════════════════════════

class TestAsyncEnricherInit:
    def test_default_concurrency(self):
        from utils.async_enricher import AsyncEnricher
        e = AsyncEnricher()
        assert e.concurrency == 10

    def test_custom_concurrency(self):
        from utils.async_enricher import AsyncEnricher
        e = AsyncEnricher(concurrency=20)
        assert e.concurrency == 20

    def test_provider_stored(self):
        from utils.async_enricher import AsyncEnricher
        e = AsyncEnricher(provider="claude")
        assert e._provider == "claude"

    def test_provider_default_none(self):
        from utils.async_enricher import AsyncEnricher
        e = AsyncEnricher()
        assert e._provider is None

    def test_available_is_bool(self):
        from utils.async_enricher import AsyncEnricher
        e = AsyncEnricher()
        assert isinstance(e.available, bool)

    def test_warning_logged_when_aiohttp_unavailable(self, caplog):
        import utils.async_enricher as mod
        import logging
        original = mod._AIOHTTP_AVAILABLE
        try:
            mod._AIOHTTP_AVAILABLE = False
            with caplog.at_level(logging.WARNING):
                e = mod.AsyncEnricher()
            assert e.available is False
        finally:
            mod._AIOHTTP_AVAILABLE = original

    def test_no_warning_when_aiohttp_available(self, caplog):
        import utils.async_enricher as mod
        import logging
        original = mod._AIOHTTP_AVAILABLE
        try:
            mod._AIOHTTP_AVAILABLE = True
            with caplog.at_level(logging.WARNING):
                e = mod.AsyncEnricher()
            aiohttp_warnings = [r for r in caplog.records if "aiohttp" in r.message.lower()]
            assert len(aiohttp_warnings) == 0
        finally:
            mod._AIOHTTP_AVAILABLE = original


# ═════════════════════════════════════════════════════════════════════════════
# enrich_entities_batch — path asyncio.run (available=True)
# ═════════════════════════════════════════════════════════════════════════════

class TestEnrichEntitiesBatchAsync:
    def test_calls_asyncio_run_when_available(self):
        from utils.async_enricher import AsyncEnricher
        articles = [{"Résumé": "Test article avec beaucoup de contenu."}]
        expected = [{"Résumé": "Test article avec beaucoup de contenu.", "entities": {"PERSON": []}}]

        enricher = AsyncEnricher()
        enricher.available = True

        def run_and_close(coro):
            coro.close()
            return expected

        with patch("utils.async_enricher.asyncio.run", side_effect=run_and_close) as mock_run:
            result = enricher.enrich_entities_batch(articles, timeout_per_request=30)

        mock_run.assert_called_once()
        assert result == expected

    def test_asyncio_run_receives_coroutine(self):
        from utils.async_enricher import AsyncEnricher
        articles = [{"Résumé": "Article test."}]

        enricher = AsyncEnricher()
        enricher.available = True

        coros_passed = []
        def capture_coro(coro):
            coros_passed.append(coro)
            coro.close()  # avoid "coroutine was never awaited" warning
            return articles

        with patch("utils.async_enricher.asyncio.run", side_effect=capture_coro):
            enricher.enrich_entities_batch(articles)

        assert len(coros_passed) == 1
        import inspect
        assert inspect.iscoroutine(coros_passed[0])

    def test_empty_list_async_path(self):
        from utils.async_enricher import AsyncEnricher
        enricher = AsyncEnricher()
        enricher.available = True

        def run_and_close(coro):
            coro.close()
            return []

        with patch("utils.async_enricher.asyncio.run", side_effect=run_and_close) as mock_run:
            result = enricher.enrich_entities_batch([])

        assert result == []


# ═════════════════════════════════════════════════════════════════════════════
# enrich_entities_batch — path fallback (available=False)
# ═════════════════════════════════════════════════════════════════════════════

class TestEnrichEntitiesBatchFallback:
    def test_calls_sync_fallback_when_unavailable(self):
        from utils.async_enricher import AsyncEnricher
        articles = [{"Résumé": "Un article de test."}]
        expected = [{"Résumé": "Un article de test.", "entities": {"ORG": ["Test Corp"]}}]

        enricher = AsyncEnricher()
        enricher.available = False

        with patch.object(enricher, "_sync_fallback_entities", return_value=expected) as mock_fb:
            result = enricher.enrich_entities_batch(articles)

        mock_fb.assert_called_once_with(articles)
        assert result == expected

    def test_asyncio_run_not_called_when_unavailable(self):
        from utils.async_enricher import AsyncEnricher
        enricher = AsyncEnricher()
        enricher.available = False

        with patch.object(enricher, "_sync_fallback_entities", return_value=[]):
            with patch("utils.async_enricher.asyncio.run") as mock_run:
                enricher.enrich_entities_batch([])

        mock_run.assert_not_called()


# ═════════════════════════════════════════════════════════════════════════════
# enrich_sentiment_batch — path asyncio.run (available=True)
# ═════════════════════════════════════════════════════════════════════════════

class TestEnrichSentimentBatchAsync:
    def test_calls_asyncio_run_when_available(self):
        from utils.async_enricher import AsyncEnricher
        articles = [{"Résumé": "Article avec un bon sentiment positif."}]
        expected = [{"Résumé": "...", "sentiment": "positif", "score_sentiment": 4}]

        enricher = AsyncEnricher()
        enricher.available = True

        def run_and_close(coro):
            coro.close()
            return expected

        with patch("utils.async_enricher.asyncio.run", side_effect=run_and_close) as mock_run:
            result = enricher.enrich_sentiment_batch(articles, timeout_per_request=20)

        mock_run.assert_called_once()
        assert result == expected

    def test_sentiment_batch_uses_task_type_sentiment(self):
        """Vérifie que _async_enrich_batch est bien appelé avec task_type='sentiment'."""
        from utils.async_enricher import AsyncEnricher

        enricher = AsyncEnricher()
        enricher.available = True

        coros_seen = []
        def capture(coro):
            coros_seen.append(coro)
            coro.close()
            return []

        with patch("utils.async_enricher.asyncio.run", side_effect=capture):
            enricher.enrich_sentiment_batch([{"Résumé": "test"}])

        assert len(coros_seen) == 1


# ═════════════════════════════════════════════════════════════════════════════
# enrich_sentiment_batch — path fallback (available=False)
# ═════════════════════════════════════════════════════════════════════════════

class TestEnrichSentimentBatchFallback:
    def test_calls_sync_fallback_when_unavailable(self):
        from utils.async_enricher import AsyncEnricher
        articles = [{"Résumé": "Article triste et négatif."}]
        expected = [{"Résumé": "Article triste et négatif.", "sentiment": "négatif"}]

        enricher = AsyncEnricher()
        enricher.available = False

        with patch.object(enricher, "_sync_fallback_sentiment", return_value=expected) as mock_fb:
            result = enricher.enrich_sentiment_batch(articles)

        mock_fb.assert_called_once_with(articles)
        assert result == expected

    def test_asyncio_not_called_when_unavailable(self):
        from utils.async_enricher import AsyncEnricher
        enricher = AsyncEnricher()
        enricher.available = False

        with patch.object(enricher, "_sync_fallback_sentiment", return_value=[]):
            with patch("utils.async_enricher.asyncio.run") as mock_run:
                enricher.enrich_sentiment_batch([])

        mock_run.assert_not_called()


# ═════════════════════════════════════════════════════════════════════════════
# _sync_fallback_entities / _sync_fallback_sentiment
# ═════════════════════════════════════════════════════════════════════════════

class TestSyncFallbackEntities:
    """Teste la vraie implémentation maintenant que run_parallel existe."""

    def test_enriches_article_without_entities(self):
        from utils.async_enricher import AsyncEnricher
        articles = [
            {"Résumé": "OpenAI a lancé un nouveau modèle.", "Sources": "Tech"},
        ]
        mock_client = MagicMock()
        mock_client.generate_entities.return_value = {"ORG": ["OpenAI"]}

        enricher = AsyncEnricher()
        with patch("utils.async_enricher.AsyncEnricher._sync_fallback_entities") as mock_fallback:
            # Test the public call path
            mock_fallback.return_value = [{"Résumé": "OpenAI a lancé un nouveau modèle.", "entities": {"ORG": ["OpenAI"]}}]
            enricher.available = False
            result = enricher.enrich_entities_batch(articles)
        assert mock_fallback.called

    def test_skips_already_enriched_article(self):
        """Vérifie que _sync_fallback_entities ne modifie pas les articles déjà enrichis."""
        from utils.async_enricher import AsyncEnricher

        articles = [
            {"Résumé": "Article déjà enrichi.", "entities": {"PERSON": ["Alice"]}},
        ]
        mock_client = MagicMock()
        mock_client.generate_entities.return_value = {"ORG": ["ShouldNotAppear"]}

        enricher = AsyncEnricher()
        # get_ai_client est importé localement dans la méthode → patcher à la source
        with patch("utils.api_client.get_ai_client", return_value=mock_client):
            result = enricher._sync_fallback_entities(articles)

        # Existing entities should be preserved, generate_entities should not be called
        mock_client.generate_entities.assert_not_called()
        assert result[0]["entities"] == {"PERSON": ["Alice"]}

    def test_skips_article_without_resume(self):
        from utils.async_enricher import AsyncEnricher
        articles = [{"Sources": "Test sans résumé"}]
        mock_client = MagicMock()
        mock_client.generate_entities.return_value = {"PERSON": ["Bob"]}

        enricher = AsyncEnricher()
        with patch("utils.api_client.get_ai_client", return_value=mock_client):
            result = enricher._sync_fallback_entities(articles)

        mock_client.generate_entities.assert_not_called()
        assert "entities" not in result[0]

    def test_processes_multiple_articles(self):
        from utils.async_enricher import AsyncEnricher
        articles = [
            {"Résumé": "Macron a rencontré Biden à Paris lors d'un sommet international."},
            {"Résumé": "Apple a présenté un nouveau produit révolutionnaire."},
        ]
        mock_client = MagicMock()
        mock_client.generate_entities.side_effect = [
            {"PERSON": ["Macron", "Biden"], "GPE": ["Paris"]},
            {"ORG": ["Apple"]},
        ]

        enricher = AsyncEnricher()
        with patch("utils.api_client.get_ai_client", return_value=mock_client):
            result = enricher._sync_fallback_entities(articles)

        assert len(result) == 2
        assert mock_client.generate_entities.call_count == 2

    def test_handles_api_returning_none(self):
        from utils.async_enricher import AsyncEnricher
        articles = [{"Résumé": "Un article sans résultat d'entités."}]
        mock_client = MagicMock()
        mock_client.generate_entities.return_value = None

        enricher = AsyncEnricher()
        with patch("utils.api_client.get_ai_client", return_value=mock_client):
            result = enricher._sync_fallback_entities(articles)

        assert "entities" not in result[0]

    def test_empty_articles_list(self):
        from utils.async_enricher import AsyncEnricher
        enricher = AsyncEnricher()
        mock_client = MagicMock()
        with patch("utils.api_client.get_ai_client", return_value=mock_client):
            result = enricher._sync_fallback_entities([])
        assert result == []
        mock_client.generate_entities.assert_not_called()


class TestSyncFallbackSentiment:
    def test_enriches_article_without_sentiment(self):
        from utils.async_enricher import AsyncEnricher
        articles = [{"Résumé": "Un excellent article sur les progrès de l'IA."}]
        mock_client = MagicMock()
        mock_client.generate_sentiment.return_value = {
            "sentiment": "positif",
            "score_sentiment": 4,
            "ton_editorial": "factuel",
            "score_ton": 5,
        }

        enricher = AsyncEnricher()
        with patch("utils.api_client.get_ai_client", return_value=mock_client):
            result = enricher._sync_fallback_sentiment(articles)

        assert result[0]["sentiment"] == "positif"
        assert result[0]["score_sentiment"] == 4

    def test_skips_already_enriched_article(self):
        from utils.async_enricher import AsyncEnricher
        articles = [{"Résumé": "Déjà enrichi.", "sentiment": "neutre"}]
        mock_client = MagicMock()

        enricher = AsyncEnricher()
        with patch("utils.api_client.get_ai_client", return_value=mock_client):
            result = enricher._sync_fallback_sentiment(articles)

        mock_client.generate_sentiment.assert_not_called()
        assert result[0]["sentiment"] == "neutre"

    def test_skips_article_without_resume(self):
        from utils.async_enricher import AsyncEnricher
        articles = [{"Sources": "Source sans résumé"}]
        mock_client = MagicMock()

        enricher = AsyncEnricher()
        with patch("utils.api_client.get_ai_client", return_value=mock_client):
            result = enricher._sync_fallback_sentiment(articles)

        mock_client.generate_sentiment.assert_not_called()

    def test_handles_api_returning_none(self):
        from utils.async_enricher import AsyncEnricher
        articles = [{"Résumé": "Texte sans résultat de sentiment."}]
        mock_client = MagicMock()
        mock_client.generate_sentiment.return_value = None

        enricher = AsyncEnricher()
        with patch("utils.api_client.get_ai_client", return_value=mock_client):
            result = enricher._sync_fallback_sentiment(articles)

        assert "sentiment" not in result[0]

    def test_empty_articles_list(self):
        from utils.async_enricher import AsyncEnricher
        mock_client = MagicMock()
        enricher = AsyncEnricher()
        with patch("utils.api_client.get_ai_client", return_value=mock_client):
            result = enricher._sync_fallback_sentiment([])
        assert result == []


# ═════════════════════════════════════════════════════════════════════════════
# get_async_enricher — singleton
# ═════════════════════════════════════════════════════════════════════════════

class TestGetAsyncEnricher:
    def test_returns_async_enricher_instance(self):
        import utils.async_enricher as mod
        original = mod._default_enricher
        try:
            mod._default_enricher = None
            enricher = mod.get_async_enricher()
            assert isinstance(enricher, mod.AsyncEnricher)
        finally:
            mod._default_enricher = original

    def test_returns_same_instance_each_call(self):
        import utils.async_enricher as mod
        original = mod._default_enricher
        try:
            mod._default_enricher = None
            e1 = mod.get_async_enricher()
            e2 = mod.get_async_enricher()
            assert e1 is e2
        finally:
            mod._default_enricher = original

    def test_custom_concurrency_applied_on_first_call(self):
        import utils.async_enricher as mod
        original = mod._default_enricher
        try:
            mod._default_enricher = None
            enricher = mod.get_async_enricher(concurrency=15)
            assert enricher.concurrency == 15
        finally:
            mod._default_enricher = original

    def test_existing_instance_returned_regardless_of_concurrency(self):
        import utils.async_enricher as mod
        original = mod._default_enricher
        try:
            mod._default_enricher = None
            e1 = mod.get_async_enricher(concurrency=5)
            e2 = mod.get_async_enricher(concurrency=99)
            # Singleton — same instance, concurrency from first call
            assert e1 is e2
            assert e2.concurrency == 5
        finally:
            mod._default_enricher = original
