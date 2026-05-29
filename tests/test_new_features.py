"""Tests pour les nouvelles fonctionnalités WUDD.ai v2.3.

Couvre :
  - utils/deduplication.py
  - utils/source_credibility.py
  - utils/reading_time.py
"""

import json
import tempfile
from pathlib import Path

import pytest

# ─────────────────────────────────────────────────────────────────────────────
# utils/deduplication.py
# ─────────────────────────────────────────────────────────────────────────────

class TestComputeTitleSimilarity:
    """Tests pour compute_title_similarity."""

    def setup_method(self):
        from utils.deduplication import compute_title_similarity
        self.sim = compute_title_similarity

    def test_identical_titles_score_1(self):
        assert self.sim("OpenAI lance GPT-5", "OpenAI lance GPT-5") == 1.0

    def test_empty_titles_score_0(self):
        assert self.sim("", "") == 0.0

    def test_one_empty_score_0(self):
        assert self.sim("OpenAI", "") == 0.0
        assert self.sim("", "OpenAI") == 0.0

    def test_different_titles_low_score(self):
        score = self.sim("Recette de tarte aux pommes", "Résultats financiers Apple")
        assert score < 0.3

    def test_similar_titles_high_score(self):
        score = self.sim(
            "IA générative : les défis de 2025",
            "Intelligence artificielle générative les défis en 2025",
        )
        assert score >= 0.4  # suffisamment similaires

    def test_accent_insensitive(self):
        # Les accents ne doivent pas empêcher la détection de similarité
        score = self.sim("déploiement IA", "deploiement IA")
        assert score >= 0.8

    def test_case_insensitive(self):
        score = self.sim("OPENAI GPT", "openai gpt")
        assert score == 1.0


class TestDeduplicator:
    """Tests pour la classe Deduplicator."""

    def setup_method(self):
        from utils.deduplication import Deduplicator
        self.Deduplicator = Deduplicator

    def _make_article(self, url="http://example.com/a", title="", resume=""):
        return {"URL": url, "Titre": title, "Résumé": resume}

    def test_strict_url_duplicate_removed(self):
        dedup = self.Deduplicator()
        articles = [
            self._make_article("http://example.com/1", "Article A"),
            self._make_article("http://example.com/1", "Article A bis"),  # même URL
        ]
        result = dedup.deduplicate(articles)
        assert len(result) == 1
        assert dedup.stats["removed"] == 1

    def test_unique_articles_kept(self):
        dedup = self.Deduplicator()
        articles = [
            self._make_article("http://example.com/1", "Article A"),
            self._make_article("http://example.com/2", "Article B"),
            self._make_article("http://example.com/3", "Article C"),
        ]
        result = dedup.deduplicate(articles)
        assert len(result) == 3
        assert dedup.stats["removed"] == 0

    def test_title_similarity_duplicate_removed(self):
        dedup = self.Deduplicator(title_threshold=0.80)
        # Même titre, URLs différentes
        articles = [
            self._make_article("http://lefigaro.fr/1", "OpenAI lance son modèle GPT-5 révolutionnaire"),
            self._make_article("http://lemonde.fr/1",  "OpenAI lance modèle GPT-5 révolutionnaire"),
        ]
        result = dedup.deduplicate(articles)
        assert len(result) == 1

    def test_resume_fingerprint_duplicate_removed(self):
        dedup = self.Deduplicator()
        resume = "A" * 210  # long résumé identique
        articles = [
            {"URL": "http://a.com/1", "Résumé": resume},
            {"URL": "http://b.com/2", "Résumé": resume},  # même résumé
        ]
        result = dedup.deduplicate(articles)
        assert len(result) == 1

    def test_reset_clears_state(self):
        dedup = self.Deduplicator()
        a = self._make_article("http://example.com/1", "Article A")
        dedup.deduplicate([a])
        assert dedup.stats["total"] == 1
        dedup.reset()
        assert dedup.stats["total"] == 0
        assert len(dedup._seen_urls) == 0

    def test_incremental_dedup(self):
        dedup = self.Deduplicator()
        existing = [self._make_article("http://example.com/1", "Article A")]
        new_articles = [
            self._make_article("http://example.com/1", "Article A — repris"),  # doublon
            self._make_article("http://example.com/2", "Article B — nouveau"),
        ]
        result = dedup.deduplicate_incremental(new_articles, existing)
        assert len(result) == 1
        assert result[0]["URL"] == "http://example.com/2"

    def test_empty_list(self):
        dedup = self.Deduplicator()
        assert dedup.deduplicate([]) == []

    def test_url_normalization(self):
        dedup = self.Deduplicator()
        # Trailing slash et casse ne doivent pas créer de doublon
        articles = [
            self._make_article("http://example.com/article/"),
            self._make_article("http://example.com/article"),
        ]
        result = dedup.deduplicate(articles)
        assert len(result) == 1


