"""
utils/mermaid_utils.py — Post-traitement des diagrammes Mermaid (charte OK-ia).

Garantit que TOUT bloc ```mermaid``` respecte la charte de couleurs OK-ia,
quelles que soient les couleurs produites par l'IA :

  - seules 6 couleurs de fond (``fill``) sont autorisées, chacune appariée à une
    couleur de texte (``color``) garantissant le contraste ;
  - les bordures (``stroke``) sont ramenées à l'une des 2 couleurs autorisées.

Toute couleur hors charte (autre hex, couleur nommée : red, green, blue…) est
ramenée à la couleur OK-ia la plus proche (distance RGB), et la couleur de texte
appariée est forcée. Les lignes ``classDef`` ET ``style`` sont traitées.

Palette OK-ia (fill → color) :
    #E8972E → #111111   (orange — accent principal)
    #111111 → #FAFAF8   (noir — élément fort)
    #9A9A90 → #111111   (gris — neutre/secondaire)
    #F0A840 → #111111   (orange clair — variante)
    #FAFAF8 → #111111   (blanc cassé — fond léger)
    #5A5A52 → #FAFAF8   (gris foncé — variante)

Bordures (stroke) autorisées : #9A9A90 ou #E8972E.

Usage:
    from utils.mermaid_utils import fix_mermaid_classdefs
    content = fix_mermaid_classdefs(ai_generated_markdown)
"""

from __future__ import annotations

import re

# ── Palette OK-ia ─────────────────────────────────────────────────────────────

# fill autorisé (lowercase) → couleur de texte appariée (charte OK-ia).
# L'ordre reflète l'ordre de priorité des catégories de la charte.
_OKIA_FILL_TO_COLOR: dict[str, str] = {
    "#e8972e": "#111111",  # orange — accent principal
    "#111111": "#fafaf8",  # noir — élément fort
    "#9a9a90": "#111111",  # gris — neutre/secondaire
    "#f0a840": "#111111",  # orange clair — variante
    "#fafaf8": "#111111",  # blanc cassé — fond léger
    "#5a5a52": "#fafaf8",  # gris foncé — variante
}

# Couleur de fond par défaut quand le fill est illisible / couleur nommée.
_OKIA_DEFAULT_FILL = "#e8972e"

# Bordures autorisées (charte : #9A9A90 ou #E8972E uniquement).
_OKIA_STROKES: tuple[str, ...] = ("#9a9a90", "#e8972e")
_OKIA_DEFAULT_STROKE = "#9a9a90"


# ── Conversion / distance couleur ─────────────────────────────────────────────

def _hex_to_rgb(hex_color: str) -> tuple[int, int, int] | None:
    """Convertit #RGB, #RRGGBB, #RRGGBBAA → (r, g, b). Retourne None si invalide."""
    h = hex_color.strip().lstrip("#")
    if len(h) in (3, 4):
        h = "".join(c * 2 for c in h[:3])
    if len(h) not in (6, 8):
        return None
    try:
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except ValueError:
        return None


def _dist2(a: tuple[int, int, int], b: tuple[int, int, int]) -> int:
    """Distance euclidienne au carré entre deux couleurs RGB."""
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2


def _nearest(value: str, candidates: tuple[str, ...], default: str) -> str:
    """Retourne la couleur de ``candidates`` la plus proche de ``value`` (RGB).

    Si ``value`` n'est pas un hex lisible (ex. couleur nommée), retourne
    ``default`` — la charte interdit toute couleur hors palette.
    """
    rgb = _hex_to_rgb(value)
    if rgb is None:
        return default
    return min(candidates, key=lambda c: _dist2(rgb, _hex_to_rgb(c)))  # type: ignore[arg-type]


def _snap_fill(value: str) -> tuple[str, str]:
    """Ramène un fill quelconque à (fill OK-ia, color appariée) en MAJUSCULES."""
    fill = _nearest(value, tuple(_OKIA_FILL_TO_COLOR), _OKIA_DEFAULT_FILL)
    return fill.upper(), _OKIA_FILL_TO_COLOR[fill].upper()


