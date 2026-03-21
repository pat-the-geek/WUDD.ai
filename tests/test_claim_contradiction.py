"""Tests pour utils/claim_extractor.py et utils/contradiction_engine.py.

claim_extractor :
  - extract_claims : résumé court/vide, réponse API moquée,
    JSON valide/invalide, filtrage, coercion de type

contradiction_engine :
  - _extract_number         : tous les formats numériques
  - _extract_year           : présent / absent
  - _sont_antonymes         : paires connues, paires inexistantes
  - compare_claims_deterministic : CHIFFRE, FAIT_BINAIRE, DATE, types différents
  - arbitrate_with_llm      : avec réponse LLM moquée
"""

import json
import pytest
from unittest.mock import MagicMock, patch


# ═════════════════════════════════════════════════════════════════════════════
# CLAIM EXTRACTOR
# ═════════════════════════════════════════════════════════════════════════════

class TestExtractClaimsInputValidation:
    def _fn(self):
        from utils.claim_extractor import extract_claims
        return extract_claims

    def test_none_returns_empty_list(self):
        assert self._fn()(None) == []  # type: ignore[arg-type]

    def test_empty_string_returns_empty_list(self):
        assert self._fn()("") == []

    def test_short_resume_under_50_chars_returns_empty(self):
        assert self._fn()("court") == []

    def test_just_50_chars_triggers_api(self):
        resume = "a" * 50
        mock_client = MagicMock()
        mock_client.ask.return_value = "[]"
        with patch("utils.claim_extractor.get_ai_client", return_value=mock_client):
            result = self._fn()(resume)
        assert result == []

    def test_whitespace_only_returns_empty(self):
        assert self._fn()("   \n\t  " * 10) == []


class TestExtractClaimsApiResponse:
    def _fn(self):
        from utils.claim_extractor import extract_claims
        return extract_claims

    def _mock_client(self, response: str) -> MagicMock:
        client = MagicMock()
        client.ask.return_value = response
        return client

    def test_valid_json_array_parsed(self):
        resume = "OpenAI a levé 6,6 milliards de dollars lors de son dernier tour de table auprès d'investisseurs institutionnels."
        claims_json = json.dumps([{
            "claim": "OpenAI a levé 6,6 milliards de dollars",
            "type": "CHIFFRE",
            "sujet": "OpenAI",
            "valeur": "6,6 milliards",
            "confiance": 0.9,
        }])
        with patch("utils.claim_extractor.get_ai_client", return_value=self._mock_client(claims_json)):
            result = self._fn()(resume, source="Test")
        assert len(result) == 1
        assert result[0]["type"] == "CHIFFRE"
        assert result[0]["claim"] == "OpenAI a levé 6,6 milliards de dollars"

    def test_empty_array_returns_empty_list(self):
        resume = "x" * 60
        with patch("utils.claim_extractor.get_ai_client", return_value=self._mock_client("[]")):
            result = self._fn()(resume)
        assert result == []

    def test_api_returns_none_gives_empty(self):
        resume = "x" * 60
        with patch("utils.claim_extractor.get_ai_client", return_value=self._mock_client(None)):
            result = self._fn()(resume)
        assert result == []

    def test_api_returns_empty_string_gives_empty(self):
        resume = "x" * 60
        with patch("utils.claim_extractor.get_ai_client", return_value=self._mock_client("")):
            result = self._fn()(resume)
        assert result == []

    def test_json_without_array_gives_empty(self):
        resume = "x" * 60
        with patch("utils.claim_extractor.get_ai_client", return_value=self._mock_client('{"claim": "foo"}')):
            result = self._fn()(resume)
        assert result == []

    def test_invalid_json_gives_empty(self):
        resume = "x" * 60
        with patch("utils.claim_extractor.get_ai_client", return_value=self._mock_client("not json {{{")):
            result = self._fn()(resume)
        assert result == []

    def test_json_embedded_in_text_extracted(self):
        resume = "x" * 60
        wrapped = 'Voici les claims :\n[{"claim":"c","type":"DATE","sujet":"s","valeur":"2026","confiance":0.8}]\nFin.'
        with patch("utils.claim_extractor.get_ai_client", return_value=self._mock_client(wrapped)):
            result = self._fn()(resume)
        assert len(result) == 1
        assert result[0]["type"] == "DATE"

    def test_api_exception_returns_empty_list(self):
        resume = "x" * 60
        client = MagicMock()
        client.ask.side_effect = RuntimeError("network error")
        with patch("utils.claim_extractor.get_ai_client", return_value=client):
            result = self._fn()(resume)
        assert result == []


