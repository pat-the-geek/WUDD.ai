#!/usr/bin/env python3
"""Importe les rapports WUDD.ai depuis le répertoire Obsidian et les intègre
dans les articles et l'index d'entités de WUDD.ai.

Parcourt les fichiers Markdown dans OBSIDIAN_DIR, détecte ceux générés par
WUDD.ai (champ frontmatter `type: Rapport-WUDD-ai`), puis :

  - Rapport d'article (frontmatter contient `url`) :
      Ajoute une entrée dans le champ `rapports` de l'article correspondant
      dans son fichier JSON source.

  - Rapport d'entité (frontmatter contient `entity_type`) :
      Ajoute une entrée dans `data/entity_reports_index.json`.

Le script est idempotent : il ne crée pas de doublons (détection par nom de
fichier). Par défaut il n'écrase rien ; utiliser --force pour re-synchroniser.

Usage :
    # Simulation (aucune écriture)
    python3 scripts/import_obsidian_reports.py --dry-run

    # Import réel
    python3 scripts/import_obsidian_reports.py

    # Répertoire Obsidian alternatif
    python3 scripts/import_obsidian_reports.py --dir /chemin/vers/vault

    # Forcer la re-synchronisation même si déjà présent
    python3 scripts/import_obsidian_reports.py --force

    # Mode verbeux
    python3 scripts/import_obsidian_reports.py --verbose
"""

import json
import re
import sys
import argparse
from datetime import datetime
from pathlib import Path

SCRIPT_DIR   = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))

from utils.logging import print_console, setup_logger
from utils.config import get_config

logger = setup_logger(__name__)


# ── Parseur de frontmatter YAML minimal ───────────────────────────────────────
# Pas de dépendance PyYAML : traite uniquement les scalaires et les listes
# simples (une valeur par ligne avec « - ») tels que produits par les dialogs.

_FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)
_SCALAR_RE = re.compile(r'^(\w[\w_-]*):\s*(.*)$')
_LIST_ITEM_RE = re.compile(r'^\s+-\s+"?([^"]+)"?\s*$')


def parse_frontmatter(text: str) -> dict:
    """Extrait le frontmatter YAML d'un fichier Markdown.

    Retourne un dictionnaire plat avec les scalaires et les listes simples.
    Retourne un dict vide si aucun frontmatter n'est trouvé.
    """
    m = _FM_RE.match(text)
    if not m:
        return {}

    result: dict = {}
    current_key: str | None = None
    current_list: list | None = None

    for line in m.group(1).splitlines():
        # Ligne de liste
        if current_list is not None:
            lm = _LIST_ITEM_RE.match(line)
            if lm:
                current_list.append(lm.group(1).strip())
                continue
            else:
                # Fin de la liste : commit
                if current_key:
                    result[current_key] = current_list
                current_key  = None
                current_list = None

        sm = _SCALAR_RE.match(line)
        if not sm:
            continue

        key = sm.group(1)
        raw = sm.group(2).strip()

        if raw == '':
            # Peut-être une liste sur les lignes suivantes
            current_key  = key
            current_list = []
        elif raw.startswith('[') and raw.endswith(']'):
            # Liste inline [val1, val2]
            inner = raw[1:-1]
            result[key] = [v.strip().strip('"').strip("'") for v in inner.split(',') if v.strip()]
        else:
            # Scalaire
            value = raw.strip('"').strip("'")
            result[key] = value
            current_key  = None
            current_list = None

    # Flush liste en fin de fichier
    if current_key and current_list is not None:
        result[current_key] = current_list

    return result


# ── Utilitaires ───────────────────────────────────────────────────────────────

def iter_wudd_reports(obsidian_dir: Path, verbose: bool = False):
    """Génère (path, frontmatter) pour chaque rapport WUDD.ai dans le vault."""
    count_total = 0
    count_wudd  = 0

    for md_file in obsidian_dir.rglob("*.md"):
        if md_file.name.startswith('.'):
            continue
        count_total += 1
        try:
            text = md_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        fm = parse_frontmatter(text)
        if fm.get("type") != "Rapport-WUDD-ai":
            continue

        count_wudd += 1
        if verbose:
            print_console(f"  Rapport trouvé : {md_file.name}", logger)
        yield md_file, fm

    print_console(
        f"Vault Obsidian : {count_total} fichiers .md scannés, "
        f"{count_wudd} rapport(s) WUDD.ai détecté(s)",
        logger,
    )


