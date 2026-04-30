"""Tests pour utils/quota.py — QuotaManager.

Couvre :
  - can_process : plafond global, par mot-clé, par source, désactivé
  - can_process_entities : plafond par entité nommée, types ignorés
  - record_article : incrémentation des compteurs
  - sort_by_priority : tri adaptatif par taux de consommation
  - reset_day : remise à zéro manuelle des compteurs
  - _maybe_reset_day : réinitialisation automatique à minuit (mock date)
  - is_global_exhausted : état d'épuisement global
"""

import json
import sys
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ─────────────────────────────────────────────────────────────────────────────
# Fixture : QuotaManager isolé (état et config en mémoire, pas de disque)
# ─────────────────────────────────────────────────────────────────────────────

def _make_quota(
    tmp_path: Path,
    *,
    enabled: bool = True,
    global_limit: int = 100,
    keyword_limit: int = 20,
    source_limit: int = 5,
    entity_limit: int = 10,
    global_source_limit: int = 15,
    adaptive_sorting: bool = True,
) -> "QuotaManager":
    """Crée un QuotaManager avec config et état isolés dans tmp_path."""
    from utils.quota import QuotaManager

    config = {
        "enabled": enabled,
        "global_daily_limit": global_limit,
        "per_keyword_daily_limit": keyword_limit,
        "per_source_daily_limit": source_limit,
        "per_entity_daily_limit": entity_limit,
        "global_source_daily_limit": global_source_limit,
        "per_run_limit": 30,
        "adaptive_sorting": adaptive_sorting,
        "summary_max_lines": 20,
        "ignored_entity_types": ["DATE", "TIME", "CARDINAL", "ORDINAL", "PERCENT", "MONEY", "QUANTITY"],
    }
    state = {
        "date": str(date.today()),
        "global_count": 0,
        "keywords": {},
        "entities": {},
        "global_sources": {},
    }

    config_path = tmp_path / "quota.json"
    state_path = tmp_path / "quota_state.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    state_path.write_text(json.dumps(state), encoding="utf-8")

    (tmp_path / "articles-from-rss" / "_WUDD.AI_").mkdir(parents=True, exist_ok=True)

    with (
        patch("utils.quota.QUOTA_CONFIG_PATH", config_path),
        patch("utils.quota.QUOTA_STATE_PATH", state_path),
        patch("utils.quota.WUDD_48H_PATH", tmp_path / "48-heures.json"),
    ):
        qm = QuotaManager()

    return qm


@pytest.fixture()
def qm(tmp_path):
    return _make_quota(tmp_path)


# ─────────────────────────────────────────────────────────────────────────────
# can_process — plafonds de base
# ─────────────────────────────────────────────────────────────────────────────

class TestCanProcess:
    def test_allows_first_article(self, qm):
        assert qm.can_process("IA", "lemonde.fr") is True

    def test_disabled_quota_always_allows(self, tmp_path):
        qm = _make_quota(tmp_path, enabled=False)
        for _ in range(200):
            assert qm.can_process("IA", "lemonde.fr") is True

    def test_blocks_when_global_limit_reached(self, tmp_path):
        qm = _make_quota(tmp_path, global_limit=3)
        for _ in range(3):
            qm.record_article("IA", "lemonde.fr")
        assert qm.can_process("IA", "lemonde.fr") is False

    def test_blocks_when_keyword_limit_reached(self, tmp_path):
        qm = _make_quota(tmp_path, keyword_limit=3, global_limit=1000)
        for _ in range(3):
            qm.record_article("IA", "lemonde.fr")
        # Nouvelle source — le plafond keyword doit bloquer
        assert qm.can_process("IA", "lefigaro.fr") is False

    def test_allows_different_keyword_after_one_exhausted(self, tmp_path):
        qm = _make_quota(tmp_path, keyword_limit=2, global_limit=1000, source_limit=10)
        for _ in range(2):
            qm.record_article("IA", "lemonde.fr")
        # "IA" est épuisé, mais "Politique" ne l'est pas
        assert qm.can_process("IA", "lefigaro.fr") is False
        assert qm.can_process("Politique", "lefigaro.fr") is True

    def test_blocks_when_source_limit_reached(self, tmp_path):
        qm = _make_quota(tmp_path, source_limit=2, keyword_limit=100, global_limit=1000)
        for _ in range(2):
            qm.record_article("IA", "lemonde.fr")
        assert qm.can_process("IA", "lemonde.fr") is False

    def test_allows_other_source_after_one_blocked(self, tmp_path):
        qm = _make_quota(tmp_path, source_limit=2, keyword_limit=100, global_limit=1000)
        for _ in range(2):
            qm.record_article("IA", "lemonde.fr")
        # lemonde.fr est épuisé pour "IA", mais lefigaro.fr ne l'est pas
        assert qm.can_process("IA", "lefigaro.fr") is True

    def test_keyword_limit_override(self, tmp_path):
        qm = _make_quota(tmp_path, keyword_limit=10, global_limit=1000, source_limit=100)
        for _ in range(3):
            qm.record_article("IA", "lemonde.fr")
        # Avec override limit=3, on doit être bloqué
        assert qm.can_process("IA", "autre.fr", keyword_limit=3) is False
        # Avec override limit=10, on est encore passant
        assert qm.can_process("IA", "autre.fr", keyword_limit=10) is True


