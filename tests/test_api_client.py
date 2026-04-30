"""Tests pour utils/api_client.py — Circuit Breaker, parsing réponses IA, comportements HTTP.

Couvre :
  - CircuitBreaker : transitions d'états, record_success/failure, reset
  - _parse_entities_response : extraction JSON NER depuis réponses brutes
  - _parse_sentiment_response : extraction JSON sentiment depuis réponses brutes
  - EurIAClient.ask : HTTP 200, 429, 500, timeout, retries
  - FallbackClient : fallback automatique sur exception principale
"""

import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ─────────────────────────────────────────────────────────────────────────────
# CircuitBreaker — états et transitions
# ─────────────────────────────────────────────────────────────────────────────

class TestCircuitBreakerInitial:
    def setup_method(self):
        from utils.api_client import CircuitBreaker
        self.CB = CircuitBreaker

    def test_initial_state_closed(self):
        cb = self.CB("test")
        assert cb.state == "CLOSED"

    def test_allow_request_when_closed(self):
        cb = self.CB("test")
        assert cb.allow_request() is True

    def test_failure_count_starts_at_zero(self):
        cb = self.CB("test")
        assert cb._failure_count == 0

    def test_custom_threshold(self):
        cb = self.CB("test", failure_threshold=3)
        assert cb.failure_threshold == 3


class TestCircuitBreakerTransientFailures:
    def setup_method(self):
        from utils.api_client import CircuitBreaker
        self.CB = CircuitBreaker

    def test_stays_closed_below_threshold(self):
        cb = self.CB("test", failure_threshold=5)
        for _ in range(4):
            cb.record_failure("transient")
        assert cb.state == "CLOSED"

    def test_opens_at_threshold(self):
        cb = self.CB("test", failure_threshold=3)
        for _ in range(3):
            cb.record_failure("transient")
        assert cb.state == "OPEN"

    def test_blocks_when_open(self):
        cb = self.CB("test", failure_threshold=2, grace_seconds=3600)
        for _ in range(2):
            cb.record_failure("transient")
        assert cb.state == "OPEN"
        assert cb.allow_request() is False

    def test_failure_count_increments(self):
        cb = self.CB("test", failure_threshold=10)
        cb.record_failure("transient")
        cb.record_failure("transient")
        assert cb._failure_count == 2

    def test_success_resets_failure_count(self):
        cb = self.CB("test", failure_threshold=10)
        cb.record_failure("transient")
        cb.record_failure("transient")
        cb.record_success()
        assert cb._failure_count == 0
        assert cb.state == "CLOSED"


class TestCircuitBreakerHalfOpen:
    def setup_method(self):
        from utils.api_client import CircuitBreaker
        self.CB = CircuitBreaker

    def test_transitions_to_half_open_after_grace(self):
        cb = self.CB("test", failure_threshold=1, grace_seconds=0.01)
        cb.record_failure("transient")
        assert cb.state == "OPEN"
        time.sleep(0.05)
        result = cb.allow_request()
        assert result is True
        assert cb.state == "HALF-OPEN"

    def test_success_in_half_open_closes_circuit(self):
        cb = self.CB("test", failure_threshold=1, grace_seconds=0.01)
        cb.record_failure("transient")
        time.sleep(0.05)
        cb.allow_request()  # transition → HALF-OPEN
        cb.record_success()
        assert cb.state == "CLOSED"

    def test_failure_in_half_open_reopens(self):
        cb = self.CB("test", failure_threshold=1, grace_seconds=0.01)
        cb.record_failure("transient")
        time.sleep(0.05)
        cb.allow_request()  # transition → HALF-OPEN
        cb.record_failure("transient")
        assert cb.state == "OPEN"


class TestCircuitBreakerQuota:
    def setup_method(self):
        from utils.api_client import CircuitBreaker
        self.CB = CircuitBreaker

    def test_quota_error_opens_quota_state(self):
        cb = self.CB("test")
        cb.record_failure("quota")
        assert cb.state == "OPEN_QUOTA"

    def test_quota_state_blocks_requests(self):
        cb = self.CB("test")
        cb.record_failure("quota")
        assert cb.allow_request() is False

    def test_quota_reset_date_is_today(self):
        cb = self.CB("test")
        cb.record_failure("quota")
        today = time.strftime("%Y-%m-%d", time.gmtime())
        assert cb._quota_reset_date == today

    def test_quota_auto_reset_next_day(self, monkeypatch):
        """Simule un reset automatique le lendemain."""
        cb = self.CB("test")
        cb.record_failure("quota")
        # Forcer une date passée
        cb._quota_reset_date = "2000-01-01"
        assert cb.allow_request() is True
        assert cb.state == "CLOSED"


