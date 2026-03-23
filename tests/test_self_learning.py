"""tests/test_self_learning.py — Tests du système auto-apprenant WUDD.ai

Couvre :
  - EngagementTracker : enregistrement des signaux, agrégation, stats
  - ScoringOptimizer  : chargement/sauvegarde des poids, normalisation
  - AlertCalibrator   : enregistrement d'alertes, mise à jour suivi
  - QualityMonitor    : calcul du score de qualité par article
  - ContradictionFeedback : enregistrement feedback, calibration seuils
  - QuotaOptimizer    : archivage et analyse historique
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _make_article(**kwargs) -> dict:
    """Crée un article minimal pour les tests."""
    base = {
        "Date de publication": "23/01/2025",
        "Sources": "Le Monde",
        "URL": "https://example.com/article-1",
        "Résumé": "Ceci est un résumé valide de plus de cent caractères pour tester le calcul de qualité des articles WUDD.ai correctement.",
        "entities": {"PERSON": ["Emmanuel Macron"], "ORG": ["OpenAI"]},
        "sentiment": "positif",
        "score_sentiment": 4,
        "Images": [{"URL": "https://img.example.com/1.jpg", "Width": 1200}],
        "temps_lecture_minutes": 2.5,
    }
    base.update(kwargs)
    return base


# ─── EngagementTracker ────────────────────────────────────────────────────────

class TestEngagementTracker:
    """Tests de l'EngagementTracker en isolation (répertoire temporaire)."""

    def _make_tracker(self, tmp_path: Path):
        """Crée un tracker avec un répertoire temporaire."""
        import utils.engagement_tracker as et
        # Patcher le chemin de persistance
        original_path = et._STATE_PATH
        et._STATE_PATH = tmp_path / "engagement_state.json"
        tracker = et.EngagementTracker()
        yield tracker
        et._STATE_PATH = original_path

    def test_record_article_opened(self, tmp_path):
        import utils.engagement_tracker as et
        et._STATE_PATH = tmp_path / "state.json"
        tracker = et.EngagementTracker()

        tracker.record("article_opened", url="https://example.com/a", source="Le Monde")
        score = tracker.get_article_score("https://example.com/a")
        assert score == pytest.approx(1.0)

    def test_record_article_deleted_negative(self, tmp_path):
        import utils.engagement_tracker as et
        et._STATE_PATH = tmp_path / "state.json"
        tracker = et.EngagementTracker()

        tracker.record("article_deleted", url="https://example.com/b", source="BFM TV")
        score = tracker.get_article_score("https://example.com/b")
        assert score == pytest.approx(-2.0)

    def test_source_score_aggregation(self, tmp_path):
        import utils.engagement_tracker as et
        et._STATE_PATH = tmp_path / "state.json"
        tracker = et.EngagementTracker()

        tracker.record("article_opened",      source="Le Monde")
        tracker.record("article_full_report", source="Le Monde")
        tracker.record("article_deleted",     source="BFM TV")

        sources = tracker.get_source_scores()
        assert sources["Le Monde"] == pytest.approx(3.0)   # 1.0 + 2.0
        assert sources["BFM TV"]   == pytest.approx(-2.0)

    def test_keyword_score_aggregation(self, tmp_path):
        import utils.engagement_tracker as et
        et._STATE_PATH = tmp_path / "state.json"
        tracker = et.EngagementTracker()

        tracker.record("article_exported", keyword="ia")
        tracker.record("article_opened",   keyword="ia")
        kws = tracker.get_keyword_scores()
        assert kws["ia"] == pytest.approx(3.5)   # 2.5 + 1.0

    def test_entity_score_aggregation(self, tmp_path):
        import utils.engagement_tracker as et
        et._STATE_PATH = tmp_path / "state.json"
        tracker = et.EngagementTracker()

        tracker.record("entity_synthesis", entities=["OpenAI", "Macron"])
        tracker.record("entity_synthesis", entities=["OpenAI"])
        ents = tracker.get_entity_scores()
        assert ents["OpenAI"] == pytest.approx(3.0)   # 1.5 × 2
        assert ents["Macron"] == pytest.approx(1.5)

    def test_dismissed_alert_recorded(self, tmp_path):
        import utils.engagement_tracker as et
        et._STATE_PATH = tmp_path / "state.json"
        tracker = et.EngagementTracker()

        tracker.record("alert_dismissed", alert_entity="PERSON:Trump")
        dismissed = tracker.get_dismissed_alerts()
        assert "PERSON:Trump" in dismissed

    def test_unknown_signal_ignored(self, tmp_path):
        import utils.engagement_tracker as et
        et._STATE_PATH = tmp_path / "state.json"
        tracker = et.EngagementTracker()

        tracker.record("signal_inexistant", url="https://example.com/x")
        assert tracker.get_article_score("https://example.com/x") == 0.0

    def test_persistence(self, tmp_path):
        import utils.engagement_tracker as et
        et._STATE_PATH = tmp_path / "state.json"
        tracker = et.EngagementTracker()
        tracker.record("article_opened", url="https://example.com/persist", source="S")

        # Recharger depuis le disque
        tracker2 = et.EngagementTracker()
        assert tracker2.get_article_score("https://example.com/persist") == pytest.approx(1.0)

    def test_stats_structure(self, tmp_path):
        import utils.engagement_tracker as et
        et._STATE_PATH = tmp_path / "state.json"
        tracker = et.EngagementTracker()
        tracker.record("article_opened", url="https://x.com", source="X")
        stats = tracker.get_stats()
        assert "total_articles_tracked" in stats
        assert "top_sources" in stats
        assert "top_keywords" in stats
        assert "daily_activity" in stats

    def test_purge_old_entries(self, tmp_path):
        import utils.engagement_tracker as et
        et._STATE_PATH = tmp_path / "state.json"
        tracker = et.EngagementTracker()
        # Injecter une entrée ancienne
        tracker._state["articles"]["old_key"] = {
            "url": "https://old.com",
            "source": "Old",
            "keyword": "",
            "score": 1.0,
            "signals": {},
            "last_seen": "2020-01-01",
        }
        removed = tracker.purge_old_entries()
        assert removed == 1