# ─────────────────────────────────────────────────────────────────────────────
# utils/source_credibility.py
# ─────────────────────────────────────────────────────────────────────────────

class TestCredibilityEngine:
    """Tests pour CredibilityEngine."""

    def setup_method(self):
        from utils.source_credibility import CredibilityEngine
        # Utiliser la racine réelle du projet (qui contient sources_credibility.json)
        project_root = Path(__file__).resolve().parent.parent
        self.engine = CredibilityEngine(project_root)

    def test_known_source_score(self):
        score = self.engine.get_score("Reuters")
        assert score > 90  # Reuters doit être très bien noté

    def test_unknown_source_default_score(self):
        score = self.engine.get_score("Blog Inconnu XYZ 999")
        assert score == 50  # Score par défaut

    def test_empty_source_default_score(self):
        assert self.engine.get_score("") == 50
        assert self.engine.get_score("   ") == 50

    def test_multiplier_range(self):
        for source in ["Le Monde", "Reuters", "CNews", ""]:
            mult = self.engine.get_multiplier(source)
            assert 0.60 <= mult <= 1.20, f"Multiplicateur hors bornes pour {source!r}: {mult}"

    def test_high_score_high_multiplier(self):
        mult_reuters  = self.engine.get_multiplier("Reuters")
        mult_unknown  = self.engine.get_multiplier("Blog XYZ inconnu")
        assert mult_reuters > mult_unknown

    def test_get_metadata_returns_dict(self):
        meta = self.engine.get_metadata("Le Monde")
        assert "score"     in meta
        assert "biais"     in meta
        assert "type"      in meta
        assert "pays"      in meta
        assert "fiabilite" in meta

    def test_rate_articles(self):
        articles = [
            {"Sources": "Reuters",    "Résumé": "Test"},
            {"Sources": "Blog XYZ",   "Résumé": "Test"},
            {"Sources": "",           "Résumé": "Test"},
        ]
        rated = self.engine.rate_articles(articles)
        assert all("score_source" in a for a in rated)
        assert rated[0]["score_source"] > rated[1]["score_source"]

    def test_partial_match(self):
        # "Le Monde" devrait matcher "Le Monde diplomatique" (correspondance partielle)
        score = self.engine.get_score("Le Monde diplomatique")
        assert score > 50  # Ne doit pas retourner le score par défaut

    def test_db_loaded(self):
        assert len(self.engine._db) > 0


class TestCredibilityEngineNoFile:
    """Test avec un fichier de crédibilité absent (projet sans base)."""

    def test_no_file_default_score(self, tmp_path):
        from utils.source_credibility import CredibilityEngine
        engine = CredibilityEngine(tmp_path)  # Aucun fichier de crédibilité
        assert engine.get_score("Le Monde") == 50
        assert engine.get_multiplier("Reuters") == pytest.approx(0.90, abs=0.01)


# ─────────────────────────────────────────────────────────────────────────────
# utils/reading_time.py
# ─────────────────────────────────────────────────────────────────────────────