class TestCircuitBreakerAuth:
    def setup_method(self):
        from utils.api_client import CircuitBreaker
        self.CB = CircuitBreaker

    def test_auth_error_opens_auth_state(self):
        cb = self.CB("test")
        cb.record_failure("auth")
        assert cb.state == "OPEN_AUTH"

    def test_auth_state_blocks_permanently(self):
        cb = self.CB("test")
        cb.record_failure("auth")
        # Même après "minuit" simulé, AUTH reste bloqué
        assert cb.allow_request() is False

    def test_auth_unblocked_by_explicit_reset(self):
        cb = self.CB("test")
        cb.record_failure("auth")
        assert cb.allow_request() is False
        cb.reset()
        assert cb.state == "CLOSED"
        assert cb.allow_request() is True

    def test_reset_clears_all_state(self):
        cb = self.CB("test", failure_threshold=3)
        for _ in range(3):
            cb.record_failure("transient")
        assert cb.state == "OPEN"
        cb.reset()
        assert cb.state == "CLOSED"
        assert cb._failure_count == 0

    def test_five_states_exist(self):
        cb = self.CB("test")
        assert cb._STATE_CLOSED    == "CLOSED"
        assert cb._STATE_OPEN      == "OPEN"
        assert cb._STATE_HALF_OPEN == "HALF-OPEN"
        assert cb._STATE_OPEN_QUOTA == "OPEN_QUOTA"
        assert cb._STATE_OPEN_AUTH  == "OPEN_AUTH"


# ─────────────────────────────────────────────────────────────────────────────
# _parse_entities_response — extraction NER
# ─────────────────────────────────────────────────────────────────────────────

class TestParseEntitiesResponse:
    def setup_method(self):
        from utils.api_client import _parse_entities_response
        self.fn = _parse_entities_response

    def test_simple_valid_json(self):
        raw = '{"PERSON": ["Emmanuel Macron"], "ORG": ["OpenAI"]}'
        result = self.fn(raw)
        assert result is not None
        assert "PERSON" in result
        assert "Emmanuel Macron" in result["PERSON"]
        assert "ORG" in result

    def test_json_in_code_block(self):
        raw = '```json\n{"PERSON": ["Alice"], "GPE": ["France"]}\n```'
        result = self.fn(raw)
        assert result is not None
        assert "PERSON" in result

    def test_json_in_plain_code_block(self):
        raw = '```\n{"ORG": ["SNCF"]}\n```'
        result = self.fn(raw)
        assert result is not None
        assert "ORG" in result

    def test_strips_think_tags(self):
        raw = '<think>Je réfléchis…</think>\n{"GPE": ["Paris"]}'
        result = self.fn(raw)
        assert result is not None
        assert "GPE" in result
        assert "Paris" in result["GPE"]

    def test_extracts_json_from_mixed_text(self):
        raw = 'Voici les entités : {"PERSON": ["Jean Dupont"]} — fin.'
        result = self.fn(raw)
        assert result is not None
        assert "PERSON" in result

    def test_deduplicates_values(self):
        raw = '{"PERSON": ["Alice", "Alice", "Bob"]}'
        result = self.fn(raw)
        assert result["PERSON"].count("Alice") == 1

    def test_ignores_unknown_entity_types(self):
        raw = '{"PERSON": ["Alice"], "UNKNOWN_TYPE": ["foo"]}'
        result = self.fn(raw)
        assert "UNKNOWN_TYPE" not in result
        assert "PERSON" in result

    def test_empty_json_returns_empty_dict(self):
        result = self.fn("{}")
        assert result == {}

    def test_invalid_json_returns_none(self):
        result = self.fn("ceci n'est pas du JSON")
        assert result is None

    def test_empty_string_returns_none(self):
        result = self.fn("")
        assert result is None

    def test_filters_non_string_values(self):
        raw = '{"PERSON": ["Alice", 42, null, "Bob"]}'
        result = self.fn(raw)
        # Seules les chaînes valides sont conservées
        assert all(isinstance(v, str) for v in result.get("PERSON", []))

    def test_strips_whitespace_from_values(self):
        raw = '{"PERSON": ["  Alice  ", " Bob"]}'
        result = self.fn(raw)
        assert "Alice" in result["PERSON"]
        assert "Bob" in result["PERSON"]

    def test_all_18_entity_types_accepted(self):
        types = [
            "PERSON", "NORP", "ORG", "GPE", "LOC", "FAC",
            "PRODUCT", "EVENT", "WORK_OF_ART", "LAW", "LANGUAGE",
            "DATE", "TIME", "PERCENT", "MONEY", "QUANTITY", "ORDINAL", "CARDINAL",
        ]
        payload = {t: [f"val_{t}"] for t in types}
        import json
        result = self.fn(json.dumps(payload))
        for t in types:
            assert t in result


