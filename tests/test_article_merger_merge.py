"""Tests pour les helpers de fusion dans utils/article_merger.py.

Couvre :
- _merge_entities          : union déduplicatée des entités
- _select_primary          : sélection source principale
- _build_combined_resume   : construction résumé multi-sources
- _get_obsidian_note_name  : extraction nom note Obsidian
- _update_obsidian_note    : modification de note (fichier)
- _archive_articles        : archivage des secondaires
- _remove_urls_from_all_files : suppression d'URLs dans les fichiers
- _insert_merged_into_primary : insertion en tête du fichier
- _update_all_48h_files    : mise à jour 48-heures.json
- execute_merge            : intégration
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest


# ═════════════════════════════════════════════════════════════════════════════
# Fixtures et helpers
# ═════════════════════════════════════════════════════════════════════════════

def _make_article(url="https://a.com/1", sources="AFP", date="2026-03-06T10:00:00Z",
                  resume="Un résumé de longueur suffisante pour les tests de fusion.",
                  entities=None, score_source=70, images=None):
    a = {
        "URL": url,
        "Sources": sources,
        "Date de publication": date,
        "Résumé": resume,
        "score_source": score_source,
    }
    if entities is not None:
        a["entities"] = entities
    if images is not None:
        a["Images"] = images
    return a


# ═════════════════════════════════════════════════════════════════════════════
# _merge_entities
# ═════════════════════════════════════════════════════════════════════════════

class TestMergeEntities:
    def _fn(self):
        from utils.article_merger import _merge_entities
        return _merge_entities

    def test_empty_list_returns_empty_dict(self):
        assert self._fn()([]) == {}

    def test_single_article_entities_preserved(self):
        articles = [_make_article(entities={"PERSON": ["Alice"], "ORG": ["OpenAI"]})]
        result = self._fn()(articles)
        assert result["PERSON"] == ["Alice"]
        assert result["ORG"] == ["OpenAI"]

    def test_union_deduplication_across_articles(self):
        a1 = _make_article(entities={"PERSON": ["Alice", "Bob"]})
        a2 = _make_article(entities={"PERSON": ["Bob", "Charlie"]})
        result = self._fn()([a1, a2])
        assert sorted(result["PERSON"]) == ["Alice", "Bob", "Charlie"]

    def test_multiple_types_merged(self):
        a1 = _make_article(entities={"PERSON": ["Alice"], "ORG": ["OpenAI"]})
        a2 = _make_article(entities={"PERSON": ["Bob"], "GPE": ["France"]})
        result = self._fn()([a1, a2])
        assert "Alice" in result["PERSON"]
        assert "Bob" in result["PERSON"]
        assert result["ORG"] == ["OpenAI"]
        assert result["GPE"] == ["France"]

    def test_article_without_entities_skipped(self):
        a1 = _make_article()  # no entities
        a2 = _make_article(entities={"PERSON": ["Alice"]})
        result = self._fn()([a1, a2])
        assert result["PERSON"] == ["Alice"]

    def test_all_articles_without_entities(self):
        articles = [_make_article(), _make_article(url="https://b.com")]
        assert self._fn()(articles) == {}

    def test_non_list_entity_values_skipped(self):
        a = _make_article(entities={"PERSON": "not-a-list", "ORG": ["ValidOrg"]})
        result = self._fn()([a])
        assert "PERSON" not in result
        assert result.get("ORG") == ["ValidOrg"]


# ═════════════════════════════════════════════════════════════════════════════
# _select_primary
# ═════════════════════════════════════════════════════════════════════════════

class TestSelectPrimary:
    def _fn(self):
        from utils.article_merger import _select_primary
        return _select_primary

    def test_single_article_selected(self):
        a = _make_article()
        assert self._fn()([a]) is a

    def test_higher_score_source_wins(self):
        low = _make_article(url="https://a.com", score_source=40)
        high = _make_article(url="https://b.com", score_source=90)
        assert self._fn()([low, high]) is high

    def test_completeness_breaks_tie_resume_length(self):
        short = _make_article(url="https://a.com", resume="Court.", score_source=70)
        long_a = _make_article(url="https://b.com", resume="x" * 200, score_source=70)
        assert self._fn()([short, long_a]) is long_a

    def test_completeness_images_bonus(self):
        no_img = _make_article(url="https://a.com", score_source=70)
        with_img = _make_article(url="https://b.com", score_source=70,
                                  images=[{"url": "https://img.com/photo.jpg"}])
        result = self._fn()([no_img, with_img])
        assert result is with_img

    def test_completeness_entities_bonus(self):
        no_ent = _make_article(url="https://a.com", score_source=70)
        with_ent = _make_article(url="https://b.com", score_source=70,
                                  entities={"PERSON": ["Alice"]})
        result = self._fn()([no_ent, with_ent])
        assert result is with_ent

    def test_most_recent_date_breaks_tie(self):
        old = _make_article(url="https://a.com", score_source=70, date="2026-03-01T00:00:00Z")
        new = _make_article(url="https://b.com", score_source=70, date="2026-03-06T00:00:00Z")
        assert self._fn()([old, new]) is new


# ═════════════════════════════════════════════════════════════════════════════
# _build_combined_resume
# ═════════════════════════════════════════════════════════════════════════════

class TestBuildCombinedResume:
    def _fn(self):
        from utils.article_merger import _build_combined_resume
        return _build_combined_resume

    def test_empty_list_returns_empty_string(self):
        assert self._fn()([]) == ""

    def test_single_article_includes_header(self):
        a = _make_article(sources="Le Monde", date="2026-03-06T10:00:00Z",
                          resume="Le texte du résumé.")
        result = self._fn()([a])
        assert "[Le Monde" in result
        assert "2026-03-06T10:00:00Z" in result
        assert "Le texte du résumé." in result

    def test_multiple_articles_all_included(self):
        a1 = _make_article(sources="AFP", resume="Résumé AFP.")
        a2 = _make_article(url="https://b.com", sources="BFMTV", resume="Résumé BFMTV.")
        result = self._fn()([a1, a2])
        assert "AFP" in result
        assert "BFMTV" in result
        assert "Résumé AFP." in result
        assert "Résumé BFMTV." in result

    def test_articles_separated_by_double_newline(self):
        a1 = _make_article(resume="Un.")
        a2 = _make_article(url="b", resume="Deux.")
        result = self._fn()([a1, a2])
        assert "\n\n" in result

    def test_article_without_resume_skipped(self):
        a1 = _make_article(resume="")
        a2 = _make_article(url="b", resume="Avec résumé.")
        result = self._fn()([a1, a2])
        assert "Avec résumé." in result
        # Should only have one block in the result
        assert "[" in result


# ═════════════════════════════════════════════════════════════════════════════
# _get_obsidian_note_name
# ═════════════════════════════════════════════════════════════════════════════

class TestGetObsidianNoteName:
    def _fn(self):
        from utils.article_merger import _get_obsidian_note_name
        return _get_obsidian_note_name

    def test_returns_stem_from_obsidian_rapport(self):
        article = {
            "rapports": [
                {"cible": "obsidian", "fichier": "2026-03-06 Titre de la note.md"}
            ]
        }
        result = self._fn()(article)
        assert result == "2026-03-06 Titre de la note"

    def test_ignores_non_obsidian_rapports(self):
        article = {
            "_fusion": {},
            "Sources": "Mon Article",
            "rapports": [
                {"cible": "pdf", "fichier": "note.pdf"},
            ],
        }
        result = self._fn()(article)
        # Falls back to Sources
        assert "Mon Article" in result

    def test_fallback_to_titre_field(self):
        article = {"Titre": "L'Intelligence Artificielle en 2026"}
        result = self._fn()(article)
        assert "Intelligence Artificielle" in result

    def test_fallback_to_sources_when_no_titre(self):
        article = {"Sources": "Le Monde"}
        result = self._fn()(article)
        assert "Le Monde" in result

    def test_default_fallback_no_fields(self):
        article = {}
        result = self._fn()(article)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_max_length_60(self):
        article = {"Sources": "x" * 100}
        result = self._fn()(article)
        assert len(result) <= 60


# ═════════════════════════════════════════════════════════════════════════════
# _update_obsidian_note
# ═════════════════════════════════════════════════════════════════════════════

class TestUpdateObsidianNote:
    def _fn(self):
        from utils.article_merger import _update_obsidian_note
        return _update_obsidian_note

    def test_missing_chemin_returns_false(self):
        assert self._fn()({"fichier": "note.md"}, "merged-note") is False

    def test_missing_fichier_returns_false(self):
        assert self._fn()({"chemin": "/tmp"}, "merged-note") is False

    def test_nonexistent_file_returns_false(self, tmp_path):
        rapport = {"chemin": str(tmp_path), "fichier": "nonexistent.md"}
        assert self._fn()(rapport, "merged note") is False

    def test_existing_file_gets_mention(self, tmp_path):
        note = tmp_path / "note.md"
        note.write_text("# Contenu original\n", encoding="utf-8")
        rapport = {"chemin": str(tmp_path), "fichier": "note.md"}
        result = self._fn()(rapport, "Note Fusionnée")
        assert result is True
        content = note.read_text(encoding="utf-8")
        assert "Fusionné dans" in content  # capital F dans le template
        assert "Note Fusionnée" in content

    def test_mention_not_duplicated(self, tmp_path):
        note = tmp_path / "note.md"
        note.write_text("fusionné dans [[autre note]]\n\n# Contenu\n", encoding="utf-8")
        rapport = {"chemin": str(tmp_path), "fichier": "note.md"}
        result = self._fn()(rapport, "Note Fusionnée")
        assert result is False
        # Content should be unchanged
        assert "fusionné dans" in note.read_text(encoding="utf-8")

    def test_mention_prepended_to_note(self, tmp_path):
        note = tmp_path / "note.md"
        original = "# Titre\n\nContenu de la note."
        note.write_text(original, encoding="utf-8")
        rapport = {"chemin": str(tmp_path), "fichier": "note.md"}
        self._fn()(rapport, "Note Principale")
        content = note.read_text(encoding="utf-8")
        # Mention should be at the start
        assert content.startswith("> [!note] Article fusionné")


# ═════════════════════════════════════════════════════════════════════════════
# _archive_articles
# ═════════════════════════════════════════════════════════════════════════════

class TestArchiveArticles:
    def _fn(self):
        from utils.article_merger import _archive_articles
        return _archive_articles

    def _make_meta(self, url="https://b.com", file_path="data/articles/kb/f.json"):
        return [{"article": _make_article(url=url), "file_path": file_path, "score": 0.75}]

    def test_creates_archive_file(self, tmp_path):
        primary = tmp_path / "data" / "articles" / "flux" / "articles.json"
        primary.parent.mkdir(parents=True)
        primary.write_text("[]", encoding="utf-8")
        merged = _make_article(url="https://merged.com")
        archive_path = self._fn()(self._make_meta(), merged, primary, tmp_path)
        assert archive_path.exists()

    def test_archive_contains_fusion_entry(self, tmp_path):
        primary = tmp_path / "data" / "articles" / "flux" / "articles.json"
        primary.parent.mkdir(parents=True)
        primary.write_text("[]", encoding="utf-8")
        merged = _make_article(url="https://merged.com")
        archive_path = self._fn()(self._make_meta(), merged, primary, tmp_path)
        data = json.loads(archive_path.read_text(encoding="utf-8"))
        assert len(data["fusions"]) == 1
        assert "url_article_fusionné" in data["fusions"][0]

    def test_cumulative_archive(self, tmp_path):
        """Deux fusions successives → deux entrées dans le fichier."""
        primary = tmp_path / "data" / "articles" / "flux" / "articles.json"
        primary.parent.mkdir(parents=True)
        primary.write_text("[]", encoding="utf-8")

        merged1 = _make_article(url="https://merged1.com")
        merged2 = _make_article(url="https://merged2.com")
        self._fn()(self._make_meta("https://b.com"), merged1, primary, tmp_path)
        archive_path = self._fn()(self._make_meta("https://c.com"), merged2, primary, tmp_path)
        data = json.loads(archive_path.read_text(encoding="utf-8"))
        assert len(data["fusions"]) == 2

    def test_archive_created_in_merged_subdirectory(self, tmp_path):
        primary = tmp_path / "data" / "flux" / "articles.json"
        primary.parent.mkdir(parents=True)
        primary.write_text("[]", encoding="utf-8")
        merged = _make_article(url="https://merged.com")
        archive_path = self._fn()(self._make_meta(), merged, primary, tmp_path)
        assert archive_path.parent.name == "merged"


# ═════════════════════════════════════════════════════════════════════════════
# _remove_urls_from_all_files
# ═════════════════════════════════════════════════════════════════════════════

class TestRemoveUrlsFromAllFiles:
    def _fn(self):
        from utils.article_merger import _remove_urls_from_all_files
        return _remove_urls_from_all_files

    def test_removes_matching_url(self, tmp_path):
        articles_dir = tmp_path / "data" / "articles" / "flux"
        articles_dir.mkdir(parents=True)
        data = [_make_article(url="https://remove-me.com"), _make_article(url="https://keep-me.com")]
        json_file = articles_dir / "articles.json"
        json_file.write_text(json.dumps(data), encoding="utf-8")

        count = self._fn()({"https://remove-me.com"}, tmp_path)
        assert count == 1
        remaining = json.loads(json_file.read_text(encoding="utf-8"))
        assert len(remaining) == 1
        assert remaining[0]["URL"] == "https://keep-me.com"

    def test_file_not_modified_when_no_match(self, tmp_path):
        articles_dir = tmp_path / "data" / "articles" / "flux"
        articles_dir.mkdir(parents=True)
        data = [_make_article(url="https://keep-me.com")]
        json_file = articles_dir / "articles.json"
        json_file.write_text(json.dumps(data), encoding="utf-8")

        count = self._fn()({"https://not-present.com"}, tmp_path)
        assert count == 0

    def test_handles_multiple_files(self, tmp_path):
        for i, flux in enumerate(["flux1", "flux2"]):
            d = tmp_path / "data" / "articles" / flux
            d.mkdir(parents=True)
            (d / "articles.json").write_text(
                json.dumps([_make_article(url=f"https://remove-{i}.com")]),
                encoding="utf-8",
            )

        urls = {"https://remove-0.com", "https://remove-1.com"}
        count = self._fn()(urls, tmp_path)
        assert count == 2

    def test_ignored_cache_files(self, tmp_path):
        cache_dir = tmp_path / "data" / "articles" / "flux" / "cache"
        cache_dir.mkdir(parents=True)
        data = [_make_article(url="https://remove-me.com")]
        (cache_dir / "cached.json").write_text(json.dumps(data), encoding="utf-8")

        count = self._fn()({"https://remove-me.com"}, tmp_path)
        # cache directory should be excluded
        assert count == 0

    def test_empty_file_handled_gracefully(self, tmp_path):
        articles_dir = tmp_path / "data" / "articles" / "flux"
        articles_dir.mkdir(parents=True)
        (articles_dir / "empty.json").write_text("[]", encoding="utf-8")
        count = self._fn()({"https://any.com"}, tmp_path)
        assert count == 0


# ═════════════════════════════════════════════════════════════════════════════
# _insert_merged_into_primary
# ═════════════════════════════════════════════════════════════════════════════

class TestInsertMergedIntoPrimary:
    def _fn(self):
        from utils.article_merger import _insert_merged_into_primary
        return _insert_merged_into_primary

    def test_inserts_at_beginning(self, tmp_path):
        existing = [_make_article(url="https://existing.com")]
        json_file = tmp_path / "articles.json"
        json_file.write_text(json.dumps(existing), encoding="utf-8")

        merged = _make_article(url="https://merged.com")
        self._fn()(merged, json_file)
        result = json.loads(json_file.read_text(encoding="utf-8"))
        assert len(result) == 2
        assert result[0]["URL"] == "https://merged.com"

    def test_removes_duplicate_url(self, tmp_path):
        merged_url = "https://merged.com"
        existing = [_make_article(url=merged_url)]
        json_file = tmp_path / "articles.json"
        json_file.write_text(json.dumps(existing), encoding="utf-8")

        merged = _make_article(url=merged_url, resume="Nouveau résumé fusionné plus long.")
        self._fn()(merged, json_file)
        result = json.loads(json_file.read_text(encoding="utf-8"))
        assert len(result) == 1
        assert result[0]["Résumé"] == "Nouveau résumé fusionné plus long."

    def test_handles_empty_file(self, tmp_path):
        json_file = tmp_path / "articles.json"
        json_file.write_text("[]", encoding="utf-8")
        merged = _make_article(url="https://merged.com")
        self._fn()(merged, json_file)
        result = json.loads(json_file.read_text(encoding="utf-8"))
        assert len(result) == 1

    def test_handles_invalid_json_gracefully(self, tmp_path):
        json_file = tmp_path / "articles.json"
        json_file.write_text("not json", encoding="utf-8")
        merged = _make_article(url="https://merged.com")
        self._fn()(merged, json_file)
        result = json.loads(json_file.read_text(encoding="utf-8"))
        assert len(result) == 1


# ═════════════════════════════════════════════════════════════════════════════
# _update_all_48h_files
# ═════════════════════════════════════════════════════════════════════════════

class TestUpdateAll48hFiles:
    def _fn(self):
        from utils.article_merger import _update_all_48h_files
        return _update_all_48h_files

    def test_removes_secondary_urls(self, tmp_path):
        wudd_dir = tmp_path / "data" / "articles-from-rss" / "_WUDD.AI_"
        wudd_dir.mkdir(parents=True)
        now = datetime.now(timezone.utc)
        articles = [
            _make_article(url="https://secondary.com",
                          date=now.strftime("%Y-%m-%dT%H:%M:%SZ")),
            _make_article(url="https://keep.com",
                          date=now.strftime("%Y-%m-%dT%H:%M:%SZ")),
        ]
        (wudd_dir / "48-heures.json").write_text(json.dumps(articles), encoding="utf-8")

        merged = _make_article(url="https://merged.com",
                               date=now.strftime("%Y-%m-%dT%H:%M:%SZ"))
        self._fn()(tmp_path, {"https://secondary.com"}, merged)

        result = json.loads((wudd_dir / "48-heures.json").read_text(encoding="utf-8"))
        urls = [a["URL"] for a in result]
        assert "https://secondary.com" not in urls
        assert "https://keep.com" in urls

    def test_inserts_merged_when_in_window(self, tmp_path):
        wudd_dir = tmp_path / "data" / "articles-from-rss" / "_WUDD.AI_"
        wudd_dir.mkdir(parents=True)
        (wudd_dir / "48-heures.json").write_text("[]", encoding="utf-8")

        now = datetime.now(timezone.utc)
        merged = _make_article(url="https://merged.com",
                               date=now.strftime("%Y-%m-%dT%H:%M:%SZ"))
        self._fn()(tmp_path, set(), merged)

        result = json.loads((wudd_dir / "48-heures.json").read_text(encoding="utf-8"))
        assert any(a["URL"] == "https://merged.com" for a in result)

    def test_does_not_insert_merged_when_old(self, tmp_path):
        wudd_dir = tmp_path / "data" / "articles-from-rss" / "_WUDD.AI_"
        wudd_dir.mkdir(parents=True)
        (wudd_dir / "48-heures.json").write_text("[]", encoding="utf-8")

        old_date = (datetime.now(timezone.utc) - timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
        merged = _make_article(url="https://old-merged.com", date=old_date)
        self._fn()(tmp_path, set(), merged)

        result = json.loads((wudd_dir / "48-heures.json").read_text(encoding="utf-8"))
        assert not any(a["URL"] == "https://old-merged.com" for a in result)

    def test_sorted_by_date_descending(self, tmp_path):
        wudd_dir = tmp_path / "data" / "articles-from-rss" / "_WUDD.AI_"
        wudd_dir.mkdir(parents=True)
        articles = [
            _make_article(url="https://old.com", date="2026-03-01T00:00:00Z"),
            _make_article(url="https://new.com", date="2026-03-06T00:00:00Z"),
        ]
        (wudd_dir / "48-heures.json").write_text(json.dumps(articles), encoding="utf-8")

        merged = _make_article(url="https://merged.com",
                               date=(datetime.now(timezone.utc) - timedelta(minutes=1))
                               .strftime("%Y-%m-%dT%H:%M:%SZ"))
        self._fn()(tmp_path, set(), merged)

        result = json.loads((wudd_dir / "48-heures.json").read_text(encoding="utf-8"))
        dates = [a["Date de publication"] for a in result]
        assert dates == sorted(dates, reverse=True)


# ═════════════════════════════════════════════════════════════════════════════
# execute_merge — intégration
# ═════════════════════════════════════════════════════════════════════════════

class TestExecuteMerge:
    def _setup_project(self, tmp_path):
        """Crée un projet minimal dans tmp_path."""
        flux_dir = tmp_path / "data" / "articles" / "test-flux"
        flux_dir.mkdir(parents=True)
        return flux_dir

    def test_returns_merged_article(self, tmp_path):
        from utils.article_merger import execute_merge
        flux_dir = self._setup_project(tmp_path)

        source = _make_article(url="https://primary.com", sources="Le Monde",
                               score_source=85,
                               entities={"PERSON": ["Alice"]},
                               resume="Résumé complet de l'article principal très détaillé.")
        secondary = _make_article(url="https://secondary.com", sources="AFP",
                                  score_source=70)
        source_file = flux_dir / "articles.json"
        source_file.write_text(json.dumps([source, secondary]), encoding="utf-8")

        secondary_meta = [
            {"article": secondary, "file_path": f"data/articles/test-flux/articles.json", "score": 0.7}
        ]
        result = execute_merge(
            source,
            "data/articles/test-flux/articles.json",
            secondary_meta,
            tmp_path,
            synthesis="Synthèse IA de l'événement.",
        )

        assert "merged_article" in result
        assert result["merged_article"]["Résumé"] == "Synthèse IA de l'événement."

    def test_returns_correct_keys(self, tmp_path):
        from utils.article_merger import execute_merge
        flux_dir = self._setup_project(tmp_path)

        source = _make_article(url="https://primary.com", score_source=90,
                               resume="Résumé principal assez long pour les tests.")
        source_file = flux_dir / "articles.json"
        source_file.write_text(json.dumps([source]), encoding="utf-8")

        result = execute_merge(source, "data/articles/test-flux/articles.json", [], tmp_path)
        expected_keys = {"merged_article", "archive_path", "obsidian_updated", "primary_source", "secondaries_count"}
        assert expected_keys <= set(result.keys())

    def test_secondaries_removed_from_file(self, tmp_path):
        from utils.article_merger import execute_merge
        flux_dir = self._setup_project(tmp_path)

        primary = _make_article(url="https://primary.com", score_source=90,
                                resume="Résumé primaire complet et détaillé.",
                                entities={"PERSON": ["Alice"]})
        secondary = _make_article(url="https://secondary.com", score_source=50)
        source_file = flux_dir / "articles.json"
        source_file.write_text(json.dumps([primary, secondary]), encoding="utf-8")

        secondary_meta = [
            {"article": secondary, "file_path": "data/articles/test-flux/articles.json", "score": 0.8}
        ]
        execute_merge(primary, "data/articles/test-flux/articles.json", secondary_meta, tmp_path)

        remaining = json.loads(source_file.read_text(encoding="utf-8"))
        urls = [a["URL"] for a in remaining]
        assert "https://secondary.com" not in urls

    def test_merged_article_inserted_into_primary_file(self, tmp_path):
        from utils.article_merger import execute_merge
        flux_dir = self._setup_project(tmp_path)

        primary = _make_article(url="https://primary.com", score_source=90,
                                resume="Résumé principal complet et suffisamment long.")
        secondary = _make_article(url="https://secondary.com", score_source=50)
        source_file = flux_dir / "articles.json"
        source_file.write_text(json.dumps([primary, secondary]), encoding="utf-8")

        execute_merge(
            primary,
            "data/articles/test-flux/articles.json",
            [{"article": secondary, "file_path": "data/articles/test-flux/articles.json", "score": 0.7}],
            tmp_path,
        )

        remaining = json.loads(source_file.read_text(encoding="utf-8"))
        assert len(remaining) >= 1
        assert remaining[0].get("_fusion", {}).get("est_article_fusionné") is True

    def test_entities_merged_in_result(self, tmp_path):
        from utils.article_merger import execute_merge
        flux_dir = self._setup_project(tmp_path)

        primary = _make_article(url="https://primary.com", score_source=90,
                                entities={"PERSON": ["Alice"]},
                                resume="Résumé complet avec les entités nommées.")
        secondary = _make_article(url="https://secondary.com", score_source=60,
                                  entities={"PERSON": ["Bob"], "ORG": ["OpenAI"]})
        source_file = flux_dir / "articles.json"
        source_file.write_text(json.dumps([primary, secondary]), encoding="utf-8")

        result = execute_merge(
            primary,
            "data/articles/test-flux/articles.json",
            [{"article": secondary, "file_path": "data/articles/test-flux/articles.json", "score": 0.75}],
            tmp_path,
        )

        entities = result["merged_article"]["entities"]
        assert "Alice" in entities.get("PERSON", [])
        assert "Bob" in entities.get("PERSON", [])
        assert "OpenAI" in entities.get("ORG", [])

    def test_no_secondaries_works(self, tmp_path):
        from utils.article_merger import execute_merge
        flux_dir = self._setup_project(tmp_path)

        source = _make_article(url="https://primary.com", score_source=80,
                               resume="Résumé du seul article à fusionner.")
        source_file = flux_dir / "articles.json"
        source_file.write_text(json.dumps([source]), encoding="utf-8")

        result = execute_merge(source, "data/articles/test-flux/articles.json", [], tmp_path)
        assert result["secondaries_count"] == 0