class TestCountWords:
    """Tests pour count_words."""

    def setup_method(self):
        from utils.reading_time import count_words
        self.count_words = count_words

    def test_empty_string(self):
        assert self.count_words("") == 0

    def test_none_returns_0(self):
        assert self.count_words(None) == 0  # type: ignore

    def test_simple_text(self):
        assert self.count_words("Bonjour monde") == 2

    def test_url_not_counted(self):
        text = "Voir https://example.com/article pour plus."
        words = self.count_words(text)
        # L'URL ne doit pas être comptée comme des mots
        assert words == self.count_words("Voir  pour plus.")

    def test_html_stripped(self):
        text = "<p>Bonjour <strong>monde</strong></p>"
        assert self.count_words(text) == 2

    def test_markdown_stripped(self):
        text = "## Titre\n\n**Bonjour** _monde_"
        assert self.count_words(text) >= 2


class TestEstimateReadingTime:
    """Tests pour estimate_reading_time."""

    def setup_method(self):
        from utils.reading_time import estimate_reading_time
        self.estimate = estimate_reading_time

    def test_empty_text(self):
        result = self.estimate("")
        assert result["mots"] == 0
        assert result["temps_lecture_minutes"] == 0.0
        assert result["temps_lecture_label"] == "< 1 min"

    def test_short_text_label(self):
        # 10 mots → < 1 min
        result = self.estimate("mot " * 10)
        assert result["temps_lecture_label"] == "< 1 min"

    def test_one_minute_text(self):
        # 230 mots → 1 min
        result = self.estimate("mot " * 230, wpm=230)
        assert result["temps_lecture_minutes"] == pytest.approx(1.0, abs=0.1)
        assert "min" in result["temps_lecture_label"]

    def test_two_minutes_text(self):
        result = self.estimate("mot " * 460, wpm=230)
        assert result["temps_lecture_minutes"] == pytest.approx(2.0, abs=0.1)
        assert result["temps_lecture_label"] == "2 min"

    def test_returns_required_keys(self):
        result = self.estimate("Test rapide")
        assert "mots"                  in result
        assert "temps_lecture_minutes" in result
        assert "temps_lecture_label"   in result

    def test_custom_wpm(self):
        result_fast = self.estimate("mot " * 100, wpm=500)
        result_slow = self.estimate("mot " * 100, wpm=100)
        assert result_fast["temps_lecture_minutes"] < result_slow["temps_lecture_minutes"]


class TestEnrichReadingTime:
    """Tests pour enrich_reading_time."""

    def setup_method(self):
        from utils.reading_time import enrich_reading_time
        self.enrich = enrich_reading_time

    def test_adds_fields(self):
        articles = [{"Résumé": "mot " * 100}]
        result = self.enrich(articles)
        assert "temps_lecture_minutes" in result[0]
        assert "temps_lecture_label"   in result[0]

    def test_no_overwrite_by_default(self):
        articles = [{"Résumé": "mot " * 100, "temps_lecture_minutes": 99.9}]
        result = self.enrich(articles)
        assert result[0]["temps_lecture_minutes"] == 99.9  # non écrasé

    def test_force_overwrite(self):
        articles = [{"Résumé": "mot " * 100, "temps_lecture_minutes": 99.9}]
        result = self.enrich(articles, overwrite=True)
        assert result[0]["temps_lecture_minutes"] != 99.9  # recalculé

    def test_empty_list(self):
        assert self.enrich([]) == []

    def test_article_without_resume(self):
        articles = [{"URL": "http://example.com"}]
        result = self.enrich(articles)
        # Doit quand même ajouter le champ (avec 0)
        assert "temps_lecture_minutes" in result[0]
        assert result[0]["temps_lecture_minutes"] == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# scripts/trend_detector.py — règles configurables
# ─────────────────────────────────────────────────────────────────────────────

