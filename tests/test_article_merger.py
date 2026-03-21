"""Tests pour utils/article_merger.py.

Couvre :
  - _get_entity_set
  - _jaccard_entities_weighted
  - _jaccard_bigrams_text
  - _temporal_bonus
  - _compute_similarity
  - _is_within_window
  - find_similar
"""

import json
import pytest
from pathlib import Path


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures / helpers
# ─────────────────────────────────────────────────────────────────────────────

def _article(
    url: str = "https://example.com/art",
    resume: str = "ceci est un résumé d'article",
    date: str = "15/01/2026",
    entities: dict | None = None,
    source: str = "Le Monde",
) -> dict:
    a = {
        "URL": url,
        "Résumé": resume,
        "Date de publication": date,
        "Sources": source,
    }
    if entities is not None:
        a["entities"] = entities
    return a


def _write_articles(path: Path, articles: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(articles, ensure_ascii=False), encoding="utf-8")


# ─────────────────────────────────────────────────────────────────────────────
# _get_entity_set
# ─────────────────────────────────────────────────────────────────────────────

class TestGetEntitySet:
    def _fn(self):
        from utils.article_merger import _get_entity_set
        return _get_entity_set

    def test_no_entities_returns_empty_dict(self):
        assert self._fn()({}) == {}

    def test_extracts_person_entities(self):
        a = _article(entities={"PERSON": ["Emmanuel Macron", "Alice Dupont"]})
        result = self._fn()(a)
        assert "PERSON" in result
        assert isinstance(result["PERSON"], frozenset)

    def test_normalizes_values(self):
        """Les valeurs doivent être normalisées (minuscules, etc.)."""
        a = _article(entities={"ORG": ["OpenAI", "openai"]})
        result = self._fn()(a)
        assert len(result["ORG"]) == 1  # dédupliqué après normalisation

    def test_empty_type_list_excluded(self):
        a = _article(entities={"PERSON": [], "ORG": ["Meta"]})
        result = self._fn()(a)
        assert "PERSON" not in result
        assert "ORG" in result


# ─────────────────────────────────────────────────────────────────────────────
# _jaccard_entities_weighted
# ─────────────────────────────────────────────────────────────────────────────

class TestJaccardEntitiesWeighted:
    def _fn(self):
        from utils.article_merger import _jaccard_entities_weighted
        return _jaccard_entities_weighted

    def test_no_entities_returns_zero(self):
        a = _article()
        b = _article(url="https://b.com")
        assert self._fn()(a, b) == 0.0

    def test_one_has_entities_other_does_not_returns_zero(self):
        a = _article(entities={"PERSON": ["Alice"]})
        b = _article(url="https://b.com")
        assert self._fn()(a, b) == 0.0

    def test_identical_entities_returns_one(self):
        ents = {"PERSON": ["Alice"], "ORG": ["Acme"]}
        a = _article(entities=ents)
        b = _article(url="https://b.com", entities=ents)
        assert self._fn()(a, b) == pytest.approx(1.0)

    def test_disjoint_entities_returns_zero(self):
        a = _article(entities={"PERSON": ["Alice"]})
        b = _article(url="https://b.com", entities={"PERSON": ["Bob"]})
        assert self._fn()(a, b) == pytest.approx(0.0)

    def test_partial_overlap_between_zero_and_one(self):
        a = _article(entities={"PERSON": ["Alice", "Bob"]})
        b = _article(url="https://b.com", entities={"PERSON": ["Alice", "Carol"]})
        score = self._fn()(a, b)
        assert 0.0 < score < 1.0

    def test_person_weighted_higher_contributes_more(self):
        """PERSON (poids 1.5) contribue plus que DATE (poids 0.3) dans le score composite.

        Cas 1 : PERSON différentes, DATE identique → score faible (DATE peu pondérée)
        Cas 2 : PERSON identique, DATE différente  → score élevé (PERSON bien pondérée)
        """
        # Cas 1 : seule DATE est en commun (faible poids)
        a1 = _article(entities={"PERSON": ["Alice"], "DATE": ["2026-01-01"]})
        b1 = _article(url="https://b1.com", entities={"PERSON": ["Bob"],   "DATE": ["2026-01-01"]})
        # Cas 2 : seule PERSON est en commun (poids élevé)
        a2 = _article(entities={"PERSON": ["Alice"], "DATE": ["2026-01-01"]})
        b2 = _article(url="https://b2.com", entities={"PERSON": ["Alice"], "DATE": ["2026-12-31"]})

        score_date_in_common   = self._fn()(a1, b1)  # DATE partagée — peu pondérée
        score_person_in_common = self._fn()(a2, b2)  # PERSON partagée — bien pondérée

        assert score_person_in_common > score_date_in_common


