"""Tests pour utils.report_cleanup — un seul rapport daté par genre."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils.report_cleanup import cleanup_old_dated_reports


def _touch(directory: Path, name: str) -> Path:
    p = directory / name
    p.write_text("x", encoding="utf-8")
    return p


def test_supprime_meme_genre_autres_dates(tmp_path):
    _touch(tmp_path, "cross_flux_2026-06-01.md")
    _touch(tmp_path, "cross_flux_2026-06-02.md")
    current = _touch(tmp_path, "cross_flux_2026-06-03.md")

    deleted = cleanup_old_dated_reports(current, verbose=False)

    assert {p.name for p in deleted} == {
        "cross_flux_2026-06-01.md",
        "cross_flux_2026-06-02.md",
    }
    assert current.exists()
    restants = sorted(p.name for p in tmp_path.iterdir())
    assert restants == ["cross_flux_2026-06-03.md"]


def test_ne_touche_pas_autres_genres(tmp_path):
    _touch(tmp_path, "digest_2026-06-02.md")
    _touch(tmp_path, "data-quality_2026-06-02.md")
    current = _touch(tmp_path, "cross_flux_2026-06-03.md")

    cleanup_old_dated_reports(current, verbose=False)

    noms = {p.name for p in tmp_path.iterdir()}
    assert noms == {
        "digest_2026-06-02.md",
        "data-quality_2026-06-02.md",
        "cross_flux_2026-06-03.md",
    }


def test_distingue_suffixe_litteral(tmp_path):
    # briefing daily ne doit pas supprimer briefing weekly
    weekly = _touch(tmp_path, "briefing_2026-06-01_weekly.md")
    _touch(tmp_path, "briefing_2026-06-02_daily.md")
    current = _touch(tmp_path, "briefing_2026-06-03_daily.md")

    deleted = cleanup_old_dated_reports(current, verbose=False)

    assert {p.name for p in deleted} == {"briefing_2026-06-02_daily.md"}
    assert weekly.exists()
    assert current.exists()


def test_distingue_prefixe_profil(tmp_path):
    # digest morning (digest_<date>) ne doit pas toucher digest_<profil>_<date>
    perso = _touch(tmp_path, "digest_macron_2026-06-03.md")
    _touch(tmp_path, "digest_2026-06-01.md")
    current = _touch(tmp_path, "digest_2026-06-03.md")

    deleted = cleanup_old_dated_reports(current, verbose=False)

    assert {p.name for p in deleted} == {"digest_2026-06-01.md"}
    assert perso.exists()
    assert current.exists()


def test_plage_de_dates(tmp_path):
    _touch(tmp_path, "radar_articles_generated_2026-04-01_2026-04-30.md")
    current = _touch(tmp_path, "radar_articles_generated_2026-05-01_2026-05-31.md")

    deleted = cleanup_old_dated_reports(current, verbose=False)

    assert {p.name for p in deleted} == {
        "radar_articles_generated_2026-04-01_2026-04-30.md"
    }
    assert current.exists()


def test_genres_mensuels_coexistants_meme_dossier(tmp_path):
    # generate_keyword_reports : <kw>_rapport_<plage>.md
    # articles_rss_to_markdown : <kw>_<plage>.md  (même dossier mot-clé)
    rss_old = _touch(tmp_path, "anthropic_2026-04-01_2026-04-30.md")
    rss_new = _touch(tmp_path, "anthropic_2026-05-01_2026-05-31.md")
    rapport_old = _touch(tmp_path, "anthropic_rapport_2026-04-01_2026-04-30.md")
    rapport_new = _touch(tmp_path, "anthropic_rapport_2026-05-01_2026-05-31.md")

    deleted_rss = cleanup_old_dated_reports(rss_new, verbose=False)
    deleted_rapport = cleanup_old_dated_reports(rapport_new, verbose=False)

    # Chaque genre ne supprime que SA propre série, pas l'autre.
    assert {p.name for p in deleted_rss} == {"anthropic_2026-04-01_2026-04-30.md"}
    assert {p.name for p in deleted_rapport} == {
        "anthropic_rapport_2026-04-01_2026-04-30.md"
    }
    assert rss_new.exists() and rapport_new.exists()
    assert not rss_old.exists() and not rapport_old.exists()


def test_nom_sans_date_ne_fait_rien(tmp_path):
    _touch(tmp_path, "rapport_48h.md")
    current = _touch(tmp_path, "notes_lecture.md")

    deleted = cleanup_old_dated_reports(current, verbose=False)

    assert deleted == []
    assert {p.name for p in tmp_path.iterdir()} == {"rapport_48h.md", "notes_lecture.md"}


def test_dry_run_ne_supprime_pas(tmp_path):
    old = _touch(tmp_path, "cross_flux_2026-06-01.md")
    current = _touch(tmp_path, "cross_flux_2026-06-03.md")

    deleted = cleanup_old_dated_reports(current, dry_run=True, verbose=False)

    assert {p.name for p in deleted} == {"cross_flux_2026-06-01.md"}
    assert old.exists()  # toujours présent en dry-run


def test_ignore_les_repertoires(tmp_path):
    (tmp_path / "cross_flux_2026-06-01.md").mkdir()  # répertoire homonyme improbable
    current = _touch(tmp_path, "cross_flux_2026-06-03.md")

    deleted = cleanup_old_dated_reports(current, verbose=False)

    assert deleted == []
    assert (tmp_path / "cross_flux_2026-06-01.md").is_dir()
