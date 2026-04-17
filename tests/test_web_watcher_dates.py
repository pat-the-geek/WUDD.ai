"""Tests pour le parsing de dates dans web_watcher.py (issue #61).

Vérifie que les dates des sites anglais (MM/DD/YYYY) et français (DD/MM/YYYY)
sont correctement interprétées selon la langue déclarée dans web_sources.json.
"""

import sys
from datetime import datetime
from pathlib import Path

import pytest

# S'assure que le répertoire racine du projet est dans le path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.web_watcher import _parse_date, _fmt_ddmmyyyy


class TestParseDateISO:
    """Les formats ISO 8601 doivent être reconnus quelle que soit la langue."""

    def test_iso_datetime_z(self):
        dt = _parse_date("2026-03-09T10:30:00Z")
        assert dt.year == 2026
        assert dt.month == 3
        assert dt.day == 9

    def test_iso_datetime_with_microseconds(self):
        dt = _parse_date("2026-03-09T10:30:00.000Z")
        assert dt.year == 2026
        assert dt.month == 3
        assert dt.day == 9

    def test_iso_date_only(self):
        dt = _parse_date("2026-03-09")
        assert dt.year == 2026
        assert dt.month == 3
        assert dt.day == 9

    def test_iso_datetime_no_tz(self):
        dt = _parse_date("2026-03-09T10:30:00")
        assert dt.year == 2026
        assert dt.month == 3
        assert dt.day == 9

    def test_iso_date_slash(self):
        """Format YYYY/MM/DD doit être reconnu comme ISO."""
        dt = _parse_date("2026/03/09")
        assert dt.year == 2026
        assert dt.month == 3
        assert dt.day == 9

    def test_iso_with_timezone_offset_stripped(self):
        dt = _parse_date("2026-03-09T10:30:00+01:00")
        assert dt.month == 3
        assert dt.day == 9

    def test_iso_langue_en_same_result(self):
        dt_en = _parse_date("2026-03-09", langue="en")
        dt_fr = _parse_date("2026-03-09", langue="fr")
        assert dt_en == dt_fr  # ISO non-ambigu : même résultat


class TestParseDateEnglish:
    """Sites anglais : MM/DD/YYYY doit être interprété comme mois/jour."""

    def test_mm_dd_yyyy_slash(self):
        """03/09/2026 en anglais = 9 mars 2026 (mm/dd/yyyy)."""
        dt = _parse_date("03/09/2026", langue="en")
        assert dt.month == 3   # mars
        assert dt.day == 9
        assert dt.year == 2026

    def test_mm_dd_yyyy_different_from_fr(self):
        """La même chaîne '09/03/2026' donne un résultat différent selon la langue."""
        dt_en = _parse_date("09/03/2026", langue="en")
        dt_fr = _parse_date("09/03/2026", langue="fr")
        # Anglais : mois=9 (septembre), jour=3
        assert dt_en.month == 9
        assert dt_en.day == 3
        # Français : jour=9, mois=3 (mars)
        assert dt_fr.month == 3
        assert dt_fr.day == 9

    def test_english_text_date_full_month(self):
        """'March 9, 2026' doit être parsé correctement pour un site anglais."""
        dt = _parse_date("March 9, 2026", langue="en")
        assert dt.month == 3
        assert dt.day == 9
        assert dt.year == 2026

    def test_english_text_date_abbr_month(self):
        """'Mar 9, 2026' doit être parsé correctement pour un site anglais."""
        dt = _parse_date("Mar 9, 2026", langue="en")
        assert dt.month == 3
        assert dt.day == 9

    def test_mm_dd_yyyy_dash(self):
        """03-09-2026 en anglais = 9 mars 2026."""
        dt = _parse_date("03-09-2026", langue="en")
        assert dt.month == 3
        assert dt.day == 9

    def test_empty_string_returns_now(self):
        dt = _parse_date("", langue="en")
        assert (datetime.now() - dt).total_seconds() < 30

    def test_invalid_string_returns_now(self):
        dt = _parse_date("not-a-date", langue="en")
        assert (datetime.now() - dt).total_seconds() < 30


class TestParseDateFrench:
    """Sites français : DD/MM/YYYY doit être interprété comme jour/mois."""

    def test_dd_mm_yyyy_slash(self):
        """03/09/2026 en français = 3 septembre 2026 (dd/mm/yyyy)."""
        dt = _parse_date("03/09/2026", langue="fr")
        assert dt.day == 3
        assert dt.month == 9   # septembre
        assert dt.year == 2026

    def test_dd_mm_yyyy_dash(self):
        """09-03-2026 en français = 9 mars 2026."""
        dt = _parse_date("09-03-2026", langue="fr")
        assert dt.day == 9
        assert dt.month == 3

    def test_dd_mm_yyyy_dot(self):
        """09.03.2026 en français = 9 mars 2026."""
        dt = _parse_date("09.03.2026", langue="fr")
        assert dt.day == 9
        assert dt.month == 3

    def test_empty_string_returns_now(self):
        dt = _parse_date("", langue="fr")
        assert (datetime.now() - dt).total_seconds() < 30


class TestFmtDdMmYyyy:
    """Vérifie que _fmt_ddmmyyyy formate correctement en JJ/MM/AAAA."""

    def test_format_march_9(self):
        dt = datetime(2026, 3, 9)
        assert _fmt_ddmmyyyy(dt) == "09/03/2026"

    def test_format_september_3(self):
        dt = datetime(2026, 9, 3)
        assert _fmt_ddmmyyyy(dt) == "03/09/2026"


class TestIssue61Scenario:
    """Scénario exact de l'issue #61 :
    Un site anglais publie une date '03/09/2026' (= 9 mars en mm/dd/yyyy).
    Le système NE doit PAS créer un article daté du 03/09/2026 (3 septembre).
    Il doit créer un article daté du 09/03/2026 (9 mars).
    """

    def test_english_site_march_date_not_september(self):
        """Un site anglais avec '03/09/2026' doit donner 09/03/2026 (mars)."""
        raw_date = "03/09/2026"  # Sur un site anglais = 9 mars 2026
        dt = _parse_date(raw_date, langue="en")
        formatted = _fmt_ddmmyyyy(dt)
        # Doit être mars (mois 03), pas septembre (mois 09)
        assert dt.month == 3, f"Mois attendu : 3 (mars), obtenu : {dt.month}"
        assert formatted == "09/03/2026", (
            f"Date formatée attendue : 09/03/2026, obtenue : {formatted}"
        )

    def test_french_site_september_date_correct(self):
        """Un site français avec '03/09/2026' doit rester 03/09/2026 (septembre)."""
        raw_date = "03/09/2026"  # Sur un site français = 3 septembre 2026
        dt = _parse_date(raw_date, langue="fr")
        formatted = _fmt_ddmmyyyy(dt)
        assert dt.month == 9, f"Mois attendu : 9 (septembre), obtenu : {dt.month}"
        assert formatted == "03/09/2026"

    def test_default_langue_is_english(self):
        """Pas de langue spécifiée → comportement anglais par défaut."""
        dt_default = _parse_date("03/09/2026")
        dt_en = _parse_date("03/09/2026", langue="en")
        assert dt_default.month == dt_en.month
        assert dt_default.day == dt_en.day