# ─────────────────────────────────────────────────────────────────────────────
# _parse_sentiment_response — extraction sentiment/ton
# ─────────────────────────────────────────────────────────────────────────────

class TestParseSentimentResponse:
    def setup_method(self):
        from utils.api_client import _parse_sentiment_response
        self.fn = _parse_sentiment_response

    def test_valid_sentiment_response(self):
        raw = '{"sentiment": "positif", "score_sentiment": 4, "ton_editorial": "factuel", "score_ton": 5}'
        result = self.fn(raw)
        assert result is not None
        assert result["sentiment"] == "positif"
        assert result["score_sentiment"] == 4
        assert result["ton_editorial"] == "factuel"
        assert result["score_ton"] == 5

    def test_json_in_code_block(self):
        raw = '```json\n{"sentiment": "négatif", "score_sentiment": 1, "ton_editorial": "alarmiste", "score_ton": 1}\n```'
        result = self.fn(raw)
        assert result is not None
        assert result["sentiment"] == "négatif"

    def test_strips_think_tags(self):
        raw = '<think>Analyse…</think>\n{"sentiment": "neutre", "score_sentiment": 3, "ton_editorial": "analytique", "score_ton": 4}'
        result = self.fn(raw)
        assert result is not None
        assert result["sentiment"] == "neutre"

    def test_invalid_json_returns_none(self):
        result = self.fn("pas de JSON ici")
        assert result is None

    def test_empty_string_returns_none(self):
        result = self.fn("")
        assert result is None

    def test_invalid_sentiment_value_filtered(self):
        """Une valeur de sentiment invalide doit être rejetée."""
        raw = '{"sentiment": "inconnu", "score_sentiment": 3, "ton_editorial": "factuel", "score_ton": 3}'
        result = self.fn(raw)
        # Doit retourner None ou un dict sans le champ sentiment invalide
        if result is not None:
            assert result.get("sentiment") != "inconnu"

    def test_valid_ton_values_accepted(self):
        for ton in ["factuel", "alarmiste", "promotionnel", "critique", "analytique"]:
            raw = f'{{"sentiment": "neutre", "score_sentiment": 3, "ton_editorial": "{ton}", "score_ton": 3}}'
            result = self.fn(raw)
            assert result is not None
            assert result["ton_editorial"] == ton

    def test_valid_sentiment_values_accepted(self):
        for sentiment in ["positif", "neutre", "négatif"]:
            raw = f'{{"sentiment": "{sentiment}", "score_sentiment": 3, "ton_editorial": "factuel", "score_ton": 3}}'
            result = self.fn(raw)
            assert result is not None
            assert result["sentiment"] == sentiment


# ─────────────────────────────────────────────────────────────────────────────
# EurIAClient.ask / generate_entities — comportements HTTP mockés
# ─────────────────────────────────────────────────────────────────────────────
# Note : ask() propage les RuntimeError, generate_entities() les absorbe (→ {}).
# On teste les comportements via generate_entities() qui wrappent ask().