class TestExtractClaimsFiltering:
    def _fn(self):
        from utils.claim_extractor import extract_claims
        return extract_claims

    def test_unknown_type_coerced_to_autre(self):
        resume = "x" * 60
        claims_json = json.dumps([{
            "claim": "quelque chose",
            "type": "INCONNUE",
            "sujet": "x",
            "valeur": "y",
            "confiance": 0.7,
        }])
        client = MagicMock()
        client.ask.return_value = claims_json
        with patch("utils.claim_extractor.get_ai_client", return_value=client):
            result = self._fn()(resume)
        assert result[0]["type"] == "AUTRE"

    def test_claim_without_claim_key_filtered(self):
        resume = "x" * 60
        claims_json = json.dumps([{"type": "CHIFFRE", "sujet": "x", "valeur": "5"}])
        client = MagicMock()
        client.ask.return_value = claims_json
        with patch("utils.claim_extractor.get_ai_client", return_value=client):
            result = self._fn()(resume)
        assert result == []

    def test_claim_without_type_key_filtered(self):
        resume = "x" * 60
        claims_json = json.dumps([{"claim": "une affirmation", "sujet": "x", "valeur": "5"}])
        client = MagicMock()
        client.ask.return_value = claims_json
        with patch("utils.claim_extractor.get_ai_client", return_value=client):
            result = self._fn()(resume)
        assert result == []

    def test_defaults_set_for_missing_optional_fields(self):
        resume = "x" * 60
        claims_json = json.dumps([{"claim": "affirmation test", "type": "FAIT_BINAIRE"}])
        client = MagicMock()
        client.ask.return_value = claims_json
        with patch("utils.claim_extractor.get_ai_client", return_value=client):
            result = self._fn()(resume)
        assert len(result) == 1
        assert result[0]["sujet"] == ""
        assert result[0]["valeur"] == ""
        assert result[0]["confiance"] == 0.5

    def test_all_valid_claim_types_accepted(self):
        from utils.claim_extractor import CLAIM_TYPES
        resume = "x" * 60
        for ctype in CLAIM_TYPES:
            claims_json = json.dumps([{"claim": f"claim {ctype}", "type": ctype}])
            client = MagicMock()
            client.ask.return_value = claims_json
            with patch("utils.claim_extractor.get_ai_client", return_value=client):
                result = self._fn()(resume)
            assert result[0]["type"] == ctype

    def test_non_dict_items_in_array_filtered(self):
        resume = "x" * 60
        claims_json = json.dumps([
            "string item",
            42,
            {"claim": "valide", "type": "ATTRIBUTION"},
        ])
        client = MagicMock()
        client.ask.return_value = claims_json
        with patch("utils.claim_extractor.get_ai_client", return_value=client):
            result = self._fn()(resume)
        assert len(result) == 1
        assert result[0]["claim"] == "valide"


# ═════════════════════════════════════════════════════════════════════════════
# CONTRADICTION ENGINE — fonctions pures
# ═════════════════════════════════════════════════════════════════════════════

class TestExtractNumber:
    def _fn(self):
        from utils.contradiction_engine import _extract_number
        return _extract_number

    def test_plain_integer(self):
        assert self._fn()("42") == 42.0

    def test_plain_float(self):
        assert abs(self._fn()("3.14") - 3.14) < 0.001

    def test_milliard(self):
        assert self._fn()("6,6 milliards") == pytest.approx(6_600_000_000)

    def test_billion(self):
        assert self._fn()("2.5 billion") == pytest.approx(2_500_000_000)

    def test_million(self):
        assert self._fn()("150 millions") == pytest.approx(150_000_000)

    def test_million_short_m(self):
        assert self._fn()("50m") == pytest.approx(50_000_000)

    def test_millier_k(self):
        assert self._fn()("5k") == pytest.approx(5_000)

    def test_empty_string_returns_none(self):
        assert self._fn()("") is None

    def test_text_only_returns_none(self):
        assert self._fn()("pas de nombre ici") is None

    def test_comma_as_decimal_separator(self):
        assert self._fn()("1,5 milliard") == pytest.approx(1_500_000_000)

    def test_with_percent_sign(self):
        val = self._fn()("15%")
        assert val == pytest.approx(15.0)


class TestExtractYear:
    def _fn(self):
        from utils.contradiction_engine import _extract_year
        return _extract_year

    def test_valid_year_2026(self):
        assert self._fn()("2026") == 2026

    def test_year_in_sentence(self):
        assert self._fn()("prévu pour 2028") == 2028

    def test_no_year_returns_none(self):
        assert self._fn()("aucune date ici") is None

    def test_partial_number_not_matched(self):
        # 4-digit number not in 2000-2099 → not a year
        assert self._fn()("code 1999") is None

    def test_year_at_start(self):
        assert self._fn()("2025 sera difficile") == 2025


