"""Tests pour les fonctions pures et FallbackClient de utils/api_client.py.

Couvre sans requête HTTP :
- _parse_entities_response
- _parse_sentiment_response
- _parse_summary_sentiment_response
- FallbackClient (primary success + fallback)
- get_ai_client (toutes les branches provider/fallback)
"""

import json
import os
from unittest.mock import MagicMock, patch

import pytest

from utils.api_client import (
    EurIAClient,
    FallbackClient,
    _build_summary_prompt,
    _contains_chinese_chars,
    _parse_entities_response,
    _parse_sentiment_response,
    _parse_summary_sentiment_response,
    _strip_summary_heading,
    get_ai_client,
)


# ─────────────────────────────────────────────────────────────
# _parse_entities_response
# ─────────────────────────────────────────────────────────────


class TestParseEntitiesResponse:
    """Tests pour _parse_entities_response."""

    def test_valid_json_direct(self):
        raw = json.dumps({"PERSON": ["Macron"], "ORG": ["OpenAI"]})
        result = _parse_entities_response(raw)
        assert result == {"PERSON": ["Macron"], "ORG": ["OpenAI"]}

    def test_fenced_json_block(self):
        raw = '```json\n{"PERSON": ["Dupont"]}\n```'
        result = _parse_entities_response(raw)
        assert result == {"PERSON": ["Dupont"]}

    def test_fenced_block_no_lang(self):
        raw = '```\n{"ORG": ["SNCF"]}\n```'
        result = _parse_entities_response(raw)
        assert result == {"ORG": ["SNCF"]}

    def test_think_tags_stripped(self):
        raw = "<think>je réfléchis…</think>\n" + json.dumps({"GPE": ["France"]})
        result = _parse_entities_response(raw)
        assert result == {"GPE": ["France"]}

    def test_think_tags_multiline(self):
        raw = "<think>\nligne 1\nligne 2\n</think>" + json.dumps({"LOC": ["Paris"]})
        result = _parse_entities_response(raw)
        assert result == {"LOC": ["Paris"]}

    def test_json_embedded_in_text(self):
        """JSON précédé de texte parasite → extraction via regex."""
        raw = 'Voici les entités : {"PERSON": ["Alice"]} merci.'
        result = _parse_entities_response(raw)
        assert result == {"PERSON": ["Alice"]}

    def test_no_json_at_all_returns_none(self):
        """Aucun JSON → retour None (line 258)."""
        raw = "Aucune entité trouvée dans ce texte."
        result = _parse_entities_response(raw)
        assert result is None

    def test_malformed_json_after_extraction_returns_none(self):
        """Regex trouve un { mais JSON invalide → retour None (lines 261-263)."""
        raw = "entités: {clé_sans_guillemets: valeur}"
        result = _parse_entities_response(raw)
        assert result is None

    def test_non_dict_json_returns_empty(self):
        """JSON valide mais pas un dict → retour {} (lines 265-266)."""
        raw = json.dumps(["PERSON", "ORG"])
        result = _parse_entities_response(raw)
        assert result == {}

    def test_non_list_value_skipped(self):
        """Valeur non-liste pour un type connu → ignorée (line 273)."""
        raw = json.dumps({"PERSON": "pas une liste", "ORG": ["Infomaniak"]})
        result = _parse_entities_response(raw)
        assert "PERSON" not in result
        assert result == {"ORG": ["Infomaniak"]}

    def test_deduplication_within_type(self):
        raw = json.dumps({"PERSON": ["Alice", "Alice", "Bob"]})
        result = _parse_entities_response(raw)
        assert result == {"PERSON": ["Alice", "Bob"]}

    def test_empty_strings_filtered(self):
        raw = json.dumps({"PERSON": ["Alice", "", "  ", "Bob"]})
        result = _parse_entities_response(raw)
        assert result == {"PERSON": ["Alice", "Bob"]}

    def test_non_string_values_in_list_filtered(self):
        raw = json.dumps({"PERSON": ["Alice", 42, None, "Bob"]})
        result = _parse_entities_response(raw)
        assert result == {"PERSON": ["Alice", "Bob"]}

    def test_empty_dict_returns_empty(self):
        raw = json.dumps({})
        result = _parse_entities_response(raw)
        assert result == {}

    def test_unknown_entity_types_ignored(self):
        raw = json.dumps({"UNKNOWN_TYPE": ["foo"], "PERSON": ["Alice"]})
        result = _parse_entities_response(raw)
        assert "UNKNOWN_TYPE" not in result
        assert result == {"PERSON": ["Alice"]}

    def test_values_stripped(self):
        raw = json.dumps({"PERSON": ["  Alice  ", " Bob "]})
        result = _parse_entities_response(raw)
        assert result == {"PERSON": ["Alice", "Bob"]}

    def test_reclassifies_money_phrase_to_money(self):
        raw = json.dumps({"ORG": ["22 milliards de dollars"]})
        result = _parse_entities_response(raw)
        assert result == {"MONEY": ["22 milliards de dollars"]}

    def test_reclassifies_pure_year_to_date(self):
        raw = json.dumps({"GPE": ["2026"]})
        result = _parse_entities_response(raw)
        assert result == {"DATE": ["2026"]}

    def test_reclassifies_law_like_value_to_law(self):
        raw = json.dumps({"EVENT": ["Cloud Act"]})
        result = _parse_entities_response(raw)
        assert result == {"LAW": ["Cloud Act"]}

    def test_reclassifies_short_false_positive_trump_to_person(self):
        raw = json.dumps({"GPE": ["Trump"], "NORP": ["Trump"], "DATE": ["Trump"]})
        result = _parse_entities_response(raw)
        assert result == {"PERSON": ["Donald Trump"]}

    def test_reclassifies_conseil_federal_person_to_org(self):
        raw = json.dumps({"PERSON": ["Conseil fédéral"]})
        result = _parse_entities_response(raw)
        assert result == {"ORG": ["Conseil Fédéral"]}


