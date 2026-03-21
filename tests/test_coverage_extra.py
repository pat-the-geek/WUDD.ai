"""Tests complémentaires ciblés pour augmenter la couverture vers 80%+.

Couvre les branches non-testées de :
- utils/synthesis_cache.py  : _now_iso, _parse_iso vides/invalides, __init__ sans root,
                              _load avec JSON corrompu, _save OSError, get_synthesis_cache
- utils/quota.py            : _domain() URL, corrupt config/state, is_global_exhausted disabled,
                              can_process_entities limit=0, reset_day, save_config,
                              _startup_reset_if_stale, _maybe_reset_day, get_quota_manager
- utils/rolling_window.py   : articles sans URL dans output préservé, JSON corrompu,
                              output dans source_dir, non-list JSON, exception source,
                              dédup URL seen, update_entity_index
"""

import json
import threading
from datetime import datetime, timezone, timedelta, date
from pathlib import Path
from unittest.mock import patch, MagicMock, PropertyMock
import pytest


# ═════════════════════════════════════════════════════════════════════════════
# Helpers
# ═════════════════════════════════════════════════════════════════════════════

def _recent_date() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _make_art(url: str, days_ago: int = 0) -> dict:
    dt = datetime.now(timezone.utc) - timedelta(days=days_ago, hours=1)
    return {"URL": url, "Date de publication": dt.strftime("%Y-%m-%dT%H:%M:%SZ")}


def _quota_ctx(tmp_path, cfg: dict | None = None):
    """Context manager patches pour QuotaManager utilisant tmp_path."""
    if cfg is None:
        cfg = {"enabled": True, "global_daily_limit": 100, "per_keyword_daily_limit": 50,
               "per_source_daily_limit": 10, "per_entity_daily_limit": 5}
    config_path = tmp_path / "config" / "quota.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(cfg), encoding="utf-8")
    state_path = tmp_path / "data" / "quota_state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    return (
        patch("utils.quota.QUOTA_CONFIG_PATH", config_path),
        patch("utils.quota.QUOTA_STATE_PATH", state_path),
    )


# ═════════════════════════════════════════════════════════════════════════════
# synthesis_cache — branches manquantes
# ═════════════════════════════════════════════════════════════════════════════

