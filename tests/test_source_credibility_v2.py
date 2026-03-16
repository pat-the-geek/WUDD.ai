"""Tests de la crédibilité des sources v2 — score composite, fallback, triangulation.

Couvre :
  - Score composite avec champs v2 complets
  - Fallback gracieux si champs manquants
  - Pondération progressive (1, 2, 3 champs disponibles)
  - Multiplicateur basé sur composite
  - Triangulation inter-sources
  - Régularité de publication
  - Migration : rate_articles() utilise get_composite_score()
"""

import json
import math
import tempfile
import time
from pathlib import Path

import pytest

# ── Fixtures ──────────────────────────────────────────────────────────────────


def _make_db(entries: dict) -> Path:
    """Crée un fichier sources_credibility.json temporaire et retourne son dossier."""
    tmp = tempfile.mkdtemp()
    config_dir = Path(tmp) / "config"
    config_dir.mkdir()
    (config_dir / "sources_credibility.json").write_text(
        json.dumps(entries), encoding="utf-8"
    )
    return Path(tmp)


@pytest.fixture
def root_static():
    """Base avec score statique uniquement (pas de champs v2)."""
    return _make_db({
        "Source A": {"score": 90, "biais": "centre", "type": "presse écrite",
                     "pays": "France", "fiabilite": "très élevée", "fact_checking": True},
        "Source B": {"score": 50, "biais": "centre", "type": "presse gratuite",
                     "pays": "France", "fiabilite": "bonne", "fact_checking": False},
        "Source C": {"score": 20, "biais": "droite", "type": "chaîne info en continu",
                     "pays": "France", "fiabilite": "variable", "fact_checking": False},
    })


@pytest.fixture
def root_enriched():
    """Base avec champs v2 complets pour une source, partiel pour une autre."""
    return _make_db({
        "Source Complète": {
            "score": 90,
            "biais": "centre",
            "type": "presse écrite",
            "pays": "France",
            "fiabilite": "très élevée",
            "fact_checking": True,
            "domain_age_years": 25.0,
            "transparence": 4,
            "mbfc_rating": "HIGH",
            "enrich_date": "2026-03-16",
        },
        "Source Partielle": {
            "score": 70,
            "biais": "centre",
            "type": "presse numérique",
            "pays": "France",
            "fiabilite": "bonne",
            "fact_checking": False,
            "domain_age_years": 3.0,
            # transparence et mbfc_rating absents
        },
        "Source Non Enrichie": {
            "score": 60,
            "biais": "centre",
            "type": "radio",
            "pays": "France",
            "fiabilite": "bonne",
            "fact_checking": False,
        },
    })


# ── Tests fallback gracieux ───────────────────────────────────────────────────


class TestFallbackGracieux:
    """B3/E1 : aucune pénalité si champs v2 absents."""

    def test_score_statique_retourne_si_pas_de_champs_v2(self, root_static):
        from utils.source_credibility import CredibilityEngine
        engine = CredibilityEngine(root_static)
        assert engine.get_composite_score("Source A") == 90.0
        assert engine.get_composite_score("Source B") == 50.0
        assert engine.get_composite_score("Source C") == 20.0

    def test_source_inconnue_retourne_50(self, root_static):
        from utils.source_credibility import CredibilityEngine
        engine = CredibilityEngine(root_static)
        assert engine.get_composite_score("Source Inconnue") == 50.0

    def test_source_vide_retourne_50(self, root_static):
        from utils.source_credibility import CredibilityEngine
        engine = CredibilityEngine(root_static)
        assert engine.get_composite_score("") == 50.0


# ── Tests score composite complet ─────────────────────────────────────────────