def _snap_stroke(value: str) -> str:
    """Ramène un stroke quelconque à une bordure OK-ia (MAJUSCULES)."""
    return _nearest(value, _OKIA_STROKES, _OKIA_DEFAULT_STROKE).upper()


# ── Correction d'une ligne classDef / style ───────────────────────────────────

# Capture la valeur après fill:/stroke:/color: jusqu'au prochain séparateur.
# Le lookbehind (?<![\w-]) évite de confondre "stroke:" avec "stroke-width:".
_FILL_RE = re.compile(r"(?<![\w-])fill:\s*([^,;\s]+)")
_STROKE_RE = re.compile(r"(?<![\w-])stroke:\s*([^,;\s]+)")
_COLOR_PROP_RE = re.compile(r"(?<![\w-])color:\s*[^,;\s]+")


def _fix_style_line(line: str) -> str:
    """Applique la charte OK-ia à une ligne ``classDef`` ou ``style``.

    - ``fill`` → couleur OK-ia la plus proche, ``color`` apparié forcé ;
    - ``stroke`` (éventuel) → bordure OK-ia la plus proche.
    Le reste de la ligne (stroke-width, sélecteur de classe, etc.) est inchangé.
    """
    fill_m = _FILL_RE.search(line)
    stroke_m = _STROKE_RE.search(line)
    if not fill_m and not stroke_m:
        return line

    new = line

    if fill_m:
        fill, color = _snap_fill(fill_m.group(1))
        # 1. ramener la valeur du fill
        new = _FILL_RE.sub(f"fill:{fill}", new, count=1)
        # 2. forcer la couleur de texte appariée (contraste garanti)
        if _COLOR_PROP_RE.search(new):
            new = _COLOR_PROP_RE.sub(f"color:{color}", new, count=1)
        else:
            new = new.rstrip("\n") + f",color:{color}"

    if stroke_m:
        new = _STROKE_RE.sub(
            lambda m: f"stroke:{_snap_stroke(m.group(1))}", new
        )

    return new


# ── Traitement d'un bloc mermaid ──────────────────────────────────────────────

def _fix_mermaid_block(block_content: str) -> str:
    """Applique la charte OK-ia à chaque ligne ``classDef``/``style`` du bloc."""
    fixed_lines = []
    for line in block_content.split("\n"):
        stripped = line.lstrip()
        is_style = stripped.startswith("classDef ") or stripped.startswith("style ")
        if is_style and ("fill:" in stripped or "stroke:" in stripped):
            fixed_lines.append(_fix_style_line(line))
        else:
            fixed_lines.append(line)
    return "\n".join(fixed_lines)


# ── Entrée publique ───────────────────────────────────────────────────────────

_MERMAID_BLOCK_RE = re.compile(
    r"(```mermaid\s*\n)(.*?)(```)",
    re.DOTALL | re.IGNORECASE,
)


def fix_mermaid_classdefs(text: str) -> str:
    """Applique la charte de couleurs OK-ia à tous les blocs ```mermaid``` du texte.

    Pour chaque ligne ``classDef`` / ``style`` :
      - ``fill`` est ramené à la couleur OK-ia la plus proche ;
      - ``color`` est forcé à la couleur appariée (contraste garanti) ;
      - ``stroke`` (s'il existe) est ramené à une bordure OK-ia (#9A9A90/#E8972E).

    Le reste du contenu est inchangé.
    """
    def replace_block(m: re.Match) -> str:
        opening = m.group(1)   # ```mermaid\n
        content = m.group(2)   # corps du diagramme
        closing = m.group(3)   # ```
        return opening + _fix_mermaid_block(content) + closing

    return _MERMAID_BLOCK_RE.sub(replace_block, text)
