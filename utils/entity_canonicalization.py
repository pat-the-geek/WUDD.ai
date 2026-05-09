"""Canonicalisation configurable des entites NER pour graphes et agregats."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Optional

_CONFIG_FILENAME = "entity_canonicalization.json"
_DEFAULT_EVENT_MAX_CHARS = 80
_DEFAULT_EVENT_MAX_WORDS = 8


def _clean_value(value: str) -> str:
    return " ".join((value or "").strip().split())


def _normalize_value(value: str) -> str:
    normalized = _clean_value(value)
    normalized = (
        normalized.replace("’", "'")
        .replace("`", "'")
        .replace("´", "'")
        .replace("–", "-")
        .replace("—", "-")
    )
    return normalized.lower()


def _entity_key(entity_type: str, entity_value: str) -> str:
    return f"{(entity_type or '').strip().upper()}:{_normalize_value(entity_value)}"


class EntityCanonicalizer:
    """Charge une table d'alias et expose une canonicalisation simple."""

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.config_path = project_root / "config" / _CONFIG_FILENAME
        self._lock = threading.Lock()
        self._loaded = False
        self._aliases: dict[str, tuple[str, str]] = {}
        self._event_max_chars = _DEFAULT_EVENT_MAX_CHARS
        self._event_max_words = _DEFAULT_EVENT_MAX_WORDS

    def _load(self) -> None:
        if self._loaded:
            return
        if self.config_path.exists():
            try:
                payload = json.loads(self.config_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                payload = {}
            if isinstance(payload, dict):
                noise = payload.get("noise", {})
                if isinstance(noise, dict):
                    event_cfg = noise.get("EVENT", {})
                    if isinstance(event_cfg, dict):
                        self._event_max_chars = int(
                            event_cfg.get("max_chars", _DEFAULT_EVENT_MAX_CHARS)
                        )
                        self._event_max_words = int(
                            event_cfg.get("max_words", _DEFAULT_EVENT_MAX_WORDS)
                        )

                aliases = payload.get("aliases", [])
                if isinstance(aliases, list):
                    for rule in aliases:
                        if not isinstance(rule, dict):
                            continue
                        canonical = rule.get("canonical", {})
                        if not isinstance(canonical, dict):
                            continue
                        canonical_type = (canonical.get("type") or "").strip().upper()
                        canonical_value = _clean_value(str(canonical.get("value") or ""))
                        if not canonical_type or not canonical_value:
                            continue
                        raw_entries = [canonical]
                        rule_aliases = rule.get("aliases", [])
                        if isinstance(rule_aliases, list):
                            raw_entries.extend(a for a in rule_aliases if isinstance(a, dict))
                        for alias in raw_entries:
                            alias_type = (alias.get("type") or "").strip().upper()
                            alias_value = _clean_value(str(alias.get("value") or ""))
                            if not alias_type or not alias_value:
                                continue
                            self._aliases[_entity_key(alias_type, alias_value)] = (
                                canonical_type,
                                canonical_value,
                            )
        self._loaded = True

    def canonicalize(self, entity_type: str, entity_value: str) -> tuple[str, str]:
        """Retourne (type, valeur) canonises."""
        cleaned_type = (entity_type or "").strip().upper()
        cleaned_value = _clean_value(entity_value)
        if not cleaned_type or not cleaned_value:
            return cleaned_type, cleaned_value
        with self._lock:
            self._load()
            return self._aliases.get(
                _entity_key(cleaned_type, cleaned_value),
                (cleaned_type, cleaned_value),
            )

    def canonical_key(self, entity_type: str, entity_value: str) -> str:
        canonical_type, canonical_value = self.canonicalize(entity_type, entity_value)
        return f"{canonical_type}:{canonical_value}"

    def is_noise(self, entity_type: str, entity_value: str) -> bool:
        """Filtre un petit sous-ensemble de bruit NER manifeste."""
        cleaned_type = (entity_type or "").strip().upper()
        cleaned_value = _clean_value(entity_value)
        if not cleaned_type or not cleaned_value:
            return True
        if cleaned_type == "EVENT":
            if len(cleaned_value) > self._event_max_chars:
                return True
            if len(cleaned_value.split()) > self._event_max_words:
                return True
        return False


_instances: dict[Path, EntityCanonicalizer] = {}
_instances_lock = threading.Lock()


def get_entity_canonicalizer(project_root: Optional[Path] = None) -> EntityCanonicalizer:
    """Retourne le canonicalizer singleton pour project_root."""
    if project_root is None:
        project_root = Path(__file__).parent.parent
    project_root = project_root.resolve()
    with _instances_lock:
        if project_root not in _instances:
            _instances[project_root] = EntityCanonicalizer(project_root)
        return _instances[project_root]