class TestScoreComposite:
    """Formule composite : statique×0.60 + age×0.15 + transp×0.10 + mbfc×0.15"""

    def test_composite_complet(self, root_enriched):
        from utils.source_credibility import CredibilityEngine
        engine = CredibilityEngine(root_enriched)
        composite = engine.get_composite_score("Source Complète")
        # score=90, domain_age=25ans→100, transparence=4→100, mbfc=HIGH→85
        expected = 90 * 0.60 + 100 * 0.15 + 100 * 0.10 + 85 * 0.15
        assert abs(composite - expected) < 1.0, f"Attendu ~{expected}, obtenu {composite}"

    def test_composite_superieur_a_statique_si_bons_signaux(self, root_enriched):
        from utils.source_credibility import CredibilityEngine
        engine = CredibilityEngine(root_enriched)
        static = engine.get_score("Source Complète")
        composite = engine.get_composite_score("Source Complète")
        assert composite >= static - 5, "Le composite ne devrait pas descendre très en dessous du statique"

    def test_composite_partiel_utilise_poids_disponibles(self, root_enriched):
        from utils.source_credibility import CredibilityEngine
        engine = CredibilityEngine(root_enriched)
        composite = engine.get_composite_score("Source Partielle")
        # Seulement score statique + domain_age (domain_age=3ans→50)
        static = 70
        age_score = 50  # 3 ans → 50
        expected_w = 0.60 + 0.15
        expected = (static * 0.60 + age_score * 0.15) / expected_w
        assert abs(composite - expected) < 2.0, f"Attendu ~{expected}, obtenu {composite}"

    def test_source_non_enrichie_retourne_statique(self, root_enriched):
        from utils.source_credibility import CredibilityEngine
        engine = CredibilityEngine(root_enriched)
        assert engine.get_composite_score("Source Non Enrichie") == 60.0

    def test_composite_borne_0_100(self, root_enriched):
        from utils.source_credibility import CredibilityEngine
        engine = CredibilityEngine(root_enriched)
        for name in ("Source Complète", "Source Partielle", "Source Non Enrichie"):
            score = engine.get_composite_score(name)
            assert 0.0 <= score <= 100.0


# ── Tests multiplicateur ──────────────────────────────────────────────────────


class TestMultiplicateur:
    """Le multiplicateur utilise get_composite_score()."""

    def test_multiplicateur_source_haute(self, root_enriched):
        from utils.source_credibility import CredibilityEngine
        engine = CredibilityEngine(root_enriched)
        mult = engine.get_multiplier("Source Complète")
        assert mult >= 1.0, "Source à haut composite → multiplicateur ≥ 1.0"
        assert mult <= 1.20

    def test_multiplicateur_source_inconnue(self, root_static):
        from utils.source_credibility import CredibilityEngine
        engine = CredibilityEngine(root_static)
        mult = engine.get_multiplier("Inconnue")
        assert abs(mult - 0.90) < 0.01, f"Source inconnue (score 50) → mult ~0.90, obtenu {mult}"

    def test_multiplicateur_borne(self, root_enriched):
        from utils.source_credibility import CredibilityEngine
        engine = CredibilityEngine(root_enriched)
        for name in ("Source Complète", "Source Non Enrichie", "Inconnue"):
            mult = engine.get_multiplier(name)
            assert 0.60 <= mult <= 1.20


# ── Tests rate_articles() ─────────────────────────────────────────────────────


class TestRateArticles:
    """rate_articles() doit utiliser get_composite_score()."""

    def test_score_source_avec_composite(self, root_enriched):
        from utils.source_credibility import CredibilityEngine
        engine = CredibilityEngine(root_enriched)
        articles = [
            {"Sources": "Source Complète", "Résumé": "Test"},
            {"Sources": "Source Non Enrichie", "Résumé": "Test"},
            {"Sources": "Inconnue", "Résumé": "Test"},
        ]
        rated = engine.rate_articles(articles)
        composite_a = engine.get_composite_score("Source Complète")
        assert rated[0]["score_source"] == round(composite_a)
        assert rated[1]["score_source"] == 60  # score statique
        assert rated[2]["score_source"] == 50  # inconnue

    def test_score_source_egal_statique_si_non_enrichi(self, root_static):
        from utils.source_credibility import CredibilityEngine
        engine = CredibilityEngine(root_static)
        articles = [{"Sources": "Source A", "Résumé": "Test"}]
        rated = engine.rate_articles(articles)
        assert rated[0]["score_source"] == 90