# ─────────────────────────────────────────────────────────────
# _parse_sentiment_response
# ─────────────────────────────────────────────────────────────


class TestParseSentimentResponse:
    """Tests pour _parse_sentiment_response."""

    def test_valid_json(self):
        raw = json.dumps(
            {
                "sentiment": "positif",
                "score_sentiment": 4,
                "ton_editorial": "factuel",
                "score_ton": 5,
            }
        )
        result = _parse_sentiment_response(raw)
        assert result == {
            "sentiment": "positif",
            "score_sentiment": 4,
            "ton_editorial": "factuel",
            "score_ton": 5,
        }

    def test_fenced_json_block(self):
        raw = '```json\n{"sentiment": "neutre", "score_sentiment": 3}\n```'
        result = _parse_sentiment_response(raw)
        assert result["sentiment"] == "neutre"
        assert result["score_sentiment"] == 3

    def test_think_tags_stripped(self):
        raw = "<think>réflexion</think>\n" + json.dumps(
            {"sentiment": "négatif", "score_sentiment": 1}
        )
        result = _parse_sentiment_response(raw)
        assert result["sentiment"] == "négatif"

    def test_no_json_returns_none(self):
        """Aucun JSON → retour None (line 309)."""
        result = _parse_sentiment_response("sentiment globalement positif")
        assert result is None

    def test_malformed_json_after_extraction_returns_none(self):
        """JSON invalide après extraction par regex → retour None (lines 310-314)."""
        raw = "résultat: {sentiment: positif}"
        result = _parse_sentiment_response(raw)
        assert result is None

    def test_non_dict_returns_empty(self):
        """JSON valide mais pas un dict → retour {} (line 315-316)."""
        raw = json.dumps(["positif", 4])
        result = _parse_sentiment_response(raw)
        assert result == {}

    def test_invalid_sentiment_excluded(self):
        raw = json.dumps({"sentiment": "inconnu", "score_sentiment": 3})
        result = _parse_sentiment_response(raw)
        assert "sentiment" not in result

    def test_score_out_of_range_excluded(self):
        raw = json.dumps({"sentiment": "positif", "score_sentiment": 9})
        result = _parse_sentiment_response(raw)
        assert "score_sentiment" not in result

    def test_invalid_ton_excluded(self):
        raw = json.dumps({"ton_editorial": "bizarre"})
        result = _parse_sentiment_response(raw)
        assert "ton_editorial" not in result

    def test_score_ton_out_of_range_excluded(self):
        raw = json.dumps({"ton_editorial": "factuel", "score_ton": 0})
        result = _parse_sentiment_response(raw)
        assert "score_ton" not in result

    def test_float_score_accepted(self):
        raw = json.dumps({"score_sentiment": 4.0})
        result = _parse_sentiment_response(raw)
        assert result.get("score_sentiment") == 4

    def test_embedded_json_in_text(self):
        raw = 'Analyse : {"sentiment": "positif", "score_sentiment": 5} fin.'
        result = _parse_sentiment_response(raw)
        assert result["sentiment"] == "positif"

    def test_all_valid_ton_values(self):
        for ton in ("factuel", "alarmiste", "promotionnel", "critique", "analytique"):
            raw = json.dumps({"ton_editorial": ton, "score_ton": 3})
            result = _parse_sentiment_response(raw)
            assert result.get("ton_editorial") == ton

    def test_all_valid_sentiment_values(self):
        for sent in ("positif", "neutre", "négatif"):
            raw = json.dumps({"sentiment": sent, "score_sentiment": 3})
            result = _parse_sentiment_response(raw)
            assert result.get("sentiment") == sent


# ─────────────────────────────────────────────────────────────
# _parse_summary_sentiment_response
# ─────────────────────────────────────────────────────────────


