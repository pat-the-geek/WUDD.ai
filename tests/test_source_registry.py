"""Tests pour utils/source_registry.py.

Couvre :
  - _sources_from_opml       : parsing OPML, priorité title/text, erreurs
  - _sources_from_web_config : parsing JSON, filtrage actif=false, fallback name
  - _sources_from_articles   : scan JSON, clob "cache", max 20 articles/fichier
  - collect_sources           : union + filtre longueur ≥ 2
"""

import json
import pytest
from pathlib import Path


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _opml(outlines: list[dict]) -> str:
    """Génère un OPML minimal contenant les outlines fournis."""
    items = ""
    for o in outlines:
        attrs = " ".join(f'{k}="{v}"' for k, v in o.items())
        items += f"    <outline {attrs}/>\n"
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<opml version="2.0">\n'
        '  <body>\n'
        + items +
        '  </body>\n'
        '</opml>\n'
    )


def _articles_json(sources: list[str]) -> str:
    """Génère un JSON d'articles avec les Sources indiquées."""
    articles = [{"Sources": s, "URL": f"https://x.com/{i}", "Résumé": "ok"}
                for i, s in enumerate(sources)]
    return json.dumps(articles, ensure_ascii=False)


# ─────────────────────────────────────────────────────────────────────────────
# _sources_from_opml
# ─────────────────────────────────────────────────────────────────────────────

class TestSourcesFromOpml:
    def _fn(self):
        from utils.source_registry import _sources_from_opml
        return _sources_from_opml

    def test_nonexistent_file_returns_empty_set(self, tmp_path):
        result = self._fn()(tmp_path / "absent.opml")
        assert result == set()

    def test_extracts_title_attribute(self, tmp_path):
        opml_file = tmp_path / "feeds.opml"
        opml_file.write_text(
            _opml([{"type": "rss", "title": "Le Monde", "xmlUrl": "https://x"}])
        )
        result = self._fn()(opml_file)
        assert "Le Monde" in result

    def test_uses_text_as_fallback(self, tmp_path):
        opml_file = tmp_path / "feeds.opml"
        opml_file.write_text(
            _opml([{"type": "rss", "text": "Libération", "xmlUrl": "https://x"}])
        )
        result = self._fn()(opml_file)
        assert "Libération" in result

    def test_skips_non_rss_outlines(self, tmp_path):
        opml_file = tmp_path / "feeds.opml"
        opml_file.write_text(
            _opml([
                {"type": "rss",     "title": "RSS Source"},
                {"type": "link",    "title": "Link Source"},
                {"type": "folder",  "title": "Folder Source"},
            ])
        )
        result = self._fn()(opml_file)
        assert "RSS Source" in result
        assert "Link Source" not in result
        assert "Folder Source" not in result

    def test_multiple_feeds(self, tmp_path):
        opml_file = tmp_path / "feeds.opml"
        opml_file.write_text(
            _opml([
                {"type": "rss", "title": "Source A"},
                {"type": "rss", "title": "Source B"},
                {"type": "rss", "title": "Source C"},
            ])
        )
        result = self._fn()(opml_file)
        assert result == {"Source A", "Source B", "Source C"}

    def test_invalid_xml_returns_empty_set(self, tmp_path):
        bad_xml = tmp_path / "bad.opml"
        bad_xml.write_text("NOT XML AT ALL <<<<<")
        result = self._fn()(bad_xml)
        assert result == set()

    def test_outline_without_title_or_text_skipped(self, tmp_path):
        opml_file = tmp_path / "feeds.opml"
        opml_file.write_text(
            _opml([{"type": "rss", "xmlUrl": "https://no-title.com"}])
        )
        result = self._fn()(opml_file)
        assert result == set()


# ─────────────────────────────────────────────────────────────────────────────
# _sources_from_web_config
# ─────────────────────────────────────────────────────────────────────────────