class TestSontAntonymes:
    def _fn(self):
        from utils.contradiction_engine import _sont_antonymes
        return _sont_antonymes

    def test_adopte_rejete(self):
        assert self._fn()("adopté", "rejeté") is True

    def test_rejete_adopte(self):
        assert self._fn()("rejeté", "adopté") is True

    def test_confirme_dementi(self):
        assert self._fn()("confirmé", "démenti") is True

    def test_hausse_baisse(self):
        assert self._fn()("hausse", "baisse") is True

    def test_augmentation_diminution(self):
        assert self._fn()("augmentation", "diminution") is True

    def test_same_word_not_antonym(self):
        assert self._fn()("adopté", "adopté") is False

    def test_unrelated_words_not_antonym(self):
        assert self._fn()("chat", "chien") is False

    def test_case_insensitive(self):
        assert self._fn()("Adopté", "Rejeté") is True

    def test_feminine_form(self):
        assert self._fn()("adoptée", "rejetée") is True

    def test_croissance_decroissance(self):
        assert self._fn()("croissance", "décroissance") is True


class TestCompareClaimsDeterministic:
    def _fn(self):
        from utils.contradiction_engine import compare_claims_deterministic
        return compare_claims_deterministic

    def _claim(self, ctype, valeur, sujet="Test"):
        return {"type": ctype, "valeur": valeur, "sujet": sujet, "claim": f"claim {valeur}"}

    # ── CHIFFRE ────────────────────────────────────────────────────────────

    def test_chiffre_large_divergence_detected(self):
        a = self._claim("CHIFFRE", "100 millions")
        b = self._claim("CHIFFRE", "200 millions")
        result = self._fn()(a, b)
        assert result is not None
        assert result["type"] == "QUANTITATIVE"
        assert result["score_confiance"] > 0.5

    def test_chiffre_small_divergence_no_contradiction(self):
        a = self._claim("CHIFFRE", "100 millions")
        b = self._claim("CHIFFRE", "105 millions")
        assert self._fn()(a, b) is None

    def test_chiffre_clearly_over_15_percent_detected(self):
        # diff = abs(100-120)/max(100,120) = 20/120 = 16.7% > 15%
        a = self._claim("CHIFFRE", "100")
        b = self._claim("CHIFFRE", "120")
        result = self._fn()(a, b)
        assert result is not None

    def test_chiffre_non_numeric_no_contradiction(self):
        a = self._claim("CHIFFRE", "plusieurs")
        b = self._claim("CHIFFRE", "quelques-uns")
        assert self._fn()(a, b) is None

    def test_chiffre_description_contains_values(self):
        a = self._claim("CHIFFRE", "1 milliard")
        b = self._claim("CHIFFRE", "5 milliards")
        result = self._fn()(a, b)
        assert result is not None
        assert "milliard" in result["description"]

    # ── FAIT_BINAIRE ───────────────────────────────────────────────────────

    def test_fait_binaire_antonymes_detected(self):
        a = self._claim("FAIT_BINAIRE", "adopté")
        b = self._claim("FAIT_BINAIRE", "rejeté")
        result = self._fn()(a, b)
        assert result is not None
        assert result["type"] == "FACTUELLE_BINAIRE"
        assert result["score_confiance"] == 0.95

    def test_fait_binaire_same_value_no_contradiction(self):
        a = self._claim("FAIT_BINAIRE", "adopté")
        b = self._claim("FAIT_BINAIRE", "approuvé")
        assert self._fn()(a, b) is None

    def test_fait_binaire_hausse_baisse(self):
        a = self._claim("FAIT_BINAIRE", "hausse")
        b = self._claim("FAIT_BINAIRE", "baisse")
        result = self._fn()(a, b)
        assert result is not None

    # ── DATE ──────────────────────────────────────────────────────────────

    def test_date_different_years_detected(self):
        a = self._claim("DATE", "en 2024")
        b = self._claim("DATE", "en 2026")
        result = self._fn()(a, b)
        assert result is not None
        assert result["type"] == "TEMPORELLE"
        assert result["score_confiance"] == 0.80

    def test_date_same_year_no_contradiction(self):
        a = self._claim("DATE", "janvier 2026")
        b = self._claim("DATE", "mars 2026")
        assert self._fn()(a, b) is None

    def test_date_no_year_no_contradiction(self):
        a = self._claim("DATE", "la semaine prochaine")
        b = self._claim("DATE", "dans un mois")
        assert self._fn()(a, b) is None

    # ── Types différents ──────────────────────────────────────────────────

    def test_different_types_returns_none(self):
        a = self._claim("CHIFFRE", "100 millions")
        b = self._claim("DATE", "2026")
        assert self._fn()(a, b) is None


