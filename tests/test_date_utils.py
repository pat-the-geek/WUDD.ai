"""Tests pour le module date_utils.

Ces tests démontrent comment tester les utilitaires du projet.
Pour exécuter: pytest tests/test_date_utils.py -v
"""

import pytest
from datetime import datetime
from utils.date_utils import (
    parse_iso_date,
    parse_simple_date,
    verifier_date_entre,
    get_default_date_range,
    validate_date_range,
    parse_article_date,
)


class TestParseIsoDate:
    """Tests pour parse_iso_date()."""
    
    def test_parse_valid_iso_date(self):
        """Test parsing d'une date ISO 8601 valide."""
        result = parse_iso_date("2026-01-24T10:30:00Z")
        
        assert result is not None
        assert isinstance(result, datetime)
        assert result.year == 2026
        assert result.month == 1
        assert result.day == 24
        assert result.hour == 10
        assert result.minute == 30
    
    def test_parse_invalid_iso_date(self):
        """Test parsing d'une date ISO invalide."""
        result = parse_iso_date("2026-01-24")  # Format incorrect
        assert result is None
    
    def test_parse_empty_string(self):
        """Test parsing d'une chaîne vide."""
        result = parse_iso_date("")
        assert result is None
    
    def test_parse_malformed_date(self):
        """Test parsing d'une date mal formée."""
        result = parse_iso_date("not-a-date")
        assert result is None


class TestParseSimpleDate:
    """Tests pour parse_simple_date()."""
    
    def test_parse_valid_simple_date(self):
        """Test parsing d'une date simple valide."""
        result = parse_simple_date("2026-01-24")
        
        assert result is not None
        assert isinstance(result, datetime)
        assert result.year == 2026
        assert result.month == 1
        assert result.day == 24
    
    def test_parse_invalid_simple_date(self):
        """Test parsing d'une date simple invalide."""
        result = parse_simple_date("24/01/2026")  # Format incorrect
        assert result is None
    
    def test_parse_invalid_month(self):
        """Test parsing d'une date avec mois invalide."""
        result = parse_simple_date("2026-13-01")  # Mois 13 n'existe pas
        assert result is None


class TestVerifierDateEntre:
    """Tests pour verifier_date_entre()."""
    
    def test_date_dans_intervalle(self):
        """Test date dans l'intervalle."""
        assert verifier_date_entre("2026-01-15", "2026-01-01", "2026-01-31") is True
    
    def test_date_debut_intervalle(self):
        """Test date égale à la borne début."""
        assert verifier_date_entre("2026-01-01", "2026-01-01", "2026-01-31") is True
    
    def test_date_fin_intervalle(self):
        """Test date égale à la borne fin."""
        assert verifier_date_entre("2026-01-31", "2026-01-01", "2026-01-31") is True
    
    def test_date_avant_intervalle(self):
        """Test date avant l'intervalle."""
        assert verifier_date_entre("2025-12-31", "2026-01-01", "2026-01-31") is False
    
    def test_date_apres_intervalle(self):
        """Test date après l'intervalle."""
        assert verifier_date_entre("2026-02-01", "2026-01-01", "2026-01-31") is False
    
    def test_date_invalide(self):
        """Test avec date invalide."""
        assert verifier_date_entre("invalid", "2026-01-01", "2026-01-31") is False


class TestGetDefaultDateRange:
    """Tests pour get_default_date_range()."""
    
    def test_returns_tuple(self):
        """Test que la fonction retourne un tuple."""
        result = get_default_date_range()
        assert isinstance(result, tuple)
        assert len(result) == 2
    
    def test_dates_are_strings(self):
        """Test que les dates sont des strings."""
        debut, fin = get_default_date_range()
        assert isinstance(debut, str)
        assert isinstance(fin, str)
    
    def test_date_format(self):
        """Test que les dates sont au format YYYY-MM-DD."""
        debut, fin = get_default_date_range()
        # Vérifier qu'on peut parser les dates
        assert parse_simple_date(debut) is not None
        assert parse_simple_date(fin) is not None
    
    def test_debut_is_first_of_month(self):
        """Test que la date de début est le 1er du mois."""
        debut, _ = get_default_date_range()
        assert debut.endswith("-01")  # Se termine par -01 (1er du mois)
    
    def test_fin_is_today_or_later(self):
        """Test que la date de fin est >= date de début."""
        debut, fin = get_default_date_range()
        date_debut = parse_simple_date(debut)
        date_fin = parse_simple_date(fin)
        assert date_fin >= date_debut