# ─── ScoringOptimizer ─────────────────────────────────────────────────────────

class TestScoringOptimizer:

    def test_load_weights_defaults(self, tmp_path):
        import utils.scoring_optimizer as so
        original = so._WEIGHTS_FILE
        so._WEIGHTS_FILE = tmp_path / "scoring_weights.json"
        try:
            weights = so.load_weights()
            assert set(weights.keys()) == {"freshness", "entities", "keywords", "completeness"}
            assert abs(sum(weights.values()) - 1.0) < 0.001
        finally:
            so._WEIGHTS_FILE = original

    def test_save_and_reload_weights(self, tmp_path):
        import utils.scoring_optimizer as so
        original = so._WEIGHTS_FILE
        so._WEIGHTS_FILE = tmp_path / "scoring_weights.json"
        try:
            custom = {"freshness": 0.40, "entities": 0.30, "keywords": 0.20, "completeness": 0.10}
            so.save_weights(custom)
            loaded = so.load_weights()
            assert loaded["freshness"] == pytest.approx(0.40, abs=0.01)
        finally:
            so._WEIGHTS_FILE = original

    def test_normalize_weights(self):
        from utils.scoring_optimizer import _normalize_weights
        w = {"freshness": 2.0, "entities": 1.0, "keywords": 1.0, "completeness": 0.0}
        norm = _normalize_weights(w)
        assert abs(sum(norm.values()) - 1.0) < 0.001

    def test_optimize_insufficient_signals(self, tmp_path):
        import utils.scoring_optimizer as so
        import utils.engagement_tracker as et
        # Patcher les chemins
        so._WEIGHTS_FILE = tmp_path / "weights.json"
        et._STATE_PATH   = tmp_path / "engagement.json"
        et._tracker_instance = None

        result = so.optimize(dry_run=True)
        assert result["applied"] is False
        assert "insuffisant" in result["reason"].lower() or "assez" in result["reason"].lower()


