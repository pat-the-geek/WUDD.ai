"""utils/entity_utils.py — Utilitaires partagés pour le champ ``entities``.

Le champ ``entities`` d'un article est un dict ``{type: [valeur, ...]}``.
Ces helpers centralisent les boucles répétées dans 4+ scripts.

Usage minimal
-------------
>>> from utils.entity_utils import iter_entities, count_entity_mentions
>>> for etype, value in iter_entities(article):
...     print(etype, value)
>>> counter = count_entity_mentions(articles)
>>> counter.most_common(5)
"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING, Iterable, Iterator

if TYPE_CHECKING:
    from collections.abc import Collection

# Types d'entités structurelles ignorées par défaut dans les comptages
_STRUCTURAL_TYPES: frozenset[str] = frozenset(
    {"DATE", "TIME", "CARDINAL", "ORDINAL", "PERCENT", "MONEY", "QUANTITY"}
)


def iter_entities(
    article: dict,
    *,
    types: "Collection[str] | None" = None,
    skip_structural: bool = False,
) -> Iterator[tuple[str, str]]:
    """Itère sur chaque couple ``(etype, valeur)`` des entités d'un article.

    Args:
        article: Dict article pouvant contenir un champ ``"entities"``.
        types: Si fourni, ne retourner que ces types (ex. ``["PERSON", "ORG"]``).
        skip_structural: Si ``True``, ignorer les types dans ``_STRUCTURAL_TYPES``
                         (DATE, TIME, CARDINAL, …).

    Yields:
        Couples ``(etype, value)`` — valeurs dupliquées si présentes plusieurs fois.
    """
    entities: dict = article.get("entities") or {}
    if not isinstance(entities, dict):
        return

    allowed = set(types) if types is not None else None
    blocked = _STRUCTURAL_TYPES if skip_structural else frozenset()

    for etype, values in entities.items():
        if allowed is not None and etype not in allowed:
            continue
        if etype in blocked:
            continue
        if not isinstance(values, list):
            continue
        for val in values:
            if val and isinstance(val, str):
                yield etype, val.strip()


def flatten_entities(
    article: dict,
    *,
    types: "Collection[str] | None" = None,
    skip_structural: bool = False,
) -> list[tuple[str, str]]:
    """Retourne la liste complète ``[(etype, valeur), ...]`` pour un article.

    Equivalent à ``list(iter_entities(article, ...))``.
    """
    return list(iter_entities(article, types=types, skip_structural=skip_structural))


def count_entity_mentions(
    articles: Iterable[dict],
    *,
    types: "Collection[str] | None" = None,
    skip_structural: bool = True,
) -> Counter[str]:
    """Compte les mentions d'entités (clé: ``"TYPE:valeur"``) dans une liste.

    Args:
        articles: Itérable de dicts article.
        types: Filtrer sur ces types uniquement.
        skip_structural: Ignorer les types structurels (activé par défaut pour
                         les comptages de tendances).

    Returns:
        ``Counter`` dont les clés sont ``"TYPE:valeur"`` (casse originale).

    Example:
        >>> counter = count_entity_mentions(articles)
        >>> counter.most_common(10)
        [("PERSON:Emmanuel Macron", 12), ...]
    """
    counter: Counter[str] = Counter()
    for article in articles:
        for etype, value in iter_entities(
            article, types=types, skip_structural=skip_structural
        ):
            counter[f"{etype}:{value}"] += 1
    return counter


def has_entities(article: dict) -> bool:
    """Retourne ``True`` si l'article possède au moins une entité nommée."""
    entities = article.get("entities")
    if not isinstance(entities, dict):
        return False
    return any(isinstance(v, list) and len(v) > 0 for v in entities.values())


def entity_types_present(article: dict) -> set[str]:
    """Retourne l'ensemble des types d'entités présents dans l'article."""
    entities: dict = article.get("entities") or {}
    if not isinstance(entities, dict):
        return set()
    return {
        etype
        for etype, vals in entities.items()
        if isinstance(vals, list) and vals
    }