# ─────────────────────────────────────────────────────────────────────────────
# _jaccard_bigrams_text
# ─────────────────────────────────────────────────────────────────────────────

class TestJaccardBigramsText:
    def _fn(self):
        from utils.article_merger import _jaccard_bigrams_text
        return _jaccard_bigrams_text

    def test_empty_texts_return_zero(self):
        assert self._fn()("", "") == 0.0

    def test_one_empty_returns_zero(self):
        assert self._fn()("hello world", "") == 0.0

    def test_identical_text_returns_one(self):
        text = "le président a rencontré le groupe de travail"
        assert self._fn()(text, text) == pytest.approx(1.0)

    def test_disjoint_text_returns_zero(self):
        a = "alpha beta gamma delta"
        b = "zulu yankee whiskey tango"
        assert self._fn()(a, b) == 0.0

    def test_partial_overlap_between_zero_and_one(self):
        # Les 3 premières paires de mots sont identiques → chevauchement partiel
        a = "intelligence artificielle generative revolutionne industries numeriques medias"
        b = "intelligence artificielle generative transforme secteur medias numeriques"
        score = self._fn()(a, b)
        assert 0.0 < score < 1.0


# ─────────────────────────────────────────────────────────────────────────────
# _temporal_bonus
# ─────────────────────────────────────────────────────────────────────────────

class TestTemporalBonus:
    def _fn(self):
        from utils.article_merger import _temporal_bonus
        return _temporal_bonus

    def test_same_date_returns_one(self):
        assert self._fn()("15/01/2026", "15/01/2026") == pytest.approx(1.0)

    def test_one_day_apart_returns_one(self):
        assert self._fn()("15/01/2026", "16/01/2026") == pytest.approx(1.0)

    def test_two_days_apart_returns_one(self):
        assert self._fn()("15/01/2026", "17/01/2026") == pytest.approx(1.0)

    def test_three_days_apart_returns_half(self):
        assert self._fn()("15/01/2026", "18/01/2026") == pytest.approx(0.5)

    def test_seven_days_apart_returns_half(self):
        assert self._fn()("01/01/2026", "08/01/2026") == pytest.approx(0.5)

    def test_eight_days_apart_returns_zero(self):
        assert self._fn()("01/01/2026", "09/01/2026") == pytest.approx(0.0)

    def test_missing_date_returns_zero(self):
        assert self._fn()("", "15/01/2026") == pytest.approx(0.0)

    def test_both_missing_returns_zero(self):
        assert self._fn()("", "") == pytest.approx(0.0)


# ─────────────────────────────────────────────────────────────────────────────
# _compute_similarity
# ─────────────────────────────────────────────────────────────────────────────

