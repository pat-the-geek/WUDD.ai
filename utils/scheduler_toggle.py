#!/usr/bin/env python3
"""Gestion centralisee des activations/desactivations de taches cron."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _flags_file(project_root: Path | None = None) -> Path:
    root = project_root or _project_root()
    return root / "config" / "scheduler_tasks.json"


def _load_flags(project_root: Path | None = None) -> dict[str, bool]:
    path = _flags_file(project_root)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, bool] = {}
    for key, val in data.items():
        if isinstance(key, str):
            out[key] = bool(val)
    return out


def is_task_enabled(task_key: str | None, default: bool = True, project_root: Path | None = None) -> bool:
    """Retourne l'etat active/inactive d'une tache selon sa cle."""
    if not task_key:
        return default
    flags = _load_flags(project_root)
    return bool(flags.get(task_key, default))


def set_task_enabled(task_key: str, enabled: bool, project_root: Path | None = None) -> dict[str, bool]:
    """Persist l'etat d'une tache et retourne la map complete."""
    key = (task_key or "").strip()
    if not key:
        raise ValueError("task_key vide")
    path = _flags_file(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = _load_flags(project_root)
    flags[key] = bool(enabled)
    path.write_text(json.dumps(flags, ensure_ascii=False, indent=2), encoding="utf-8")
    return flags


def _should_enforce_toggles() -> bool:
    """Controle si les toggles doivent etre appliques a l'execution."""
    env_val = (os.getenv("WUDD_ENFORCE_TASK_TOGGLES") or "").strip().lower()
    if env_val in {"1", "true", "yes", "on"}:
        return True
    if env_val in {"0", "false", "no", "off"}:
        return False
    # Mode auto: on applique en contexte non interactif (cron/daemon).
    return not sys.stdout.isatty()


def should_run_task(task_key: str, default: bool = True, project_root: Path | None = None) -> bool:
    """Retourne False si la tache est desactivee et que l'execution doit etre bloquee."""
    if not _should_enforce_toggles():
        return True
    enabled = is_task_enabled(task_key, default=default, project_root=project_root)
    if enabled:
        return True
    msg = f"[scheduler] Tache desactivee ({task_key}) - execution ignoree"
    try:
        from utils.logging import print_console

        print_console(msg, level="info")
    except Exception:
        print(msg)
    return False
