"""Utilitaires de nommage pour les fichiers data/articles-from-rss/*.json.

Objectif: stabiliser les chemins de sortie par mot-cle et ignorer les copies
accidentelles generees hors pipeline (ex: "keyword 2.json").
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

_COPY_SUFFIX_RE = re.compile(r"\s+\d+$")


def _nfc(value: str) -> str:
    return unicodedata.normalize("NFC", value or "")


def keyword_slug(keyword: str) -> str:
    """Retourne le slug canonique d'un mot-cle (NFC + lower + espaces->-)."""
    normalized = " ".join(_nfc(keyword).strip().split())
    return normalized.lower().replace(" ", "-")


def canonical_stem(stem: str) -> str:
    """Normalise un stem de fichier pour comparer des variantes accidentelles."""
    s = " ".join(_nfc(stem).strip().split())
    s = _COPY_SUFFIX_RE.sub("", s)
    return s


def is_numbered_copy(path: Path) -> bool:
    """True si le nom ressemble a une copie Finder/Cloud ("name 2.json")."""
    return bool(_COPY_SUFFIX_RE.search(_nfc(path.stem)))


def keyword_json_path(base_dir: Path, keyword: str) -> Path:
    """Chemin canonique de sortie pour un mot-cle."""
    return base_dir / f"{keyword_slug(keyword)}.json"


def keyword_alias_paths(base_dir: Path, keyword: str) -> list[Path]:
    """Liste les fichiers JSON equivalents a un mot-cle (canonique + copies)."""
    target = keyword_json_path(base_dir, keyword)
    wanted = canonical_stem(target.stem)
    candidates = [p for p in sorted(base_dir.glob("*.json")) if canonical_stem(p.stem) == wanted]
    if target not in candidates:
        candidates.insert(0, target)
    return candidates
