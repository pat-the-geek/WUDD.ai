#!/usr/bin/env python3
"""Renomme les rapports WUDD.ai mal nommes dans un vault Obsidian.

Le script scanne les notes Markdown generees par WUDD.ai dans OBSIDIAN_DIR.
Pour chaque note de rapport d'article dont le nom de fichier ne commence pas
par une date au format AAAA-MM-JJ, il :

1. lit le frontmatter et recupere l'URL de l'article ;
2. cherche l'article correspondant dans data/articles-from-rss/*.json ;
3. lit les entrees du champ rapports ;
4. recupere le nom cible depuis rapports[].fichier ;
5. execute la commande Obsidian CLI de renommage.

Par defaut, le script utilise la commande native suivante :
`obsidian rename vault=<vault> path=<ancien-chemin> name=<nouveau-nom>`

L'option --rename-command reste disponible pour un override avance.

Exemples :

    # Simulation sur 20 fichiers maximum
    python3 scripts/rename_obsidian_reports.py --dry-run --limit 20

    # Renommage reel via Obsidian CLI
    python3 scripts/rename_obsidian_reports.py \
        --limit 20 \
        --vault-name "Coffre-de-Pat"

    # Variante: override avec une commande personnalisee
    python3 scripts/rename_obsidian_reports.py \
        --limit 20 \
        --vault-name "MonVault" \
        --rename-command 'obsidian rename vault={vault_name_q} path={old_rel_q} name={new_name_q}'
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))

from utils.config import get_config
from utils.logging import print_console


DATE_PREFIX_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")
FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)
SCALAR_RE = re.compile(r"^(\w[\w_-]*):\s*(.*)$")
LIST_ITEM_RE = re.compile(r'^\s+-\s+"?([^\"]+)"?\s*$')


@dataclass(frozen=True)
class ArticleRef:
    json_file: Path
    article_index: int
    url: str
    rapports: list[dict]


@dataclass(frozen=True)
class RenamePlan:
    source_path: Path
    target_name: str
    article_ref: ArticleRef
    reason: str

    @property
    def target_path(self) -> Path:
        return self.source_path.with_name(self.target_name)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Renomme les rapports Obsidian WUDD.ai dont le nom ne commence "
            "pas par AAAA-MM-JJ, en s'appuyant sur data/articles-from-rss/."
        )
    )
    parser.add_argument(
        "--dir",
        metavar="CHEMIN",
        help="Chemin du repertoire Obsidian a scanner (sinon OBSIDIAN_DIR)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Nombre maximal de fichiers mal nommes a verifier (0 = sans limite)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulation uniquement, sans renommage effectif",
    )
    parser.add_argument(
        "--rename-command",
        default="",
        help=(
            "Commande shell de renommage. Placeholders disponibles : "
            "{old_abs}, {new_abs}, {old_rel}, {new_rel}, {old_name}, {new_name}, "
            "{vault_dir}, {vault_name} et leurs variantes suffixees par _q."
        ),
    )
    parser.add_argument(
        "--vault-name",
        default=os.environ.get("OBSIDIAN_VAULT_NAME", "").strip(),
        help="Nom exact du vault Obsidian si votre commande de renommage en a besoin",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Affiche le detail des fichiers inspectes et des decisions prises",
    )
    return parser.parse_args()


def parse_frontmatter(text: str) -> dict:
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}

    result: dict = {}
    current_key: str | None = None
    current_list: list[str] | None = None

    for line in match.group(1).splitlines():
        if current_list is not None:
            list_match = LIST_ITEM_RE.match(line)
            if list_match:
                current_list.append(list_match.group(1).strip())
                continue
            result[current_key] = current_list
            current_key = None
            current_list = None

        scalar_match = SCALAR_RE.match(line)
        if not scalar_match:
            continue

        key = scalar_match.group(1)
        raw = scalar_match.group(2).strip()
        if raw == "":
            current_key = key
            current_list = []
        elif raw.startswith("[") and raw.endswith("]"):
            inner = raw[1:-1].strip()
            if not inner:
                result[key] = []
            else:
                result[key] = [
                    value.strip().strip('"').strip("'")
                    for value in inner.split(",")
                    if value.strip()
                ]
        else:
            result[key] = raw.strip('"').strip("'")

    if current_key is not None and current_list is not None:
        result[current_key] = current_list

    return result


def iter_obsidian_reports(obsidian_dir: Path) -> Iterable[tuple[Path, dict]]:
    for md_file in sorted(obsidian_dir.rglob("*.md")):
        if md_file.name.startswith("."):
            continue
        try:
            text = md_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        frontmatter = parse_frontmatter(text)
        if frontmatter.get("type") != "Rapport-WUDD-ai":
            continue
        yield md_file, frontmatter


def starts_with_date(filename: str) -> bool:
    return bool(DATE_PREFIX_RE.match(filename))


def normalize_relpath(path: Path, base_dir: Path) -> str:
    try:
        return path.resolve().relative_to(base_dir.resolve()).as_posix()
    except ValueError:
        return path.name


def resolve_vault_root(obsidian_dir: Path, vault_name: str) -> Path:
        """Retrouve la racine du vault a partir du nom de vault et du sous-dossier cible.

        Exemple:
            obsidian_dir = /.../Coffre-de-Pat/Rapports-WUDD-ai
            vault_name   = Coffre-de-Pat
            -> vault_root = /.../Coffre-de-Pat
        """
        resolved = obsidian_dir.resolve()
        parts = list(resolved.parts)
        for idx, part in enumerate(parts):
                if part == vault_name:
                        return Path(*parts[: idx + 1])
        # Fallback: supposer que le dossier fourni est la racine du vault.
        return resolved


def extract_date_hint(frontmatter: dict) -> str:
    raw = str(frontmatter.get("date") or "").strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}$", raw):
        return raw

    raw = str(frontmatter.get("date_publication") or "").strip()
    fr_match = re.match(r"^(\d{2})/(\d{2})/(\d{4})$", raw)
    if fr_match:
        day, month, year = fr_match.groups()
        return f"{year}-{month}-{day}"

    return ""


def build_url_index(rss_dir: Path) -> dict[str, list[ArticleRef]]:
    index: dict[str, list[ArticleRef]] = {}
    for json_file in sorted(rss_dir.glob("*.json")):
        if json_file.name.startswith("."):
            continue
        try:
            articles = json.loads(json_file.read_text(encoding="utf-8"))
        except Exception:
            continue

        if not isinstance(articles, list):
            continue

        for article_index, article in enumerate(articles):
            if not isinstance(article, dict):
                continue
            url = str(article.get("URL") or "").strip()
            if not url:
                continue
            rapports = article.get("rapports")
            if not isinstance(rapports, list):
                rapports = []
            index.setdefault(url, []).append(
                ArticleRef(
                    json_file=json_file,
                    article_index=article_index,
                    url=url,
                    rapports=rapports,
                )
            )
    return index


def score_candidate(current_name: str, candidate_name: str, chemin_name: str, date_hint: str) -> int:
    score = 0
    if candidate_name == current_name:
        score += 100
    if chemin_name == current_name:
        score += 80
    if date_hint and candidate_name.startswith(date_hint):
        score += 20
    if starts_with_date(candidate_name):
        score += 5
    return score


def resolve_target_name(current_name: str, frontmatter: dict, refs: list[ArticleRef]) -> tuple[str | None, ArticleRef | None, str]:
    date_hint = extract_date_hint(frontmatter)
    candidates: list[tuple[int, str, ArticleRef]] = []

    for ref in refs:
        for rapport in ref.rapports:
            if not isinstance(rapport, dict):
                continue
            if rapport.get("cible") not in (None, "obsidian"):
                continue
            candidate_name = Path(str(rapport.get("fichier") or "")).name
            if not candidate_name:
                continue
            chemin_name = Path(str(rapport.get("chemin") or "")).name if rapport.get("chemin") else ""
            candidates.append(
                (score_candidate(current_name, candidate_name, chemin_name, date_hint), candidate_name, ref)
            )

    if not candidates:
        return None, None, "aucune entree rapports[].fichier" 

    unique_names = sorted({candidate_name for _, candidate_name, _ in candidates})
    if len(unique_names) == 1:
        only_name = unique_names[0]
        for _, candidate_name, ref in candidates:
            if candidate_name == only_name:
                return only_name, ref, "nom unique via URL"

    exact_matches = [item for item in candidates if item[0] >= 80]
    exact_names = sorted({candidate_name for _, candidate_name, _ in exact_matches})
    if len(exact_names) == 1:
        selected = exact_names[0]
        for _, candidate_name, ref in exact_matches:
            if candidate_name == selected:
                return selected, ref, "correspondance exacte avec le fichier courant"

    if date_hint:
        dated = [item for item in candidates if item[1].startswith(date_hint)]
        dated_names = sorted({candidate_name for _, candidate_name, _ in dated})
        if len(dated_names) == 1:
            selected = dated_names[0]
            for _, candidate_name, ref in dated:
                if candidate_name == selected:
                    return selected, ref, "nom unique via date du frontmatter"

    return None, None, f"plusieurs noms cibles possibles : {', '.join(unique_names[:5])}"


def build_plan(
    obsidian_dir: Path,
    url_index: dict[str, list[ArticleRef]],
    limit: int,
    verbose: bool,
) -> tuple[list[RenamePlan], dict[str, int]]:
    plans: list[RenamePlan] = []
    stats = {
        "reports_seen": 0,
        "article_reports_seen": 0,
        "already_ok": 0,
        "checked": 0,
        "missing_url": 0,
        "not_found": 0,
        "ambiguous": 0,
    }

    for md_path, frontmatter in iter_obsidian_reports(obsidian_dir):
        stats["reports_seen"] += 1
        article_url = str(frontmatter.get("url") or "").strip()
        if not article_url:
            continue

        stats["article_reports_seen"] += 1
        if starts_with_date(md_path.name):
            stats["already_ok"] += 1
            if verbose:
                print_console(f"OK    {md_path.name}")
            continue

        if limit > 0 and stats["checked"] >= limit:
            break
        stats["checked"] += 1

        refs = url_index.get(article_url)
        if not refs:
            stats["not_found"] += 1
            if verbose:
                print_console(f"SKIP  {md_path.name} -> URL introuvable dans data/articles-from-rss")
            continue

        target_name, article_ref, reason = resolve_target_name(md_path.name, frontmatter, refs)
        if not target_name or article_ref is None:
            stats["ambiguous"] += 1
            if verbose:
                print_console(f"SKIP  {md_path.name} -> {reason}")
            continue

        plans.append(
            RenamePlan(
                source_path=md_path,
                target_name=target_name,
                article_ref=article_ref,
                reason=reason,
            )
        )
        if verbose:
            print_console(f"PLAN  {md_path.name} -> {target_name} ({reason})")

    return plans, stats


def build_command(template: str, plan: RenamePlan, obsidian_dir: Path, vault_name: str) -> str:
    old_abs = str(plan.source_path)
    new_abs = str(plan.target_path)
    old_rel = normalize_relpath(plan.source_path, obsidian_dir)
    new_rel = normalize_relpath(plan.target_path, obsidian_dir)
    values = {
        "old_abs": old_abs,
        "new_abs": new_abs,
        "old_rel": old_rel,
        "new_rel": new_rel,
        "old_name": plan.source_path.name,
        "new_name": plan.target_name,
        "vault_dir": str(obsidian_dir),
        "vault_name": vault_name,
        "old_abs_q": shlex.quote(old_abs),
        "new_abs_q": shlex.quote(new_abs),
        "old_rel_q": shlex.quote(old_rel),
        "new_rel_q": shlex.quote(new_rel),
        "old_name_q": shlex.quote(plan.source_path.name),
        "new_name_q": shlex.quote(plan.target_name),
        "vault_dir_q": shlex.quote(str(obsidian_dir)),
        "vault_name_q": shlex.quote(vault_name),
    }
    return template.format_map(values)


def build_obsidian_cli_args(plan: RenamePlan, vault_root: Path, vault_name: str) -> list[str]:
    # `file=` est plus tolerant que `path=` sur certains noms accentues.
    # On conserve vault=... pour limiter la resolution au bon coffre.
    _old_rel = normalize_relpath(plan.source_path, vault_root)
    file_name_nfc = unicodedata.normalize("NFC", plan.source_path.name)
    return [
        "obsidian",
        "rename",
        f"vault={vault_name}",
        f"file={file_name_nfc}",
        f"name={plan.target_name}",
    ]


def shell_preview(args: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in args)


def execute_plan(
    plans: list[RenamePlan],
    obsidian_dir: Path,
    rename_command: str,
    vault_name: str,
    dry_run: bool,
) -> tuple[int, int]:
    renamed = 0
    failed = 0
    vault_root = resolve_vault_root(obsidian_dir, vault_name)

    for plan in plans:
        if plan.target_path == plan.source_path:
            print_console(f"SKIP  {plan.source_path.name} -> deja conforme")
            continue

        if plan.target_path.exists() and plan.target_path != plan.source_path:
            failed += 1
            print_console(
                f"ERREUR collision : {plan.target_path.name} existe deja pour {plan.source_path.name}",
                "error",
            )
            continue

        use_custom_command = bool(rename_command)
        if use_custom_command:
            command = build_command(rename_command, plan, obsidian_dir, vault_name)
        else:
            command_args = build_obsidian_cli_args(plan, vault_root, vault_name)
            command = shell_preview(command_args)
        prefix = "[dry-run] " if dry_run else ""
        print_console(
            f"{prefix}{plan.source_path.name} -> {plan.target_name} "
            f"[{plan.article_ref.json_file.name}#{plan.article_ref.article_index}]"
        )

        if dry_run:
            print_console(f"  commande : {command}")
            continue

        if use_custom_command:
            completed = subprocess.run(
                command,
                shell=True,
                text=True,
                capture_output=True,
            )
        else:
            completed = subprocess.run(
                command_args,
                shell=False,
                text=True,
                capture_output=True,
            )
        if completed.returncode != 0:
            failed += 1
            stderr = (completed.stderr or completed.stdout or "commande de renommage en echec").strip()
            print_console(f"  echec : {stderr}", "error")
            continue

        # Obsidian CLI peut retourner RC=0 tout en affichant une erreur textuelle.
        out = (completed.stdout or "").strip().lower()
        if "error:" in out or "not found" in out:
            failed += 1
            print_console(f"  echec : {completed.stdout.strip()}", "error")
            continue

        # Verification defensive: certains appels CLI peuvent retourner 0 sans
        # effet si le path est mal resolu.
        if plan.source_path.exists() and not plan.target_path.exists():
            failed += 1
            print_console(
                "  echec : commande retournee sans erreur mais fichier non renomme "
                f"({plan.source_path.name} toujours present)",
                "error",
            )
            continue

        renamed += 1

    return renamed, failed


def main() -> int:
    args = parse_args()
    config = get_config()

    obsidian_dir_str = args.dir or os.environ.get("OBSIDIAN_DIR", "").strip()
    if not obsidian_dir_str:
        print_console(
            "ERREUR : OBSIDIAN_DIR n'est pas configure. Utilisez --dir ou renseignez .env.",
            "error",
        )
        return 1

    obsidian_dir = Path(obsidian_dir_str).expanduser().resolve()
    if not obsidian_dir.is_dir():
        print_console(f"ERREUR : repertoire Obsidian introuvable : {obsidian_dir}", "error")
        return 1

    if not args.dry_run and not args.rename_command.strip() and shutil.which("obsidian") is None:
        print_console(
            "ERREUR : commande 'obsidian' introuvable. Installez Obsidian CLI "
            "ou utilisez --rename-command.",
            "error",
        )
        return 1

    rss_dir = config.project_root / "data" / "articles-from-rss"
    if not rss_dir.is_dir():
        print_console(f"ERREUR : repertoire introuvable : {rss_dir}", "error")
        return 1

    vault_name = args.vault_name.strip() or obsidian_dir.name
    limit_label = "sans limite" if args.limit == 0 else str(args.limit)
    mode = "DRY-RUN" if args.dry_run else "EXECUTION"
    print_console(
        f"{mode} rename_obsidian_reports.py - vault={obsidian_dir} - limit={limit_label}"
    )

    print_console("Construction de l'index URL depuis data/articles-from-rss...")
    url_index = build_url_index(rss_dir)
    print_console(f"  {len(url_index)} URL indexees")

    print_console("Analyse des rapports Obsidian...")
    plans, stats = build_plan(
        obsidian_dir=obsidian_dir,
        url_index=url_index,
        limit=args.limit,
        verbose=args.verbose,
    )

    print_console(
        "  rapports WUDD.ai vus : {reports_seen} | rapports d'articles : {article_reports_seen} | "
        "deja conformes : {already_ok} | verifies : {checked} | URL absentes : {missing_url} | "
        "introuvables : {not_found} | ambigus : {ambiguous} | a renommer : {to_rename}".format(
            to_rename=len(plans),
            **stats,
        )
    )

    renamed, failed = execute_plan(
        plans=plans,
        obsidian_dir=obsidian_dir,
        rename_command=args.rename_command.strip(),
        vault_name=vault_name,
        dry_run=args.dry_run,
    )

    print_console(
        f"Termine - renommes : {renamed} | echecs : {failed} | dry-run : {'oui' if args.dry_run else 'non'}"
    )
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())