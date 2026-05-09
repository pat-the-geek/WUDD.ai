"""Canonicalisation configurable des entites NER pour graphes et agregats."""

from __future__ import annotations

import json
import re
import threading
import unicodedata
from pathlib import Path
from typing import Optional

_CONFIG_FILENAME = "entity_canonicalization.json"
_DEFAULT_EVENT_MAX_CHARS = 80
_DEFAULT_EVENT_MAX_WORDS = 8


def _clean_value(value: str) -> str:
    return " ".join((value or "").strip().split())


def _fold_text(value: str) -> str:
    normalized = _clean_value(value)
    normalized = (
        normalized.replace("’", "'")
        .replace("`", "'")
        .replace("´", "'")
        .replace("–", "-")
        .replace("—", "-")
    )
    normalized = unicodedata.normalize("NFKD", normalized)
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return normalized.lower()


def _normalize_value(value: str) -> str:
    return _fold_text(value)


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
        self._search_expansions: dict[str, list[str]] = {}
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
                expansions = payload.get("search_expansions", [])
                if isinstance(expansions, list):
                    for entry in expansions:
                        if not isinstance(entry, dict):
                            continue
                        query = _normalize_value(str(entry.get("query") or ""))
                        if not query:
                            continue
                        terms = []
                        for term in entry.get("terms", []) if isinstance(entry.get("terms"), list) else []:
                            if not isinstance(term, str):
                                continue
                            cleaned = _clean_value(term)
                            if cleaned:
                                terms.append(cleaned)
                        if terms:
                            self._search_expansions[query] = terms
        self._loaded = True

    def get_explicit_canonical(
        self,
        entity_type: str,
        entity_value: str,
    ) -> tuple[str, str] | None:
        """Retourne la canonicalisation explicite configurée, si elle existe."""
        cleaned_type = (entity_type or "").strip().upper()
        cleaned_value = _clean_value(entity_value)
        if not cleaned_type or not cleaned_value:
            return None
        with self._lock:
            self._load()
            return self._aliases.get(_entity_key(cleaned_type, cleaned_value))

    def canonicalize(self, entity_type: str, entity_value: str) -> tuple[str, str]:
        """Retourne (type, valeur) canonises."""
        cleaned_type = (entity_type or "").strip().upper()
        cleaned_value = _clean_value(entity_value)
        if not cleaned_type or not cleaned_value:
            return cleaned_type, cleaned_value
        explicit = self.get_explicit_canonical(cleaned_type, cleaned_value)
        if explicit is not None:
            return explicit
        return cleaned_type, cleaned_value

    def canonical_key(self, entity_type: str, entity_value: str) -> str:
        canonical_type, canonical_value = self.canonicalize(entity_type, entity_value)
        return f"{canonical_type}:{canonical_value}"

    def normalize_for_matching(self, value: str) -> str:
        return _normalize_value(value)

    def is_short_query(self, query: str) -> bool:
        cleaned = _clean_value(query)
        token = re.sub(r"[^A-Za-z0-9]+", "", cleaned)
        return bool(token) and len(token) <= 5 and " " not in cleaned and not token.islower()

    def expand_search_terms(self, query: str) -> list[str]:
        cleaned = _clean_value(query)
        if not cleaned:
            return []
        normalized_query = _normalize_value(cleaned)
        with self._lock:
            self._load()
            terms = [cleaned]
            for term in self._search_expansions.get(normalized_query, []):
                if term not in terms:
                    terms.append(term)
            return terms

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
