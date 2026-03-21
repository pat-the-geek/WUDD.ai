"""Tests pour utils/scoring.py et utils/cache.py.

Couvre :
  - Fonctions de scoring : fraîcheur, entités, mots-clés, complétude, régularité
  - CACHE_TTL et get_ttl()
  - Cache : set/get, expiration, delete, clear, isolation par provider
"""

import json
import os
import time
import math
import pytest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch


# ─────────────────────────────────────────────────────────────────────────────
# scoring.py — fonctions internes
# ─────────────────────────────────────────────────────────────────────────────

class TestFreshnessScore:
    def setup_method(self):
        from utils.scoring import _freshness_score
        self.fn = _freshness_score
        self.now = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

    def test_very_recent_article_near_100(self):
        date_str = "2026-01-15T11:30:00Z"  # 30min ago
        score = self.fn(date_str, self.now)
        assert score > 95.0

    def test_article_24h_old_near_50(self):
        date_str = "2026-01-14T12:00:00Z"  # exactly 24h
        score = self.fn(date_str, self.now)
        # half-life=24h → score ≈ 50
        assert 45.0 < score < 55.0

    def test_article_7_days_old_around_20(self):
        date_str = "2026-01-08T12:00:00Z"  # 7 days = 168h
        score = self.fn(date_str, self.now)
        # 100 * exp(-0.693 * 7) = 100 / 2^7 ≈ 0.78 — très faible après 7 jours
        assert score < 5.0
        assert score > 0.0

    def test_article_30_days_old_very_low(self):
        date_str = "2025-12-16T12:00:00Z"  # 30 days
        score = self.fn(date_str, self.now)
        assert score < 15.0

    def test_unknown_date_returns_neutral(self):
        score = self.fn("not-a-date", self.now)
        assert score == 20.0

    def test_empty_date_returns_neutral(self):
        score = self.fn("", self.now)
        assert score == 20.0

    def test_score_never_negative(self):
        date_str = "2000-01-01T00:00:00Z"  # very old
        score = self.fn(date_str, self.now)
        assert score >= 0.0

    def test_score_never_exceeds_100(self):
        date_str = "2026-01-15T11:59:59Z"  # 1s ago
        score = self.fn(date_str, self.now)
        assert score <= 100.0

    def test_dd_mm_yyyy_format_parsed(self):
        score = self.fn("15/01/2026", self.now)
        assert score > 0.0

    def test_iso_date_only_format_parsed(self):
        score = self.fn("2026-01-15", self.now)
        assert score > 0.0


class TestEntityScore:
    def setup_method(self):
        from utils.scoring import _entity_score
        self.fn = _entity_score

    def test_empty_entities_returns_zero(self):
        assert self.fn({}) == 0.0

    def test_none_returns_zero(self):
        assert self.fn(None) == 0.0

    def test_non_dict_returns_zero(self):
        assert self.fn("invalid") == 0.0

    def test_persons_weighted_highest(self):
        score_persons = self.fn({"PERSON": ["A", "B", "C"]})
        score_dates   = self.fn({"DATE": ["A", "B", "C"]})
        assert score_persons > score_dates

    def test_score_capped_at_100(self):
        large = {t: [f"e{i}" for i in range(20)] for t in ["PERSON", "ORG", "GPE"]}
        assert self.fn(large) == 100.0

    def test_single_person_positive(self):
        assert self.fn({"PERSON": ["Alice"]}) > 0.0

    def test_unknown_entity_type_uses_default_weight(self):
        score = self.fn({"UNKNOWN_TYPE": ["x", "y"]})
        assert score > 0.0

    def test_non_list_value_ignored(self):
        # Si la valeur n'est pas une liste, la fonction doit l'ignorer sans planter
        score = self.fn({"PERSON": "not-a-list"})
        assert isinstance(score, float)
        assert score >= 0.0