class TestSynthesisCacheInternals:
    """Couvre les lignes 56, 61, 64-65, 76, 92-94, 105-106, 222-228."""

    def test_now_iso_returns_formatted_string(self):
        """Line 56 : _now_iso() retourne une chaîne ISO 8601."""
        from utils.synthesis_cache import _now_iso
        s = _now_iso()
        assert isinstance(s, str)
        # Doit être parseable
        dt = datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ")
        assert dt is not None

    def test_parse_iso_empty_string_returns_none(self):
        """Line 61 : _parse_iso('') → None."""
        from utils.synthesis_cache import _parse_iso
        assert _parse_iso("") is None

    def test_parse_iso_none_like_returns_none(self):
        """Line 61 : _parse_iso avec None-like empty."""
        from utils.synthesis_cache import _parse_iso
        # La fonction prend une str, tester avec chaîne vide
        result = _parse_iso("")
        assert result is None

    def test_parse_iso_invalid_format_returns_none(self):
        """Lines 64-65 : _parse_iso avec format incorrect → ValueError → None."""
        from utils.synthesis_cache import _parse_iso
        assert _parse_iso("2026-01-23") is None
        assert _parse_iso("not-a-date") is None

    def test_parse_iso_valid_format(self):
        """Les lignes 62-63 : chemin normal."""
        from utils.synthesis_cache import _parse_iso
        result = _parse_iso("2026-01-23T10:00:00Z")
        assert result is not None
        assert result.year == 2026

    def test_init_without_project_root_uses_default(self):
        """Line 76 : SynthesisCache() sans project_root."""
        from utils.synthesis_cache import SynthesisCache
        sc = SynthesisCache()  # project_root=None → utilise __file__
        assert sc.project_root is not None
        assert isinstance(sc.project_root, Path)

    def test_load_handles_corrupt_json(self, tmp_path):
        """Lines 92-94 : _load() quand le fichier cache est du JSON invalide."""
        from utils.synthesis_cache import SynthesisCache
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        cache_file = data_dir / "synthesis_cache.json"
        cache_file.write_text("not valid json}", encoding="utf-8")

        sc = SynthesisCache(tmp_path)
        # _load doit gérer l'exception et retourner un cache vide
        result = sc.get("PERSON", "Test")
        assert result is None  # Pas de crash, cache vide

    def test_load_handles_oserror(self, tmp_path):
        """Lines 92-94 : _load() quand read_text lève OSError."""
        from utils.synthesis_cache import SynthesisCache
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        # Créer un fichier valide pour que .exists() soit True
        cache_file = data_dir / "synthesis_cache.json"
        cache_file.write_text("{}", encoding="utf-8")

        sc = SynthesisCache(tmp_path)
        # Forcer un rechargement en simulant OSError à la lecture
        sc._loaded = False
        with patch("utils.synthesis_cache.open", side_effect=OSError("denied"), create=True), \
             patch.object(Path, "read_text", side_effect=OSError("permission denied")):
            sc._load()
        assert isinstance(sc._data, dict)

    def test_save_handles_oserror(self, tmp_path):
        """Lines 105-106 : _save() quand l'écriture échoue."""
        from utils.synthesis_cache import SynthesisCache
        data_dir = tmp_path / "data"
        data_dir.mkdir()

        sc = SynthesisCache(tmp_path)
        sc._loaded = True
        sc._data = {"key": "value"}

        with patch.object(Path, "write_text", side_effect=OSError("disk full")):
            # Ne doit pas lever d'exception
            sc._save()

    def test_get_synthesis_cache_singleton(self, tmp_path):
        """Lines 222-228 : get_synthesis_cache retourne le même objet."""
        from utils.synthesis_cache import get_synthesis_cache, _instances
        # Nettoyer les instances précédentes pour ce tmp_path
        root = tmp_path.resolve()
        _instances.pop(root, None)

        sc1 = get_synthesis_cache(tmp_path)
        sc2 = get_synthesis_cache(tmp_path)
        assert sc1 is sc2

    def test_get_synthesis_cache_none_root(self):
        """Lines 222-228 : get_synthesis_cache avec None → project root par défaut."""
        from utils.synthesis_cache import get_synthesis_cache
        sc = get_synthesis_cache(None)
        assert sc is not None
        assert isinstance(sc, object)

    def test_get_synthesis_cache_custom_ttl(self, tmp_path):
        """Lines 222-228 : TTL personnalisé passé au constructeur."""
        from utils.synthesis_cache import get_synthesis_cache, _instances
        root = tmp_path.resolve()
        _instances.pop(root, None)

        sc = get_synthesis_cache(tmp_path, ttl_hours=48)
        assert sc._ttl == timedelta(hours=48)


# ═════════════════════════════════════════════════════════════════════════════
# quota — branches manquantes
# ═════════════════════════════════════════════════════════════════════════════

class TestQuotaDomainHelper:
    """Line 40 : _domain() avec URL HTTP."""

    def test_url_source_extracts_domain(self):
        from utils.quota import _domain
        assert _domain("https://www.lemonde.fr/article/1") == "lemonde.fr"

    def test_url_source_removes_www(self):
        from utils.quota import _domain
        assert _domain("https://www.lefigaro.fr/") == "lefigaro.fr"

    def test_plain_name_returned_lowercase(self):
        from utils.quota import _domain
        assert _domain("Le Monde") == "le monde"


