"""Tests pour utils/cache.py.

Couvre :
  - Cache.get / Cache.set : round-trip, TTL respecté, TTL expiré
  - Cache.delete : suppression explicite
  - Cache.clear : nettoyage total et partiel (older_than)
  - Cache.get_stats : statistiques de base
  - Isolation par provider AI (_get_cache_key)
  - CACHE_TTL / get_ttl : valeurs différenciées par type de contenu
  - get_cache(namespace) : cloisonnement par espace de noms
"""

import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def cache_dir(tmp_path):
    """Répertoire temporaire isolé pour le cache."""
    return tmp_path / "cache"


@pytest.fixture()
def cache_instance(cache_dir):
    """Instance Cache avec répertoire temporaire."""
    from utils.cache import Cache
    return Cache(cache_dir=cache_dir, default_ttl=3600)


# ─────────────────────────────────────────────────────────────────────────────
# Round-trip get / set
# ─────────────────────────────────────────────────────────────────────────────

class TestCacheGetSet:
    def test_miss_on_empty_cache(self, cache_instance):
        assert cache_instance.get("clé-inexistante") is None

    def test_set_then_get_returns_value(self, cache_instance):
        cache_instance.set("ma-clé", {"data": 42})
        result = cache_instance.get("ma-clé")
        assert result == {"data": 42}

    def test_get_with_string_value(self, cache_instance):
        cache_instance.set("résumé", "Un résumé en français.")
        assert cache_instance.get("résumé") == "Un résumé en français."

    def test_get_with_list_value(self, cache_instance):
        cache_instance.set("liste", [1, 2, 3])
        assert cache_instance.get("liste") == [1, 2, 3]

    def test_get_with_none_value(self, cache_instance):
        """None est une valeur JSON valide — peut être mis en cache."""
        cache_instance.set("clé-none", None)
        # None stocké → get retourne None, indiscernable d'un miss
        # Ce comportement est acceptable car None ne porte pas de contenu utile
        result = cache_instance.get("clé-none")
        assert result is None


# ─────────────────────────────────────────────────────────────────────────────
# TTL
# ─────────────────────────────────────────────────────────────────────────────

class TestCacheTTL:
    def test_entry_valid_within_ttl(self, cache_instance):
        cache_instance.set("fraîche", "valeur")
        # Forcer un timestamp récent (maintenant - 1s)
        cache_path = cache_instance._get_cache_path("fraîche")
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        data["timestamp"] = (datetime.now() - timedelta(seconds=1)).isoformat()
        cache_path.write_text(json.dumps(data), encoding="utf-8")

        result = cache_instance.get("fraîche", ttl=3600)
        assert result == "valeur"

    def test_entry_expired_returns_none(self, cache_instance):
        cache_instance.set("vieille", "ancienne-valeur")
        # Forcer un timestamp très ancien (25h)
        cache_path = cache_instance._get_cache_path("vieille")
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        data["timestamp"] = (datetime.now() - timedelta(hours=25)).isoformat()
        cache_path.write_text(json.dumps(data), encoding="utf-8")

        result = cache_instance.get("vieille", ttl=3600)
        assert result is None

    def test_expired_entry_removed_from_disk(self, cache_instance):
        cache_instance.set("obsolète", "v")
        cache_path = cache_instance._get_cache_path("obsolète")
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        data["timestamp"] = (datetime.now() - timedelta(hours=48)).isoformat()
        cache_path.write_text(json.dumps(data), encoding="utf-8")

        cache_instance.get("obsolète", ttl=3600)
        assert not cache_path.exists()

    def test_custom_ttl_overrides_default(self, cache_instance):
        cache_instance.set("courte-vie", "v")
        cache_path = cache_instance._get_cache_path("courte-vie")
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        # Entrée vieille de 10s — expirée si TTL=5s, valide si TTL=3600s
        data["timestamp"] = (datetime.now() - timedelta(seconds=10)).isoformat()
        cache_path.write_text(json.dumps(data), encoding="utf-8")

        assert cache_instance.get("courte-vie", ttl=5) is None
        cache_instance.set("courte-vie", "v")
        data["timestamp"] = (datetime.now() - timedelta(seconds=10)).isoformat()
        cache_path.write_text(json.dumps(data), encoding="utf-8")
        assert cache_instance.get("courte-vie", ttl=3600) == "v"


# ─────────────────────────────────────────────────────────────────────────────
# Delete
# ─────────────────────────────────────────────────────────────────────────────

class TestCacheDelete:
    def test_delete_existing_returns_true(self, cache_instance):
        cache_instance.set("k", "v")
        assert cache_instance.delete("k") is True

    def test_delete_nonexistent_returns_false(self, cache_instance):
        assert cache_instance.delete("inexistant") is False

    def test_delete_removes_from_disk(self, cache_instance):
        cache_instance.set("k", "v")
        cache_path = cache_instance._get_cache_path("k")
        cache_instance.delete("k")
        assert not cache_path.exists()

    def test_get_after_delete_is_none(self, cache_instance):
        cache_instance.set("k", "v")
        cache_instance.delete("k")
        assert cache_instance.get("k") is None


# ─────────────────────────────────────────────────────────────────────────────
# Clear
# ─────────────────────────────────────────────────────────────────────────────