class TestComputeSimilarity:
    def _fn(self):
        from utils.article_merger import _compute_similarity
        return _compute_similarity

    def test_returns_required_keys(self):
        a = _article()
        b = _article(url="https://b.com")
        result = self._fn()(a, b)
        assert "score" in result
        assert "score_entites" in result
        assert "score_bigrammes" in result
        assert "score_temporel" in result

    def test_score_is_composite(self):
        """score = 0.40*entities + 0.35*bigrams + 0.15*temporal."""
        from utils.article_merger import _compute_similarity
        text = "macron rencontre ursula von der leyen à bruxelles"
        ents = {"PERSON": ["Macron"], "GPE": ["Bruxelles"]}
        a = _article(resume=text, date="15/01/2026", entities=ents)
        b = _article(url="https://b.com", resume=text, date="15/01/2026", entities=ents)
        result = self._fn()(a, b)
        expected = round(
            0.40 * result["score_entites"]
            + 0.35 * result["score_bigrammes"]
            + 0.15 * result["score_temporel"],
            3,
        )
        assert result["score"] == expected

    def test_identical_articles_high_score(self):
        text = "l'intelligence artificielle révolutionne les médias numériques"
        ents = {"PRODUCT": ["ChatGPT"], "ORG": ["OpenAI"]}
        a = _article(resume=text, date="01/02/2026", entities=ents)
        b = _article(url="https://b.com", resume=text, date="01/02/2026", entities=ents)
        result = self._fn()(a, b)
        assert result["score"] > 0.5

    def test_unrelated_articles_low_score(self):
        a = _article(
            resume="le football est populaire en europe",
            date="01/01/2026",
            entities={"GPE": ["France"]},
        )
        b = _article(
            url="https://b.com",
            resume="la météo sera ensoleillée demain matin",
            date="15/06/2026",
            entities={"GPE": ["Brésil"]},
        )
        result = self._fn()(a, b)
        assert result["score"] < 0.35

    def test_no_entities_uses_bigrams_only(self):
        """Sans entités, les bigrammes + temporel déterminent le score."""
        text = "la réforme des retraites en france est controversée"
        a = _article(resume=text, date="10/01/2026")
        b = _article(url="https://b.com", resume=text, date="10/01/2026")
        result = self._fn()(a, b)
        assert result["score_entites"] == 0.0
        assert result["score_bigrammes"] == pytest.approx(1.0)


# ─────────────────────────────────────────────────────────────────────────────
# _is_within_window
# ─────────────────────────────────────────────────────────────────────────────

class TestIsWithinWindow:
    def _fn(self):
        from utils.article_merger import _is_within_window
        return _is_within_window

    def test_same_date_within_any_window(self):
        assert self._fn()("15/01/2026", "15/01/2026", days=1) is True

    def test_exactly_at_limit(self):
        assert self._fn()("01/01/2026", "08/01/2026", days=7) is True

    def test_just_beyond_limit(self):
        assert self._fn()("01/01/2026", "09/01/2026", days=7) is False

    def test_missing_date_a_returns_false(self):
        assert self._fn()("", "15/01/2026", days=7) is False

    def test_missing_date_b_returns_false(self):
        assert self._fn()("15/01/2026", "", days=7) is False

    def test_both_missing_returns_false(self):
        assert self._fn()("", "", days=7) is False

    def test_window_of_zero_days_only_same_date(self):
        assert self._fn()("15/01/2026", "15/01/2026", days=0) is True
        assert self._fn()("15/01/2026", "16/01/2026", days=0) is False


# ─────────────────────────────────────────────────────────────────────────────
# find_similar
# ─────────────────────────────────────────────────────────────────────────────

