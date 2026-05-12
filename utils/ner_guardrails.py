"""Garde-fous NER partagés pour réduire les faux positifs PERSON.

Fonction principale:
- sanitize_entities(entities, validate_person_p31=False)

Quand validate_person_p31=True, les entités de type PERSON sont validées via
Wikidata (P31 = instance of). Les non-humains sont reclassés quand possible.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

import requests

from .cache import Cache, get_ttl
from .logging import default_logger

_WIKIDATA_SEARCH_URL = "https://www.wikidata.org/w/api.php"
_USER_AGENT = "WUDD.ai/NER-Guardrails"
_REQUEST_TIMEOUT = 5

# Cache 7 jours (même TTL que les entités NER)
_CACHE = Cache(default_ttl=get_ttl("entities"))

_HUMAN_IDS = {"Q5"}
_GPE_IDS = {
    "Q6256",      # country
    "Q3624078",   # sovereign state
    "Q15634554",  # geopolitical entity
}
_ORG_IDS = {
    "Q43229",     # organization
    "Q4830453",   # business
    "Q783794",    # company
    "Q891723",    # public company
}
_FAC_IDS = {
    "Q41176",     # building
    "Q13226383",  # facility
    "Q1576642",   # official residence
}
_PRODUCT_IDS = {
    "Q2424752",   # product
    "Q7397",      # software
    "Q2002016",   # chatbot
}


def _fold(value: str) -> str:
    normalized = " ".join((value or "").strip().split())
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


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _classify_from_p31(p31_ids: set[str]) -> str | None:
    if p31_ids & _HUMAN_IDS:
        return "PERSON"
    if p31_ids & _GPE_IDS:
        return "GPE"
    if p31_ids & _ORG_IDS:
        return "ORG"
    if p31_ids & _FAC_IDS:
        return "FAC"
    if p31_ids & _PRODUCT_IDS:
        return "PRODUCT"
    return None


def _search_candidates(name: str, timeout: int) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for lang in ("fr", "en"):
        try:
            response = requests.get(
                _WIKIDATA_SEARCH_URL,
                params={
                    "action": "wbsearchentities",
                    "format": "json",
                    "language": lang,
                    "type": "item",
                    "search": name,
                    "limit": 5,
                    "origin": "*",
                },
                headers={"User-Agent": _USER_AGENT},
                timeout=timeout,
            )
            payload = response.json()
            for row in payload.get("search", []):
                qid = row.get("id")
                if not qid or qid in seen_ids:
                    continue
                seen_ids.add(qid)
                candidates.append(row)
        except Exception:
            continue
    return candidates


def _fetch_p31_by_qids(qids: list[str], timeout: int) -> dict[str, set[str]]:
    if not qids:
        return {}
    try:
        response = requests.get(
            _WIKIDATA_SEARCH_URL,
            params={
                "action": "wbgetentities",
                "ids": "|".join(qids),
                "props": "claims",
                "format": "json",
                "origin": "*",
            },
            headers={"User-Agent": _USER_AGENT},
            timeout=timeout,
        )
        entities = response.json().get("entities", {})
    except Exception:
        return {}

    result: dict[str, set[str]] = {}
    for qid in qids:
        claims = entities.get(qid, {}).get("claims", {})
        p31_ids = {
            claim["mainsnak"]["datavalue"]["value"]["id"]
            for claim in claims.get("P31", [])
            if claim.get("mainsnak", {}).get("datavalue")
            and isinstance(claim["mainsnak"]["datavalue"].get("value"), dict)
            and claim["mainsnak"]["datavalue"]["value"].get("id")
        }
        result[qid] = p31_ids
    return result


def _resolve_person_type(name: str, timeout: int) -> str | None:
    folded = _fold(name)
    if not folded:
        return None

    cache_key = f"ner_guardrails:p31:{folded}"
    cached = _CACHE.get(cache_key)
    if isinstance(cached, dict) and cached.get("resolved_type"):
        return str(cached["resolved_type"])

    candidates = _search_candidates(name, timeout=timeout)
    if not candidates:
        return None

    p31_by_qid = _fetch_p31_by_qids([c.get("id") for c in candidates if c.get("id")], timeout=timeout)

    exact_matches: list[str] = []
    non_exact: list[str] = []
    for candidate in candidates:
        qid = candidate.get("id")
        if not qid:
            continue
        label = _fold(candidate.get("label", ""))
        aliases = [_fold(a) for a in (candidate.get("aliases") or []) if isinstance(a, str)]
        if folded == label or folded in aliases:
            exact_matches.append(qid)
        else:
            non_exact.append(qid)

    # Priorité aux correspondances exactes pour éviter les homonymies agressives.
    ordered_qids = exact_matches + non_exact
    resolved_type: str | None = None
    for qid in ordered_qids:
        resolved_type = _classify_from_p31(p31_by_qid.get(qid, set()))
        if resolved_type:
            break

    _CACHE.set(cache_key, {"resolved_type": resolved_type})
    return resolved_type


def sanitize_entities(
    entities: dict[str, Any] | None,
    *,
    validate_person_p31: bool = False,
    timeout: int = _REQUEST_TIMEOUT,
) -> dict[str, list[str]]:
    """Nettoie et optionnellement revalide les entités.

    Args:
        entities: Dictionnaire NER brut.
        validate_person_p31: Active la validation P31 Wikidata des PERSON.
        timeout: Timeout HTTP pour les appels Wikidata.

    Returns:
        Dictionnaire NER nettoyé et reclassé.
    """
    if not isinstance(entities, dict):
        return {}

    sanitized: dict[str, list[str]] = {}
    for entity_type, values in entities.items():
        if not isinstance(entity_type, str) or not isinstance(values, list):
            continue
        entity_type = entity_type.strip().upper()
        cleaned_values = [v.strip() for v in values if isinstance(v, str) and v.strip()]
        if not cleaned_values:
            continue
        sanitized[entity_type] = _dedupe(cleaned_values)

    if not validate_person_p31:
        return sanitized

    persons = list(sanitized.get("PERSON", []))
    if not persons:
        return sanitized

    kept_persons: list[str] = []
    reclassified_count = 0
    for name in persons:
        resolved_type = _resolve_person_type(name, timeout=timeout)
        if resolved_type in (None, "PERSON"):
            kept_persons.append(name)
            continue
        sanitized.setdefault(resolved_type, [])
        if name not in sanitized[resolved_type]:
            sanitized[resolved_type].append(name)
        reclassified_count += 1

    if kept_persons:
        sanitized["PERSON"] = _dedupe(kept_persons)
    else:
        sanitized.pop("PERSON", None)

    if reclassified_count:
        default_logger.info(
            f"[ner_guardrails] PERSON reclassées via P31: {reclassified_count}"
        )

    # Re-dédoublonnage final par type
    for entity_type, values in list(sanitized.items()):
        deduped = _dedupe(values)
        if deduped:
            sanitized[entity_type] = deduped
        else:
            sanitized.pop(entity_type, None)

    return sanitized