class TestValidateDateRange:
    """Tests pour validate_date_range()."""
    
    def test_valid_date_range(self):
        """Test plage de dates valide."""
        assert validate_date_range("2026-01-01", "2026-01-31") is True
    
    def test_invalid_date_format(self):
        """Test avec format de date invalide."""
        with pytest.raises(ValueError, match="Format de date invalide"):
            validate_date_range("01/01/2026", "31/01/2026")
    
    def test_debut_after_fin(self):
        """Test date début après date fin."""
        with pytest.raises(ValueError, match="date de début doit être antérieure"):
            validate_date_range("2026-01-31", "2026-01-01")
    
    def test_same_dates(self):
        """Test dates identiques."""
        with pytest.raises(ValueError, match="date de début doit être antérieure"):
            validate_date_range("2026-01-15", "2026-01-15")


# Tests paramétrés pour plus de couverture
@pytest.mark.parametrize("date_str,expected_year,expected_month,expected_day", [
    ("2026-01-24", 2026, 1, 24),
    ("2025-12-31", 2025, 12, 31),
    ("2026-02-28", 2026, 2, 28),
    ("2024-02-29", 2024, 2, 29),  # Année bissextile
])
def test_parse_simple_date_parametrized(date_str, expected_year, expected_month, expected_day):
    """Test parsing de dates avec paramètres."""
    result = parse_simple_date(date_str)
    assert result is not None
    assert result.year == expected_year
    assert result.month == expected_month
    assert result.day == expected_day


@pytest.mark.parametrize("date,debut,fin,expected", [
    ("2026-01-15", "2026-01-01", "2026-01-31", True),
    ("2026-01-01", "2026-01-01", "2026-01-31", True),
    ("2026-01-31", "2026-01-01", "2026-01-31", True),
    ("2025-12-31", "2026-01-01", "2026-01-31", False),
    ("2026-02-01", "2026-01-01", "2026-01-31", False),
])
def test_verifier_date_entre_parametrized(date, debut, fin, expected):
    """Test vérification de dates avec paramètres."""
    assert verifier_date_entre(date, debut, fin) == expected


# ── Tests parse_article_date (proposition 4) ──────────────────────────────────

class TestParseArticleDate:
    """Tests pour parse_article_date() — parser multi-format centralisé."""

    def test_ddmmyyyy(self):
        dt = parse_article_date("15/03/2026")
        assert dt is not None
        assert dt.day == 15
        assert dt.month == 3
        assert dt.year == 2026

    def test_iso_date_only(self):
        dt = parse_article_date("2026-03-15")
        assert dt is not None
        assert dt.year == 2026
        assert dt.month == 3
        assert dt.day == 15

    def test_iso_date_only_end_of_day_policy(self):
        dt = parse_article_date("2026-03-15", date_only_policy="end")
        assert dt is not None
        assert dt.hour == 23
        assert dt.minute == 59
        assert dt.second == 59

    def test_iso_datetime_z(self):
        dt = parse_article_date("2026-03-15T10:30:00Z")
        assert dt is not None
        assert dt.hour == 10
        assert dt.minute == 30

    def test_iso_datetime_no_z(self):
        dt = parse_article_date("2026-03-15T08:00:00")
        assert dt is not None
        assert dt.hour == 8

    def test_rfc822(self):
        dt = parse_article_date("Mon, 15 Mar 2026 10:30:00 +0000")
        assert dt is not None
        assert dt.year == 2026
        assert dt.month == 3
        assert dt.day == 15

    def test_empty_string(self):
        assert parse_article_date("") is None

    def test_none_input(self):
        assert parse_article_date(None) is None

    def test_invalid_format(self):
        assert parse_article_date("not-a-date") is None

    def test_leading_trailing_spaces(self):
        dt = parse_article_date("  2026-03-15  ")
        assert dt is not None
        assert dt.year == 2026

    def test_returns_datetime(self):
        dt = parse_article_date("15/03/2026")
        assert isinstance(dt, datetime)
