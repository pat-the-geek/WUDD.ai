"""Module utilitaires pour la manipulation des dates.

Fournit des fonctions pour parser, valider et comparer des dates
dans différents formats.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple
from .logging import default_logger


def utc_now_naive() -> datetime:
    """Retourne l'heure courante UTC sous forme de datetime naïf (sans tzinfo).

    Utiliser cette fonction au lieu de ``datetime.utcnow()`` (déprécié depuis
    Python 3.12).  Le résultat est naïf pour rester compatible avec les dates
    retournées par ``parse_article_date()`` et permettre des comparaisons directes.

    Returns:
        datetime naïf représentant l'heure courante en UTC.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def parse_iso_date(date_str: str) -> Optional[datetime]:
    """Parse une date au format ISO 8601.
    
    Args:
        date_str: Date au format "YYYY-MM-DDTHH:MM:SSZ"
    
    Returns:
        Objet datetime ou None si le parsing échoue
    
    Example:
        >>> dt = parse_iso_date("2026-01-24T10:00:00Z")
        >>> print(dt.strftime("%Y-%m-%d"))
        2026-01-24
    """
    try:
        return datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as e:
        default_logger.error(f"Erreur de parsing de date ISO: {date_str} - {e}")
        return None


def parse_simple_date(date_str: str) -> Optional[datetime]:
    """Parse une date au format simple YYYY-MM-DD.
    
    Args:
        date_str: Date au format "YYYY-MM-DD"
    
    Returns:
        Objet datetime ou None si le parsing échoue
    """
    try:
        return datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError as e:
        default_logger.error(f"Erreur de parsing de date simple: {date_str} - {e}")
        return None


def verifier_date_entre(
    date_a_verifier: str,
    date_debut: str,
    date_fin: str
) -> bool:
    """Vérifie si une date se situe entre deux bornes incluses.
    
    Args:
        date_a_verifier: Date à tester au format "YYYY-MM-DD"
        date_debut: Date de début au format "YYYY-MM-DD"
        date_fin: Date de fin au format "YYYY-MM-DD"
    
    Returns:
        True si la date est dans l'intervalle [date_debut, date_fin], False sinon.
        Retourne également False en cas d'erreur de format de date.
    
    Example:
        >>> verifier_date_entre("2026-01-15", "2026-01-01", "2026-01-31")
        True
        >>> verifier_date_entre("2026-02-01", "2026-01-01", "2026-01-31")
        False
    """
    date_a_verifier_obj = parse_simple_date(date_a_verifier)
    date_debut_obj = parse_simple_date(date_debut)
    date_fin_obj = parse_simple_date(date_fin)
    
    if not all([date_a_verifier_obj, date_debut_obj, date_fin_obj]):
        default_logger.error(
            f"Format de date invalide: vérifier={date_a_verifier}, "
            f"début={date_debut}, fin={date_fin}"
        )
        return False
    
    return date_debut_obj <= date_a_verifier_obj <= date_fin_obj


def get_default_date_range() -> Tuple[str, str]:
    """Retourne une plage de dates par défaut (1er du mois → aujourd'hui).
    
    Returns:
        Tuple (date_debut, date_fin) au format "YYYY-MM-DD"
    
    Example:
        >>> debut, fin = get_default_date_range()
        >>> print(f"Du {debut} au {fin}")
        Du 2026-01-01 au 2026-01-24
    """
    today = datetime.today()
    date_debut = today.replace(day=1).strftime("%Y-%m-%d")
    date_fin = today.strftime("%Y-%m-%d")
    
    default_logger.info(f"Plage de dates par défaut: {date_debut} → {date_fin}")
    return date_debut, date_fin


def _apply_date_only_policy(dt: datetime, date_only_policy: str) -> datetime:
    """Ajuste une date sans heure selon la politique demandée."""
    if date_only_policy == "start":
        return dt
    if date_only_policy == "end":
        return dt + timedelta(days=1) - timedelta(seconds=1)
    raise ValueError("date_only_policy doit valoir 'start' ou 'end'")


def parse_article_date(date_str: Optional[str], date_only_policy: str = "start") -> Optional[datetime]:
    """Parse une date d'article dans tous les formats du pipeline WUDD.ai.

    Formats gérés dans l'ordre :
    - DD/MM/YYYY           (format interne standard)
    - YYYY-MM-DD           (ISO court)
    - YYYY-MM-DDTHH:MM:SSZ (ISO long avec Z)
    - YYYY-MM-DDTHH:MM:SS  (ISO long sans timezone)
    - RFC 822 (ex. "Mon, 01 Jan 2026 00:00:00 +0000")

    Retourne un datetime naïf (sans timezone) pour comparaison uniforme.

    Args:
        date_str: Date à parser.
        date_only_policy: Politique pour les dates sans heure :
            - ``"start"`` : 00:00:00
            - ``"end"``   : 23:59:59
    """
    if not date_str:
        return None
    date_str = date_str.strip()
    # Formats ISO longs testés en premier pour éviter qu'ISO court tronque les heures
    for fmt, length, is_date_only in (
        ("%Y-%m-%dT%H:%M:%SZ", 20, False),
        ("%Y-%m-%dT%H:%M:%S", 19, False),
        ("%d/%m/%Y", 10, True),
        ("%Y-%m-%d", 10, True),
    ):
        try:
            dt = datetime.strptime(date_str[:length], fmt)
            return _apply_date_only_policy(dt, date_only_policy) if is_date_only else dt
        except ValueError:
            continue
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(date_str)
        if dt.tzinfo is not None:
            return dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt.replace(tzinfo=None)
    except Exception:
        pass
    return None


def validate_date_range(date_debut: str, date_fin: str) -> bool:
    """Valide qu'une plage de dates est cohérente.
    
    Args:
        date_debut: Date de début au format "YYYY-MM-DD"
        date_fin: Date de fin au format "YYYY-MM-DD"
    
    Returns:
        True si date_debut < date_fin, False sinon
    
    Raises:
        ValueError: Si les dates sont invalides ou dans le mauvais ordre
    """
    date_debut_obj = parse_simple_date(date_debut)
    date_fin_obj = parse_simple_date(date_fin)
    
    if not date_debut_obj or not date_fin_obj:
        raise ValueError("Format de date invalide. Utilisez le format YYYY-MM-DD.")
    
    if date_debut_obj >= date_fin_obj:
        raise ValueError("La date de début doit être antérieure à la date de fin.")
    
    return True