# ─────────────────────────────────────────────────────────────────────────────
# can_process_entities
# ─────────────────────────────────────────────────────────────────────────────

class TestCanProcessEntities:
    def test_no_entities_always_allowed(self, qm):
        ok, name = qm.can_process_entities({})
        assert ok is True
        assert name == ""

    def test_allows_entity_below_limit(self, tmp_path):
        qm = _make_quota(tmp_path, entity_limit=5)
        entities = {"PERSON": ["Macron"]}
        # 4 enregistrements — encore sous la limite
        for _ in range(4):
            qm.record_article("IA", "lemonde.fr", entities=entities)
        ok, _ = qm.can_process_entities(entities)
        assert ok is True

    def test_blocks_entity_at_limit(self, tmp_path):
        qm = _make_quota(tmp_path, entity_limit=3, keyword_limit=100, global_limit=1000, source_limit=100)
        entities = {"PERSON": ["Macron"]}
        for _ in range(3):
            qm.record_article("IA", "lemonde.fr", entities=entities)
        ok, name = qm.can_process_entities(entities)
        assert ok is False
        assert name == "Macron"

    def test_ignored_entity_types_not_counted(self, tmp_path):
        qm = _make_quota(tmp_path, entity_limit=2)
        # DATE est ignoré — ne doit pas bloquer
        entities = {"DATE": ["2026-01-01"], "TIME": ["10:00"]}
        for _ in range(5):
            qm.record_article("IA", "lemonde.fr", entities=entities)
        ok, _ = qm.can_process_entities(entities)
        assert ok is True

    def test_entity_limit_zero_always_allowed(self, tmp_path):
        qm = _make_quota(tmp_path, entity_limit=0)
        entities = {"PERSON": ["Macron"] * 20}
        ok, _ = qm.can_process_entities(entities)
        assert ok is True

    def test_disabled_quota_ignores_entity_limit(self, tmp_path):
        qm = _make_quota(tmp_path, enabled=False, entity_limit=1)
        entities = {"PERSON": ["Macron"]}
        for _ in range(5):
            qm.record_article("IA", "lemonde.fr", entities=entities)
        ok, _ = qm.can_process_entities(entities)
        assert ok is True


# ─────────────────────────────────────────────────────────────────────────────
# record_article
# ─────────────────────────────────────────────────────────────────────────────

class TestRecordArticle:
    def test_global_count_increments(self, qm):
        assert qm._state["global_count"] == 0
        qm.record_article("IA", "lemonde.fr")
        assert qm._state["global_count"] == 1

    def test_keyword_count_increments(self, qm):
        qm.record_article("IA", "lemonde.fr")
        assert qm._state["keywords"]["IA"]["total"] == 1

    def test_source_count_increments(self, qm):
        qm.record_article("IA", "lemonde.fr")
        assert qm._state["keywords"]["IA"]["sources"]["lemonde.fr"] == 1

    def test_entity_count_increments(self, qm):
        qm.record_article("IA", "lemonde.fr", entities={"PERSON": ["Macron"]})
        assert qm._state["entities"].get("Macron", 0) == 1

    def test_ignored_entity_types_not_counted_in_state(self, qm):
        qm.record_article("IA", "lemonde.fr", entities={"DATE": ["2026-01-01"]})
        assert "2026-01-01" not in qm._state["entities"]

    def test_multiple_records_accumulate(self, qm):
        for _ in range(5):
            qm.record_article("IA", "lemonde.fr")
        assert qm._state["global_count"] == 5
        assert qm._state["keywords"]["IA"]["total"] == 5


# ─────────────────────────────────────────────────────────────────────────────
# is_global_exhausted
# ─────────────────────────────────────────────────────────────────────────────

class TestIsGlobalExhausted:
    def test_not_exhausted_initially(self, qm):
        assert qm.is_global_exhausted() is False

    def test_exhausted_at_limit(self, tmp_path):
        qm = _make_quota(tmp_path, global_limit=3, keyword_limit=100, source_limit=100)
        for _ in range(3):
            qm.record_article("IA", "lemonde.fr")
        assert qm.is_global_exhausted() is True

    def test_disabled_quota_never_exhausted(self, tmp_path):
        qm = _make_quota(tmp_path, enabled=False, global_limit=1)
        for _ in range(5):
            qm.record_article("IA", "lemonde.fr")
        assert qm.is_global_exhausted() is False


