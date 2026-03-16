"""
WUDD.ai Viewer — fonctions utilitaires partagées entre les blueprints Flask.
"""

import datetime
import json
import os
from pathlib import Path

from flask import abort

# La racine du projet est le dossier parent de viewer/
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def safe_path(relative: str) -> Path:
    """Résout et valide un chemin pour qu'il reste dans PROJECT_ROOT."""
    resolved = (PROJECT_ROOT / relative).resolve()
    if not str(resolved).startswith(str(PROJECT_ROOT) + "/") and resolved != PROJECT_ROOT:
        abort(403, "Accès refusé")
    if not resolved.exists():
        abort(404, "Fichier non trouvé")
    return resolved


def collect_files() -> list:
    files = []

    def scan(directory: Path, file_type: str, flux_override: str | None = None):
        if not directory.exists():
            return
        exts = ["*.json"] if file_type == "json" else ["*.md", "*.markdown"]
        for ext in exts:
            # Matérialiser le générateur rglob() pour intercepter les OSError
            # survenant pendant le parcours (volumes Docker, race avec cron)
            try:
                paths = list(directory.rglob(ext))
            except OSError:
                paths = []
            for f in paths:
                parts = f.relative_to(PROJECT_ROOT).parts
                if any(p in ("cache", ".git") for p in parts):
                    continue
                try:
                    stat = f.stat()
                    rel = f.relative_to(PROJECT_ROOT)
                    flux = flux_override or (f.parent.name if f.parent != directory else "")
                    files.append({
                        "name": f.name,
                        "path": str(rel).replace("\\", "/"),
                        "type": file_type,
                        "flux": flux,
                        "size": stat.st_size,
                        "modified": stat.st_mtime,
                    })
                except OSError:
                    continue

    # Scan large de data/ : couvre articles/, articles-from-rss/, et toute
    # autre structure que l'utilisateur pourrait avoir sous data/
    scan(PROJECT_ROOT / "data", "json")
    scan(PROJECT_ROOT / "rapports", "markdown")
    # Fichiers d'exemple (visibles tant que data/ et rapports/ sont vides)
    scan(PROJECT_ROOT / "samples", "json",     "Samples")
    scan(PROJECT_ROOT / "samples", "markdown", "Samples")
    return sorted(files, key=lambda x: x["modified"], reverse=True)


def parse_cron_field(s: str, lo: int, hi: int) -> list:
    if s == "*":
        return list(range(lo, hi + 1))
    if s.startswith("*/"):
        step = int(s[2:])
        return list(range(lo, hi + 1, step))
    if "," in s:
        return [int(x) for x in s.split(",")]
    if "-" in s:
        # Gère a-b/step (ex: 6-22/2) et a-b
        if "/" in s:
            rng, step_str = s.split("/", 1)
            a, b = rng.split("-", 1)
            return list(range(int(a), int(b) + 1, int(step_str)))
        a, b = s.split("-", 1)
        return list(range(int(a), int(b) + 1))
    return [int(s)]


def next_cron_occurrence(cron: str, after: datetime.datetime | None = None) -> datetime.datetime | None:
    """Calcule la prochaine occurrence d'une expression cron à 5 champs."""
    if after is None:
        after = datetime.datetime.now()
    parts = cron.strip().split()
    if len(parts) != 5:
        return None
    try:
        minutes = parse_cron_field(parts[0], 0, 59)
        hours   = parse_cron_field(parts[1], 0, 23)
        doms    = parse_cron_field(parts[2], 1, 31)
        months  = parse_cron_field(parts[3], 1, 12)
        # cron DOW: 0=dim…6=sam ; Python isoweekday: 1=lun…7=dim
        if parts[4] == "*":
            dows = set(range(1, 8))
        else:
            raw = parse_cron_field(parts[4], 0, 7)
            # 0 et 7 = dimanche (isoweekday=7)
            dows = set(7 if d in (0, 7) else d for d in raw)

        current = after.replace(second=0, microsecond=0) + datetime.timedelta(minutes=1)
        end = after + datetime.timedelta(days=35)

        while current <= end:
            if (current.month in months
                    and current.day in doms
                    and current.isoweekday() in dows
                    and current.hour in hours
                    and current.minute in minutes):
                return current
            # Optimisation : avancer directement à la bonne minute
            valid_mins = sorted(m for m in minutes if m > current.minute)
            if not valid_mins:
                current = current.replace(minute=0) + datetime.timedelta(hours=1)
            else:
                current = current.replace(minute=valid_mins[0])
        return None
    except (ValueError, IndexError):
        return None


