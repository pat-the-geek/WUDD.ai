"""Tests pour utils/config.py et utils/quota.py.

Couvre :
  - Config : chargement .env, validation, valeurs par défaut
  - QuotaManager : can_process, can_process_entities, record_article,
    sort_by_priority, reset journalier, persistence, désactivation
"""

import json
import os
import pytest
from pathlib import Path
from unittest.mock import patch


# ─────────────────────────────────────────────────────────────────────────────
# Helpers / fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def env_euria(monkeypatch, tmp_path):
    """Variables d'env minimales pour le provider EurIA."""
    monkeypatch.setenv("URL", "https://api.example.com/v1/chat/completions")
    monkeypatch.setenv("bearer", "test-token-euria")
    monkeypatch.setenv("AI_PROVIDER", "euria")
    # Supprimer les éventuels résidus du vrai .env
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    return tmp_path


@pytest.fixture()
def env_claude(monkeypatch, tmp_path):
    """Variables d'env minimales pour le provider Claude."""
    monkeypatch.setenv("AI_PROVIDER", "claude")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key")
    monkeypatch.delenv("URL", raising=False)
    monkeypatch.delenv("bearer", raising=False)
    return tmp_path


@pytest.fixture()
def quota_dir(tmp_path):
    """Répertoire temporaire avec config quota et data/ pour QuotaManager."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    return tmp_path


@pytest.fixture()
def quota_config(quota_dir):
    """Config quota par défaut dans tmp_path/config/quota.json."""
    from datetime import date as _date
    cfg = {
        "enabled": True,
        "global_daily_limit": 20,
        "per_keyword_daily_limit": 5,
        "per_source_daily_limit": 2,
        "per_entity_daily_limit": 3,
        "adaptive_sorting": True,
        "summary_max_lines": 20,
    }
    (quota_dir / "config" / "quota.json").write_text(json.dumps(cfg), encoding="utf-8")
    # Crée un état initial vide pour aujourd'hui afin d'éviter que
    # _build_state_from_48h lise le vrai fichier 48-heures.json
    state = {
        "date": str(_date.today()),
        "global_count": 0,
        "keywords": {},
        "entities": {},
        "global_sources": {},
    }
    (quota_dir / "data" / "quota_state.json").write_text(json.dumps(state), encoding="utf-8")
    return quota_dir


# ─────────────────────────────────────────────────────────────────────────────
# Config — chargement et validation
# ─────────────────────────────────────────────────────────────────────────────

class TestConfigEurIA:
    def test_loads_url_and_bearer(self, env_euria):
        from utils.config import Config
        cfg = Config(project_root=env_euria)
        assert cfg.url == "https://api.example.com/v1/chat/completions"
        assert cfg.bearer == "test-token-euria"

    def test_ai_provider_defaults_to_euria(self, env_euria):
        from utils.config import Config
        cfg = Config(project_root=env_euria)
        assert cfg.ai_provider == "euria"

    def test_default_max_attempts(self, env_euria):
        from utils.config import Config
        cfg = Config(project_root=env_euria)
        assert cfg.max_attempts == 3

    def test_default_timeout_resume(self, env_euria):
        from utils.config import Config
        cfg = Config(project_root=env_euria)
        assert cfg.timeout_resume == 60

    def test_default_timeout_rapport(self, env_euria):
        from utils.config import Config
        cfg = Config(project_root=env_euria)
        assert cfg.timeout_rapport == 300

    def test_custom_max_attempts(self, env_euria, monkeypatch):
        monkeypatch.setenv("max_attempts", "5")
        from utils.config import Config
        cfg = Config(project_root=env_euria)
        assert cfg.max_attempts == 5

    def test_raises_if_url_missing(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AI_PROVIDER", "euria")
        monkeypatch.setenv("bearer", "tok")
        monkeypatch.delenv("URL", raising=False)
        from utils.config import Config
        with pytest.raises(ValueError, match="URL"):
            Config(project_root=tmp_path)

    def test_raises_if_bearer_missing(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AI_PROVIDER", "euria")
        monkeypatch.setenv("URL", "https://api.example.com")
        monkeypatch.delenv("bearer", raising=False)
        from utils.config import Config
        with pytest.raises(ValueError, match="bearer"):
            Config(project_root=tmp_path)

    def test_get_api_headers_contains_bearer(self, env_euria):
        from utils.config import Config
        cfg = Config(project_root=env_euria)
        headers = cfg.get_api_headers()
        assert "Authorization" in headers
        assert "test-token-euria" in headers["Authorization"]


class TestConfigClaude:
    def test_claude_provider_valid(self, env_claude):
        from utils.config import Config
        cfg = Config(project_root=env_claude)
        assert cfg.ai_provider == "claude"
        assert cfg.anthropic_api_key == "sk-ant-test-key"

    def test_raises_if_anthropic_key_missing(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AI_PROVIDER", "claude")
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("URL", raising=False)
        monkeypatch.delenv("bearer", raising=False)
        from utils.config import Config
        with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
            Config(project_root=tmp_path)


class TestConfigInvalidProvider:
    def test_invalid_provider_raises(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AI_PROVIDER", "gpt4")
        monkeypatch.delenv("URL", raising=False)
        monkeypatch.delenv("bearer", raising=False)
        from utils.config import Config
        with pytest.raises(ValueError, match="AI_PROVIDER"):
            Config(project_root=tmp_path)


class TestConfigPaths:
    def test_data_articles_dir(self, env_euria):
        from utils.config import Config
        cfg = Config(project_root=env_euria)
        assert cfg.data_articles_dir == env_euria / "data" / "articles"

    def test_config_dir(self, env_euria):
        from utils.config import Config
        cfg = Config(project_root=env_euria)
        assert cfg.config_dir == env_euria / "config"

    def test_setup_directories_creates_dirs(self, env_euria):
        from utils.config import Config
        cfg = Config(project_root=env_euria)
        cfg.setup_directories()
        assert cfg.data_articles_dir.exists()
        assert cfg.rapports_markdown_dir.exists()


# ─────────────────────────────────────────────────────────────────────────────
# QuotaManager — limites et compteurs
# ─────────────────────────────────────────────────────────────────────────────

class TestQuotaManagerFactory:
    def test_can_process_within_all_limits(self, quota_config):
        from utils.quota import QuotaManager
        with patch("utils.quota.QUOTA_CONFIG_PATH", quota_config / "config" / "quota.json"), \
             patch("utils.quota.QUOTA_STATE_PATH", quota_config / "data" / "quota_state.json"):
            qm = QuotaManager()
            assert qm.can_process("ia", "Le Monde") is True

    def test_global_limit_blocks(self, quota_config):
        from utils.quota import QuotaManager
        with patch("utils.quota.QUOTA_CONFIG_PATH", quota_config / "config" / "quota.json"), \
             patch("utils.quota.QUOTA_STATE_PATH", quota_config / "data" / "quota_state.json"):
            qm = QuotaManager()
            # global_daily_limit = 20 → enregistrer 20 articles sur des mots-clés différents
            for i in range(20):
                qm.record_article(f"kw{i}", "source.com")
            assert qm.can_process("kwnew", "other.com") is False

    def test_keyword_limit_blocks(self, quota_config):
        from utils.quota import QuotaManager
        with patch("utils.quota.QUOTA_CONFIG_PATH", quota_config / "config" / "quota.json"), \
             patch("utils.quota.QUOTA_STATE_PATH", quota_config / "data" / "quota_state.json"):
            qm = QuotaManager()
            # per_keyword_daily_limit = 5
            for i in range(5):
                qm.record_article("ia", f"source{i}.com")
            assert qm.can_process("ia", "new_source.com") is False

    def test_source_limit_blocks(self, quota_config):
        from utils.quota import QuotaManager
        with patch("utils.quota.QUOTA_CONFIG_PATH", quota_config / "config" / "quota.json"), \
             patch("utils.quota.QUOTA_STATE_PATH", quota_config / "data" / "quota_state.json"):
            qm = QuotaManager()
            # per_source_daily_limit = 2
            qm.record_article("ia", "lemonde.fr")
            qm.record_article("ia", "lemonde.fr")
            assert qm.can_process("ia", "lemonde.fr") is False
            # Une autre source n'est pas bloquée
            assert qm.can_process("ia", "lefigaro.fr") is True

    def test_record_article_increments_global(self, quota_config):
        from utils.quota import QuotaManager
        with patch("utils.quota.QUOTA_CONFIG_PATH", quota_config / "config" / "quota.json"), \
             patch("utils.quota.QUOTA_STATE_PATH", quota_config / "data" / "quota_state.json"):
            qm = QuotaManager()
            qm.record_article("ia", "lemonde.fr")
            qm.record_article("ia", "lemonde.fr")
            stats = qm.get_stats()
            assert stats["global"]["count"] == 2

    def test_record_article_increments_keyword(self, quota_config):
        from utils.quota import QuotaManager
        with patch("utils.quota.QUOTA_CONFIG_PATH", quota_config / "config" / "quota.json"), \
             patch("utils.quota.QUOTA_STATE_PATH", quota_config / "data" / "quota_state.json"):
            qm = QuotaManager()
            qm.record_article("ia", "lemonde.fr")
            qm.record_article("ia", "lefigaro.fr")
            stats = qm.get_stats()
            # get_stats() wraps totals: stats["keywords"][kw]["total"]
            assert stats["keywords"]["ia"]["total"] == 2


class TestQuotaManagerEntities:
    def test_entities_within_limit(self, quota_config):
        from utils.quota import QuotaManager
        with patch("utils.quota.QUOTA_CONFIG_PATH", quota_config / "config" / "quota.json"), \
             patch("utils.quota.QUOTA_STATE_PATH", quota_config / "data" / "quota_state.json"):
            qm = QuotaManager()
            entities = {"PERSON": ["Alice", "Bob"], "ORG": ["OpenAI"]}
            ok, blocked = qm.can_process_entities(entities)
            assert ok is True
            assert blocked == ""

    def test_entities_exceeded_limit(self, quota_config):
        from utils.quota import QuotaManager
        with patch("utils.quota.QUOTA_CONFIG_PATH", quota_config / "config" / "quota.json"), \
             patch("utils.quota.QUOTA_STATE_PATH", quota_config / "data" / "quota_state.json"):
            qm = QuotaManager()
            # per_entity_daily_limit = 3, enregistrer "Alice" 3 fois
            for _ in range(3):
                qm.record_article("ia", f"src{_}.com", entities={"PERSON": ["Alice"]})
            ok, blocked = qm.can_process_entities({"PERSON": ["Alice"]})
            assert ok is False
            assert blocked == "Alice"

    def test_record_article_increments_entity_count(self, quota_config):
        from utils.quota import QuotaManager
        with patch("utils.quota.QUOTA_CONFIG_PATH", quota_config / "config" / "quota.json"), \
             patch("utils.quota.QUOTA_STATE_PATH", quota_config / "data" / "quota_state.json"):
            qm = QuotaManager()
            qm.record_article("ia", "lemonde.fr", entities={"PERSON": ["Alice", "Bob"]})
            stats = qm.get_stats()
            # get_stats() wraps entity counts: stats["entities"][name]["count"]
            assert stats["entities"]["Alice"]["count"] == 1
            assert stats["entities"]["Bob"]["count"] == 1

    def test_no_entities_does_not_block(self, quota_config):
        from utils.quota import QuotaManager
        with patch("utils.quota.QUOTA_CONFIG_PATH", quota_config / "config" / "quota.json"), \
             patch("utils.quota.QUOTA_STATE_PATH", quota_config / "data" / "quota_state.json"):
            qm = QuotaManager()
            ok, blocked = qm.can_process_entities({})
            assert ok is True


class TestQuotaManagerSorting:
    def test_sort_by_priority_least_consumed_first(self, quota_config):
        from utils.quota import QuotaManager
        with patch("utils.quota.QUOTA_CONFIG_PATH", quota_config / "config" / "quota.json"), \
             patch("utils.quota.QUOTA_STATE_PATH", quota_config / "data" / "quota_state.json"):
            qm = QuotaManager()
            qm.record_article("sport", "s.com")
            qm.record_article("sport", "s.com")
            qm.record_article("ia", "s.com")
            # "ia" a 1 article, "sport" en a 2 → "ia" doit être en premier
            sorted_kws = qm.sort_by_priority(["sport", "ia", "sante"])
            assert sorted_kws.index("ia") < sorted_kws.index("sport")

    def test_sort_by_priority_disabled(self, tmp_path):
        from utils.quota import QuotaManager
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (tmp_path / "data").mkdir()
        cfg = {
            "enabled": True,
            "global_daily_limit": 100,
            "per_keyword_daily_limit": 30,
            "per_source_daily_limit": 5,
            "per_entity_daily_limit": 10,
            "adaptive_sorting": False,
        }
        (config_dir / "quota.json").write_text(json.dumps(cfg), encoding="utf-8")
        with patch("utils.quota.QUOTA_CONFIG_PATH", tmp_path / "config" / "quota.json"), \
             patch("utils.quota.QUOTA_STATE_PATH", tmp_path / "data" / "quota_state.json"):
            qm = QuotaManager()
            original = ["sport", "ia", "sante"]
            assert qm.sort_by_priority(original) == original


class TestQuotaManagerDisabled:
    def test_disabled_always_allows(self, tmp_path):
        from utils.quota import QuotaManager
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (tmp_path / "data").mkdir()
        cfg = {
            "enabled": False,
            "global_daily_limit": 0,
            "per_keyword_daily_limit": 0,
            "per_source_daily_limit": 0,
            "per_entity_daily_limit": 0,
        }
        (config_dir / "quota.json").write_text(json.dumps(cfg), encoding="utf-8")
        with patch("utils.quota.QUOTA_CONFIG_PATH", tmp_path / "config" / "quota.json"), \
             patch("utils.quota.QUOTA_STATE_PATH", tmp_path / "data" / "quota_state.json"):
            qm = QuotaManager()
            assert qm.can_process("anything", "anyone") is True
            ok, _ = qm.can_process_entities({"PERSON": ["Alice"]})
            assert ok is True


class TestQuotaManagerPersistence:
    def test_state_persisted_to_disk(self, quota_config):
        from utils.quota import QuotaManager
        state_file = quota_config / "data" / "quota_state.json"
        with patch("utils.quota.QUOTA_CONFIG_PATH", quota_config / "config" / "quota.json"), \
             patch("utils.quota.QUOTA_STATE_PATH", state_file):
            qm = QuotaManager()
            qm.record_article("ia", "test.com")
            assert state_file.exists()
            # La structure interne (brute) a bien le compteur global
            saved = json.loads(state_file.read_text(encoding="utf-8"))
            assert saved["global_count"] == 1

    def test_state_reloaded_across_instances(self, quota_config):
        from utils.quota import QuotaManager
        state_file = quota_config / "data" / "quota_state.json"
        with patch("utils.quota.QUOTA_CONFIG_PATH", quota_config / "config" / "quota.json"), \
             patch("utils.quota.QUOTA_STATE_PATH", state_file):
            qm1 = QuotaManager()
            qm1.record_article("ia", "test.com")
            # Nouvelle instance — doit lire l'état persisté
            qm2 = QuotaManager()
            assert qm2.get_stats()["global"]["count"] == 1

    def test_daily_reset_on_stale_state(self, quota_config):
        from utils.quota import QuotaManager
        state_file = quota_config / "data" / "quota_state.json"
        # Injecter un état d'hier
        stale_state = {
            "date": "2000-01-01",
            "global_count": 99,
            "keywords": {},
            "entities": {},
        }
        state_file.write_text(json.dumps(stale_state), encoding="utf-8")
        with patch("utils.quota.QUOTA_CONFIG_PATH", quota_config / "config" / "quota.json"), \
             patch("utils.quota.QUOTA_STATE_PATH", state_file), \
             patch("utils.quota.WUDD_48H_PATH", quota_config / "data" / "nonexistent_48h.json"):
            qm = QuotaManager()
            # L'état doit avoir été réinitialisé
            assert qm.get_stats()["global"]["count"] == 0
