"""Tests ciblés pour le rendu Markdown du Morning Digest."""

from scripts.generate_morning_digest import _article_display_title, _highlight_ner


def test_highlight_ner_avoids_nested_entity_markup():
    text = "Le peuple Palestinien souffre et le Palestinien exile temoigne."
    entities = {
        "GPE": ["peuple Palestinien", "Palestinien"],
        "PERSON": ["Palestinien exile"],
    }

    result = _highlight_ner(text, entities)

    assert "**peuple Palestinien** *(GPE)*" in result
    assert "**Palestinien exile** *(PERSON)*" in result
    assert "**peuple **Palestinien**" not in result
    assert result.count("*(GPE)*") == 1


def test_highlight_ner_only_highlights_first_occurrence_per_entity():
    text = "OpenAI lance un modele. OpenAI publie ensuite une note."
    entities = {"ORG": ["OpenAI"]}

    result = _highlight_ner(text, entities)

    assert result.count("**OpenAI** *(ORG)*") == 1
    assert result.endswith("OpenAI publie ensuite une note.")


def test_article_display_title_prefers_explicit_title_field():
    article = {
        "Titre": "La grande solitude des juifs face à Israël",
        "Résumé": "Le texte évoque le sentiment de solitude experimente...",
    }

    assert _article_display_title(article) == "La grande solitude des juifs face à Israël"


def test_article_display_title_falls_back_to_summary_when_no_title_exists():
    article = {
        "Résumé": "Premiere ligne du resume.\nDeuxieme ligne.",
        "Images": [{"title": ""}],
    }

    assert _article_display_title(article) == "Premiere ligne du resume."