class TestKeywordScore:
    def setup_method(self):
        from utils.scoring import _keyword_score
        self.fn = _keyword_score

    def test_no_keywords_returns_zero(self):
        assert self.fn("texte avec contenu", []) == 0.0

    def test_empty_resume_returns_zero(self):
        assert self.fn("", ["intelligence", "artificielle"]) == 0.0

    def test_no_match_returns_zero(self):
        assert self.fn("bonjour le monde", ["intelligence", "robot"]) == 0.0

    def test_one_match_returns_33(self):
        score = self.fn("l'intelligence artificielle progresse", ["intelligence"])
        assert abs(score - 33.3) < 1.0

    def test_three_matches_returns_100(self):
        resume = "intelligence artificielle chatgpt"
        score = self.fn(resume, ["intelligence", "artificielle", "chatgpt"])
        # 3 * 33.3 = 99.9 ≈ 100 (flòating‑point)
        assert score == pytest.approx(100.0, abs=0.2)

    def test_capped_at_100(self):
        keywords = [f"kw{i}" for i in range(20)]
        resume = " ".join(keywords)
        assert self.fn(resume, keywords) == 100.0

    def test_case_insensitive(self):
        score = self.fn("L'INTELLIGENCE ARTIFICIELLE", ["intelligence"])
        assert score > 0.0


class TestCompletenessScore:
    def setup_method(self):
        from utils.scoring import _completeness_score
        self.fn = _completeness_score

    def test_full_article_scores_100(self):
        article = {
            "Résumé": "x" * 200,
            "Images": [{"url": "https://img.example.com/photo.jpg"}],
            "sentiment": "positif",
            "entities": {"PERSON": ["Alice"]},
        }
        assert self.fn(article) == 100.0

    def test_no_resume_scores_zero(self):
        assert self.fn({}) == 0.0

    def test_short_resume_no_bonus(self):
        article = {"Résumé": "court"}
        assert self.fn(article) == 0.0

    def test_error_prefix_no_resume_bonus(self):
        article = {"Résumé": "Erreur lors de la génération du résumé. " * 5}
        score = self.fn(article)
        # Score < 50 (pas de bonus résumé)
        assert score < 50.0

    def test_resume_only_scores_50(self):
        article = {"Résumé": "x" * 200}
        assert self.fn(article) == 50.0

    def test_images_add_25(self):
        article = {
            "Résumé": "x" * 200,
            "Images": [{"url": "https://img.example.com/photo.jpg"}],
        }
        assert self.fn(article) == 75.0

    def test_sentiment_adds_12_5(self):
        article = {
            "Résumé": "x" * 200,
            "sentiment": "neutre",
        }
        assert self.fn(article) == 62.5

    def test_entities_add_12_5(self):
        article = {
            "Résumé": "x" * 200,
            "entities": {"PERSON": ["Alice"]},
        }
        assert self.fn(article) == 62.5


class TestRegularityMalus:
    def setup_method(self):
        from utils.scoring import _regularity_malus
        self.fn = _regularity_malus

    def test_few_articles_no_malus(self):
        """Moins de 10 articles → pas de malus."""
        articles_by_src = {"Le Monde": [1000.0 * i for i in range(5)]}
        assert self.fn("Le Monde", articles_by_src) == 0.0

    def test_missing_source_no_malus(self):
        assert self.fn("Source Inconnue", {}) == 0.0

    def test_very_regular_source_no_malus(self):
        """Source publiant toutes les 2h exactement → std < 24h → 0."""
        base = 1_000_000.0
        intervals_2h = [base + i * 7200.0 for i in range(20)]
        articles_by_src = {"Source": intervals_2h}
        assert self.fn("Source", articles_by_src) == 0.0

    def test_irregular_source_gets_malus(self):
        """Source avec intervalles très irréguliers (alternant 1h et 200h) → malus négatif."""
        # Intervals: 1h, 200h, 1h, 200h... std ≈ 99.5h >> 72h threshold
        timestamps = [0.0]
        for i in range(19):
            gap = 3600.0 if i % 2 == 0 else 720000.0  # 1h ou 200h
            timestamps.append(timestamps[-1] + gap)
        articles_by_src = {"IrregSource": timestamps}
        malus = self.fn("IrregSource", articles_by_src)
        assert malus < 0.0