def cron_label(cron: str) -> str:
    """Description humaine en français d'une expression cron courante."""
    p = cron.strip().split()
    if len(p) != 5:
        return cron
    minute, hour, dom, month, dow = p
    jours = ["Dimanche", "Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi"]

    # Toutes les N minutes : */N * * * *
    if minute.startswith("*/"):
        return f"Toutes les {minute[2:]} min"

    # Toutes les Xh entre heures : 0 6-22/2 * * *
    if minute == "0" and "/" in hour and "-" in hour and dom == "*":
        try:
            range_part, step = hour.split("/")
            start, end = range_part.split("-")
            return f"Toutes les {step}h de {start}h à {end}h"
        except ValueError:
            pass

    # Heure H:M — construire le libellé d'heure
    if minute.isdigit() and hour.isdigit():
        t = f"{int(hour):02d}:{int(minute):02d}"

        # Fin de mois (dom 28-31) : M H 28-31 * *
        if dom == "28-31" and month == "*" and dow == "*":
            return f"Fin de mois à {t}"

        # Jour de semaine spécifique, tous les mois : M H * * D
        if dom == "*" and month == "*" and dow.isdigit():
            try:
                return f"{jours[int(dow) % 7]} à {t}"
            except (ValueError, IndexError):
                pass

        # Quotidien : M H * * *
        if dom == "*" and month == "*" and dow == "*":
            return f"Quotidien à {t}"

    return cron


def latest_mtime(directory: Path) -> datetime.datetime | None:
    """Retourne la date de modification du fichier JSON le plus récent dans directory."""
    if not directory.exists():
        return None
    candidates = [
        f for f in directory.rglob("*.json")
        if "cache" not in f.relative_to(directory).parts
    ]
    if not candidates:
        return None
    return datetime.datetime.fromtimestamp(max(f.stat().st_mtime for f in candidates))


def _call_ai_blocking(prompt: str, timeout: int = 90,
                      enable_web_search: bool = False) -> str:
    """Appel synchrone bloquant à l'API IA configurée (EurIA ou Claude).

    Consomme le stream SSE en interne et retourne le texte complet généré.
    Filtre les blocs <think>…</think> (Qwen3 chain-of-thought).
    Retourne "" en cas d'erreur ou de configuration manquante.
    """
    import re
    import requests as _req
    provider = os.environ.get("AI_PROVIDER", "euria").strip().lower()
    chunks: list[str] = []

    if provider == "claude":
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            return ""
        try:
            from utils.api_client import ClaudeClient as _CC
            _claude = _CC(api_key=api_key)
            for chunk in _claude.stream(prompt=prompt, timeout=timeout):
                chunk = chunk.strip()
                if not chunk or chunk == "data: [DONE]":
                    continue
                raw = chunk[6:] if chunk.startswith("data: ") else chunk
                try:
                    d = json.loads(raw)
                    content = (d.get("choices") or [{}])[0].get("delta", {}).get("content", "")
                    if content:
                        chunks.append(content)
                except Exception:
                    pass
        except Exception:
            pass
    else:
        api_url = os.environ.get("URL", "")
        bearer  = os.environ.get("bearer", "")
        if not api_url or not bearer:
            return ""
        payload: dict = {
            "messages": [{"role": "user", "content": prompt}],
            "model": "qwen3",
            "stream": True,
        }
        if enable_web_search:
            payload["enable_web_search"] = True
        api_headers = {
            "Authorization": f"Bearer {bearer}",
            "Content-Type": "application/json",
        }
        try:
            r = _req.post(api_url, json=payload, headers=api_headers,
                          stream=True, timeout=timeout)
            r.raise_for_status()
            for line in r.iter_lines():
                if not line:
                    continue
                decoded = line.decode("utf-8")
                raw = decoded[5:].strip() if decoded.startswith("data:") else decoded.strip()
                if raw == "[DONE]":
                    break
                try:
                    d = json.loads(raw)
                    content = (d.get("choices") or [{}])[0].get("delta", {}).get("content", "")
                    if content:
                        chunks.append(content)
                except Exception:
                    pass
        except Exception:
            pass

    full_text = "".join(chunks)
    # Supprimer les blocs <think>…</think> (chain-of-thought Qwen3)
    full_text = re.sub(r"<think>.*?</think>", "", full_text, flags=re.DOTALL).strip()
    return full_text