class TestParseSummarySentimentResponse:
    """Tests pour _parse_summary_sentiment_response."""

    def _make_full_json(self, **kwargs):
        base = {
            "resume": "Ceci est un résumé.",
            "sentiment": "positif",
            "score_sentiment": 4,
            "ton_editorial": "factuel",
            "score_ton": 5,
        }
        base.update(kwargs)
        return json.dumps(base)

    def test_full_valid_response(self):
        raw = self._make_full_json()
        result = _parse_summary_sentiment_response(raw)
        assert result is not None
        assert result["resume"] == "Ceci est un résumé."
        assert result["sentiment"] == "positif"
        assert result["score_sentiment"] == 4
        assert result["ton_editorial"] == "factuel"
        assert result["score_ton"] == 5

    def test_fenced_json_block(self):
        payload = json.dumps({"resume": "Texte résumé.", "sentiment": "neutre"})
        raw = f"```json\n{payload}\n```"
        result = _parse_summary_sentiment_response(raw)
        assert result["resume"] == "Texte résumé."

    def test_think_tags_stripped(self):
        payload = json.dumps({"resume": "Résumé propre.", "sentiment": "positif"})
        raw = f"<think>réflexion interne</think>\n{payload}"
        result = _parse_summary_sentiment_response(raw)
        assert result["resume"] == "Résumé propre."

    def test_multiline_think_tags(self):
        payload = json.dumps({"resume": "OK.", "score_sentiment": 3})
        raw = f"<THINK>\nligne 1\nligne 2\n</THINK>\n{payload}"
        result = _parse_summary_sentiment_response(raw)
        assert result["resume"] == "OK."

    def test_no_json_returns_resume_as_text(self):
        """Texte brut sans JSON — depuis la réécriture du parser markdown,
        le texte est retourné comme résumé (comportement plus robuste que None)."""
        result = _parse_summary_sentiment_response("Voici un résumé sans JSON.")
        # Ne retourne plus None — le parser markdown capture le texte comme résumé
        assert result is not None
        assert result.get("resume") == "Voici un résumé sans JSON."

    def test_malformed_json_after_extraction_returns_resume(self):
        """JSON invalide après extraction — depuis la réécriture du parser markdown,
        le parser tente d'extraire le résumé plutôt que retourner None."""
        raw = "résumé: {resume: sans guillemets}"
        result = _parse_summary_sentiment_response(raw)
        # Ne retourne plus None — le parser markdown extrait ce qu'il peut
        assert result is not None

    def test_non_dict_json_returns_none(self):
        """JSON valide mais pas un dict → retour None (lines 373-374)."""
        raw = json.dumps(["résumé1", "positif"])
        result = _parse_summary_sentiment_response(raw)
        assert result is None

    def test_empty_resume_excluded(self):
        raw = json.dumps({"resume": "", "sentiment": "positif"})
        result = _parse_summary_sentiment_response(raw)
        assert "resume" not in result

    def test_whitespace_resume_excluded(self):
        raw = json.dumps({"resume": "   ", "sentiment": "neutre"})
        result = _parse_summary_sentiment_response(raw)
        assert "resume" not in result

    def test_invalid_sentiment_excluded(self):
        raw = json.dumps({"resume": "OK", "sentiment": "inconnu"})
        result = _parse_summary_sentiment_response(raw)
        assert "sentiment" not in result

    def test_invalid_score_out_of_range(self):
        raw = json.dumps({"resume": "OK", "score_sentiment": 10})
        result = _parse_summary_sentiment_response(raw)
        assert "score_sentiment" not in result

    def test_invalid_ton_excluded(self):
        raw = json.dumps({"resume": "OK", "ton_editorial": "bizarre"})
        result = _parse_summary_sentiment_response(raw)
        assert "ton_editorial" not in result

    def test_score_ton_boundary_valid(self):
        raw = json.dumps({"resume": "OK", "score_ton": 1})
        result = _parse_summary_sentiment_response(raw)
        assert result["score_ton"] == 1

    def test_score_ton_boundary_invalid(self):
        raw = json.dumps({"resume": "OK", "score_ton": 6})
        result = _parse_summary_sentiment_response(raw)
        assert "score_ton" not in result

    def test_float_score_accepted(self):
        raw = json.dumps({"resume": "OK", "score_sentiment": 3.0})
        result = _parse_summary_sentiment_response(raw)
        assert result.get("score_sentiment") == 3

    def test_embedded_json_in_text(self):
        payload = json.dumps({"resume": "Résumé.", "sentiment": "neutre"})
        raw = f"Voici le résultat : {payload} — fin."
        result = _parse_summary_sentiment_response(raw)
        assert result["resume"] == "Résumé."

    def test_resume_header_stripped(self):
        """Entêtes Markdown de type '# Résumé' supprimés du résumé (line 379)."""
        raw = json.dumps({"resume": "## Résumé\nContenu du résumé."})
        result = _parse_summary_sentiment_response(raw)
        assert result is not None
        assert result["resume"] == "Contenu du résumé."

    def test_all_sentiment_values(self):
        for sent in ("positif", "neutre", "négatif"):
            raw = json.dumps({"resume": "OK", "sentiment": sent})
            result = _parse_summary_sentiment_response(raw)
            assert result.get("sentiment") == sent

    def test_all_ton_values(self):
        for ton in ("factuel", "alarmiste", "promotionnel", "critique", "analytique"):
            raw = json.dumps({"resume": "OK", "ton_editorial": ton})
            result = _parse_summary_sentiment_response(raw)
            assert result.get("ton_editorial") == ton