class TestTriangulationBonus:
    def setup_method(self):
        from utils.scoring import _triangulation_bonus
        self.fn = _triangulation_bonus

    def test_no_corpus_returns_zero(self):
        assert self.fn({}, [], credibility=None) == 0.0

    def test_null_credibility_returns_zero(self):
        article = {"Résumé": "x" * 200, "Sources": "Le Monde"}
        corpus = [{"Résumé": "x" * 200, "Sources": "Le Figaro"}]
        assert self.fn(article, corpus, credibility=None) == 0.0

    def test_no_confirming_sources_returns_zero(self):
        cred = _make_credibility_mock(score=30)  # score trop faible
        article = {"Résumé": "a b c d e f g h i j k l m n o", "Sources": "A"}
        corpus = [{"Résumé": "a b c d e f g h i j k l m n o", "Sources": "B"}]
        assert self.fn(article, corpus, credibility=cred) == 0.0

    def test_two_confirming_sources_returns_4(self):
        cred = _make_credibility_mock(score=80)
        long_resume = "intelligence artificielle france paris openai chatgpt europe innovation" * 5
        article = {"Résumé": long_resume, "Sources": "Source_A"}
        corpus = [
            {"Résumé": long_resume, "Sources": "Source_B"},
            {"Résumé": long_resume, "Sources": "Source_C"},
        ]
        bonus = self.fn(article, corpus, credibility=cred)
        assert bonus == 4.0

    def test_four_confirming_sources_returns_10(self):
        cred = _make_credibility_mock(score=80)
        long_resume = "intelligence artificielle france paris openai chatgpt europe innovation" * 5
        article = {"Résumé": long_resume, "Sources": "Source_A"}
        corpus = [
            {"Résumé": long_resume, "Sources": f"Source_{c}"}
            for c in ["B", "C", "D", "E"]
        ]
        bonus = self.fn(article, corpus, credibility=cred)
        assert bonus == 10.0


def _make_credibility_mock(score: int):
    """Crée un mock de CredibilityEngine avec un score fixe."""
    from unittest.mock import MagicMock
    cred = MagicMock()
    cred.get_composite_score.return_value = score
    return cred


# ─────────────────────────────────────────────────────────────────────────────
# cache.py — TTL et opérations de cache
# ─────────────────────────────────────────────────────────────────────────────

class TestCacheTTL:
    def test_all_8_types_present(self):
        from utils.cache import CACHE_TTL
        expected = {"summary", "entities", "sentiment", "synthesis",
                    "geocode", "images", "html", "report"}
        assert expected == set(CACHE_TTL.keys())

    def test_summary_24h(self):
        from utils.cache import CACHE_TTL
        assert CACHE_TTL["summary"] == 86400

    def test_entities_7_days(self):
        from utils.cache import CACHE_TTL
        assert CACHE_TTL["entities"] == 604800

    def test_sentiment_7_days(self):
        from utils.cache import CACHE_TTL
        assert CACHE_TTL["sentiment"] == 604800

    def test_synthesis_1h(self):
        from utils.cache import CACHE_TTL
        assert CACHE_TTL["synthesis"] == 3600

    def test_geocode_30_days(self):
        from utils.cache import CACHE_TTL
        assert CACHE_TTL["geocode"] == 2592000

    def test_html_12h(self):
        from utils.cache import CACHE_TTL
        assert CACHE_TTL["html"] == 43200


class TestGetTTL:
    def setup_method(self):
        from utils.cache import get_ttl
        self.fn = get_ttl

    def test_known_type_returns_correct_ttl(self):
        assert self.fn("summary") == 86400
        assert self.fn("entities") == 604800

    def test_unknown_type_returns_24h_default(self):
        assert self.fn("unknown_type") == 86400

    def test_empty_string_returns_default(self):
        assert self.fn("") == 86400


class TestCacheSetGet:
    def test_set_and_get_string(self, tmp_path):
        from utils.cache import Cache
        c = Cache(cache_dir=tmp_path)
        c.set("my_key", "hello world")
        assert c.get("my_key") == "hello world"

    def test_set_and_get_dict(self, tmp_path):
        from utils.cache import Cache
        c = Cache(cache_dir=tmp_path)
        data = {"a": 1, "b": [1, 2, 3]}
        c.set("json_key", data)
        result = c.get("json_key")
        assert result == data

    def test_miss_returns_none(self, tmp_path):
        from utils.cache import Cache
        c = Cache(cache_dir=tmp_path)
        assert c.get("non_existent") is None

    def test_expired_entry_returns_none(self, tmp_path):
        from utils.cache import Cache
        c = Cache(cache_dir=tmp_path, default_ttl=1)
        c.set("expiry_key", "value")
        time.sleep(1.1)
        # TTL=1s, donc expiré
        assert c.get("expiry_key", ttl=1) is None

    def test_custom_ttl_overrides_default(self, tmp_path):
        """Un TTL plus court que l'âge du cache doit forcer l'expiration."""
        from utils.cache import Cache
        c = Cache(cache_dir=tmp_path, default_ttl=3600)
        c.set("stale_key", "stale_value")
        # Falsifier le timestamp pour simuler une entrée vieille de 10 secondes
        key_hash = c._get_cache_key("stale_key")
        cache_file = tmp_path / f"{key_hash}.json"
        data = json.loads(cache_file.read_text(encoding="utf-8"))
        data["timestamp"] = (datetime.now() - timedelta(seconds=10)).isoformat()
        cache_file.write_text(json.dumps(data), encoding="utf-8")
        # TTL de 5s → l'entrée a 10s → expirée
        assert c.get("stale_key", ttl=5) is None

    def test_valid_entry_still_returns_value(self, tmp_path):
        from utils.cache import Cache
        c = Cache(cache_dir=tmp_path, default_ttl=86400)
        c.set("fresh_key", {"status": "ok"})
        assert c.get("fresh_key") == {"status": "ok"}


