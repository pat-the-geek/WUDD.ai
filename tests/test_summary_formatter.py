"""Tests pour utils/summary_formatter.py.

Couvre :
  - degrade_overbold : garde-fou anti sur-gras (lignes entières / ratio élevé), titres préservés
  - format_summary_markdown : délégation à get_summary_client, repli sur échec
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.summary_formatter import degrade_overbold, format_summary_markdown


class TestDegradeOverbold:
    def test_ligne_entierement_grasse_deshabillee(self):
        assert degrade_overbold("**Toute la ligne en gras**") == "Toute la ligne en gras"

    def test_titre_preserve(self):
        assert degrade_overbold("### En bref") == "### En bref"

    def test_gras_parcimonieux_conserve(self):
        line = "OpenAI lance **ChatGPT** pour les entreprises cette année."
        assert degrade_overbold(line) == line  # ratio de gras faible → conservé

    def test_ratio_eleve_deshabille(self):
        # > 60% de la ligne en gras → marqueurs retirés
        line = "**OpenAI lance une super application** aujourd'hui."
        out = degrade_overbold(line)
        assert "**" not in out
        assert "OpenAI lance une super application aujourd'hui." in out

    def test_multilignes_mixte(self):
        txt = "### Titre\n**Phrase entière en gras.**\nTexte avec **mot** clé."
        out = degrade_overbold(txt).split("\n")
        assert out[0] == "### Titre"
        assert out[1] == "Phrase entière en gras."
        assert out[2] == "Texte avec **mot** clé."


class TestFormatSummaryMarkdown:
    def test_resume_vide_retourne_vide(self):
        assert format_summary_markdown("") == ""
        assert format_summary_markdown("   ") == ""

    def test_delegue_au_client_et_degrade(self):
        client = MagicMock()
        client.ask.return_value = "### En bref\n**Ligne entière en gras à déshabiller.**"
        with patch("utils.api_client.get_summary_client", return_value=client):
            out = format_summary_markdown("Un résumé suffisamment long pour être reformaté.")
        assert out.startswith("### En bref")
        assert "**" not in out  # la ligne entièrement grasse a été déshabillée
        client.ask.assert_called_once()

    def test_repli_sur_exception(self):
        client = MagicMock()
        client.ask.side_effect = RuntimeError("Ollama injoignable")
        with patch("utils.api_client.get_summary_client", return_value=client):
            assert format_summary_markdown("Un résumé assez long pour reformatage.") == ""

    def test_repli_sur_reponse_erreur(self):
        client = MagicMock()
        client.ask.return_value = "Erreur : modèle indisponible"
        with patch("utils.api_client.get_summary_client", return_value=client):
            assert format_summary_markdown("Un résumé assez long pour reformatage.") == ""

    def test_entity_label_dans_le_prompt(self):
        client = MagicMock()
        client.ask.return_value = "### En bref\nTexte."
        with patch("utils.api_client.get_summary_client", return_value=client):
            format_summary_markdown("Résumé mentionnant OpenAI longuement ici.", entity_label="OpenAI")
        prompt = client.ask.call_args[0][0]
        assert "OpenAI" in prompt
