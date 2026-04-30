"""
utils/file_io.py — Lectures/écritures JSON centralisées pour WUDD.ai

Patterns exposés :
  - json_read(path)           → dict | list  (lève FileNotFoundError / JSONDecodeError)
  - json_read_safe(path, default=None) → dict | list | default  (ne lève jamais)
  - json_write(path, data, indent=2)   → None  (écriture atomique via .tmp + rename)
  - json_write_compact(path, data)     → None  (écriture atomique sans indent — index)

Conventions :
  - Encodage UTF-8 systématique, ensure_ascii=False
  - Écriture atomique : le fichier cible n'est jamais partiellement écrit
  - mkdir parents=True automatique à l'écriture
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


# ── Lecture ──────────────────────────────────────────────────────────────────

def json_read(path: Path | str, *, errors: str = "strict") -> Any:
    """Lit et parse un fichier JSON.

    Args:
        path: Chemin vers le fichier JSON.
        errors: Stratégie de décodage pour les octets invalides (``"strict"``
            par défaut, ``"replace"`` pour les fichiers potentiellement corrompus).

    Returns:
        L'objet Python désérialisé (dict, list, …).

    Raises:
        FileNotFoundError: si le fichier n'existe pas.
        json.JSONDecodeError: si le contenu n'est pas du JSON valide.
    """
    p = Path(path)
    return json.loads(p.read_text(encoding="utf-8", errors=errors))


def json_read_safe(
    path: Path | str,
    default: Any = None,
    *,
    errors: str = "replace",
) -> Any:
    """Lit et parse un fichier JSON sans lever d'exception.

    Retourne *default* si le fichier est absent, vide ou malformé.
    Utilise ``errors="replace"`` par défaut pour tolérer les encodages imparfaits.
    """
    try:
        result = json_read(path, errors=errors)
        return result if result is not None else default
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


# ── Écriture atomique ─────────────────────────────────────────────────────────

def json_write(path: Path | str, data: Any, *, indent: int = 2) -> None:
    """Sérialise *data* en JSON et l'écrit de façon atomique dans *path*.

    L'écriture passe par un fichier ``.tmp`` adjacent puis ``rename``,
    ce qui garantit qu'un lecteur concurrent ne voit jamais un fichier
    partiellement écrit.

    Args:
        path:   Chemin cible (créé si absent, répertoires parents créés).
        data:   Objet Python sérialisable (dict, list, …).
        indent: Indentation JSON (2 par défaut ; 0 pour une ligne unique).
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(data, ensure_ascii=False, indent=indent),
        encoding="utf-8",
    )
    tmp.replace(p)


def json_write_compact(path: Path | str, data: Any) -> None:
    """Écriture atomique JSON sans indentation — pour les index volumineux.

    Équivalent de ``json_write(path, data, indent=None)`` mais utilise
    des séparateurs compacts ``(",", ":")`` pour minimiser la taille du fichier.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(data, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    tmp.replace(p)