class TestQuotaCorruptFiles:
    """Lines 65-68, 76-77 : gestion des fichiers corrompus au chargement."""

    def test_corrupt_config_file_uses_defaults(self, tmp_path):
        """Lines 65-68 : config JSON invalide → DEFAULT_CONFIG."""
        from utils.quota import QuotaManager, DEFAULT_CONFIG
        config_path = tmp_path / "config" / "quota.json"
        config_path.parent.mkdir()
        config_path.write_text("not json", encoding="utf-8")
        state_path = tmp_path / "data" / "quota_state.json"
        state_path.parent.mkdir()

        with patch("utils.quota.QUOTA_CONFIG_PATH", config_path), \
             patch("utils.quota.QUOTA_STATE_PATH", state_path):
            qm = QuotaManager()

        assert qm._config.get("global_daily_limit") == DEFAULT_CONFIG["global_daily_limit"]

    def test_corrupt_state_file_uses_fresh_state(self, tmp_path):
        """Lines 76-77 : état JSON invalide → nouvel état vide."""
        from utils.quota import QuotaManager
        config_path = tmp_path / "config" / "quota.json"
        config_path.parent.mkdir()
        config_path.write_text('{"enabled": true, "global_daily_limit": 100}', encoding="utf-8")
        state_path = tmp_path / "data" / "quota_state.json"
        state_path.parent.mkdir()
        state_path.write_text("bad json", encoding="utf-8")

        with patch("utils.quota.QUOTA_CONFIG_PATH", config_path), \
             patch("utils.quota.QUOTA_STATE_PATH", state_path):
            qm = QuotaManager()

        # La machine doit démarrer sans crash avec un état frais
        assert qm._state.get("global_count", 0) == 0

    def test_missing_config_file_uses_defaults(self, tmp_path):
        """Line 68 : fichier config absent → branche else → DEFAULT_CONFIG."""
        from utils.quota import QuotaManager, DEFAULT_CONFIG
        config_path = tmp_path / "config" / "quota.json"
        config_path.parent.mkdir()
        # Ne PAS créer le fichier → QUOTA_CONFIG_PATH.exists() == False → ligne 68
        state_path = tmp_path / "data" / "quota_state.json"
        state_path.parent.mkdir()

        with patch("utils.quota.QUOTA_CONFIG_PATH", config_path), \
             patch("utils.quota.QUOTA_STATE_PATH", state_path):
            qm = QuotaManager()

        assert qm._config.get("global_daily_limit") == DEFAULT_CONFIG["global_daily_limit"]


class TestQuotaIsGlobalExhausted:
    """Line 114 : is_global_exhausted quand quota désactivé."""

    def test_disabled_quota_not_exhausted(self, tmp_path):
        """Line 114 : quand quota désactivé, is_global_exhausted → False."""
        from utils.quota import QuotaManager
        config_path = tmp_path / "config" / "quota.json"
        config_path.parent.mkdir()
        config_path.write_text('{"enabled": false, "global_daily_limit": 1}', encoding="utf-8")
        state_path = tmp_path / "data" / "quota_state.json"
        state_path.parent.mkdir()

        with patch("utils.quota.QUOTA_CONFIG_PATH", config_path), \
             patch("utils.quota.QUOTA_STATE_PATH", state_path):
            qm = QuotaManager()
            qm._state["global_count"] = 9999  # dépasse la limite

        assert qm.is_global_exhausted() is False


class TestQuotaCanProcessEntitiesLimitZero:
    """Line 154 : can_process_entities avec per_entity_daily_limit=0."""

    def test_zero_limit_always_allows(self, tmp_path):
        from utils.quota import QuotaManager
        config_path = tmp_path / "config" / "quota.json"
        config_path.parent.mkdir()
        config_path.write_text('{"enabled": true, "global_daily_limit": 100, '
                                '"per_keyword_daily_limit": 50, "per_source_daily_limit": 10, '
                                '"per_entity_daily_limit": 0}', encoding="utf-8")
        state_path = tmp_path / "data" / "quota_state.json"
        state_path.parent.mkdir()

        with patch("utils.quota.QUOTA_CONFIG_PATH", config_path), \
             patch("utils.quota.QUOTA_STATE_PATH", state_path):
            qm = QuotaManager()
            ok, blocked = qm.can_process_entities({"PERSON": ["Macron"] * 100})

        assert ok is True
        assert blocked == ""


class TestQuotaResetDay:
    """Lines 251-258 : reset_day()."""

    def test_reset_clears_all_counters(self, tmp_path):
        from utils.quota import QuotaManager
        cfg = {"enabled": True, "global_daily_limit": 100, "per_keyword_daily_limit": 50,
               "per_source_daily_limit": 10, "per_entity_daily_limit": 5}
        config_path = tmp_path / "config" / "quota.json"
        config_path.parent.mkdir()
        config_path.write_text(json.dumps(cfg), encoding="utf-8")
        state_path = tmp_path / "data" / "quota_state.json"
        state_path.parent.mkdir()

        with patch("utils.quota.QUOTA_CONFIG_PATH", config_path), \
             patch("utils.quota.QUOTA_STATE_PATH", state_path):
            qm = QuotaManager()
            qm._state["global_count"] = 50
            qm._state["keywords"] = {"ia": {"total": 10, "sources": {}}}
            qm._state["entities"] = {"macron": 3}

            qm.reset_day()

        assert qm._state["global_count"] == 0
        assert qm._state["keywords"] == {}
        assert qm._state["entities"] == {}