class TestTrendDetectorWithRules:
    """Tests pour detect_trends avec les nouvelles règles configurables."""

    def setup_method(self):
        from scripts.trend_detector import detect_trends, _niveau_from_rules
        self.detect_trends      = detect_trends
        self._niveau_from_rules = _niveau_from_rules

    def test_basic_trend_detected(self):
        counts_24h = {"PERSON:Macron": 6}
        counts_7j  = {"PERSON:Macron": 7}  # avg_per_day = 1 → ratio = 6
        alerts = self.detect_trends(counts_24h, counts_7j, threshold=2.0, top_n=10)
        assert len(alerts) == 1
        assert alerts[0]["entity_value"] == "Macron"

    def test_below_threshold_not_detected(self):
        counts_24h = {"PERSON:Dupont": 2}
        counts_7j  = {"PERSON:Dupont": 14}  # avg = 2/day → ratio = 1.0
        alerts = self.detect_trends(counts_24h, counts_7j, threshold=2.0, top_n=10)
        assert len(alerts) == 0

    def test_new_entity_no_history(self):
        counts_24h = {"ORG:NouvelleOrg": 4}
        counts_7j  = {}  # aucune mention sur 7j
        alerts = self.detect_trends(counts_24h, counts_7j, threshold=2.0, top_n=10)
        assert len(alerts) == 1
        # Lissage de Laplace (k=1) : ratio = 4 / (0 + 1) = 4.0 (remplace l'ancien 999.9)
        assert alerts[0]["ratio"] == 4.0
        assert alerts[0]["nouveaute"] is True  # absente sur 7j

    def test_niveau_from_rules_defaults(self):
        rules = {}
        assert self._niveau_from_rules(rules, 1.5) == "modéré"
        assert self._niveau_from_rules(rules, 3.5) == "élevé"
        assert self._niveau_from_rules(rules, 6.0) == "critique"

    def test_niveau_from_config(self):
        rules = {
            "niveaux": {
                "bas":    {"ratio_min": 2.0, "ratio_max": 4.0, "label": "bas",    "emoji": "🟡"},
                "haut":   {"ratio_min": 4.0, "ratio_max": None,"label": "haut",   "emoji": "🔴"},
            }
        }
        assert self._niveau_from_rules(rules, 3.0) == "bas"
        assert self._niveau_from_rules(rules, 5.0) == "haut"

    def test_top_n_respected(self):
        counts_24h = {f"PERSON:P{i}": 10 for i in range(50)}
        counts_7j  = {}
        alerts = self.detect_trends(counts_24h, counts_7j, threshold=2.0, top_n=5)
        assert len(alerts) == 5

    def test_sorted_by_ratio_desc(self):
        counts_24h = {"PERSON:A": 10, "PERSON:B": 5}
        counts_7j  = {"PERSON:A": 7, "PERSON:B": 7}  # ratio A=10, ratio B=5
        alerts = self.detect_trends(counts_24h, counts_7j, threshold=2.0, top_n=10)
        assert alerts[0]["entity_value"] == "A"

    def test_per_type_threshold(self):
        """Les seuils par type (via rules) doivent être respectés."""
        rules = {
            "types_entites": {
                "PERSON": {"enabled": True, "threshold_ratio": 5.0, "min_mentions": 2},
                "ORG":    {"enabled": True, "threshold_ratio": 2.0, "min_mentions": 2},
            }
        }
        counts_24h = {"PERSON:Dupont": 4, "ORG:Acme": 4}
        counts_7j  = {"PERSON:Dupont": 7, "ORG:Acme": 7}
        # Dupont : ratio = 4 < seuil PERSON 5.0 → pas d'alerte
        # Acme   : ratio = 4 > seuil ORG   2.0 → alerte
        alerts = self.detect_trends(counts_24h, counts_7j, threshold=2.0, top_n=10, rules=rules)
        entities = [a["entity_value"] for a in alerts]
        assert "Acme"   in entities
        assert "Dupont" not in entities


# ─────────────────────────────────────────────────────────────────────────────
# scripts/trend_detector.py — détection de silences (optimisation 3.7)
# ─────────────────────────────────────────────────────────────────────────────