# ─────────────────────────────────────────────────────────────
# Gardes langue FR / caractères chinois
# ─────────────────────────────────────────────────────────────


class TestSummaryLanguageGuards:
    """Tests des garde-fous de langue pour les résumés."""

    def test_contains_chinese_chars_true_false(self):
        assert _contains_chinese_chars("这是一个摘要") is True
        assert _contains_chinese_chars("Résumé uniquement en français") is False

    def test_strip_summary_heading(self):
        assert _strip_summary_heading("## Résumé\nTexte final") == "Texte final"

    def test_build_summary_prompt_contains_french_constraints(self):
        prompt = _build_summary_prompt("texte", max_lines=10, language="français", retry=False)
        assert "uniquement en français" in prompt
        assert "aucun caractère chinois" in prompt

    def test_euria_generate_summary_regenerates_when_chinese(self):
        client = EurIAClient(url="http://localhost", bearer="dummy")
        with patch.object(
            EurIAClient,
            "ask",
            side_effect=["这是中文摘要", "Résumé final entièrement en français."],
        ) as ask_mock:
            result = client.generate_summary("texte source", max_lines=5, timeout=1)
        assert "Résumé final" in result
        assert ask_mock.call_count == 2

    def test_euria_generate_summary_no_regeneration_if_french(self):
        client = EurIAClient(url="http://localhost", bearer="dummy")
        with patch.object(
            EurIAClient,
            "ask",
            return_value="Résumé valide en français.",
        ) as ask_mock:
            result = client.generate_summary("texte source", max_lines=5, timeout=1)
        assert result == "Résumé valide en français."
        assert ask_mock.call_count == 1


# ─────────────────────────────────────────────────────────────
# FallbackClient
# ─────────────────────────────────────────────────────────────


