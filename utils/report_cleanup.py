"""Nettoyage des rapports datés — un seul fichier par « genre ».

Lorsqu'un rapport daté est généré (date `YYYY-MM-DD` dans le nom de fichier),
on ne conserve dans le répertoire que le dernier généré et on supprime les
fichiers frères du même « genre » portant d'autres dates.

Le « genre » d'un fichier est son nom dont chaque portion date (`YYYY-MM-DD`)
est remplacée par un joker. Ainsi :

    cross_flux_2026-06-03.md         → genre « cross_flux_<date>.md »
    briefing_2026-06-03_daily.md     → genre « briefing_<date>_daily.md »
    digest_macron_2026-06-03.md      → genre « digest_macron_<date>.md »

Les parties littérales non-date sont préservées, ce qui évite les faux
positifs : `briefing_..._daily.md` ne supprime pas `briefing_..._weekly.md`,
et `digest_<date>.md` ne touche pas `digest_macron_<date>.md`.

Si le nom de fichier ne contient aucune date, la fonction ne fait rien
(noms fixes type `rapport_48h.md`, `notes_lecture.md`).
"""

import re
from pathlib import Path
from typing import List, Union

from utils.logging import print_console

# Date ISO : YYYY-MM-DD
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def cleanup_old_dated_reports(
    report_path: Union[str, Path],
    *,
    dry_run: bool = False,
    verbose: bool = True,
) -> List[Path]:
    """Supprime les rapports du même genre que `report_path`, autres dates.

    Ne conserve que `report_path` (le dernier généré) parmi tous les fichiers
    du même genre présents dans son répertoire.

    Args:
        report_path: chemin du rapport qui vient d'être généré.
        dry_run: si True, ne supprime rien et retourne les fichiers qui le
            seraient.
        verbose: si True, loggue chaque suppression via `print_console`.

    Returns:
        La liste des chemins supprimés (ou qui le seraient en dry-run).
    """
    report_path = Path(report_path)
    directory = report_path.parent
    name = report_path.name

    matches = list(_DATE_RE.finditer(name))
    if not matches:
        # Nom de fichier sans date → pas de nettoyage par genre.
        return []

    # Construit un motif regex : littéraux échappés + joker date.
    pattern_parts: List[str] = []
    last = 0
    for m in matches:
        pattern_parts.append(re.escape(name[last:m.start()]))
        pattern_parts.append(r"\d{4}-\d{2}-\d{2}")
        last = m.end()
    pattern_parts.append(re.escape(name[last:]))
    genre_re = re.compile("^" + "".join(pattern_parts) + "$")

    if not directory.exists():
        return []

    deleted: List[Path] = []
    for sibling in sorted(directory.iterdir()):
        if not sibling.is_file():
            continue
        if sibling.name == name:
            continue
        if not genre_re.match(sibling.name):
            continue
        if dry_run:
            deleted.append(sibling)
            if verbose:
                print_console(f"[dry-run] Supprimerait l'ancien rapport : {sibling.name}")
            continue
        try:
            sibling.unlink()
            deleted.append(sibling)
            if verbose:
                print_console(f"Ancien rapport supprimé : {sibling.name}")
        except OSError as exc:
            print_console(
                f"⚠️  Impossible de supprimer {sibling.name} : {exc}", level="warning"
            )

    return deleted