class TestFindSimilar:
    """Tests d'intégration pour find_similar avec corpus dans tmp_path."""

    def _fn(self):
        from utils.article_merger import find_similar
        return find_similar

    def _project(self, tmp_path: Path) -> Path:
        (tmp_path / "data" / "articles" / "flux1").mkdir(parents=True)
        return tmp_path

    def test_empty_corpus_returns_empty_list(self, tmp_path):
        proj = self._project(tmp_path)
        source = _article()
        result = self._fn()(source, proj)
        assert result == []

    def test_finds_similar_article_by_text(self, tmp_path):
        proj = self._project(tmp_path)
        text = "macron dévoile son plan pour la réforme de l'éducation nationale"
        source = _article(resume=text, date="15/01/2026")
        similar = _article(
            url="https://similar.com/art",
            resume=text + " suite de l'article",
            date="15/01/2026",
        )
        _write_articles(
            proj / "data" / "articles" / "flux1" / "articles.json",
            [similar]
        )
        result = self._fn()(source, proj)
        assert len(result) >= 1
        assert result[0]["article"]["URL"] == "https://similar.com/art"

    def test_self_not_returned(self, tmp_path):
        """L'article source lui-même ne doit pas apparaître dans les résultats."""
        proj = self._project(tmp_path)
        same_url = "https://self.com/art"
        source = _article(url=same_url,
                          resume="le gouvernement présente son budget 2026")
        _write_articles(
            proj / "data" / "articles" / "flux1" / "articles.json",
            [source]  # même article dans le corpus
        )
        result = self._fn()(source, proj)
        for item in result:
            assert item["article"]["URL"] != same_url

    def test_results_sorted_by_score_descending(self, tmp_path):
        proj = self._project(tmp_path)
        text_base = "intelligence artificielle générative et modèles de langage"
        source = _article(resume=text_base, date="01/02/2026")
        art_high = _article(
            url="https://high.com",
            resume=text_base + " openai anthropic google deepmind",
            date="01/02/2026",
        )
        art_low = _article(
            url="https://low.com",
            resume=text_base + " sport football ligue des champions",
            date="01/02/2026",
        )
        _write_articles(
            proj / "data" / "articles" / "flux1" / "articles.json",
            [art_high, art_low]
        )
        results = self._fn()(source, proj, threshold=0.0)
        if len(results) >= 2:
            assert results[0]["score"] >= results[1]["score"]

    def test_below_threshold_excluded(self, tmp_path):
        proj = self._project(tmp_path)
        source = _article(resume="l'économie française est en croissance")
        unrelated = _article(
            url="https://unrelated.com",
            resume="victoire de l'équipe de rugby lors du tournoi des six nations",
            date="01/06/2026",  # hors fenêtre temporelle aussi
        )
        _write_articles(
            proj / "data" / "articles" / "flux1" / "articles.json",
            [unrelated]
        )
        result = self._fn()(source, proj, days=7, threshold=0.35)
        # Soit vide, soit les scores sont tous ≥ threshold
        for item in result:
            assert item["score"] >= 0.35

    def test_index_files_not_scanned(self, tmp_path):
        """Les fichiers d'index ne doivent pas être lus comme articles."""
        proj = self._project(tmp_path)
        source = _article(resume="test article content")
        # Écrire un 'article' dans un fichier d'index — doit être ignoré
        (tmp_path / "data" / "article_index.json").write_text(
            json.dumps([{"URL": "https://index.com", "Résumé": "test article content",
                          "Date de publication": "15/01/2026", "Sources": "Index"}])
        )
        result = self._fn()(source, proj)
        for item in result:
            assert item["article"]["URL"] != "https://index.com"

    def test_cache_dirs_not_scanned(self, tmp_path):
        """Les sous-dossiers 'cache' doivent être ignorés."""
        proj = self._project(tmp_path)
        source = _article(resume="résumé de test pour fusion")
        cache_dir = tmp_path / "data" / "articles" / "flux1" / "cache"
        cache_dir.mkdir(parents=True)
        (cache_dir / "cached.json").write_text(
            json.dumps([{
                "URL": "https://cached.com",
                "Résumé": "résumé de test pour fusion",
                "Date de publication": "15/01/2026",
                "Sources": "Cache"
            }])
        )
        result = self._fn()(source, proj)
        for item in result:
            assert item["article"]["URL"] != "https://cached.com"

    def test_file_path_in_result_is_relative(self, tmp_path):
        proj = self._project(tmp_path)
        text = "la politique étrangère de l'union européenne au proche-orient"
        source = _article(resume=text, date="15/01/2026")
        similar = _article(url="https://similar.com", resume=text, date="15/01/2026")
        _write_articles(
            proj / "data" / "articles" / "flux1" / "articles.json",
            [similar]
        )
        results = self._fn()(source, proj)
        if results:
            file_path = results[0]["file_path"]
            assert not file_path.startswith("/"), "file_path doit être relatif"
