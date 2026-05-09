"""Helpers partages pour resoudre les variantes d'entites cote timeline/articles."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .entity_canonicalization import get_entity_canonicalizer
from .entity_index import STRUCTURAL_ENTITY_TYPES, get_entity_index

_DEFAULT_MATCH_MODE = "canonical"
_TIMELINE_MATCH_MODE = "contains"
_ALLOWED_MATCH_MODES = ("strict", "canonical", "contains", "aggregate")


def _clean_query(value: str | None) -> str:
    return " ".join((value or "").strip().split())


def normalize_match_mode(match_mode: str | None, *, default: str = _DEFAULT_MATCH_MODE) -> str:
    mode = (match_mode or "").strip().lower()
    if not mode:
        return default
    if mode in _ALLOWED_MATCH_MODES:
        return mode
    allowed = ", ".join(_ALLOWED_MATCH_MODES)
    raise ValueError(f"match_mode invalide: {mode}. Valeurs autorisées: {allowed}")


def allowed_match_modes() -> tuple[str, ...]:
    return _ALLOWED_MATCH_MODES


def default_timeline_match_mode() -> str:
    return _TIMELINE_MATCH_MODE


def resolve_entity_matches(
    project_root: Path,
    query: str | None,
    entity_type: str | None = None,
    *,
    match_mode: str | None = None,
    all_types: bool = False,
    include_structural: bool = False,
    limit_per_type: int = 200,
) -> list[dict[str, Any]]:
    query_clean = _clean_query(query)
    if not query_clean:
        return []

    normalized_type = (entity_type or "").strip().upper()
    mode = normalize_match_mode(match_mode)
    canonicalizer = get_entity_canonicalizer(project_root)
    eidx = get_entity_index(project_root)

    if mode == "aggregate":
        groups = eidx.search_values(
            query_clean,
            None if all_types else (normalized_type or None),
            include_structural=include_structural,
            limit_per_type=limit_per_type,
        )
        matches: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for group in groups:
            group_type = str(group.get("type") or "").strip().upper()
            if not group_type:
                continue
            for item in group.get("top", []) if isinstance(group.get("top"), list) else []:
                value = _clean_query(str(item.get("value") or ""))
                if not value:
                    continue
                key = (group_type, value)
                if key in seen:
                    continue
                seen.add(key)
                matches.append(
                    {
                        "type": group_type,
                        "value": value,
                        "count": int(item.get("count", 0)),
                    }
                )
        return matches

    entries = eidx.get_all_entries(
        canonicalize=(mode != "strict"),
        include_structural=include_structural or normalized_type in STRUCTURAL_ENTITY_TYPES,
    )
    if mode == "canonical":
        query_type = normalized_type if normalized_type and not all_types else ""
        _, resolved_query = canonicalizer.canonicalize(query_type, query_clean)
        query_norm = canonicalizer.normalize_for_matching(resolved_query)
    else:
        query_norm = canonicalizer.normalize_for_matching(query_clean)

    matches: list[dict[str, Any]] = []
    for key, refs in entries.items():
        if ":" not in key:
            continue
        etype, _, value = key.partition(":")
        if normalized_type and not all_types and etype != normalized_type:
            continue
        value_norm = canonicalizer.normalize_for_matching(value)
        if mode in {"strict", "canonical"}:
            if value_norm != query_norm:
                continue
        elif query_norm not in value_norm:
            continue
        matches.append({"type": etype, "value": value, "count": len(refs)})

    matches.sort(key=lambda item: (-int(item["count"]), str(item["type"]), str(item["value"])))
    return matches


def load_match_refs(
    project_root: Path,
    matches: list[dict[str, Any]],
    *,
    canonicalize: bool,
    cutoff_date: str = "",
    max_refs: int = 0,
) -> list[dict[str, Any]]:
    eidx = get_entity_index(project_root)
    merged: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()

    for match in matches:
        entity_type = str(match.get("type") or "").strip().upper()
        entity_value = _clean_query(str(match.get("value") or ""))
        if not entity_type or not entity_value:
            continue
        refs = (
            eidx.get_canonical_refs(entity_type, entity_value)
            if canonicalize
            else eidx.get_refs(entity_type, entity_value)
        )
        for ref in refs:
            if cutoff_date and ref.get("date", "") < cutoff_date:
                continue
            sig = (str(ref.get("file", "")), int(ref.get("idx", -1)))
            if sig in seen:
                continue
            seen.add(sig)
            merged.append(ref)

    merged.sort(key=lambda ref: ref.get("date", ""), reverse=True)
    if max_refs > 0:
        return merged[:max_refs]
    return merged


def build_aggregate_key(query: str | None, entity_type: str | None, *, all_types: bool = False) -> str:
    label = _clean_query(query)
    if not label:
        label = "Agrégat"
    if all_types or not (entity_type or "").strip():
        return f"ALL:{label}"
    return f"{(entity_type or '').strip().upper()}:{label}"