class TestFallbackClient:
    """Tests pour FallbackClient (primary → fallback sur erreur)."""

    def _make_clients(self):
        primary = MagicMock()
        secondary = MagicMock()
        return primary, secondary

    def test_init_logs_names(self, capfd):
        primary = MagicMock()
        primary.__class__.__name__ = "EurIAClient"
        secondary = MagicMock()
        secondary.__class__.__name__ = "ClaudeClient"
        # Construction ne doit pas lever
        fc = FallbackClient(primary, secondary)
        assert fc._primary is primary
        assert fc._secondary is secondary

    def test_call_primary_success(self):
        primary, secondary = self._make_clients()
        primary.generate_summary.return_value = "résumé"
        fc = FallbackClient(primary, secondary)
        result = fc.generate_summary("texte")
        assert result == "résumé"
        primary.generate_summary.assert_called_once_with("texte")
        secondary.generate_summary.assert_not_called()

    def test_call_primary_fails_uses_secondary(self):
        primary, secondary = self._make_clients()
        primary.generate_summary.side_effect = RuntimeError("timeout")
        secondary.generate_summary.return_value = "résumé fallback"
        fc = FallbackClient(primary, secondary)
        result = fc.generate_summary("texte")
        assert result == "résumé fallback"
        secondary.generate_summary.assert_called_once()

    def test_call_primary_raises_generic_exception(self):
        primary, secondary = self._make_clients()
        primary.generate_entities.side_effect = ValueError("erreur générique")
        secondary.generate_entities.return_value = {"PERSON": ["Alice"]}
        fc = FallbackClient(primary, secondary)
        result = fc.generate_entities("texte")
        assert result == {"PERSON": ["Alice"]}

    def test_generate_summary_delegates(self):
        primary, secondary = self._make_clients()
        primary.generate_summary.return_value = "summary"
        fc = FallbackClient(primary, secondary)
        assert fc.generate_summary("t") == "summary"

    def test_generate_entities_delegates(self):
        primary, secondary = self._make_clients()
        primary.generate_entities.return_value = {"ORG": ["SNCF"]}
        fc = FallbackClient(primary, secondary)
        assert fc.generate_entities("t") == {"ORG": ["SNCF"]}

    def test_generate_sentiment_delegates(self):
        primary, secondary = self._make_clients()
        primary.generate_sentiment.return_value = {"sentiment": "neutre"}
        fc = FallbackClient(primary, secondary)
        assert fc.generate_sentiment("t") == {"sentiment": "neutre"}

    def test_synthesize_topic_delegates(self):
        primary, secondary = self._make_clients()
        primary.synthesize_topic.return_value = "synthèse"
        fc = FallbackClient(primary, secondary)
        assert fc.synthesize_topic("entité", []) == "synthèse"

    def test_generate_report_delegates(self):
        primary, secondary = self._make_clients()
        primary.generate_report.return_value = "rapport"
        fc = FallbackClient(primary, secondary)
        assert fc.generate_report("data") == "rapport"

    def test_ask_delegates(self):
        primary, secondary = self._make_clients()
        primary.ask.return_value = "réponse"
        fc = FallbackClient(primary, secondary)
        assert fc.ask("question?") == "réponse"

    def test_fallback_on_sentiment(self):
        primary, secondary = self._make_clients()
        primary.generate_sentiment.side_effect = ConnectionError("réseau down")
        secondary.generate_sentiment.return_value = {"sentiment": "positif"}
        fc = FallbackClient(primary, secondary)
        result = fc.generate_sentiment("texte")
        assert result["sentiment"] == "positif"

    def test_fallback_on_report(self):
        primary, secondary = self._make_clients()
        primary.generate_report.side_effect = RuntimeError("quota dépassé")
        secondary.generate_report.return_value = "rapport de secours"
        fc = FallbackClient(primary, secondary)
        result = fc.generate_report("données json")
        assert result == "rapport de secours"

    def test_kwargs_forwarded_to_primary(self):
        primary, secondary = self._make_clients()
        primary.generate_summary.return_value = "ok"
        fc = FallbackClient(primary, secondary)
        fc.generate_summary("texte", max_lines=10, lang="fr")
        primary.generate_summary.assert_called_once_with("texte", max_lines=10, lang="fr")

    def test_kwargs_forwarded_to_secondary_on_fail(self):
        primary, secondary = self._make_clients()
        primary.ask.side_effect = RuntimeError("erreur")
        secondary.ask.return_value = "fallback ok"
        fc = FallbackClient(primary, secondary)
        fc.ask("ma question", context="ctx", temperature=0.5)
        secondary.ask.assert_called_once_with("ma question", context="ctx", temperature=0.5)

    def test_generate_entities_none_triggers_fallback(self):
        """generate_entities retourne None → fallback cloud (JSON invalide depuis Ollama)."""
        primary, secondary = self._make_clients()
        primary.generate_entities.return_value = None
        secondary.generate_entities.return_value = {"ORG": ["OpenAI"]}
        fc = FallbackClient(primary, secondary)
        result = fc.generate_entities("texte")
        assert result == {"ORG": ["OpenAI"]}
        secondary.generate_entities.assert_called_once()

    def test_generate_sentiment_none_triggers_fallback(self):
        """generate_sentiment retourne None → fallback cloud (JSON invalide depuis Ollama)."""
        primary, secondary = self._make_clients()
        primary.generate_sentiment.return_value = None
        secondary.generate_sentiment.return_value = {"sentiment": "neutre", "score_sentiment": 3}
        fc = FallbackClient(primary, secondary)
        result = fc.generate_sentiment("texte")
        assert result == {"sentiment": "neutre", "score_sentiment": 3}
        secondary.generate_sentiment.assert_called_once()

    def test_generate_summary_none_no_fallback(self):
        """generate_summary retourne None → pas de fallback (résumé brut acceptable)."""
        primary, secondary = self._make_clients()
        primary.generate_summary.return_value = None
        secondary.generate_summary.return_value = "résumé cloud"
        fc = FallbackClient(primary, secondary)
        result = fc.generate_summary("texte")
        assert result is None  # None propagé sans déclencher le secondaire
        secondary.generate_summary.assert_not_called()


# ─────────────────────────────────────────────────────────────
# get_ai_client
# ─────────────────────────────────────────────────────────────


_ENV_BASE = {
    "URL": "https://api.infomaniak.com/euria/v1",
    "bearer": "fake-bearer",
    "AI_PROVIDER": "euria",
}