# ── Tests get_metadata() ──────────────────────────────────────────────────────


class TestGetMetadata:
    def test_metadata_inclut_champs_v2(self, root_enriched):
        from utils.source_credibility import CredibilityEngine
        engine = CredibilityEngine(root_enriched)
        meta = engine.get_metadata("Source Complète")
        assert meta["enrichi"] is True
        assert "domain_age_years" in meta
        assert "transparence" in meta
        assert "mbfc_rating" in meta
        assert "score_composite" in meta
        assert meta["score_composite"] > 0

    def test_metadata_source_inconnue(self, root_static):
        from utils.source_credibility import CredibilityEngine
        engine = CredibilityEngine(root_static)
        meta = engine.get_metadata("Inconnue")
        assert meta["enrichi"] is False
        assert meta["score"] == 50
        assert meta["score_composite"] == 50.0


# ── Tests triangulation (utils/scoring.py) ────────────────────────────────────


class TestTriangulation:
    """Critère 1 : triangulation inter-sources."""

    def _make_article(self, source: str, resume: str) -> dict:
        return {
            "Sources": source,
            "Résumé": resume,
            "Date de publication": "2026-03-16",
        }

    def test_pas_de_triangulation_sans_corpus(self, root_static):
        from utils.source_credibility import CredibilityEngine
        from utils.scoring import _triangulation_bonus
        engine = CredibilityEngine(root_static)
        article = self._make_article("Source A", "OpenAI lance un nouveau modèle GPT-5 très puissant")
        assert _triangulation_bonus(article, [], engine) == 0.0

    def test_bonus_2_sources_similaires(self, root_static):
        from utils.source_credibility import CredibilityEngine
        from utils.scoring import _triangulation_bonus
        engine = CredibilityEngine(root_static)
        resume = "OpenAI annonce le lancement de GPT-5 un modèle d'intelligence artificielle très avancé"
        article = self._make_article("Source A", resume)
        corpus = [
            self._make_article("Source A", resume),  # même source — ignorée
            self._make_article("Source B", resume + " disponible dès maintenant"),
        ]
        bonus = _triangulation_bonus(article, corpus, engine)
        # Source B score=50 < 75 → pas compté
        assert bonus == 0.0

    def test_bonus_sources_credibles(self):
        """Sources avec score ≥ 75 dans une base personnalisée."""
        root = _make_db({
            "Media Credible 1": {"score": 88, "biais": "centre", "type": "presse écrite", "pays": "France", "fiabilite": "élevée", "fact_checking": True},
            "Media Credible 2": {"score": 85, "biais": "centre", "type": "presse écrite", "pays": "France", "fiabilite": "élevée", "fact_checking": True},
            "Source Cible":     {"score": 80, "biais": "centre", "type": "presse écrite", "pays": "France", "fiabilite": "élevée", "fact_checking": True},
        })
        from utils.source_credibility import CredibilityEngine
        from utils.scoring import _triangulation_bonus
        engine = CredibilityEngine(root)
        resume = "Emmanuel Macron annonce une réforme majeure de l intelligence artificielle en France"
        article = {"Sources": "Source Cible", "Résumé": resume, "Date de publication": "2026-03-16"}
        corpus = [
            {"Sources": "Media Credible 1", "Résumé": resume + " lors d un discours à l Élysée", "Date de publication": "2026-03-16"},
            {"Sources": "Media Credible 2", "Résumé": resume + " dans le cadre du plan France 2030", "Date de publication": "2026-03-16"},
        ]
        bonus = _triangulation_bonus(article, corpus, engine)
        assert bonus == 4.0, f"2 sources crédibles → bonus 4, obtenu {bonus}"

    def test_bonus_max_4_sources(self):
        root = _make_db({f"Media {i}": {"score": 85, "biais": "centre", "type": "presse écrite", "pays": "France", "fiabilite": "élevée", "fact_checking": True} for i in range(6)})
        root2 = _make_db({**json.loads((root / "config" / "sources_credibility.json").read_text()), "Cible": {"score": 80, "biais": "centre", "type": "presse écrite", "pays": "France", "fiabilite": "élevée", "fact_checking": True}})
        from utils.source_credibility import CredibilityEngine
        from utils.scoring import _triangulation_bonus
        engine = CredibilityEngine(root2)
        resume = "Décision historique du Parlement européen sur l intelligence artificielle"
        article = {"Sources": "Cible", "Résumé": resume}
        corpus = [
            {"Sources": f"Media {i}", "Résumé": resume + f" version {i}"}
            for i in range(5)
        ]
        bonus = _triangulation_bonus(article, corpus, engine)
        assert bonus == 10.0, f"≥4 sources crédibles → bonus max 10, obtenu {bonus}"