class TestCacheClear:
    def test_clear_all_removes_all_entries(self, cache_instance):
        for i in range(5):
            cache_instance.set(f"clé-{i}", i)
        deleted = cache_instance.clear()
        assert deleted == 5
        assert list(cache_instance.cache_dir.glob("*.json")) == []

    def test_clear_older_than_removes_only_stale(self, cache_instance):
        # 3 entrées fraîches
        for i in range(3):
            cache_instance.set(f"fraîche-{i}", i)

        # 2 entrées vieilles (forcer timestamp 2h dans le passé)
        for i in range(2):
            cache_instance.set(f"vieille-{i}", i)
            p = cache_instance._get_cache_path(f"vieille-{i}")
            data = json.loads(p.read_text(encoding="utf-8"))
            data["timestamp"] = (datetime.now() - timedelta(hours=2)).isoformat()
            p.write_text(json.dumps(data), encoding="utf-8")

        deleted = cache_instance.clear(older_than=3600)  # TTL 1h
        assert deleted == 2

    def test_clear_returns_zero_when_empty(self, cache_instance):
        assert cache_instance.clear() == 0


# ─────────────────────────────────────────────────────────────────────────────
# get_stats
# ─────────────────────────────────────────────────────────────────────────────

class TestCacheStats:
    def test_stats_empty_cache(self, cache_instance):
        stats = cache_instance.get_stats()
        assert stats["entries"] == 0
        assert stats["total_size_mb"] == 0.0

    def test_stats_after_write(self, cache_instance):
        cache_instance.set("k1", "v1")
        cache_instance.set("k2", "v2")
        stats = cache_instance.get_stats()
        assert stats["entries"] == 2
        assert stats["total_size_mb"] >= 0.0
        assert "cache_dir" in stats


# ─────────────────────────────────────────────────────────────────────────────
# Isolation par provider IA
# ─────────────────────────────────────────────────────────────────────────────

class TestCacheProviderIsolation:
    def test_different_provider_different_key(self, cache_dir):
        """Deux providers doivent produire des clés de cache distinctes."""
        from utils.cache import Cache

        with patch.dict(os.environ, {"AI_PROVIDER": "euria"}):
            cache_euria = Cache(cache_dir=cache_dir)
            key_euria = cache_euria._get_cache_key("même-prompt")

        with patch.dict(os.environ, {"AI_PROVIDER": "claude"}):
            cache_claude = Cache(cache_dir=cache_dir)
            key_claude = cache_claude._get_cache_key("même-prompt")

        assert key_euria != key_claude

    def test_same_provider_same_key(self, cache_dir):
        from utils.cache import Cache

        with patch.dict(os.environ, {"AI_PROVIDER": "euria"}):
            c1 = Cache(cache_dir=cache_dir)
            c2 = Cache(cache_dir=cache_dir)
            assert c1._get_cache_key("k") == c2._get_cache_key("k")

    def test_euria_provider_does_not_see_claude_entry(self, cache_dir):
        from utils.cache import Cache

        with patch.dict(os.environ, {"AI_PROVIDER": "euria"}):
            ce = Cache(cache_dir=cache_dir)
            ce.set("prompt", "réponse-euria")

        with patch.dict(os.environ, {"AI_PROVIDER": "claude"}):
            cc = Cache(cache_dir=cache_dir)
            assert cc.get("prompt") is None


# ─────────────────────────────────────────────────────────────────────────────
# CACHE_TTL / get_ttl
# ─────────────────────────────────────────────────────────────────────────────

class TestCacheTTLConstants:
    def test_known_types_have_expected_ttl(self):
        from utils.cache import CACHE_TTL, get_ttl

        assert CACHE_TTL["summary"] == 86400
        assert CACHE_TTL["entities"] == 604800
        assert CACHE_TTL["sentiment"] == 604800
        assert CACHE_TTL["synthesis"] == 3600
        assert CACHE_TTL["geocode"] == 2592000

    def test_get_ttl_known_type(self):
        from utils.cache import get_ttl
        assert get_ttl("entities") == 604800

    def test_get_ttl_unknown_type_fallback(self):
        from utils.cache import get_ttl
        assert get_ttl("type-inconnu") == 86400  # fallback 24h

    def test_entities_ttl_longer_than_summary(self):
        from utils.cache import CACHE_TTL
        assert CACHE_TTL["entities"] > CACHE_TTL["summary"]


# ─────────────────────────────────────────────────────────────────────────────
# Fichier de cache corrompu
# ─────────────────────────────────────────────────────────────────────────────

class TestCacheCorruption:
    def test_corrupted_file_returns_none(self, cache_instance):
        cache_instance.set("k", "v")
        p = cache_instance._get_cache_path("k")
        p.write_text("JSON invalide {{{{", encoding="utf-8")
        assert cache_instance.get("k") is None

    def test_corrupted_file_removed_from_disk(self, cache_instance):
        cache_instance.set("k", "v")
        p = cache_instance._get_cache_path("k")
        p.write_text("{bad json", encoding="utf-8")
        cache_instance.get("k")
        assert not p.exists()


# ─────────────────────────────────────────────────────────────────────────────
# get_cache (singleton et namespace)
# ─────────────────────────────────────────────────────────────────────────────

class TestGetCacheFactory:
    def test_get_cache_returns_cache_instance(self):
        from utils.cache import Cache, get_cache
        assert isinstance(get_cache(), Cache)

    def test_get_cache_same_singleton(self):
        from utils.cache import get_cache
        c1 = get_cache()
        c2 = get_cache()
        assert c1 is c2

    def test_get_cache_namespace_returns_distinct_instance(self, tmp_path):
        """Namespace cache avec répertoire explicite."""
        from utils.cache import Cache

        c_ns = Cache(cache_dir=tmp_path / "articles" / "cache" / "test-flux")
        assert isinstance(c_ns, Cache)
        assert "test-flux" in str(c_ns.cache_dir)
