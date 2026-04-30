"""utils/synthesis_cache.py — Cache persistant pour les synthèses IA par entité.

Évite de refaire un appel IA (90s + 120s = 210s) pour une entité déjà analysée
récemment. Stocke les synthèses dans data/synthesis_cache.json avec une TTL
configurable (défaut : 24h).

Format du cache :
    {
        "<md5_key>": {
            "entity_type": "PERSON",
            "entity_value": "Emmanuel Macron",
            "info_text": "...",    # Synthèse encyclopédique
            "rag_text": "...",     # Analyse RAG multi-sources
            "cached_at": "2026-03-14T10:00:00Z",
            "expires_at": "2026-03-15T10:00:00Z"
        }
    }

Utilisation typique :
    from utils.synthesis_cache import get_synthesis_cache
    cache = get_synthesis_cache(project_root)

    # Lecture
    entry = cache.get("PERSON", "Emmanuel Macron")
    if entry:
        info_text = entry["info_text"]
        rag_text  = entry["rag_text"]

    # Écriture
    cache.set("PERSON", "Emmanuel Macron", info_text="...", rag_text="...")

    # Invalidation manuelle
    cache.invalidate("PERSON", "Emmanuel Macron")
"""

import hashlib
import json
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from .file_io import json_read, json_write_compact
from .logging import default_logger

_CACHE_FILENAME = "synthesis_cache.json"
_DEFAULT_TTL_HOURS = 24


def _make_key(entity_type: str, entity_value: str) -> str:
    """Génère une clé de cache MD5 pour une entité."""
    raw = f"{entity_type}:{entity_value}".encode("utf-8")
    return hashlib.md5(raw).hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(s: str) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


class SynthesisCache:
    """Cache persistant des synthèses IA par entité.

    Thread-safe via threading.Lock.
    """

    def __init__(self, project_root: Optional[Path] = None, ttl_hours: int = _DEFAULT_TTL_HOURS):
        if project_root is None:
            project_root = Path(__file__).parent.parent
        self.project_root = project_root
        self._cache_path = project_root / "data" / _CACHE_FILENAME
        self._ttl = timedelta(hours=ttl_hours)
        self._lock = threading.Lock()
        self._data: dict = {}
        self._loaded = False

    # ── Chargement / sauvegarde ─────────────────────────────────────────────

    def _load(self) -> None:
        if self._loaded:
            return
        if self._cache_path.exists():
            try:
                self._data = json_read(self._cache_path)
            except (json.JSONDecodeError, OSError) as e:
                default_logger.warning(f"Impossible de charger synthesis_cache.json : {e}")
                self._data = {}
        self._loaded = True

    def _save(self) -> None:
        try:
            json_write_compact(self._cache_path, self._data)
        except OSError as e:
            default_logger.error(f"Impossible de sauvegarder synthesis_cache.json : {e}")

    # ── API publique ─────────────────────────────────────────────────────────

    def get(self, entity_type: str, entity_value: str) -> Optional[dict]:
        """Retourne l'entrée de cache si elle existe et n'est pas expirée.

        Returns:
            Dict avec clés 'info_text', 'rag_text', 'cached_at', 'expires_at'
            ou None si absent / expiré.
        """
        key = _make_key(entity_type, entity_value)
        with self._lock:
            self._load()
            entry = self._data.get(key)
            if not entry:
                return None
            expires = _parse_iso(entry.get("expires_at", ""))
            if expires and datetime.now(timezone.utc) > expires:
                # Expiré — supprimer silencieusement
                del self._data[key]
                self._save()
                return None
            return entry

    def set(
        self,
        entity_type: str,
        entity_value: str,
        info_text: str = "",
        rag_text: str = "",
    ) -> None:
        """Stocke une synthèse dans le cache.

        Args:
            entity_type  : type NER (ex. "PERSON")
            entity_value : valeur (ex. "Emmanuel Macron")
            info_text    : synthèse encyclopédique
            rag_text     : analyse RAG multi-sources
        """
        key = _make_key(entity_type, entity_value)
        now = datetime.now(timezone.utc)
        entry = {
            "entity_type": entity_type,
            "entity_value": entity_value,
            "info_text": info_text,
            "rag_text": rag_text,
            "cached_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "expires_at": (now + self._ttl).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        with self._lock:
            self._load()
            self._data[key] = entry
            self._save()

    def invalidate(self, entity_type: str, entity_value: str) -> bool:
        """Invalide une entrée de cache.

        Returns:
            True si l'entrée existait et a été supprimée.
        """
        key = _make_key(entity_type, entity_value)
        with self._lock:
            self._load()
            if key in self._data:
                del self._data[key]
                self._save()
                return True
            return False

    def purge_expired(self) -> int:
        """Supprime toutes les entrées expirées du cache.

        Returns:
            Nombre d'entrées supprimées.
        """
        now = datetime.now(timezone.utc)
        with self._lock:
            self._load()
            expired_keys = [
                k for k, v in self._data.items()
                if (exp := _parse_iso(v.get("expires_at", ""))) and now > exp
            ]
            for k in expired_keys:
                del self._data[k]
            if expired_keys:
                self._save()
            return len(expired_keys)

    def stats(self) -> dict:
        """Retourne des statistiques sur le cache."""
        with self._lock:
            self._load()
        now = datetime.now(timezone.utc)
        valid = sum(
            1 for v in self._data.values()
            if (exp := _parse_iso(v.get("expires_at", ""))) and now <= exp
        )
        return {
            "total": len(self._data),
            "valid": valid,
            "expired": len(self._data) - valid,
        }


# ── Singleton ────────────────────────────────────────────────────────────────

_instances: dict[Path, SynthesisCache] = {}
_instances_lock = threading.Lock()


def get_synthesis_cache(
    project_root: Optional[Path] = None,
    ttl_hours: int = _DEFAULT_TTL_HOURS,
) -> SynthesisCache:
    """Retourne l'instance singleton du SynthesisCache pour project_root."""
    if project_root is None:
        project_root = Path(__file__).parent.parent
    project_root = project_root.resolve()
    with _instances_lock:
        if project_root not in _instances:
            _instances[project_root] = SynthesisCache(project_root, ttl_hours=ttl_hours)
        return _instances[project_root]