# ─── QualityMonitor ───────────────────────────────────────────────────────────

class TestQualityMonitor:

    def test_complete_article_score(self):
        from utils.quality_monitor import compute_quality_score, quality_level
        art = _make_article()
        score = compute_quality_score(art)
        assert score >= 80
        assert quality_level(score) == "complet"

    def test_empty_article_score(self):
        from utils.quality_monitor import compute_quality_score, quality_level
        score = compute_quality_score({})
        assert score <= 30
        assert quality_level(score) == "critique"

    def test_article_with_error_resume(self):
        from utils.quality_monitor import compute_quality_score
        art = _make_article(Résumé="Erreur : impossible de générer le résumé")
        score = compute_quality_score(art)
        # Pas de points résumé
        assert score < 50

    def test_article_missing_entities(self):
        from utils.quality_monitor import compute_quality_score
        art = _make_article()
        del art["entities"]
        score = compute_quality_score(art)
        full = compute_quality_score(_make_article())
        assert score < full

    def test_repair_priority_error_resume(self):
        from utils.quality_monitor import compute_repair_priority
        art = {"Résumé": "désolé, je n'ai pas pu générer", "entities": {}, "sentiment": None}
        priority = compute_repair_priority(art)
        assert priority >= 5

    def test_repair_priority_complete_article(self):
        from utils.quality_monitor import compute_repair_priority
        art = _make_article()
        assert compute_repair_priority(art) == 0

    def test_quality_levels(self):
        from utils.quality_monitor import quality_level
        assert quality_level(20) == "critique"
        assert quality_level(50) == "dégradé"
        assert quality_level(70) == "bon"
        assert quality_level(90) == "complet"


# ─── ContradictionFeedback ────────────────────────────────────────────────────

class TestContradictionFeedback:
    """Instancie directement ContradictionFeedback (évite les conflits de locks entre tests)."""

    def _make_fb(self, tmp_path):
        import utils.contradiction_feedback as cf
        cf._FEEDBACK_PATH = tmp_path / "cf.json"
        return cf.ContradictionFeedback()

    def test_record_confirmed(self, tmp_path):
        fb = self._make_fb(tmp_path)
        fb.record("CHIFFRE", "confirmed", description="Test", confidence=0.8)
        stats = fb.get_stats()
        assert stats["total_confirmed"] == 1
        assert stats["total_rejected"]  == 0

    def test_record_rejected(self, tmp_path):
        fb = self._make_fb(tmp_path)
        fb.record("FAIT_BINAIRE", "rejected")
        stats = fb.get_stats()
        assert stats["total_rejected"] == 1

    def test_invalid_action_ignored(self, tmp_path):
        fb = self._make_fb(tmp_path)
        fb.record("CHIFFRE", "invalid_action")
        stats = fb.get_stats()
        assert stats["total_feedback"] == 0

    def test_calibrate_insufficient_feedback(self, tmp_path):
        fb = self._make_fb(tmp_path)
        result = fb.calibrate(dry_run=True)
        assert result["applied"] is False
        assert result["adjustments"] == {}

    def test_calibrate_low_precision_raises_threshold(self, tmp_path):
        fb = self._make_fb(tmp_path)

        # Simuler 12 rejets et 3 confirmations (precision = 20%)
        for _ in range(3):
            fb.record("CHIFFRE", "confirmed")
        for _ in range(12):
            fb.record("CHIFFRE", "rejected")

        old_thresholds = fb.get_thresholds()
        result = fb.calibrate(dry_run=True)

        if "CHIFFRE" in result["adjustments"]:
            new_t = result["new_thresholds"].get("CHIFFRE", old_thresholds["CHIFFRE"])
            assert new_t > old_thresholds["CHIFFRE"]

    def test_thresholds_default_values(self):
        from utils.contradiction_feedback import _DEFAULT_THRESHOLDS
        for ctype in ("CHIFFRE", "DATE", "FAIT_BINAIRE", "ATTRIBUTION", "AUTRE"):
            assert ctype in _DEFAULT_THRESHOLDS
            assert 0.0 < _DEFAULT_THRESHOLDS[ctype] < 1.0