def _make_http_response(status_code: int, json_body=None):
    """Crée un mock requests.Response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_body or {}
    if status_code >= 400:
        import requests
        err = requests.exceptions.HTTPError(response=resp)
        resp.raise_for_status.side_effect = err
    else:
        resp.raise_for_status = MagicMock()
    return resp


def _ok_response(content="Résumé de test."):
    return _make_http_response(200, {
        "choices": [{"message": {"content": content}}]
    })


def _entities_ok_response():
    return _ok_response('{"PERSON": ["Macron"], "ORG": ["OpenAI"]}')


class TestEurIAClientHTTP:
    """Tests EurIAClient avec HTTP mocké via generate_entities()."""

    @pytest.fixture(autouse=True)
    def setup(self, monkeypatch):
        """Crée un client avec circuit breaker frais et env minimal."""
        monkeypatch.setenv("AI_PROVIDER", "euria")
        from utils.api_client import CircuitBreaker, EurIAClient, _euria_breaker
        # Reset le circuit breaker global
        _euria_breaker.reset()
        self.client = EurIAClient.__new__(EurIAClient)
        self.client.url = "https://api.test/completions"
        self.client.headers = {"Authorization": "Bearer test-token"}
        self.client.model = "test-model"
        self.client.enable_web_search = False
        self.client._provider_label = "EurIA"

    def test_returns_entities_on_200(self):
        with patch("requests.post", return_value=_entities_ok_response()):
            result = self.client.generate_entities("Emmanuel Macron dirige OpenAI.")
        assert result is not None
        assert "PERSON" in result

    def test_returns_empty_dict_on_timeout(self):
        import requests as req
        with patch("requests.post", side_effect=req.exceptions.Timeout):
            result = self.client.generate_entities("texte test", timeout=1)
        assert result == {}

    def test_returns_empty_dict_on_500(self):
        import requests as req
        err_resp = _make_http_response(500)
        with patch("requests.post", side_effect=req.exceptions.HTTPError(response=err_resp)):
            result = self.client.generate_entities("texte test")
        assert result == {}

    def test_returns_empty_dict_on_connection_error(self):
        import requests as req
        with patch("requests.post", side_effect=req.exceptions.ConnectionError("réseau mort")):
            result = self.client.generate_entities("texte test")
        assert result == {}

    def test_circuit_breaker_open_quota_blocks_request(self):
        from utils.api_client import _euria_breaker
        _euria_breaker.record_failure("quota")
        assert _euria_breaker.state == "OPEN_QUOTA"
        with patch("requests.post") as mock_post:
            result = self.client.generate_entities("texte test")
        # Circuit ouvert → RuntimeError → generate_entities retourne {}
        assert result == {}
        mock_post.assert_not_called()

    def test_retries_then_succeeds(self):
        import requests as req
        call_count = {"n": 0}

        def side_effect(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] < 2:
                raise req.exceptions.ConnectionError("fail")
            return _entities_ok_response()

        with patch("requests.post", side_effect=side_effect):
            result = self.client.generate_entities("texte test")
        assert result is not None
        assert "PERSON" in result
        assert call_count["n"] == 2


# ─────────────────────────────────────────────────────────────────────────────
# FallbackClient — fallback automatique
# ─────────────────────────────────────────────────────────────────────────────

class TestFallbackClient:
    """Tests FallbackClient — primary → secondary sur exception ou None."""

    def _make_fallback(self, primary_result, secondary_result):
        from utils.api_client import FallbackClient
        primary = MagicMock()
        secondary = MagicMock()

        if isinstance(primary_result, Exception):
            primary.generate_summary.side_effect = primary_result
        else:
            primary.generate_summary.return_value = primary_result

        if isinstance(secondary_result, Exception):
            secondary.generate_summary.side_effect = secondary_result
        else:
            secondary.generate_summary.return_value = secondary_result

        # FallbackClient utilise _primary et _secondary (avec underscore)
        client = FallbackClient.__new__(FallbackClient)
        client._primary = primary
        client._secondary = secondary
        return client

    def test_primary_succeeds_no_fallback(self):
        client = self._make_fallback("résumé-primaire", "résumé-secondaire")
        result = client.generate_summary("texte")
        assert result == "résumé-primaire"
        client._secondary.generate_summary.assert_not_called()

    def test_fallback_triggered_on_primary_exception(self):
        client = self._make_fallback(Exception("primaire KO"), "résumé-secondaire")
        result = client.generate_summary("texte")
        assert result == "résumé-secondaire"

    def test_returns_none_when_both_fail(self):
        client = self._make_fallback(Exception("KO1"), Exception("KO2"))
        # Quand les deux clients échouent, FallbackClient propage l'exception du secondaire
        with pytest.raises(Exception, match="KO2"):
            client.generate_summary("texte")

    def test_fallback_triggered_on_entities_returns_none(self):
        """Pour generate_entities, fallback_on_none=True → fallback si None."""
        from utils.api_client import FallbackClient
        primary = MagicMock()
        secondary = MagicMock()
        primary.generate_entities.return_value = None
        secondary.generate_entities.return_value = {"PERSON": ["Alice"]}

        client = FallbackClient.__new__(FallbackClient)
        client._primary = primary
        client._secondary = secondary
        result = client.generate_entities("texte")
        assert result == {"PERSON": ["Alice"]}