class TestGetAiClient:
    """Tests pour get_ai_client() — toutes les branches provider/fallback."""

    def _patch_env(self, **overrides):
        env = {**_ENV_BASE, **overrides}
        return patch.dict(os.environ, env, clear=False)

    def test_only_euria_configured_returns_euria_client(self):
        """Pas de clé Anthropic → EurIAClient direct.

        On force ANTHROPIC_API_KEY à vide dans patch.dict : load_dotenv utilise
        override=False par défaut, donc la valeur vide déjà présente dans
        os.environ n'est pas écrasée par le fichier .env.
        """
        import utils.config as cfg_mod
        from utils.api_client import EurIAClient

        env = {**_ENV_BASE, "ANTHROPIC_API_KEY": ""}
        with patch.dict(os.environ, env, clear=False):
            cfg_mod._config_instance = None
            try:
                client = get_ai_client(fallback=True)
            finally:
                cfg_mod._config_instance = None
        assert isinstance(client, EurIAClient)

    def test_fallback_false_returns_euria_without_claude(self):
        """fallback=False → client simple même si les deux sont configurés."""
        from utils.api_client import EurIAClient

        with patch.dict(
            os.environ,
            {**_ENV_BASE, "ANTHROPIC_API_KEY": "sk-fake", "AI_PROVIDER": "euria"},
        ):
            client = get_ai_client(fallback=False)
        assert isinstance(client, EurIAClient)

    def test_both_providers_euria_default_returns_fallback(self):
        """EurIA + Anthropic configurés, provider=euria → FallbackClient(EurIA, Claude)."""
        with patch.dict(
            os.environ,
            {**_ENV_BASE, "ANTHROPIC_API_KEY": "sk-fake", "AI_PROVIDER": "euria"},
        ):
            # Reset singleton config pour prendre les nouvelles valeurs
            import utils.config as cfg_mod

            cfg_mod._config_instance = None
            try:
                client = get_ai_client(fallback=True)
            finally:
                cfg_mod._config_instance = None
        assert isinstance(client, FallbackClient)

    def test_both_providers_claude_default_returns_fallback_reversed(self):
        """EurIA + Anthropic configurés, provider=claude → FallbackClient(Claude, EurIA)."""
        from utils.api_client import ClaudeClient

        with patch.dict(
            os.environ,
            {**_ENV_BASE, "ANTHROPIC_API_KEY": "sk-fake", "AI_PROVIDER": "claude"},
        ):
            import utils.config as cfg_mod

            cfg_mod._config_instance = None
            try:
                client = get_ai_client(fallback=True)
            finally:
                cfg_mod._config_instance = None
        assert isinstance(client, FallbackClient)
        # Le primaire doit être Claude
        assert isinstance(client._primary, ClaudeClient)

    def test_claude_provider_no_fallback_returns_claude(self):
        """provider=claude, fallback=False → ClaudeClient direct."""
        from utils.api_client import ClaudeClient

        with patch.dict(
            os.environ,
            {**_ENV_BASE, "ANTHROPIC_API_KEY": "sk-fake", "AI_PROVIDER": "claude"},
        ):
            import utils.config as cfg_mod

            cfg_mod._config_instance = None
            try:
                client = get_ai_client(fallback=False)
            finally:
                cfg_mod._config_instance = None
        assert isinstance(client, ClaudeClient)

    def test_fallback_false_euria_no_claude_returns_euria(self):
        """fallback=False, provider=euria, pas d'Anthropic → EurIAClient direct."""
        import utils.config as cfg_mod
        from utils.api_client import EurIAClient

        with patch.dict(
            os.environ,
            {**_ENV_BASE, "AI_PROVIDER": "euria", "ANTHROPIC_API_KEY": ""},
            clear=False,
        ):
            cfg_mod._config_instance = None
            try:
                client = get_ai_client(fallback=False)
            finally:
                cfg_mod._config_instance = None
        assert isinstance(client, EurIAClient)


# ─────────────────────────────────────────────────────────────
# OllamaClient
# ─────────────────────────────────────────────────────────────


class TestOllamaClient:
    """Tests unitaires pour OllamaClient — sans requête réseau réelle."""

    def test_import(self):
        from utils.api_client import OllamaClient
        assert OllamaClient is not None

    def test_ollama_host_default(self):
        from utils.api_client import OllamaClient
        with patch.object(OllamaClient, "_is_running_in_docker", return_value=False):
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("OLLAMA_HOST_LOCAL", None)
                os.environ.pop("OLLAMA_HOST_DOCKER", None)
                os.environ.pop("OLLAMA_HOST", None)
                assert OllamaClient._ollama_host() == "localhost"

    def test_ollama_host_from_env(self):
        from utils.api_client import OllamaClient
        with patch.object(OllamaClient, "_is_running_in_docker", return_value=False):
            with patch.dict(os.environ, {"OLLAMA_HOST": "host.docker.internal"}, clear=False):
                os.environ.pop("OLLAMA_HOST_LOCAL", None)
                os.environ.pop("OLLAMA_HOST_DOCKER", None)
                assert OllamaClient._ollama_host() == "host.docker.internal"

    def test_ollama_host_local_preferred_on_host(self):
        from utils.api_client import OllamaClient
        with patch.object(OllamaClient, "_is_running_in_docker", return_value=False):
            with patch.dict(
                os.environ,
                {
                    "OLLAMA_HOST": "legacy-host",
                    "OLLAMA_HOST_LOCAL": "localhost",
                    "OLLAMA_HOST_DOCKER": "host.docker.internal",
                },
                clear=False,
            ):
                assert OllamaClient._ollama_host() == "localhost"

    def test_ollama_host_docker_preferred_in_container(self):
        from utils.api_client import OllamaClient
        with patch.object(OllamaClient, "_is_running_in_docker", return_value=True):
            with patch.dict(
                os.environ,
                {
                    "OLLAMA_HOST": "legacy-host",
                    "OLLAMA_HOST_LOCAL": "localhost",
                    "OLLAMA_HOST_DOCKER": "host.docker.internal",
                },
                clear=False,
            ):
                assert OllamaClient._ollama_host() == "host.docker.internal"

    def test_default_url_uses_host(self):
        from utils.api_client import OllamaClient
        with patch.object(OllamaClient, "_is_running_in_docker", return_value=False):
            with patch.dict(os.environ, {"OLLAMA_HOST": "myhost"}, clear=False):
                os.environ.pop("OLLAMA_HOST_LOCAL", None)
                os.environ.pop("OLLAMA_HOST_DOCKER", None)
                url = OllamaClient._default_url()
        assert "myhost" in url
        assert "11434" in url
        assert url.endswith("/v1/chat/completions")

    def test_init_default_model(self):
        from utils.api_client import OllamaClient
        client = OllamaClient()
        assert client._ollama_model == "qwen2.5:7b"

    def test_init_custom_model(self):
        from utils.api_client import OllamaClient
        client = OllamaClient(model="qwen2.5:14b")
        assert client._ollama_model == "qwen2.5:14b"

    def test_is_available_returns_true_on_200(self):
        from utils.api_client import OllamaClient
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        with patch("requests.get", return_value=mock_resp):
            assert OllamaClient.is_available() is True

    def test_is_available_returns_false_on_non_200(self):
        from utils.api_client import OllamaClient
        mock_resp = MagicMock()
        mock_resp.status_code = 503
        with patch("requests.get", return_value=mock_resp):
            assert OllamaClient.is_available() is False

    def test_is_available_returns_false_on_exception(self):
        from utils.api_client import OllamaClient
        with patch("requests.get", side_effect=ConnectionError("refused")):
            assert OllamaClient.is_available() is False

    def test_list_models_returns_names(self):
        from utils.api_client import OllamaClient
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"models": [{"name": "qwen2.5:7b"}, {"name": "mistral:7b"}]}
        with patch("requests.get", return_value=mock_resp):
            models = OllamaClient.list_models()
        assert models == ["qwen2.5:7b", "mistral:7b"]

    def test_list_models_returns_empty_on_error(self):
        from utils.api_client import OllamaClient
        with patch("requests.get", side_effect=ConnectionError("down")):
            assert OllamaClient.list_models() == []

    def test_list_models_returns_empty_on_non_200(self):
        from utils.api_client import OllamaClient
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        with patch("requests.get", return_value=mock_resp):
            assert OllamaClient.list_models() == []