# ─── AlertCalibrator ──────────────────────────────────────────────────────────

class TestAlertCalibrator:

    def test_record_alert(self, tmp_path):
        import utils.alert_calibrator as ac
        ac._FEEDBACK_PATH = tmp_path / "alert_fb.json"

        ac.record_alert("PERSON", "Emmanuel Macron", ratio=3.5, level="élevé", mentions_24h=5)
        data = ac.load_feedback()
        assert len(data["alerts"]) == 1
        assert data["alerts"][0]["value"] == "Emmanuel Macron"
        assert data["alerts"][0]["ratio"] == 3.5

    def test_mark_dismissed(self, tmp_path):
        import utils.alert_calibrator as ac
        from datetime import datetime, timezone
        ac._FEEDBACK_PATH = tmp_path / "alert_fb.json"

        ac.record_alert("ORG", "OpenAI", ratio=2.1, level="modéré", mentions_24h=2)
        ac.mark_dismissed("OpenAI")

        data = ac.load_feedback()
        assert data["alerts"][0]["dismissed"] is True

    def test_calibrate_no_analyzable(self, tmp_path):
        import utils.alert_calibrator as ac
        ac._FEEDBACK_PATH = tmp_path / "alert_fb.json"
        ac._RULES_PATH    = tmp_path / "alert_rules.json"

        result = ac.calibrate(dry_run=True)
        assert result["applied"] is False


# ─── QuotaOptimizer ───────────────────────────────────────────────────────────

class TestQuotaOptimizer:

    def test_archive_today_no_state(self, tmp_path):
        import utils.quota_optimizer as qo
        qo._QUOTA_STATE_PATH  = tmp_path / "quota_state.json"
        qo._QUOTA_HISTORY_DIR = tmp_path / "quota_history"

        result = qo.archive_today(dry_run=True)
        assert result is False

    def test_optimize_insufficient_history(self, tmp_path):
        import utils.quota_optimizer as qo
        qo._QUOTA_HISTORY_DIR = tmp_path / "quota_history"
        qo._QUOTA_CONFIG_PATH = tmp_path / "quota.json"

        result = qo.optimize(dry_run=True)
        assert result["applied"] is False
        assert "insuffisant" in result["reason"].lower()

    def test_optimize_with_saturation(self, tmp_path):
        import utils.quota_optimizer as qo
        qo._QUOTA_HISTORY_DIR = tmp_path / "quota_history"
        qo._QUOTA_CONFIG_PATH = tmp_path / "quota.json"

        # Créer 6 jours d'historique avec keyword saturé
        (tmp_path / "quota_history").mkdir()
        from datetime import date, timedelta
        for i in range(1, 7):
            d = str(date.today() - timedelta(days=i))
            state = {
                "date": d,
                "global_count": 145,  # ~97% du plafond par défaut 150
                "keywords": {
                    "intelligence-artificielle": {"total": 29, "sources": {}}
                },
                "entities": {},
            }
            (tmp_path / "quota_history" / f"{d}.json").write_text(
                json.dumps(state), encoding="utf-8"
            )

        result = qo.optimize(dry_run=True)
        # Doit détecter la saturation
        assert any("saturé" in adj for adj in result.get("adjustments", []))