class TestDetectSilences:
    """Tests pour detect_silences() — entités actives sur 7j disparues sur 24h."""

    def setup_method(self):
        from scripts.trend_detector import detect_silences
        self.detect_silences = detect_silences

    def test_silence_detected_when_entity_missing_from_24h(self):
        """Une entité avec moy >= 3/j sur 7j et absente sur 24h → alerte silence."""
        counts_7j  = {"PERSON:Macron": 21}   # 3.0/j exactement
        counts_24h = {}
        silences = self.detect_silences(counts_24h, counts_7j, min_baseline_avg=3.0)
        assert len(silences) == 1
        s = silences[0]
        assert s["type"] == "silence"
        assert s["entity_value"] == "Macron"
        assert s["count_24h"] == 0
        assert s["count_7j"] == 21
        assert s["baseline_avg_per_day"] == 3.0

    def test_no_silence_when_entity_present_on_24h(self):
        """Si l'entité a des mentions sur 24h, pas d'alerte silence."""
        counts_7j  = {"ORG:OpenAI": 35}
        counts_24h = {"ORG:OpenAI": 2}
        silences = self.detect_silences(counts_24h, counts_7j, min_baseline_avg=3.0)
        assert len(silences) == 0

    def test_no_silence_below_baseline_threshold(self):
        """Entité avec moy < 3/j sur 7j → pas d'alerte silence."""
        counts_7j  = {"GPE:Paris": 14}   # 2.0/j < 3.0 seuil
        counts_24h = {}
        silences = self.detect_silences(counts_24h, counts_7j, min_baseline_avg=3.0)
        assert len(silences) == 0

    def test_niveau_eleve_above_10_per_day(self):
        """Entité avec moy >= 10/j → niveau 'élevé'."""
        counts_7j  = {"ORG:NvidiaAI": 77}  # 11/j
        counts_24h = {}
        silences = self.detect_silences(counts_24h, counts_7j, min_baseline_avg=3.0)
        assert len(silences) == 1
        assert silences[0]["niveau"] == "élevé"

    def test_niveau_modere_below_10_per_day(self):
        """Entité avec 3 <= moy < 10/j → niveau 'modéré'."""
        counts_7j  = {"PERSON:Leclerc": 28}  # 4/j
        counts_24h = {}
        silences = self.detect_silences(counts_24h, counts_7j, min_baseline_avg=3.0)
        assert len(silences) == 1
        assert silences[0]["niveau"] == "modéré"

    def test_sorted_by_baseline_desc(self):
        """Les silences sont triés par baseline_avg_per_day décroissant."""
        counts_7j = {
            "ORG:Airbus":   14,   # 2/j — sous seuil
            "PERSON:A":     42,   # 6/j
            "PERSON:B":     63,   # 9/j
            "ORG:Safran":   21,   # 3/j exactement
        }
        counts_24h = {}
        silences = self.detect_silences(counts_24h, counts_7j, min_baseline_avg=3.0)
        assert len(silences) == 3  # Airbus sous seuil
        assert silences[0]["entity_value"] == "B"
        assert silences[1]["entity_value"] == "A"

    def test_top_n_respected(self):
        counts_7j = {f"PERSON:P{i}": 30 for i in range(20)}
        counts_24h = {}
        silences = self.detect_silences(counts_24h, counts_7j, top_n=5)
        assert len(silences) == 5

    def test_empty_counts_returns_empty(self):
        silences = self.detect_silences({}, {}, min_baseline_avg=3.0)
        assert silences == []

    def test_required_fields_present(self):
        """Chaque alerte de silence contient tous les champs requis."""
        counts_7j  = {"PRODUCT:ChatGPT": 28}
        counts_24h = {}
        silences = self.detect_silences(counts_24h, counts_7j, min_baseline_avg=3.0)
        assert len(silences) == 1
        s = silences[0]
        required = {"type", "entity_type", "entity_value", "count_24h",
                    "count_7j", "baseline_avg_per_day", "niveau", "detected_at"}
        assert required.issubset(s.keys())

    def test_monitored_types_filter(self):
        """Seuls les types activés dans les règles sont inclus."""
        rules = {
            "types_entites": {
                "PERSON": {"enabled": True},
                "ORG":    {"enabled": False},
            }
        }
        counts_7j  = {"PERSON:Dupont": 21, "ORG:Acme": 35}
        counts_24h = {}
        silences = self.detect_silences(counts_24h, counts_7j, rules=rules, min_baseline_avg=3.0)
        entity_values = [s["entity_value"] for s in silences]
        assert "Dupont" in entity_values
        assert "Acme" not in entity_values
