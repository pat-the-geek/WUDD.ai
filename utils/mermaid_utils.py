"""
utils/mermaid_utils.py — Post-traitement des diagrammes Mermaid.

Fonctions:
  fix_mermaid_classdefs(text) -> str
      Corrige la couleur de police (color:) dans chaque classDef d'un texte
      Markdown pouvant contenir un ou plusieurs blocs ```mermaid```.

      Règle WCAG appliquée :
        - luminance relative (sRGB) < 0.35  →  color:#ffffff  (fond sombre)
        - luminance relative (sRGB) ≥ 0.35  →  color:#333333  (fond clair)

Usage:
    from utils.mermaid_utils import fix_mermaid_classdefs
    content = fix_mermaid_classdefs(ai_generated_markdown)
"""

from __future__ import annotations

import re


# ── Calcul de luminance WCAG ──────────────────────────────────────────────────

def _hex_to_rgb(hex_color: str) -> tuple[int, int, int] | None:
    """Convertit #RGB, #RRGGBB, #RRGGBBAA → (r, g, b). Retourne None si invalide."""
    h = hex_color.lstrip("#")
    if len(h) in (3, 4):
        h = "".join(c * 2 for c in h[:3])
    if len(h) not in (6, 8):
        return None
    try:
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except ValueError:
        return None


def _relative_luminance(r: int, g: int, b: int) -> float:
    """Luminance relative WCAG 2.1 (0 = noir, 1 = blanc)."""
    def _lin(c: int) -> float:
        v = c / 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def _is_dark(hex_color: str, threshold: float = 0.35) -> bool:
    """Retourne True si la couleur hex est perçue comme sombre."""
    rgb = _hex_to_rgb(hex_color)
    if rgb is None:
        return False
    return _relative_luminance(*rgb) < threshold


# ── Correction d'une ligne classDef ──────────────────────────────────────────

_FILL_RE = re.compile(r"fill:(#[0-9a-fA-F]{3,8})")
_COLOR_PROP_RE = re.compile(r"\bcolor:#[0-9a-fA-F]{3,8}")


def _fix_classdef_line(line: str) -> str:
    """
    Analyse une ligne ``classDef`` et corrige/ajoute la propriété ``color:``.

    Seules les lignes dont l'indentation est conservée sont modifiées ;
    le reste de la ligne (stroke, stroke-width, etc.) est inchangé.
    """
    fill_m = _FILL_RE.search(line)
    if not fill_m:
        return line  # pas de fill: → rien à corriger

    text_color = "#ffffff" if _is_dark(fill_m.group(1)) else "#333333"

    if _COLOR_PROP_RE.search(line):
        # Remplacer le color: existant (quelle que soit la valeur courante)
        return _COLOR_PROP_RE.sub(f"color:{text_color}", line)
    else:
        # Ajouter color: à la fin (avant un éventuel saut de ligne)
        return line.rstrip("\n") + f",color:{text_color}"


# ── Traitement d'un bloc mermaid ──────────────────────────────────────────────

def _fix_mermaid_block(block_content: str) -> str:
    """
    Applique la correction sur chaque ligne ``classDef`` d'un bloc Mermaid.
    ``block_content`` est le texte entre les balises ``` (sans les backticks).
    """
    fixed_lines = []
    for line in block_content.split("\n"):
        stripped = line.lstrip()
        if stripped.startswith("classDef ") and "fill:" in stripped:
            fixed_lines.append(_fix_classdef_line(line))
        else:
            fixed_lines.append(line)
    return "\n".join(fixed_lines)


# ── Entrée publique ───────────────────────────────────────────────────────────

_MERMAID_BLOCK_RE = re.compile(
    r"(```mermaid\s*\n)(.*?)(```)",
    re.DOTALL | re.IGNORECASE,
)


def fix_mermaid_classdefs(text: str) -> str:
    """
    Parcourt tous les blocs ```mermaid``` d'un texte Markdown et corrige
    la couleur de police de chaque ``classDef`` selon la luminance WCAG du fill:.

    - fond sombre (luminance < 0.35) → color:#ffffff
    - fond clair  (luminance ≥ 0.35) → color:#333333

    Le reste du contenu est inchangé.
    """
    def replace_block(m: re.Match) -> str:
        opening = m.group(1)   # ```mermaid\n
        content = m.group(2)   # corps du diagramme
        closing = m.group(3)   # ```
        return opening + _fix_mermaid_block(content) + closing

    return _MERMAID_BLOCK_RE.sub(replace_block, text)
