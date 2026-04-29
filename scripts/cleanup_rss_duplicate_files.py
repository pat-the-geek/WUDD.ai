#!/usr/bin/env python3
"""Fusionne les fichiers JSON RSS aliases (ex: "keyword 2.json") vers un fichier canonique.

Usage:
  python3 scripts/cleanup_rss_duplicate_files.py --dry-run
  python3 scripts/cleanup_rss_duplicate_files.py --apply
"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path

import sys
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.deduplication import Deduplicator
from utils.rss_file_naming import canonical_stem, is_numbered_copy


DATA_DIR = PROJECT_ROOT / "data" / "articles-from-rss"
ROOT_DATA_DIR = PROJECT_ROOT / "data"


def cleanup_root_duplicates(apply: bool, archive_root: Path) -> dict:
    """Nettoie les copies suffixees en racine data/ pour des fichiers critiques.

    Cible explicitement : annotations.json, article_index.json, entity_index.json.
    """
    targets = {
        "annotations": ROOT_DATA_DIR / "annotations.json",
        "article_index": ROOT_DATA_DIR / "article_index.json",
        "entity_index": ROOT_DATA_DIR / "entity_index.json",
    }
    report = {
        "groups_total": 0,
        "groups_changed": 0,
        "files_archived": 0,
        "files_deleted": 0,
        "annotations_added": 0,
    }

    for stem, canonical_path in targets.items():
        aliases = sorted(ROOT_DATA_DIR.glob(f"{stem} *.json"), key=lambda p: p.name.lower())
        aliases = [p for p in aliases if p != canonical_path]
        if not aliases:
            continue
        report["groups_total"] += 1
        if not apply:
            continue

        archive_root.mkdir(parents=True, exist_ok=True)

        # Archive canonical + aliases before mutation.
        to_archive = [canonical_path] + aliases
        for src in to_archive:
            if not src.exists():
                continue
            rel = src.relative_to(PROJECT_ROOT)
            dst = archive_root / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            report["files_archived"] += 1

        # Fusion conservatrice pour annotations.
        if stem == "annotations" and canonical_path.exists():
            try:
                canonical = json.loads(canonical_path.read_text(encoding="utf-8"))
                if isinstance(canonical, dict):
                    for alias in aliases:
                        alias_data = json.loads(alias.read_text(encoding="utf-8"))
                        if not isinstance(alias_data, dict):
                            continue
                        for url, value in alias_data.items():
                            if url not in canonical:
                                canonical[url] = value
                                report["annotations_added"] += 1
                    canonical_path.write_text(
                        json.dumps(canonical, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
            except Exception:
                pass

        for alias in aliases:
            if alias.exists():
                alias.unlink()
                report["files_deleted"] += 1

        report["groups_changed"] += 1

    return report


def _write_atomic(path: Path, payload: list[dict]) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _load_articles(path: Path) -> list[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    return [a for a in data if isinstance(a, dict)]


def _canonical_file_name(stem: str) -> str:
    return f"{canonical_stem(stem)}.json"


def _pick_canonical_file(files: list[Path]) -> Path:
    # Prefer a non-numbered file if available, then shortest name.
    non_numbered = [p for p in files if not is_numbered_copy(p)]
    if non_numbered:
        return sorted(non_numbered, key=lambda p: (len(p.name), p.name.lower()))[0]
    return sorted(files, key=lambda p: (len(p.name), p.name.lower()))[0]


def _group_aliases(scan_dir: Path) -> dict[tuple[Path, str], list[Path]]:
    groups: dict[tuple[Path, str], list[Path]] = {}
    for jf in scan_dir.rglob("*.json"):
        if "cache" in jf.parts:
            continue
        key = (jf.parent, canonical_stem(jf.stem))
        groups.setdefault(key, []).append(jf)
    return groups


def cleanup_duplicates(apply: bool, archive_root: Path) -> dict:
    groups = _group_aliases(DATA_DIR)
    report = {
        "groups_total": 0,
        "groups_changed": 0,
        "files_archived": 0,
        "files_deleted": 0,
        "articles_before": 0,
        "articles_after": 0,
        "details": [],
    }

    for (parent, stem_key), files in sorted(groups.items(), key=lambda x: (str(x[0][0]), x[0][1])):
        canonical_name = _canonical_file_name(stem_key)
        canonical_path = parent / canonical_name

        needs_merge = len(files) > 1
        needs_rename = any(f.name != canonical_name for f in files)
        if not (needs_merge or needs_rename):
            continue

        report["groups_total"] += 1

        # Merge all articles from aliases.
        merged_candidates: list[dict] = []
        file_sizes = {}
        for f in sorted(files, key=lambda p: p.name.lower()):
            arts = _load_articles(f)
            merged_candidates.extend(arts)
            file_sizes[f.name] = len(arts)

        report["articles_before"] += len(merged_candidates)

        dedup = Deduplicator(title_threshold=0.85)
        merged_unique = dedup.deduplicate(merged_candidates)
        report["articles_after"] += len(merged_unique)

        group_info = {
            "directory": str(parent.relative_to(PROJECT_ROOT)).replace("\\", "/"),
            "stem": stem_key,
            "canonical": canonical_name,
            "aliases": [f.name for f in sorted(files, key=lambda p: p.name.lower())],
            "counts": file_sizes,
            "merged": len(merged_unique),
            "removed": dedup.stats.get("removed", 0),
        }
        report["details"].append(group_info)

        if not apply:
            continue

        archive_root.mkdir(parents=True, exist_ok=True)

        # Archive all source files before mutation.
        for src in sorted(files, key=lambda p: p.name.lower()):
            rel = src.relative_to(PROJECT_ROOT)
            dst = archive_root / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            report["files_archived"] += 1

        # Write canonical merged file.
        canonical_path.parent.mkdir(parents=True, exist_ok=True)
        _write_atomic(canonical_path, merged_unique)

        # Delete aliases except canonical file path.
        for src in sorted(files, key=lambda p: p.name.lower()):
            if src.resolve() == canonical_path.resolve():
                continue
            if src.exists():
                src.unlink()
                report["files_deleted"] += 1

        report["groups_changed"] += 1

    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Nettoie les doublons de fichiers JSON RSS (suffixes numeriques).")
    parser.add_argument("--apply", action="store_true", help="Applique les changements (sinon simulation).")
    args = parser.parse_args()

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_root = PROJECT_ROOT / "archives" / f"rss-duplicate-cleanup-{ts}"

    report = cleanup_duplicates(apply=args.apply, archive_root=archive_root)
    root_report = cleanup_root_duplicates(apply=args.apply, archive_root=archive_root)

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"[{mode}] groupes candidats: {report['groups_total']}")
    print(f"[{mode}] groupes candidats (racine data): {root_report['groups_total']}")
    if args.apply:
        print(f"[{mode}] groupes modifies: {report['groups_changed']}")
        print(f"[{mode}] groupes modifies (racine data): {root_report['groups_changed']}")
        print(f"[{mode}] fichiers archives: {report['files_archived']}")
        print(f"[{mode}] fichiers archives (racine data): {root_report['files_archived']}")
        print(f"[{mode}] fichiers supprimes: {report['files_deleted']}")
        print(f"[{mode}] fichiers supprimes (racine data): {root_report['files_deleted']}")
        if root_report['annotations_added']:
            print(f"[{mode}] annotations fusionnees (ajoutees): {root_report['annotations_added']}")
        print(f"[{mode}] archive: {archive_root}")
    print(f"[{mode}] articles concat: {report['articles_before']} -> uniques: {report['articles_after']}")

    for d in report["details"]:
        aliases = ", ".join(d["aliases"])
        print(f"  - {d['directory']} :: {aliases} -> {d['canonical']} (merged={d['merged']}, removed={d['removed']})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
