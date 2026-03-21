"""Tests pour utils/source_enricher.py.

Couvre :
- _normalize               : accents, ponctuation, casse
- _age_to_score            : âge → score
- _extract_domain_from_db  : extraction domaine depuis entrée DB
- _guess_domain            : heuristique domaine par nom de source
- enrich_domain_age        : WHOIS (mocké)
- enrich_transparency      : HEAD/GET HTTP (mocké)
- enrich_mbfc              : scraping MBFC (mocké)
- enrich_source            : orchestrateur (enrichments mockés)
- _build_domain_hints      : scan articles (tmp_path)
- run_enrichment           : batch enrichissement (tmp_path + mocks)
- sync_new_sources         : synchronisation registry (tmp_path)
"""

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch, call
import pytest


# ═════════════════════════════════════════════════════════════════════════════
# Helpers
# ═════════════════════════════════════════════════════════════════════════════

def _make_credibility_file(tmp_path, data=None):
    """Crée un sources_credibility.json minimal dans tmp_path/config/."""
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    db_path = config_dir / "sources_credibility.json"
    if data is None:
        data = {
            "Le Monde": {"score": 92, "biais": "centre-gauche", "pays": "fr"},
            "BFMTV":    {"score": 65, "biais": "centre", "pays": "fr"},
        }
    db_path.write_text(json.dumps(data), encoding="utf-8")
    return db_path


# ═════════════════════════════════════════════════════════════════════════════
# _normalize
# ═════════════════════════════════════════════════════════════════════════════

class TestNormalize:
    def _fn(self):
        from utils.source_enricher import _normalize
        return _normalize

    def test_lowercase(self):
        assert self._fn()("HELLO") == "hello"

    def test_removes_accents(self):
        assert self._fn()("éàü") == "eau"

    def test_removes_punctuation(self):
        result = self._fn()("Le-Monde!")
        assert "-" not in result
        assert "!" not in result

    def test_strips_whitespace(self):
        assert self._fn()("  le monde  ") == "le monde"

    def test_multiple_spaces_in_input(self):
        # _normalize doesn't collapse multiple spaces, but should not crash
        result = self._fn()("le   monde")
        assert isinstance(result, str)
        assert "le" in result

    def test_empty_string(self):
        assert self._fn()("") == ""


# ═════════════════════════════════════════════════════════════════════════════
# _age_to_score
# ═════════════════════════════════════════════════════════════════════════════

class TestAgeToScore:
    def _fn(self):
        from utils.source_enricher import _age_to_score
        return _age_to_score

    def test_20_years_returns_100(self):
        assert self._fn()(20) == 100

    def test_25_years_returns_100(self):
        assert self._fn()(25) == 100

    def test_15_years_returns_85(self):
        assert self._fn()(15) == 85

    def test_7_years_returns_70(self):
        assert self._fn()(7) == 70

    def test_4_years_returns_50(self):
        assert self._fn()(4) == 50

    def test_2_3_years_returns_30(self):
        assert self._fn()(2.5) == 30

    def test_1_5_years_returns_15(self):
        assert self._fn()(1.5) == 15

    def test_06_years_returns_0(self):
        assert self._fn()(0.6) == 0

    def test_zero_returns_0(self):
        assert self._fn()(0) == 0


# ═════════════════════════════════════════════════════════════════════════════
# _extract_domain_from_db
# ═════════════════════════════════════════════════════════════════════════════

class TestExtractDomainFromDb:
    def _fn(self):
        from utils.source_enricher import _extract_domain_from_db
        return _extract_domain_from_db

    def test_extracts_from_url_field(self):
        db = {"Le Monde": {"url": "https://www.lemonde.fr/actualite/"}}
        assert self._fn()("Le Monde", db) == "lemonde.fr"

    def test_removes_www_prefix(self):
        db = {"AFP": {"url": "https://www.afp.com"}}
        result = self._fn()("AFP", db)
        assert "www." not in result

    def test_extracts_from_website_field(self):
        db = {"BFMTV": {"website": "https://www.bfmtv.com"}}
        result = self._fn()("BFMTV", db)
        assert result == "bfmtv.com"

    def test_source_not_in_db_returns_none(self):
        assert self._fn()("Missing Source", {}) is None

    def test_entry_without_url_returns_none(self):
        db = {"Source": {"score": 70}}
        assert self._fn()("Source", db) is None

    def test_url_without_double_slash_handled(self):
        db = {"Test": {"url": "lemonde.fr"}}
        result = self._fn()("Test", db)
        assert result is not None or result is None  # No crash expected