class TestCacheDelete:
    def test_delete_existing_key(self, tmp_path):
        from utils.cache import Cache
        c = Cache(cache_dir=tmp_path)
        c.set("del_key", "to_delete")
        assert c.delete("del_key") is True
        assert c.get("del_key") is None

    def test_delete_missing_key_returns_false(self, tmp_path):
        from utils.cache import Cache
        c = Cache(cache_dir=tmp_path)
        assert c.delete("ghost_key") is False


class TestCacheClear:
    def test_clear_all_removes_all_entries(self, tmp_path):
        from utils.cache import Cache
        c = Cache(cache_dir=tmp_path)
        c.set("k1", "v1")
        c.set("k2", "v2")
        deleted = c.clear()
        assert deleted == 2
        assert c.get("k1") is None
        assert c.get("k2") is None

    def test_clear_older_than_keeps_fresh_entries(self, tmp_path):
        from utils.cache import Cache
        c = Cache(cache_dir=tmp_path)
        c.set("fresh", "value")
        # Créer un fichier de cache "vieux" manuellement avec un timestamp passé
        old_path = tmp_path / "old_entry.json"
        old_data = {
            "timestamp": (datetime.now() - timedelta(hours=48)).isoformat(),
            "key": "old",
            "value": "old_value",
        }
        old_path.write_text(json.dumps(old_data), encoding="utf-8")
        # clear(older_than=3600) doit supprimer old (48h) mais garder fresh
        deleted = c.clear(older_than=3600)
        assert deleted >= 1
        # L'entrée fraîche doit encore être lisible
        assert c.get("fresh") == "value"

    def test_clear_empty_cache_returns_zero(self, tmp_path):
        from utils.cache import Cache
        c = Cache(cache_dir=tmp_path)
        assert c.clear() == 0


class TestCacheProviderIsolation:
    def test_different_providers_different_keys(self, tmp_path):
        """Les clés EurIA et Claude ne doivent pas se croiser."""
        from utils.cache import Cache
        with patch.dict(os.environ, {"AI_PROVIDER": "euria"}):
            c_euria = Cache(cache_dir=tmp_path)
            c_euria.set("prompt_x", "response_euria")

        with patch.dict(os.environ, {"AI_PROVIDER": "claude"}):
            c_claude = Cache(cache_dir=tmp_path)
            result = c_claude.get("prompt_x")
        # Ne doit pas retourner la réponse EurIA
        assert result != "response_euria"

    def test_same_provider_same_key_hits(self, tmp_path):
        from utils.cache import Cache
        with patch.dict(os.environ, {"AI_PROVIDER": "euria"}):
            c1 = Cache(cache_dir=tmp_path)
            c1.set("shared_key", "v1")
            c2 = Cache(cache_dir=tmp_path)
            assert c2.get("shared_key") == "v1"


class TestCacheCorruption:
    def test_corrupted_file_returns_none(self, tmp_path):
        from utils.cache import Cache
        c = Cache(cache_dir=tmp_path)
        # Écrire un fichier JSON invalide à la place d'une entrée de cache
        key_hash = c._get_cache_key("corrupted_entry")
        corrupt_file = tmp_path / f"{key_hash}.json"
        corrupt_file.write_text("not valid json!!!!", encoding="utf-8")
        result = c.get("corrupted_entry")
        assert result is None
