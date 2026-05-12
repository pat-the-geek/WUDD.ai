import json
from unittest.mock import Mock, patch

from utils.ner_guardrails import sanitize_entities


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def _fake_wikidata_get(url, params=None, headers=None, timeout=None):
    action = (params or {}).get("action")
    if action == "wbsearchentities":
        query = (params or {}).get("search", "")
        if query == "OpenAI":
            return _FakeResponse({
                "search": [{"id": "Q21708200", "label": "OpenAI", "aliases": []}]
            })
        if query == "Mark Zuckerberg":
            return _FakeResponse({
                "search": [{"id": "Q36215", "label": "Mark Zuckerberg", "aliases": ["Mark Elliot Zuckerberg"]}]
            })
        return _FakeResponse({"search": []})

    if action == "wbgetentities":
        ids = ((params or {}).get("ids") or "").split("|")
        entities = {}
        for qid in ids:
            if qid == "Q21708200":
                entities[qid] = {
                    "claims": {
                        "P31": [
                            {"mainsnak": {"datavalue": {"value": {"id": "Q4830453"}}}}
                        ]
                    }
                }
            elif qid == "Q36215":
                entities[qid] = {
                    "claims": {
                        "P31": [
                            {"mainsnak": {"datavalue": {"value": {"id": "Q5"}}}}
                        ]
                    }
                }
            else:
                entities[qid] = {"claims": {}}
        return _FakeResponse({"entities": entities})

    return _FakeResponse({})


def test_sanitize_entities_without_p31_keeps_person():
    entities = {"PERSON": ["OpenAI", "Mark Zuckerberg"]}
    result = sanitize_entities(entities, validate_person_p31=False)
    assert result == {"PERSON": ["OpenAI", "Mark Zuckerberg"]}


@patch("utils.ner_guardrails.requests.get", side_effect=_fake_wikidata_get)
def test_sanitize_entities_with_p31_reclassifies_non_human_person(_mock_get: Mock):
    entities = {"PERSON": ["OpenAI", "Mark Zuckerberg"]}
    result = sanitize_entities(entities, validate_person_p31=True)

    assert "PERSON" in result
    assert "Mark Zuckerberg" in result["PERSON"]
    assert "ORG" in result
    assert "OpenAI" in result["ORG"]


@patch("utils.ner_guardrails.requests.get", side_effect=_fake_wikidata_get)
def test_sanitize_entities_with_p31_preserves_non_person_types(_mock_get: Mock):
    entities = {"PERSON": ["OpenAI"], "GPE": ["France"]}
    result = sanitize_entities(entities, validate_person_p31=True)
    assert result.get("GPE") == ["France"]
    assert result.get("ORG") == ["OpenAI"]