def build_url_index(data_dir: Path) -> dict[str, tuple[Path, int]]:
    """Construit un index { url → (fichier_json, indice_article) } en
    parcourant tous les fichiers JSON d'articles.

    Utilisé pour retrouver rapidement l'article correspondant à une URL.
    """
    index: dict[str, tuple[Path, int]] = {}

    dirs_to_scan = []
    articles_dir = data_dir / "articles"
    rss_dir      = data_dir / "articles-from-rss"

    if articles_dir.is_dir():
        for sub in articles_dir.iterdir():
            if sub.is_dir():
                dirs_to_scan.extend(sub.glob("*.json"))

    if rss_dir.is_dir():
        dirs_to_scan.extend(rss_dir.glob("*.json"))

    for json_file in dirs_to_scan:
        if json_file.name.startswith('.'):
            continue
        try:
            articles = json.loads(json_file.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(articles, list):
            continue
        for i, art in enumerate(articles):
            url = art.get("URL")
            if url and url not in index:
                index[url] = (json_file, i)

    return index


def make_rapport_entry(md_path: Path, fm: dict, cible: str) -> dict:
    """Crée une entrée de métadonnées rapport normalisée."""
    date_creation = fm.get("date") or datetime.now().strftime("%Y-%m-%d")
    # Enrichir avec l'heure depuis le nom de fichier si possible (YYYYMMDD_HHMMSS)
    ts_match = re.search(r'_(\d{8})_(\d{6})\.md$', md_path.name)
    if ts_match:
        d, t = ts_match.group(1), ts_match.group(2)
        date_creation = f"{d[:4]}-{d[4:6]}-{d[6:8]}T{t[:2]}:{t[2:4]}:{t[4:6]}"

    return {
        "fichier":       md_path.name,
        "chemin":        str(md_path),
        "cible":         cible,
        "date_creation": date_creation,
    }


# ── Import articles ────────────────────────────────────────────────────────────

def import_article_reports(
    reports: list[tuple[Path, dict]],
    url_index: dict[str, tuple[Path, int]],
    dry_run: bool,
    force: bool,
    verbose: bool,
) -> tuple[int, int, int]:
    """Intègre les rapports d'articles dans les fichiers JSON WUDD.ai.

    Retourne (nb_importés, nb_déjà_présents, nb_introuvables).
    """
    imported   = 0
    already    = 0
    not_found  = 0

    # Grouper les rapports par fichier JSON cible pour écrire en une fois
    file_updates: dict[Path, list[tuple[int, dict]]] = {}

    for md_path, fm in reports:
        url = fm.get("url", "").strip()
        if not url:
            not_found += 1
            continue

        location = url_index.get(url)
        if not location:
            not_found += 1
            if verbose:
                print_console(f"  ↯ Article introuvable pour : {url[:80]}", logger)
            continue

        json_file, art_idx = location
        entry = make_rapport_entry(md_path, fm, "obsidian")

        if json_file not in file_updates:
            file_updates[json_file] = []
        file_updates[json_file].append((art_idx, entry))

    # Appliquer les mises à jour fichier par fichier
    for json_file, updates in file_updates.items():
        try:
            articles = json.loads(json_file.read_text(encoding="utf-8"))
        except Exception as e:
            print_console(f"  Erreur lecture {json_file.name} : {e}", logger)
            continue

        changed = False
        for art_idx, entry in updates:
            if art_idx >= len(articles):
                not_found += 1
                continue
            art      = articles[art_idx]
            rapports = art.get("rapports") or []
            exists   = any(r.get("fichier") == entry["fichier"] for r in rapports)

            if exists and not force:
                already += 1
                if verbose:
                    print_console(f"  ✓ Déjà présent : {entry['fichier']}", logger)
                continue

            if exists and force:
                # Mettre à jour l'entrée existante
                rapports = [r for r in rapports if r.get("fichier") != entry["fichier"]]

            rapports.append(entry)
            art["rapports"] = rapports
            changed = True
            imported += 1
            if verbose or not dry_run:
                print_console(
                    f"  {'[dry-run] ' if dry_run else ''}← {entry['fichier']} → {art.get('Sources','?')} ({art.get('Date de publication','?')})",
                    logger,
                )

        if changed and not dry_run:
            try:
                json_file.write_text(
                    json.dumps(articles, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except OSError as e:
                print_console(f"  Erreur écriture {json_file.name} : {e}", logger)

    return imported, already, not_found


# ── Import entités ─────────────────────────────────────────────────────────────

def import_entity_reports(
    reports: list[tuple[Path, dict]],
    data_dir: Path,
    dry_run: bool,
    force: bool,
    verbose: bool,
) -> tuple[int, int]:
    """Intègre les rapports d'entités dans entity_reports_index.json.

    Retourne (nb_importés, nb_déjà_présents).
    """
    index_path = data_dir / "entity_reports_index.json"
    index: dict = {}
    if index_path.exists():
        try:
            index = json.loads(index_path.read_text(encoding="utf-8"))
        except Exception:
            index = {}

    imported = 0
    already  = 0

    for md_path, fm in reports:
        entity_type = fm.get("entity_type", "").strip()
        if not entity_type:
            continue

        # Extraire la valeur de l'entité depuis le titre :
        # Format : "Rapport — TYPE : Valeur"
        title = fm.get("title", "")
        m = re.search(r"—\s*[A-Z]+\s*:\s*(.+)$", title)
        entity_value = m.group(1).strip().rstrip('"\'') if m else title.strip().rstrip('"\'')
        if not entity_value:
            continue

        key   = f"{entity_type}:{entity_value}"
        entry = make_rapport_entry(md_path, fm, "obsidian")
        rapports = index.get(key) or []
        exists   = any(r.get("fichier") == entry["fichier"] for r in rapports)

        if exists and not force:
            already += 1
            if verbose:
                print_console(f"  ✓ Entité déjà indexée : {key} — {entry['fichier']}", logger)
            continue

        if exists and force:
            rapports = [r for r in rapports if r.get("fichier") != entry["fichier"]]

        rapports.append(entry)
        index[key] = rapports
        imported  += 1
        if verbose or not dry_run:
            print_console(
                f"  {'[dry-run] ' if dry_run else ''}← {entry['fichier']} → {key}",
                logger,
            )

    if imported > 0 and not dry_run:
        try:
            index_path.parent.mkdir(parents=True, exist_ok=True)
            index_path.write_text(
                json.dumps(index, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as e:
            print_console(f"  Erreur écriture entity_reports_index.json : {e}", logger)

    return imported, already


# ── Point d'entrée ─────────────────────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(
        description="Importe les rapports Obsidian WUDD.ai dans les fichiers JSON d'articles et l'index d'entités.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--dir",
        metavar="CHEMIN",
        help="Répertoire du vault Obsidian (remplace la variable OBSIDIAN_DIR du .env)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulation : aucune écriture sur disque",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-synchroniser même les entrées déjà présentes",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Afficher le détail de chaque fichier traité",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    config = get_config()
    data_dir = config.project_root / "data"

    # ── Résolution du répertoire Obsidian ──────────────────────────────────────
    import os
    obsidian_dir_str = args.dir or os.environ.get("OBSIDIAN_DIR", "").strip()
    if not obsidian_dir_str:
        print_console(
            "ERREUR : répertoire Obsidian non configuré.\n"
            "Définissez OBSIDIAN_DIR dans .env ou utilisez --dir <chemin>.",
            logger,
        )
        sys.exit(1)

    obsidian_dir = Path(obsidian_dir_str)
    if not obsidian_dir.is_dir():
        print_console(
            f"ERREUR : répertoire Obsidian introuvable : {obsidian_dir}",
            logger,
        )
        sys.exit(1)

    mode = "[dry-run] " if args.dry_run else ""
    print_console(
        f"{mode}Import rapports Obsidian → WUDD.ai — vault : {obsidian_dir}",
        logger,
    )

    # ── Collecte des rapports ──────────────────────────────────────────────────
    article_reports: list[tuple[Path, dict]] = []
    entity_reports:  list[tuple[Path, dict]] = []

    for md_path, fm in iter_wudd_reports(obsidian_dir, verbose=args.verbose):
        if fm.get("url"):
            article_reports.append((md_path, fm))
        elif fm.get("entity_type"):
            entity_reports.append((md_path, fm))
        else:
            if args.verbose:
                print_console(
                    f"  ⚠ Rapport ignoré (ni url ni entity_type) : {md_path.name}",
                    logger,
                )

    print_console(
        f"  → {len(article_reports)} rapport(s) d'articles, "
        f"{len(entity_reports)} rapport(s) d'entités",
        logger,
    )

    # ── Import articles ────────────────────────────────────────────────────────
    if article_reports:
        print_console("Construction de l'index URL des articles…", logger)
        url_index = build_url_index(data_dir)
        print_console(f"  → {len(url_index)} article(s) indexés", logger)

        print_console("Import des rapports d'articles…", logger)
        imported, already, not_found = import_article_reports(
            article_reports, url_index,
            dry_run=args.dry_run, force=args.force, verbose=args.verbose,
        )
        print_console(
            f"  Articles — importés : {imported}, déjà présents : {already}, "
            f"introuvables : {not_found}",
            logger,
        )

    # ── Import entités ─────────────────────────────────────────────────────────
    if entity_reports:
        print_console("Import des rapports d'entités…", logger)
        imported_e, already_e = import_entity_reports(
            entity_reports, data_dir,
            dry_run=args.dry_run, force=args.force, verbose=args.verbose,
        )
        print_console(
            f"  Entités — importées : {imported_e}, déjà présentes : {already_e}",
            logger,
        )

    print_console(
        f"{'[dry-run] ' if args.dry_run else ''}Import terminé.",
        logger,
    )


if __name__ == "__main__":
    main()