class TestArbitrateWithLlm:
    def _fn(self):
        from utils.contradiction_engine import arbitrate_with_llm
        return arbitrate_with_llm

    def _make_articles(self):
        return (
            {"Sources": "Le Monde", "score_source": 80, "Résumé": "Le gouvernement a approuvé la mesure."},
            {"Sources": "BFMTV", "score_source": 65, "Résumé": "Le gouvernement a rejeté la mesure."},
        )

    def _make_claims(self):
        return (
            {"claim": "mesure approuvée", "type": "FAIT_BINAIRE", "valeur": "approuvé"},
            {"claim": "mesure rejetée", "type": "FAIT_BINAIRE", "valeur": "rejeté"},
        )

    def test_returns_contradiction_when_detected(self):
        art_a, art_b = self._make_articles()
        cl_a, cl_b = self._make_claims()
        response = json.dumps({
            "contradiction_detectee": True,
            "type": "FACTUELLE_BINAIRE",
            "description": "contradictions",
            "source_probable": "A",
            "justification": "Le Monde plus crédible",
            "score_confiance": 0.85,
        })
        mock_client = MagicMock()
        mock_client.ask.return_value = response
        with patch("utils.contradiction_engine.get_ai_client", return_value=mock_client):
            result = self._fn()(art_a, art_b, cl_a, cl_b)
        assert result is not None
        assert result["type"] == "FACTUELLE_BINAIRE"

    def test_returns_none_when_no_contradiction(self):
        art_a, art_b = self._make_articles()
        cl_a, cl_b = self._make_claims()
        response = json.dumps({
            "contradiction_detectee": False,
            "type": "AUCUNE",
            "description": "pas de contradiction",
            "source_probable": "INCONNUE",
            "justification": "compatible",
            "score_confiance": 0.2,
        })
        mock_client = MagicMock()
        mock_client.ask.return_value = response
        with patch("utils.contradiction_engine.get_ai_client", return_value=mock_client):
            result = self._fn()(art_a, art_b, cl_a, cl_b)
        assert result is None

    def test_returns_none_when_score_too_low(self):
        """score_confiance < 0.40 → retourne None."""
        art_a, art_b = self._make_articles()
        cl_a, cl_b = self._make_claims()
        response = json.dumps({
            "contradiction_detectee": True,
            "type": "NUANCE",
            "description": "nuance légère",
            "source_probable": "INCONNUE",
            "justification": "différence mineure",
            "score_confiance": 0.35,
        })
        mock_client = MagicMock()
        mock_client.ask.return_value = response
        with patch("utils.contradiction_engine.get_ai_client", return_value=mock_client):
            result = self._fn()(art_a, art_b, cl_a, cl_b)
        assert result is None

    def test_returns_none_on_empty_api_response(self):
        art_a, art_b = self._make_articles()
        cl_a, cl_b = self._make_claims()
        mock_client = MagicMock()
        mock_client.ask.return_value = ""
        with patch("utils.contradiction_engine.get_ai_client", return_value=mock_client):
            result = self._fn()(art_a, art_b, cl_a, cl_b)
        assert result is None

    def test_returns_none_on_invalid_json(self):
        art_a, art_b = self._make_articles()
        cl_a, cl_b = self._make_claims()
        mock_client = MagicMock()
        mock_client.ask.return_value = "réponse invalide"
        with patch("utils.contradiction_engine.get_ai_client", return_value=mock_client):
            result = self._fn()(art_a, art_b, cl_a, cl_b)
        assert result is None

    def test_returns_none_on_api_exception(self):
        art_a, art_b = self._make_articles()
        cl_a, cl_b = self._make_claims()
        mock_client = MagicMock()
        mock_client.ask.side_effect = ConnectionError("timeout")
        with patch("utils.contradiction_engine.get_ai_client", return_value=mock_client):
            result = self._fn()(art_a, art_b, cl_a, cl_b)
        assert result is None

    def test_returns_none_when_api_returns_none(self):
        art_a, art_b = self._make_articles()
        cl_a, cl_b = self._make_claims()
        mock_client = MagicMock()
        mock_client.ask.return_value = None
        with patch("utils.contradiction_engine.get_ai_client", return_value=mock_client):
            result = self._fn()(art_a, art_b, cl_a, cl_b)
        assert result is None