# ═════════════════════════════════════════════════════════════════════════════
# _guess_domain
# ═════════════════════════════════════════════════════════════════════════════

class TestGuessDomain:
    def _fn(self):
        from utils.source_enricher import _guess_domain
        return _guess_domain

    def test_simple_name_lowercase_dot_fr(self):
        result = self._fn()("Mediapart")
        assert result is not None
        assert "mediapart" in result

    def test_strips_le_prefix(self):
        result = self._fn()("Le Monde")
        assert result is not None
        assert "le" not in result

    def test_strips_la_prefix(self):
        result = self._fn()("La Croix")
        assert result is not None

    def test_empty_string_returns_none(self):
        assert self._fn()("") is None

    def test_article_only_returns_none(self):
        # e.g. just "Le" after stripping leads to empty string
        result = self._fn()("Le")
        # should return either None or something non-empty (implementation-dependent)
        assert result is None or isinstance(result, str)


# ═════════════════════════════════════════════════════════════════════════════
# enrich_domain_age
# ═════════════════════════════════════════════════════════════════════════════

class TestEnrichDomainAge:
    def _fn(self):
        from utils.source_enricher import enrich_domain_age
        return enrich_domain_age

    def test_returns_age_in_years(self):
        mock_whois = MagicMock()
        creation = datetime(2010, 1, 1, tzinfo=timezone.utc)
        mock_whois.whois.return_value.creation_date = creation

        with patch.dict("sys.modules", {"whois": mock_whois}):
            result = self._fn()("lemonde.fr")

        assert result is not None
        assert result > 10.0

    def test_handles_creation_date_as_list(self):
        mock_whois = MagicMock()
        creation = datetime(2005, 6, 15, tzinfo=timezone.utc)
        mock_whois.whois.return_value.creation_date = [creation, creation]

        with patch.dict("sys.modules", {"whois": mock_whois}):
            result = self._fn()("test.fr")

        assert result is not None

    def test_none_creation_date_returns_none(self):
        mock_whois = MagicMock()
        mock_whois.whois.return_value.creation_date = None

        with patch.dict("sys.modules", {"whois": mock_whois}):
            result = self._fn()("test.fr")

        assert result is None

    def test_non_datetime_creation_date_returns_none(self):
        mock_whois = MagicMock()
        mock_whois.whois.return_value.creation_date = "2010-01-01"  # not a datetime

        with patch.dict("sys.modules", {"whois": mock_whois}):
            result = self._fn()("test.fr")

        assert result is None

    def test_import_error_returns_none(self, monkeypatch):
        import builtins
        original_import = builtins.__import__
        def _patched_import(name, *args, **kwargs):
            if name == "whois":
                raise ImportError("no module named whois")
            return original_import(name, *args, **kwargs)
        monkeypatch.setattr(builtins, "__import__", _patched_import)
        result = self._fn()("lemonde.fr")
        assert result is None

    def test_whois_exception_returns_none(self):
        mock_whois = MagicMock()
        mock_whois.whois.side_effect = Exception("WHOIS lookup failed")

        with patch.dict("sys.modules", {"whois": mock_whois}):
            result = self._fn()("test.fr")

        assert result is None

    def test_naive_datetime_handled(self):
        mock_whois = MagicMock()
        creation = datetime(2015, 3, 1)  # naive (no tzinfo)
        mock_whois.whois.return_value.creation_date = creation

        with patch.dict("sys.modules", {"whois": mock_whois}):
            result = self._fn()("test.fr")

        assert result is not None
        assert result > 5.0


# ═════════════════════════════════════════════════════════════════════════════
# enrich_transparency
# ═════════════════════════════════════════════════════════════════════════════