# ─────────────────────────────────────────────────────────────────────────────
# reset_day
# ─────────────────────────────────────────────────────────────────────────────

class TestResetDay:
    def test_reset_clears_all_counters(self, qm):
        qm.record_article("IA", "lemonde.fr", entities={"PERSON": ["Macron"]})
        qm.reset_day()
        assert qm._state["global_count"] == 0
        assert qm._state["keywords"] == {}
        assert qm._state["entities"] == {}

    def test_reset_keeps_today_date(self, qm):
        qm.record_article("IA", "lemonde.fr")
        qm.reset_day()
        assert qm._state["date"] == str(date.today())

    def test_reset_allows_processing_again(self, tmp_path):
        qm = _make_quota(tmp_path, global_limit=2, keyword_limit=100, source_limit=100)
        for _ in range(2):
            qm.record_article("IA", "lemonde.fr")
        assert qm.can_process("IA", "lemonde.fr") is False
        qm.reset_day()
        assert qm.can_process("IA", "lemonde.fr") is True


# ─────────────────────────────────────────────────────────────────────────────
# _maybe_reset_day — réinitialisation automatique à minuit
# ─────────────────────────────────────────────────────────────────────────────

class TestMaybeResetDay:
    def test_resets_when_date_changes(self, tmp_path):
        """Simule un changement de jour en mockant date.today()."""
        qm = _make_quota(tmp_path, global_limit=100, keyword_limit=100, source_limit=100)
        qm.record_article("IA", "lemonde.fr")
        assert qm._state["global_count"] == 1

        # Simuler le lendemain
        future_date = "2099-01-01"
        with patch("utils.quota.date") as mock_date:
            mock_date.today.return_value = MagicMock()
            mock_date.today.return_value.__str__ = lambda self: future_date
            # Forcer la condition de détection du changement de jour
            qm._state["date"] = "2099-01-01"  # même date que mock → pas de reset
            # Test contraire : ancienne date dans state
            qm._state["date"] = "2098-12-31"
            qm._maybe_reset_day()

        # Après reset, les compteurs doivent être à 0
        assert qm._state["global_count"] == 0

    def test_no_reset_same_day(self, qm):
        qm.record_article("IA", "lemonde.fr")
        count_before = qm._state["global_count"]
        qm._maybe_reset_day()  # Même jour → pas de reset
        assert qm._state["global_count"] == count_before


# ─────────────────────────────────────────────────────────────────────────────
# sort_by_priority — tri adaptatif
# ─────────────────────────────────────────────────────────────────────────────

class TestSortByPriority:
    def test_empty_list_returns_empty(self, qm):
        assert qm.sort_by_priority([]) == []

    def test_single_keyword_returns_same(self, qm):
        assert qm.sort_by_priority(["IA"]) == ["IA"]

    def test_less_consumed_comes_first(self, tmp_path):
        qm = _make_quota(tmp_path, keyword_limit=10, global_limit=1000, source_limit=100)
        # "Politique" consomme 5/10 = 50%, "IA" consomme 1/10 = 10%
        for _ in range(5):
            qm.record_article("Politique", "lemonde.fr")
        qm.record_article("IA", "lemonde.fr")
        sorted_kws = qm.sort_by_priority(["Politique", "IA"])
        assert sorted_kws[0] == "IA"

    def test_adaptive_sorting_disabled_preserves_order(self, tmp_path):
        qm = _make_quota(tmp_path, adaptive_sorting=False, keyword_limit=10,
                         global_limit=1000, source_limit=100)
        for _ in range(8):
            qm.record_article("Politique", "lemonde.fr")
        # Sans tri adaptatif, l'ordre est préservé
        kws = ["Politique", "IA", "Tech"]
        assert qm.sort_by_priority(kws) == kws

    def test_keyword_limits_override_used_in_ratio(self, tmp_path):
        qm = _make_quota(tmp_path, keyword_limit=10, global_limit=1000, source_limit=100)
        qm.record_article("IA", "lemonde.fr")  # 1/10 = 10%
        qm.record_article("Tech", "lemonde.fr")  # 1/5 = 20% avec override=5
        # Tech est plus "cher" avec override=5 → IA d'abord
        sorted_kws = qm.sort_by_priority(["Tech", "IA"], keyword_limits={"Tech": 5})
        assert sorted_kws[0] == "IA"


# ─────────────────────────────────────────────────────────────────────────────
# get_stats
# ─────────────────────────────────────────────────────────────────────────────

class TestGetStats:
    def test_stats_initial_state(self, qm):
        stats = qm.get_stats()
        assert stats["global"]["count"] == 0
        assert stats["global"]["limit"] > 0
        assert "keywords" in stats
        assert "date" in stats

    def test_stats_after_record(self, qm):
        qm.record_article("IA", "lemonde.fr", entities={"PERSON": ["Macron"]})
        stats = qm.get_stats()
        assert stats["global"]["count"] == 1