class TestQuotaSaveConfig:
    """Lines 262-279 : save_config()."""

    def test_saves_valid_keys_only(self, tmp_path):
        from utils.quota import QuotaManager
        cfg = {"enabled": True, "global_daily_limit": 100, "per_keyword_daily_limit": 50,
               "per_source_daily_limit": 10, "per_entity_daily_limit": 5}
        config_path = tmp_path / "config" / "quota.json"
        config_path.parent.mkdir()
        config_path.write_text(json.dumps(cfg), encoding="utf-8")
        state_path = tmp_path / "data" / "quota_state.json"
        state_path.parent.mkdir()

        with patch("utils.quota.QUOTA_CONFIG_PATH", config_path), \
             patch("utils.quota.QUOTA_STATE_PATH", state_path):
            qm = QuotaManager()
            qm.save_config({
                "global_daily_limit": 200,
                "invalid_key": "should_be_ignored",
                "enabled": False,
            })

        saved = json.loads(config_path.read_text(encoding="utf-8"))
        assert saved["global_daily_limit"] == 200
        assert saved["enabled"] is False
        assert "invalid_key" not in saved

    def test_enforces_minimum_1_for_int_keys(self, tmp_path):
        from utils.quota import QuotaManager
        cfg = {"enabled": True, "global_daily_limit": 100, "per_keyword_daily_limit": 50,
               "per_source_daily_limit": 10, "per_entity_daily_limit": 5}
        config_path = tmp_path / "config" / "quota.json"
        config_path.parent.mkdir()
        config_path.write_text(json.dumps(cfg), encoding="utf-8")
        state_path = tmp_path / "data" / "quota_state.json"
        state_path.parent.mkdir()

        with patch("utils.quota.QUOTA_CONFIG_PATH", config_path), \
             patch("utils.quota.QUOTA_STATE_PATH", state_path):
            qm = QuotaManager()
            qm.save_config({"global_daily_limit": -5})

        saved = json.loads(config_path.read_text(encoding="utf-8"))
        assert saved["global_daily_limit"] == 1  # max(1, -5)


class TestQuotaStartupReset:
    """Lines 292-301 : _startup_reset_if_stale() quand date stockée ≠ aujourd'hui."""

    def test_stale_state_resets_on_startup(self, tmp_path):
        from utils.quota import QuotaManager
        yesterday = str(date.today() - timedelta(days=1))
        cfg = {"enabled": True, "global_daily_limit": 100, "per_keyword_daily_limit": 50,
               "per_source_daily_limit": 10, "per_entity_daily_limit": 5}
        config_path = tmp_path / "config" / "quota.json"
        config_path.parent.mkdir()
        config_path.write_text(json.dumps(cfg), encoding="utf-8")
        # État avec date ancienne
        state = {"date": yesterday, "global_count": 50, "keywords": {"ia": {"total": 5}}, "entities": {}}
        state_path = tmp_path / "data" / "quota_state.json"
        state_path.parent.mkdir()
        state_path.write_text(json.dumps(state), encoding="utf-8")

        with patch("utils.quota.QUOTA_CONFIG_PATH", config_path), \
             patch("utils.quota.QUOTA_STATE_PATH", state_path):
            qm = QuotaManager()

        # _startup_reset_if_stale doit avoir remis les compteurs à 0
        assert qm._state["global_count"] == 0
        assert qm._state["keywords"] == {}

    def test_startup_reset_direct_call_stale_state(self, tmp_path):
        """Lines 292-301 : appel direct de _startup_reset_if_stale() avec état périmé.

        Après construction, _reload() fixe la date à aujourd'hui. On force ensuite
        un état périmé manuellement puis on appelle la méthode directement pour
        couvrir le corps de la condition (lignes 292-301).
        """
        from utils.quota import QuotaManager
        cfg = {"enabled": True, "global_daily_limit": 100, "per_keyword_daily_limit": 50,
               "per_source_daily_limit": 10, "per_entity_daily_limit": 5}
        config_path = tmp_path / "config" / "quota.json"
        config_path.parent.mkdir()
        config_path.write_text(json.dumps(cfg), encoding="utf-8")
        state_path = tmp_path / "data" / "quota_state.json"
        state_path.parent.mkdir()

        with patch("utils.quota.QUOTA_CONFIG_PATH", config_path), \
             patch("utils.quota.QUOTA_STATE_PATH", state_path):
            qm = QuotaManager()
            # État post-construction : date = aujourd'hui
            # On force manuellement un état périmé
            qm._state["date"] = "2000-01-01"
            qm._state["global_count"] = 999
            qm._state["keywords"] = {"ia": {"total": 10}}
            # Appel direct pour déclencher le bloc lines 292-301
            qm._startup_reset_if_stale()

        today = str(date.today())
        assert qm._state["global_count"] == 0
        assert qm._state["date"] == today
        assert qm._state.get("keywords") == {}