# ── Tests régularité (utils/scoring.py) ───────────────────────────────────────


class TestRegularite:
    """Critère 4 : régularité de publication."""

    def test_pas_de_malus_si_moins_de_10_articles(self):
        from utils.scoring import _regularity_malus
        dates = [time.time() - i * 3600 for i in range(5)]  # 5 articles seulement
        assert _regularity_malus("Source X", {"Source X": dates}) == 0.0

    def test_pas_de_malus_si_publications_regulieres(self):
        from utils.scoring import _regularity_malus
        # Publication toutes les 24h exactement → écart-type ≈ 0
        now = time.time()
        dates = [now - i * 86400 for i in range(15)]
        assert _regularity_malus("Source X", {"Source X": dates}) == 0.0

    def test_malus_si_tres_irregulier(self):
        from utils.scoring import _regularity_malus
        # Burst de 10 articles en 1h, puis silence → écart-type très élevé
        now = time.time()
        dates = [now - i * 60 for i in range(10)] + [now - 30 * 86400]
        malus = _regularity_malus("Source X", {"Source X": dates})
        assert malus < 0, f"Publication erratique → malus négatif, obtenu {malus}"

    def test_source_absente_retourne_zero(self):
        from utils.scoring import _regularity_malus
        assert _regularity_malus("Source Inconnue", {}) == 0.0


# ── Test d'intégration scoring complet ───────────────────────────────────────


class TestScoringIntegration:
    """score_article() intègre composite + triangulation + régularité."""

    def test_score_article_sans_corpus(self, root_static):
        from utils.scoring import ScoringEngine
        engine = ScoringEngine(root_static)
        article = {
            "Sources": "Source A",
            "Résumé": "Test de pertinence pour un article de presse",
            "Date de publication": "2026-03-16",
        }
        score = engine.score_article(article)
        assert 0.0 <= score <= 100.0

    def test_score_article_avec_corpus(self, root_enriched):
        from utils.scoring import ScoringEngine
        engine = ScoringEngine(root_enriched)
        resume = "La Commission européenne adopte le règlement IA Act après un long débat"
        article = {
            "Sources": "Source Complète",
            "Résumé": resume,
            "Date de publication": "2026-03-16",
            "entities": {"ORG": ["Commission européenne"]},
        }
        corpus = [
            {"Sources": "Source Non Enrichie", "Résumé": resume + " en session plénière"},
        ]
        score_sans = engine.score_article(article)
        score_avec = engine.score_article(article, corpus=corpus)
        # Avec corpus (même source non crédible), le bonus peut être 0 si score < 75
        assert 0.0 <= score_sans <= 100.0
        assert 0.0 <= score_avec <= 100.0