class TestSourcesFromWebConfig:
    def _fn(self):
        from utils.source_registry import _sources_from_web_config
        return _sources_from_web_config

    def test_nonexistent_file_returns_empty_set(self, tmp_path):
        result = self._fn()(tmp_path / "absent.json")
        assert result == set()

    def test_active_sources_included(self, tmp_path):
        cfg = tmp_path / "web.json"
        cfg.write_text(json.dumps([{"title": "Site A", "actif": True}]))
        assert "Site A" in self._fn()(cfg)

    def test_inactive_sources_excluded(self, tmp_path):
        cfg = tmp_path / "web.json"
        cfg.write_text(json.dumps([
            {"title": "Active",   "actif": True},
            {"title": "Inactive", "actif": False},
        ]))
        result = self._fn()(cfg)
        assert "Active" in result
        assert "Inactive" not in result

    def test_default_actif_true(self, tmp_path):
        """Entrées sans champ 'actif' sont incluses par défaut."""
        cfg = tmp_path / "web.json"
        cfg.write_text(json.dumps([{"title": "Default Active"}]))
        assert "Default Active" in self._fn()(cfg)

    def test_uses_name_as_fallback(self, tmp_path):
        cfg = tmp_path / "web.json"
        cfg.write_text(json.dumps([{"name": "Name Source"}]))
        assert "Name Source" in self._fn()(cfg)

    def test_title_takes_priority_over_name(self, tmp_path):
        cfg = tmp_path / "web.json"
        cfg.write_text(json.dumps([{"title": "Title", "name": "Name"}]))
        result = self._fn()(cfg)
        assert "Title" in result

    def test_invalid_json_returns_empty_set(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text("{ not valid json {{{{")
        assert self._fn()(bad) == set()

    def test_non_list_json_returns_empty_set(self, tmp_path):
        cfg = tmp_path / "web.json"
        cfg.write_text(json.dumps({"key": "not a list"}))
        assert self._fn()(cfg) == set()

    def test_entry_without_title_or_name_skipped(self, tmp_path):
        cfg = tmp_path / "web.json"
        cfg.write_text(json.dumps([{"url": "https://no-title.com"}]))
        assert self._fn()(cfg) == set()


# ─────────────────────────────────────────────────────────────────────────────
# _sources_from_articles
# ─────────────────────────────────────────────────────────────────────────────

class TestSourcesFromArticles:
    def _fn(self):
        from utils.source_registry import _sources_from_articles
        return _sources_from_articles

    def test_empty_dirs_returns_empty_set(self, tmp_path):
        result = self._fn()([tmp_path / "nonexistent"])
        assert result == set()

    def test_extracts_sources_field(self, tmp_path):
        data = tmp_path / "articles"
        data.mkdir()
        (data / "articles.json").write_text(_articles_json(["Le Figaro", "L'Express"]))
        result = self._fn()([data])
        assert "Le Figaro" in result
        assert "L'Express" in result

    def test_extracts_lowercase_source_fallback(self, tmp_path):
        data = tmp_path / "articles"
        data.mkdir()
        (data / "articles.json").write_text(
            json.dumps([{"source": "Mediapart", "URL": "https://x.com"}])
        )
        result = self._fn()([data])
        assert "Mediapart" in result

    def test_skips_files_in_cache_subdirs(self, tmp_path):
        data = tmp_path / "articles"
        (data / "cache").mkdir(parents=True)
        (data / "cache" / "cache.json").write_text(
            json.dumps([{"Sources": "Should Be Skipped"}])
        )
        result = self._fn()([data])
        assert "Should Be Skipped" not in result

    def test_max_20_articles_per_file(self, tmp_path):
        """Ne lit que les 20 premiers articles d'un fichier."""
        data = tmp_path / "articles"
        data.mkdir()
        articles = [
            {"Sources": f"Source {i}", "URL": f"https://x.com/{i}"}
            for i in range(30)
        ]
        (data / "big.json").write_text(json.dumps(articles))
        result = self._fn()([data])
        # Sources 0–19 doivent être présentes
        for i in range(20):
            assert f"Source {i}" in result
        # Sources 20–29 ne doivent pas être présentes
        for i in range(20, 30):
            assert f"Source {i}" not in result

    def test_multiple_dirs_combined(self, tmp_path):
        dir_a = tmp_path / "dir_a"
        dir_b = tmp_path / "dir_b"
        dir_a.mkdir()
        dir_b.mkdir()
        (dir_a / "a.json").write_text(_articles_json(["Source A"]))
        (dir_b / "b.json").write_text(_articles_json(["Source B"]))
        result = self._fn()([dir_a, dir_b])
        assert "Source A" in result
        assert "Source B" in result

    def test_invalid_json_file_skipped(self, tmp_path):
        data = tmp_path / "articles"
        data.mkdir()
        (data / "bad.json").write_text("{ not valid {{")
        (data / "ok.json").write_text(_articles_json(["Good Source"]))
        result = self._fn()([data])
        assert "Good Source" in result  # fichier valide parsé quand même

    def test_non_list_json_file_skipped(self, tmp_path):
        data = tmp_path / "articles"
        data.mkdir()
        (data / "notlist.json").write_text(json.dumps({"key": "value"}))
        result = self._fn()([data])
        assert result == set()

    def test_article_without_source_skipped(self, tmp_path):
        data = tmp_path / "articles"
        data.mkdir()
        (data / "nosource.json").write_text(
            json.dumps([{"URL": "https://x.com", "Résumé": "test"}])
        )
        result = self._fn()([data])
        assert result == set()


# ─────────────────────────────────────────────────────────────────────────────
# collect_sources
# ─────────────────────────────────────────────────────────────────────────────

class TestCollectSources:
    def _fn(self):
        from utils.source_registry import collect_sources
        return collect_sources

    def _make_project(self, tmp_path: Path):
        """Crée une structure minimale de projet."""
        (tmp_path / "data" / "articles").mkdir(parents=True)
        (tmp_path / "data" / "articles-from-rss").mkdir(parents=True)
        (tmp_path / "config").mkdir(parents=True)
        return tmp_path

    def test_returns_set_type(self, tmp_path):
        proj = self._make_project(tmp_path)
        result = self._fn()(proj)
        assert isinstance(result, set)

    def test_combines_sources_from_all_inputs(self, tmp_path):
        proj = self._make_project(tmp_path)
        # OPML
        (proj / "data" / "WUDD.opml").write_text(
            _opml([{"type": "rss", "title": "OPML Source"}])
        )
        # web_sources.json
        (proj / "config" / "web_sources.json").write_text(
            json.dumps([{"title": "Web Source", "actif": True}])
        )
        # article JSON
        (proj / "data" / "articles" / "test.json").write_text(
            _articles_json(["Article Source"])
        )
        result = self._fn()(proj)
        assert "OPML Source" in result
        assert "Web Source" in result
        assert "Article Source" in result

    def test_filters_strings_shorter_than_2(self, tmp_path):
        """Les chaînes de longueur 0 ou 1 doivent être filtrées."""
        proj = self._make_project(tmp_path)
        (proj / "data" / "articles" / "short.json").write_text(
            json.dumps([{"Sources": "X", "URL": "https://a.com"},    # longueur 1 → filtré
                        {"Sources": "OK", "URL": "https://b.com"}])  # longueur 2 → gardé
        )
        result = self._fn()(proj)
        assert "X" not in result
        assert "OK" in result

    def test_deduplicates_sources(self, tmp_path):
        proj = self._make_project(tmp_path)
        (proj / "data" / "articles" / "dup1.json").write_text(
            _articles_json(["Le Monde"])
        )
        (proj / "data" / "articles-from-rss" / "dup2.json").write_text(
            _articles_json(["Le Monde"])
        )
        result = self._fn()(proj)
        # set — donc déjà dédupliqué ; juste vérifier présence et que pas de doublons
        assert "Le Monde" in result
        assert isinstance(result, set)

    def test_empty_project_returns_empty_set(self, tmp_path):
        proj = self._make_project(tmp_path)
        result = self._fn()(proj)
        assert result == set()