class TestQuotaMaybeResetDay:
    """Lines 307-308 : _maybe_reset_day() quand date ≠ aujourd'hui."""

    def test_reset_triggered_on_new_day(self, tmp_path):
        from utils.quota import QuotaManager
        today_str = str(date.today())
        cfg = {"enabled": True, "global_daily_limit": 100, "per_keyword_daily_limit": 50,
               "per_source_daily_limit": 10, "per_entity_daily_limit": 5}
        config_path = tmp_path / "config" / "quota.json"
        config_path.parent.mkdir()
        config_path.write_text(json.dumps(cfg), encoding="utf-8")
        state_path = tmp_path / "data" / "quota_state.json"
        state_path.parent.mkdir()

        with patch("utils.quota.QUOTA_CONFIG_PATH", config_path), \
             patch("utils.quota.QUOTA_STATE_PATH", state_path):
            qm = QuotaManager()
            # Simuler un état d'un autre jour
            qm._state["date"] = "2000-01-01"
            qm._state["global_count"] = 999
            # can_process appelle _maybe_reset_day
            qm.can_process("keyword", "source")

        assert qm._state["global_count"] == 0
        assert qm._state["date"] == today_str


class TestQuotaGetSingleton:
    """Lines 318-320 : get_quota_manager() singleton."""

    def test_singleton_returns_same_instance(self, tmp_path):
        from utils import quota as quota_module
        cfg = {"enabled": True, "global_daily_limit": 100, "per_keyword_daily_limit": 50,
               "per_source_daily_limit": 10, "per_entity_daily_limit": 5}
        config_path = tmp_path / "config" / "quota.json"
        config_path.parent.mkdir()
        config_path.write_text(json.dumps(cfg), encoding="utf-8")
        state_path = tmp_path / "data" / "quota_state.json"
        state_path.parent.mkdir()

        # Sauvegarder et restaurer le singleton
        original = quota_module._quota_manager
        try:
            quota_module._quota_manager = None
            with patch("utils.quota.QUOTA_CONFIG_PATH", config_path), \
                 patch("utils.quota.QUOTA_STATE_PATH", state_path):
                qm1 = quota_module.get_quota_manager()
                qm2 = quota_module.get_quota_manager()
            assert qm1 is qm2
        finally:
            quota_module._quota_manager = original


# ═════════════════════════════════════════════════════════════════════════════
# rolling_window — branches manquantes
# ═════════════════════════════════════════════════════════════════════════════

from utils.rolling_window import update_rolling_window