# ─────────────────────────────────────────────────────────────
# get_ai_client — branche ollama
# ─────────────────────────────────────────────────────────────


class TestGetAiClientOllama:
    """Tests pour get_ai_client() avec AI_PROVIDER=ollama."""

    def test_provider_ollama_returns_ollama_client(self):
        from utils.api_client import OllamaClient
        import utils.config as cfg_mod

        with patch.dict(os.environ, {**_ENV_BASE, "AI_PROVIDER": "ollama", "OLLAMA_MODEL": "qwen2.5:7b"}):
            cfg_mod._config_instance = None
            try:
                client = get_ai_client(fallback=False)
            finally:
                cfg_mod._config_instance = None
        assert isinstance(client, OllamaClient)

    def test_provider_ollama_uses_ollama_model_env(self):
        from utils.api_client import OllamaClient
        import utils.config as cfg_mod

        with patch.dict(os.environ, {**_ENV_BASE, "AI_PROVIDER": "ollama", "OLLAMA_MODEL": "qwen2.5:14b"}):
            cfg_mod._config_instance = None
            try:
                client = get_ai_client(fallback=False)
            finally:
                cfg_mod._config_instance = None
        assert isinstance(client, OllamaClient)
        assert client._ollama_model == "qwen2.5:14b"


# ─────────────────────────────────────────────────────────────
# get_ner_client
# ─────────────────────────────────────────────────────────────


class TestGetNerClient:
    """Tests pour get_ner_client() — routage NER vers Ollama ou cloud."""

    def test_import(self):
        from utils.api_client import get_ner_client
        assert callable(get_ner_client)

    def test_ner_provider_ollama_available_returns_ollama(self):
        from utils.api_client import OllamaClient, FallbackClient, get_ner_client
        with patch.dict(os.environ, {"AI_PROVIDER_NER": "ollama", "OLLAMA_MODEL": "qwen2.5:7b"}):
            with patch.object(OllamaClient, "is_available", return_value=True):
                client = get_ner_client()
        # get_ner_client retourne FallbackClient(OllamaClient, cloud) pour le fallback qualité
        assert isinstance(client, FallbackClient)
        assert isinstance(client._primary, OllamaClient)
        assert client._primary._ollama_model == "qwen2.5:7b"

    def test_ner_provider_ollama_unavailable_falls_back_to_cloud(self):
        from utils.api_client import EurIAClient, OllamaClient, get_ner_client
        import utils.config as cfg_mod

        with patch.dict(
            os.environ,
            {**_ENV_BASE, "AI_PROVIDER_NER": "ollama", "ANTHROPIC_API_KEY": ""},
            clear=False,
        ):
            cfg_mod._config_instance = None
            with patch.object(OllamaClient, "is_available", return_value=False):
                try:
                    client = get_ner_client()
                finally:
                    cfg_mod._config_instance = None
        assert isinstance(client, EurIAClient)

    def test_ner_provider_empty_returns_cloud(self):
        from utils.api_client import EurIAClient, get_ner_client
        import utils.config as cfg_mod

        with patch.dict(
            os.environ,
            {**_ENV_BASE, "AI_PROVIDER_NER": "", "ANTHROPIC_API_KEY": ""},
            clear=False,
        ):
            cfg_mod._config_instance = None
            try:
                client = get_ner_client()
            finally:
                cfg_mod._config_instance = None
        assert isinstance(client, EurIAClient)

    def test_ner_provider_not_set_returns_cloud(self):
        from utils.api_client import EurIAClient, get_ner_client
        import utils.config as cfg_mod

        env = {**_ENV_BASE, "ANTHROPIC_API_KEY": "", "AI_PROVIDER_NER": ""}
        with patch.dict(os.environ, env, clear=False):
            cfg_mod._config_instance = None
            try:
                client = get_ner_client()
            finally:
                cfg_mod._config_instance = None
        assert isinstance(client, EurIAClient)

    def test_ner_provider_ollama_custom_model(self):
        from utils.api_client import OllamaClient, FallbackClient, get_ner_client
        with patch.dict(os.environ, {"AI_PROVIDER_NER": "ollama", "OLLAMA_MODEL": "qwen2.5:14b"}):
            with patch.object(OllamaClient, "is_available", return_value=True):
                client = get_ner_client()
        # FallbackClient wraps OllamaClient — le modèle est accessible via _primary
        assert isinstance(client, FallbackClient)
        assert isinstance(client._primary, OllamaClient)
        assert client._primary._ollama_model == "qwen2.5:14b"