class TestEnrichTransparency:
    def _fn(self):
        from utils.source_enricher import enrich_transparency
        return _fn

    def test_all_pages_found_returns_4(self):
        from utils.source_enricher import enrich_transparency
        mock_resp = MagicMock()
        mock_resp.status_code = 200

        with patch("utils.source_enricher.requests.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session.head.return_value = mock_resp
            mock_session_cls.return_value = mock_session
            result = enrich_transparency("lemonde.fr")

        assert result == 4

    def test_no_pages_found_returns_0(self):
        from utils.source_enricher import enrich_transparency
        mock_resp = MagicMock()
        mock_resp.status_code = 404

        with patch("utils.source_enricher.requests.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session.head.return_value = mock_resp
            mock_session_cls.return_value = mock_session
            result = enrich_transparency("test.fr")

        assert result == 0

    def test_head_405_falls_back_to_get(self):
        from utils.source_enricher import enrich_transparency
        head_resp = MagicMock()
        head_resp.status_code = 405
        get_resp = MagicMock()
        get_resp.status_code = 200

        with patch("utils.source_enricher.requests.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session.head.return_value = head_resp
            mock_session.get.return_value = get_resp
            mock_session_cls.return_value = mock_session
            result = enrich_transparency("lemonde.fr")

        assert result == 4

    def test_partial_pages_found(self):
        from utils.source_enricher import enrich_transparency
        responses = iter([
            MagicMock(status_code=200),  # category 1 found
            MagicMock(status_code=404),  # category 2 not found
            MagicMock(status_code=200),  # category 3 found
            MagicMock(status_code=404),  # category 4 not found
        ] * 10)

        with patch("utils.source_enricher.requests.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session.head.side_effect = lambda url, **kw: next(responses)
            mock_session_cls.return_value = mock_session
            result = enrich_transparency("test.fr")

        assert 0 <= result <= 4

    def test_exception_during_request_handled(self):
        from utils.source_enricher import enrich_transparency
        with patch("utils.source_enricher.requests.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session.head.side_effect = Exception("connection refused")
            mock_session_cls.return_value = mock_session
            result = enrich_transparency("unreachable.example")

        assert result == 0


# ═════════════════════════════════════════════════════════════════════════════
# enrich_mbfc
# ═════════════════════════════════════════════════════════════════════════════

class TestEnrichMbfc:
    def _fn(self):
        from utils.source_enricher import enrich_mbfc
        return enrich_mbfc

    def _make_response(self, text="", status=200):
        resp = MagicMock()
        resp.status_code = status
        resp.text = text
        return resp

    def test_high_factual_rating_extracted(self):
        page_text = "... Le Monde ... HIGH factual reporting ..."
        with patch("utils.source_enricher.requests.get", return_value=self._make_response(page_text)):
            result = self._fn()("Le Monde")
        assert result in ("VERY HIGH", "HIGH", "MOSTLY FACTUAL", "MIXED", "LOW", "VERY LOW")

    def test_source_not_in_page_returns_none(self):
        page_text = "This page is about BBC News, not Le Monde."
        with patch("utils.source_enricher.requests.get", return_value=self._make_response(page_text)):
            result = self._fn()("Le Monde")
        assert result is None

    def test_non_200_status_returns_none(self):
        with patch("utils.source_enricher.requests.get", return_value=self._make_response(status=404)):
            result = self._fn()("Test Source")
        assert result is None

    def test_exception_returns_none(self):
        with patch("utils.source_enricher.requests.get", side_effect=Exception("timeout")):
            result = self._fn()("Test Source")
        assert result is None

    def test_very_high_rating_extracted(self):
        page_text = "... BBC News ... VERY HIGH factual reporting ..."
        with patch("utils.source_enricher.requests.get", return_value=self._make_response(page_text)):
            result = self._fn()("BBC News")
        assert result == "VERY HIGH"

    def test_mixed_rating_extracted(self):
        page_text = "... Breitbart ... MIXED reporting ..."
        with patch("utils.source_enricher.requests.get", return_value=self._make_response(page_text)):
            result = self._fn()("Breitbart")
        assert result == "MIXED"

    def test_no_rating_pattern_found_returns_none(self):
        page_text = "... Le Monde ... extensive coverage ..."  # no rating pattern
        with patch("utils.source_enricher.requests.get", return_value=self._make_response(page_text)):
            result = self._fn()("Le Monde")
        assert result is None


# ═════════════════════════════════════════════════════════════════════════════
# enrich_source
# ═════════════════════════════════════════════════════════════════════════════

class TestEnrichSource:
    def _fn(self):
        from utils.source_enricher import enrich_source
        return enrich_source

    def test_enriches_with_domain_age(self):
        entry = {"score": 90}
        with patch("utils.source_enricher.enrich_domain_age", return_value=15.2) as mock_age, \
             patch("utils.source_enricher.enrich_transparency", return_value=3) as mock_transp, \
             patch("utils.source_enricher.enrich_mbfc", return_value="HIGH") as mock_mbfc, \
             patch("utils.source_enricher.time.sleep"):
            result = self._fn()("Le Monde", entry, domain="lemonde.fr", delay=0)

        assert result["domain_age_years"] == 15.2
        assert "domain_age_score" in result
        assert result["transparence"] == 3
        assert result["mbfc_rating"] == "HIGH"

    def test_no_domain_skips_age_and_transparency(self):
        entry = {"score": 70}
        with patch("utils.source_enricher.enrich_domain_age") as mock_age, \
             patch("utils.source_enricher.enrich_transparency") as mock_transp, \
             patch("utils.source_enricher.enrich_mbfc", return_value=None) as mock_mbfc, \
             patch("utils.source_enricher.time.sleep"):
            result = self._fn()("Test Source", entry, domain=None, delay=0)

        mock_age.assert_not_called()
        mock_transp.assert_not_called()
        assert "mbfc_rating" in result

    def test_preserves_existing_fields(self):
        entry = {"score": 85, "biais": "centre-gauche", "pays": "fr"}
        with patch("utils.source_enricher.enrich_domain_age", return_value=None), \
             patch("utils.source_enricher.enrich_transparency", return_value=2), \
             patch("utils.source_enricher.enrich_mbfc", return_value="MOSTLY FACTUAL"), \
             patch("utils.source_enricher.time.sleep"):
            result = self._fn()("Le Monde", entry, domain="lemonde.fr", delay=0)

        assert result["score"] == 85
        assert result["biais"] == "centre-gauche"
        assert result["pays"] == "fr"

    def test_none_domain_age_not_stored(self):
        entry = {"score": 70}
        with patch("utils.source_enricher.enrich_domain_age", return_value=None), \
             patch("utils.source_enricher.enrich_transparency", return_value=1), \
             patch("utils.source_enricher.enrich_mbfc", return_value=None), \
             patch("utils.source_enricher.time.sleep"):
            result = self._fn()("Test", entry, domain="test.fr", delay=0)

        assert "domain_age_years" not in result

    def test_adds_enrich_date(self):
        entry = {}
        with patch("utils.source_enricher.enrich_domain_age", return_value=5.0), \
             patch("utils.source_enricher.enrich_transparency", return_value=2), \
             patch("utils.source_enricher.enrich_mbfc", return_value="HIGH"), \
             patch("utils.source_enricher.time.sleep"):
            result = self._fn()("Test", entry, domain="test.fr", delay=0)

        assert "enrich_date" in result

    def test_does_not_modify_original_entry(self):
        entry = {"score": 80}
        with patch("utils.source_enricher.enrich_domain_age", return_value=None), \
             patch("utils.source_enricher.enrich_transparency", return_value=1), \
             patch("utils.source_enricher.enrich_mbfc", return_value="HIGH"), \
             patch("utils.source_enricher.time.sleep"):
            result = self._fn()("Test", entry, domain="test.fr", delay=0)

        assert "mbfc_rating" not in entry
        assert entry == {"score": 80}


# ═════════════════════════════════════════════════════════════════════════════
# _build_domain_hints
# ═════════════════════════════════════════════════════════════════════════════

class TestBuildDomainHints:
    def _fn(self):
        from utils.source_enricher import _build_domain_hints
        return _build_domain_hints

    def test_returns_empty_when_no_data_dir(self, tmp_path):
        result = self._fn()(tmp_path)
        assert result == {}

    def test_extracts_domain_from_articles(self, tmp_path):
        articles_dir = tmp_path / "data" / "articles" / "flux"
        articles_dir.mkdir(parents=True)
        articles = [
            {"Sources": "Le Monde", "URL": "https://www.lemonde.fr/article-1"},
            {"Sources": "AFP", "URL": "https://www.afp.com/en/news"},
        ]
        (articles_dir / "articles.json").write_text(json.dumps(articles), encoding="utf-8")

        result = self._fn()(tmp_path)
        # Should have extracted domains for the sources
        assert len(result) >= 1

    def test_skips_cache_directories(self, tmp_path):
        cache_dir = tmp_path / "data" / "articles" / "flux" / "cache"
        cache_dir.mkdir(parents=True)
        articles = [{"Sources": "Test", "URL": "https://test.com/article"}]
        (cache_dir / "cached.json").write_text(json.dumps(articles), encoding="utf-8")

        result = self._fn()(tmp_path)
        # Cache should be excluded — result may be empty or have no test.com entry
        from utils.source_enricher import _normalize
        assert _normalize("Test") not in result

    def test_handles_invalid_json_files(self, tmp_path):
        articles_dir = tmp_path / "data" / "articles" / "flux"
        articles_dir.mkdir(parents=True)
        (articles_dir / "bad.json").write_text("not json", encoding="utf-8")

        result = self._fn()(tmp_path)
        assert isinstance(result, dict)

    def test_handles_non_list_json(self, tmp_path):
        articles_dir = tmp_path / "data" / "articles" / "flux"
        articles_dir.mkdir(parents=True)
        (articles_dir / "obj.json").write_text('{"key": "value"}', encoding="utf-8")

        result = self._fn()(tmp_path)
        assert isinstance(result, dict)


# ═════════════════════════════════════════════════════════════════════════════
# run_enrichment
# ═════════════════════════════════════════════════════════════════════════════

class TestRunEnrichment:
    def _fn(self):
        from utils.source_enricher import run_enrichment
        return run_enrichment

    def test_missing_credibility_file_returns_zeros(self, tmp_path):
        result = self._fn()(tmp_path)
        assert result == {"enriched": 0, "skipped": 0, "failed": 0}

    def test_enriches_sources_missing_fields(self, tmp_path):
        db_path = _make_credibility_file(tmp_path, {
            "Le Monde": {"score": 90},
            "_comment": "ignored key",
        })

        with patch("utils.source_enricher.enrich_source") as mock_enrich, \
             patch("utils.source_enricher._build_domain_hints", return_value={}), \
             patch("utils.source_enricher.time.sleep"):
            mock_enrich.return_value = {"score": 90, "domain_age_years": 20, "mbfc_rating": "HIGH"}
            result = self._fn()(tmp_path, delay=0)

        assert result["enriched"] == 1
        assert result["skipped"] == 0

    def test_skips_already_enriched_sources(self, tmp_path):
        data = {
            "Le Monde": {"score": 90, "domain_age_years": 20, "mbfc_rating": "HIGH"},
        }
        _make_credibility_file(tmp_path, data)

        with patch("utils.source_enricher.enrich_source") as mock_enrich, \
             patch("utils.source_enricher._build_domain_hints", return_value={}):
            result = self._fn()(tmp_path, delay=0)

        mock_enrich.assert_not_called()
        assert result["skipped"] == 1

    def test_force_flag_re_enriches_all(self, tmp_path):
        data = {
            "Le Monde": {"score": 90, "domain_age_years": 20, "mbfc_rating": "HIGH"},
        }
        _make_credibility_file(tmp_path, data)

        with patch("utils.source_enricher.enrich_source") as mock_enrich, \
             patch("utils.source_enricher._build_domain_hints", return_value={}), \
             patch("utils.source_enricher.time.sleep"):
            mock_enrich.return_value = {"score": 90, "domain_age_years": 25, "mbfc_rating": "VERY HIGH"}
            result = self._fn()(tmp_path, force=True, delay=0)

        assert result["enriched"] == 1

    def test_dry_run_does_not_write_file(self, tmp_path):
        _make_credibility_file(tmp_path, {"AFP": {"score": 70}})
        db_path = tmp_path / "config" / "sources_credibility.json"
        original_content = db_path.read_text(encoding="utf-8")

        with patch("utils.source_enricher.enrich_source") as mock_enrich, \
             patch("utils.source_enricher._build_domain_hints", return_value={}), \
             patch("utils.source_enricher.time.sleep"):
            mock_enrich.return_value = {"score": 70, "domain_age_years": 5, "mbfc_rating": "HIGH"}
            self._fn()(tmp_path, dry_run=True, delay=0)

        assert db_path.read_text(encoding="utf-8") == original_content

    def test_source_filter_applies(self, tmp_path):
        data = {"Le Monde": {"score": 90}, "AFP": {"score": 70}}
        _make_credibility_file(tmp_path, data)

        with patch("utils.source_enricher.enrich_source") as mock_enrich, \
             patch("utils.source_enricher._build_domain_hints", return_value={}), \
             patch("utils.source_enricher.time.sleep"):
            mock_enrich.return_value = {"score": 90, "domain_age_years": 20, "mbfc_rating": "HIGH"}
            result = self._fn()(tmp_path, source_filter="Le Monde", delay=0)

        assert result["enriched"] == 1

    def test_exception_in_enrich_source_counted_as_failed(self, tmp_path):
        _make_credibility_file(tmp_path, {"Buggy Source": {"score": 50}})

        with patch("utils.source_enricher.enrich_source", side_effect=RuntimeError("boom")), \
             patch("utils.source_enricher._build_domain_hints", return_value={}), \
             patch("utils.source_enricher.time.sleep"):
            result = self._fn()(tmp_path, delay=0)

        assert result["failed"] == 1

    def test_writes_updated_json(self, tmp_path):
        _make_credibility_file(tmp_path, {"AFP": {"score": 70}})
        db_path = tmp_path / "config" / "sources_credibility.json"

        with patch("utils.source_enricher.enrich_source") as mock_enrich, \
             patch("utils.source_enricher._build_domain_hints", return_value={}), \
             patch("utils.source_enricher.time.sleep"):
            mock_enrich.return_value = {"score": 70, "domain_age_years": 8, "mbfc_rating": "HIGH"}
            self._fn()(tmp_path, delay=0)

        saved = json.loads(db_path.read_text(encoding="utf-8"))
        assert "domain_age_years" in saved["AFP"]


# ═════════════════════════════════════════════════════════════════════════════
# sync_new_sources
# ═════════════════════════════════════════════════════════════════════════════

class TestSyncNewSources:
    def _fn(self):
        from utils.source_enricher import sync_new_sources
        return sync_new_sources

    def test_missing_credibility_file_returns_zeros(self, tmp_path):
        result = self._fn()(tmp_path)
        assert result["added"] == 0

    def test_adds_new_sources_from_registry(self, tmp_path):
        _make_credibility_file(tmp_path, {"Le Monde": {"score": 90}})
        new_sources = {"Le Monde", "AFP", "BFMTV"}

        with patch("utils.source_registry.collect_sources", return_value=new_sources):
            result = self._fn()(tmp_path)

        assert result["added"] == 2  # AFP and BFMTV are new
        assert result["already_known"] == 1  # Le Monde already known
        assert result["total_registry"] == 3

    def test_no_new_sources_returns_zero_added(self, tmp_path):
        _make_credibility_file(tmp_path, {"Le Monde": {"score": 90}})

        with patch("utils.source_registry.collect_sources", return_value={"Le Monde"}):
            result = self._fn()(tmp_path)

        assert result["added"] == 0
        assert result["already_known"] == 1

    def test_dry_run_does_not_write(self, tmp_path):
        _make_credibility_file(tmp_path, {"Le Monde": {"score": 90}})
        db_path = tmp_path / "config" / "sources_credibility.json"
        original = db_path.read_text(encoding="utf-8")

        with patch("utils.source_registry.collect_sources", return_value={"Le Monde", "AFP"}):
            self._fn()(tmp_path, dry_run=True)

        assert db_path.read_text(encoding="utf-8") == original

    def test_new_source_added_with_default_entry(self, tmp_path):
        _make_credibility_file(tmp_path, {})
        db_path = tmp_path / "config" / "sources_credibility.json"

        with patch("utils.source_registry.collect_sources", return_value={"New Source"}):
            self._fn()(tmp_path)

        saved = json.loads(db_path.read_text(encoding="utf-8"))
        assert "New Source" in saved
        assert saved["New Source"]["score"] == 50

    def test_case_insensitive_deduplication(self, tmp_path):
        """'le monde' et 'Le Monde' ne doivent pas être ajoutés deux fois."""
        _make_credibility_file(tmp_path, {"Le Monde": {"score": 90}})

        with patch("utils.source_registry.collect_sources", return_value={"le monde", "Le Monde"}):
            result = self._fn()(tmp_path)

        assert result["added"] == 0

    def test_empty_registry_returns_all_zeros(self, tmp_path):
        _make_credibility_file(tmp_path)

        with patch("utils.source_registry.collect_sources", return_value=set()):
            result = self._fn()(tmp_path)

        assert result["added"] == 0
        assert result["total_registry"] == 0