class TestRollingWindowExtraBranches:
    """Couvre les branches non-testées de rolling_window.py."""

    def test_reconstruction_skips_article_without_url(self, tmp_path):
        """Line 81 : article sans URL dans le fichier de sortie existant → continue."""
        src = tmp_path / "src"
        src.mkdir()
        output = src / "output.json"

        # Article frais dans le fichier source
        article = _make_art("https://a.com/1", days_ago=0)
        (src / "ia.json").write_text(json.dumps([article]), encoding="utf-8")

        # Fichier de sortie existant avec un article SANS URL
        existing_without_url = {"Date de publication": _recent_date(), "rapports": [{"fichier": "f.md"}]}
        output.write_text(json.dumps([existing_without_url]), encoding="utf-8")

        n = update_rolling_window([], output, hours=48, source_dir=src)
        assert n == 1  # L'article frais est dans la sortie

    def test_reconstruction_handles_corrupt_existing_output(self, tmp_path):
        """Lines 87-88 : fichier de sortie existant avec JSON invalide → except: pass."""
        src = tmp_path / "src"
        src.mkdir()
        output = src / "output.json"

        article = _make_art("https://b.com/1", days_ago=0)
        (src / "ia.json").write_text(json.dumps([article]), encoding="utf-8")
        # Fichier de sortie corrompu
        output.write_text("{ invalid json }", encoding="utf-8")

        # Ne doit pas planter
        n = update_rolling_window([], output, hours=48, source_dir=src)
        assert n == 1

    def test_reconstruction_skips_output_file_in_source_dir(self, tmp_path):
        """Line 94 : le fichier output est dans source_dir → ignoré."""
        src = tmp_path / "src"
        src.mkdir()
        output = src / "48-heures.json"  # output DANS source_dir

        article = _make_art("https://c.com/1", days_ago=0)
        (src / "ia.json").write_text(json.dumps([article]), encoding="utf-8")
        # Créer le fichier output dans source_dir avec un contenu différent
        output.write_text(json.dumps([_make_art("https://old.com/1", days_ago=0)]),
                          encoding="utf-8")

        n = update_rolling_window([], output, hours=48, source_dir=src)
        # L'output lui-même ne doit pas être relu comme source
        urls = [a["URL"] for a in json.loads(output.read_text())]
        assert "https://old.com/1" not in urls
        assert "https://c.com/1" in urls

    def test_reconstruction_skips_non_list_json(self, tmp_path):
        """Lines 99-100 : source JSON contenant un objet (non-liste) → continue."""
        src = tmp_path / "src"
        src.mkdir()
        output = tmp_path / "output.json"

        # Fichier source avec un dict (non-liste)
        (src / "bad.json").write_text('{"not": "a list"}', encoding="utf-8")
        # Fichier source valide
        article = _make_art("https://d.com/1", days_ago=0)
        (src / "good.json").write_text(json.dumps([article]), encoding="utf-8")

        n = update_rolling_window([], output, hours=48, source_dir=src)
        assert n == 1

    def test_reconstruction_handles_exception_in_source_file(self, tmp_path):
        """Lines 101-102 : exception lors de la lecture d'un fichier source → continue."""
        src = tmp_path / "src"
        src.mkdir()
        output = tmp_path / "output.json"

        # Fichier source invalide
        bad = src / "bad.json"
        bad.write_text("@@@@", encoding="utf-8")
        # Fichier source valide
        article = _make_art("https://e.com/1", days_ago=0)
        (src / "good.json").write_text(json.dumps([article]), encoding="utf-8")

        n = update_rolling_window([], output, hours=48, source_dir=src)
        assert n == 1

    def test_incremental_skips_duplicate_url(self, tmp_path):
        """Line 139 : mode incrémental, URL déjà vue → continue."""
        output = tmp_path / "48h.json"
        article = _make_art("https://f.com/1", days_ago=0)

        # Première passe
        update_rolling_window([article], output, hours=48)
        # Deuxième passe avec le même article
        count = update_rolling_window([article], output, hours=48)
        data = json.loads(output.read_text())

        assert data.count(article) <= 1  # dédupliqué

    def test_incremental_existing_file_not_a_list(self, tmp_path):
        """Lines 127-128 : fichier existant non-liste → repart de zéro."""
        output = tmp_path / "48h.json"
        output.write_text('{"not": "a list"}', encoding="utf-8")

        article = _make_art("https://g.com/1", days_ago=0)
        n = update_rolling_window([article], output, hours=48)
        assert n == 1

    def test_incremental_corrupt_existing_file(self, tmp_path):
        """Lines 129-130 : fichier existant avec JSON invalide → repart de zéro."""
        output = tmp_path / "48h.json"
        output.write_text("not json at all", encoding="utf-8")

        article = _make_art("https://h.com/1", days_ago=0)
        n = update_rolling_window([article], output, hours=48)
        assert n == 1

    def test_update_entity_index_success(self, tmp_path):
        """Lines 172-178 : update_entity_index=True avec entity_index disponible."""
        output = tmp_path / "48h.json"
        article = _make_art("https://i.com/1", days_ago=0)

        mock_idx = MagicMock()
        mock_idx.update.return_value = 2

        # get_entity_index est importé localement → patcher dans utils.entity_index
        with patch("utils.entity_index.get_entity_index", return_value=mock_idx):
            n = update_rolling_window([article], output, hours=48, update_entity_index=True)

        assert n == 1
        mock_idx.update.assert_called_once()

    def test_update_entity_index_exception_handled(self, tmp_path):
        """Lines 179-181 : exception dans entity_index → log warning, pas de crash."""
        output = tmp_path / "48h.json"
        article = _make_art("https://j.com/1", days_ago=0)

        with patch("utils.entity_index.get_entity_index",
                   side_effect=RuntimeError("entity_index failed")):
            # Ne doit pas lever d'exception
            n = update_rolling_window([article], output, hours=48, update_entity_index=True)

        assert n == 1

    def test_update_entity_index_false_no_call(self, tmp_path):
        """Line 171 : update_entity_index=False → entity_index non appelé."""
        output = tmp_path / "48h.json"
        article = _make_art("https://k.com/1", days_ago=0)

        with patch("utils.entity_index.get_entity_index") as mock_get:
            update_rolling_window([article], output, hours=48, update_entity_index=False)

        mock_get.assert_not_called()

    def test_reconstruction_source_dir_not_exists_falls_to_incremental(self, tmp_path):
        """Line 68 : source_dir fourni mais n'existe pas → mode incrémental."""
        output = tmp_path / "48h.json"
        nonexistent = tmp_path / "does_not_exist"

        article = _make_art("https://l.com/1", days_ago=0)
        n = update_rolling_window([article], output, hours=48, source_dir=nonexistent)
        assert n == 1

    def test_reconstruction_skips_file_with_cache_in_path(self, tmp_path):
        """Line 96 : fichier avec 'cache' dans parts → ignoré lors de la reconstruction.

        On place source_dir DANS un répertoire nommé 'cache'. Tous les fichiers
        JSON dans source_dir ont 'cache' dans leurs parts → continuescopy=0.
        On vérifie qu'aucun article n'est collecté depuis ce répertoire.
        """
        cache_src = tmp_path / "cache"
        cache_src.mkdir()
        article = _make_art("https://cache.com/1", days_ago=0)
        (cache_src / "articles.json").write_text(json.dumps([article]), encoding="utf-8")

        output = tmp_path / "output.json"
        n = update_rolling_window([], output, hours=48, source_dir=cache_src)
        # Tous les fichiers sont skippés car 'cache' est dans leurs parts
        assert n == 0

    def test_incremental_existing_with_duplicate_urls(self, tmp_path):
        """Line 139 : existing contient deux entrées avec la même URL → dedup.

        Le fichier output existant peut contenir des doublons si edité manuellement.
        La deuxième occurrence déclenche 'continue' sur la ligne 139.
        """
        output = tmp_path / "48h.json"
        article = _make_art("https://dup.com/1", days_ago=0)
        # Créer un fichier output avec l'article EN DOUBLE
        output.write_text(json.dumps([article, article]), encoding="utf-8")

        # Mode incrémental (pas de source_dir) − new_articles sans doublons
        n = update_rolling_window([], output, hours=48)
        data = json.loads(output.read_text())

        # Le doublon doit avoir été éliminé
        urls = [a.get("URL") for a in data]
        assert urls.count("https://dup.com/1") == 1

    def test_atomic_write_oserror_handled(self, tmp_path):
        """Lines 163-168 : OSError pendant tmp.replace() → log erreur, pas de crash. """
        output = tmp_path / "48h.json"
        article = _make_art("https://x.com/1", days_ago=0)

        # Simuler une OSError lors de replace()
        original_replace = output.__class__.replace
        call_count = [0]

        def mock_replace(self, target):
            call_count[0] += 1
            raise OSError("disque plein simulé")

        with patch.object(output.__class__, "replace", mock_replace):
            # Ne doit pas lever d'exception
            n = update_rolling_window([article], output, hours=48)

        # La fonction ne doit pas planter même si replace() échoue
        assert n >= 0  # la valeur peut être 0 ou 1

    def test_atomic_write_oserror_tmp_unlink_also_fails(self, tmp_path):
        """Lines 165-168 : tmp.unlink() lève aussi OSError → continue sans crash. """
        output = tmp_path / "48h.json"
        article = _make_art("https://y.com/1", days_ago=0)

        def _fail_replace(self, target):
            raise OSError("replace failed")

        def _fail_unlink(self, *args, **kwargs):
            raise OSError("unlink failed")

        with patch.object(output.__class__, "replace", _fail_replace), \
             patch.object(output.__class__, "unlink", _fail_unlink):
            # Ne doit pas lever d'exception même si unlink() échoue aussi
            n = update_rolling_window([article], output, hours=48)

        assert n >= 0