# ─────────────────────────────────────────────────────────────
# get_summary_client
# ─────────────────────────────────────────────────────────────

class TestGetSummaryClient:
    """Tests pour get_summary_client() — Option B résumés via Ollama."""

    def test_summary_provider_ollama_available_returns_fallback_client(self):
        from utils.api_client import OllamaClient, FallbackClient, get_summary_client
        with patch.dict(os.environ, {"AI_PROVIDER_SUMMARY": "ollama", "OLLAMA_MODEL": "qwen2.5:7b"}):
            with patch.object(OllamaClient, "is_available", return_value=True):
                client = get_summary_client()
        assert isinstance(client, FallbackClient)
        assert isinstance(client._primary, OllamaClient)
        assert client._primary._ollama_model == "qwen2.5:7b"

    def test_summary_provider_ollama_unavailable_falls_back_to_cloud(self):
        from utils.api_client import EurIAClient, OllamaClient, get_summary_client
        import utils.config as cfg_mod
        with patch.dict(
            os.environ,
            {**_ENV_BASE, "AI_PROVIDER_SUMMARY": "ollama", "ANTHROPIC_API_KEY": ""},
            clear=False,
        ):
            cfg_mod._config_instance = None
            with patch.object(OllamaClient, "is_available", return_value=False):
                try:
                    client = get_summary_client()
                finally:
                    cfg_mod._config_instance = None
        assert isinstance(client, EurIAClient)

    def test_summary_provider_empty_returns_cloud(self):
        from utils.api_client import EurIAClient, get_summary_client
        import utils.config as cfg_mod
        with patch.dict(
            os.environ,
            {**_ENV_BASE, "AI_PROVIDER_SUMMARY": "", "ANTHROPIC_API_KEY": ""},
            clear=False,
        ):
            cfg_mod._config_instance = None
            try:
                client = get_summary_client()
            finally:
                cfg_mod._config_instance = None
        assert isinstance(client, EurIAClient)

    def test_summary_generate_summary_with_sentiment_none_triggers_fallback(self):
        """generate_summary_with_sentiment None depuis Ollama → fallback cloud."""
        from utils.api_client import FallbackClient, OllamaClient, get_summary_client
        with patch.dict(os.environ, {"AI_PROVIDER_SUMMARY": "ollama"}):
            with patch.object(OllamaClient, "is_available", return_value=True):
                client = get_summary_client()
        cloud_result = {"resume": "résumé cloud", "sentiment": "neutre"}
        with patch.object(client._primary, "generate_summary_with_sentiment", return_value=None), \
             patch.object(client._secondary, "generate_summary_with_sentiment", return_value=cloud_result) as mock_cloud:
            result = client.generate_summary_with_sentiment("texte")
        assert result == cloud_result
        mock_cloud.assert_called_once()

    def test_summary_generate_summary_none_no_fallback(self):
        """generate_summary None depuis Ollama → pas de fallback (texte brut OK)."""
        from utils.api_client import FallbackClient, OllamaClient, get_summary_client
        with patch.dict(os.environ, {"AI_PROVIDER_SUMMARY": "ollama"}):
            with patch.object(OllamaClient, "is_available", return_value=True):
                client = get_summary_client()
        with patch.object(client._primary, "generate_summary", return_value=None), \
             patch.object(client._secondary, "generate_summary", return_value="résumé cloud") as mock_cloud:
            result = client.generate_summary("texte")
        assert result is None
        mock_cloud.assert_not_called()
