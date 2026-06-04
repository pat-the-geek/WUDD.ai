"""Persistance de la consommation IA (tokens) — append-only JSONL par jour.

Indépendant des logs cron (robuste à la rotation). Une ligne JSON par appel IA,
ajoutée en mode append (pas de read-modify-write → pas de course concurrente).
Alimente aussi les métriques Prometheus (utils/metrics) si disponibles.

Format d'une ligne : {"ts","provider","operation","prompt","completion","total"}
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from .logging import default_logger

_USAGE_DIR = Path(__file__).resolve().parent.parent / "data" / "ai_usage"


def record_ai_usage(provider: str, prompt_tokens=0, completion_tokens=0,
                    operation: str = "ai") -> None:
    """Enregistre la consommation d'un appel IA (JSONL + Prometheus, best-effort)."""
    try:
        prompt = int(prompt_tokens or 0)
    except (TypeError, ValueError):
        prompt = 0
    try:
        completion = int(completion_tokens or 0)
    except (TypeError, ValueError):
        completion = 0

    # Métriques Prometheus (#10) — sans jamais casser l'appel IA
    try:
        from . import metrics
        metrics.record_ai_call(str(provider).lower(), operation, "success",
                               tokens_prompt=prompt, tokens_completion=completion)
    except Exception:
        pass

    # Persistance JSONL (#3)
    try:
        _USAGE_DIR.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc)
        rec = {"ts": now.isoformat(), "provider": str(provider), "operation": operation,
               "prompt": prompt, "completion": completion, "total": prompt + completion}
        with open(_USAGE_DIR / f"{now.strftime('%Y-%m-%d')}.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError as exc:
        default_logger.debug(f"ai_usage non persisté : {exc}")


def aggregate_usage(project_root, date_str: str) -> dict:
    """Agrège un jour depuis le JSONL → {provider: {calls, prompt, completion, total}}."""
    f = Path(project_root) / "data" / "ai_usage" / f"{date_str}.jsonl"
    out: dict = {}
    if not f.exists():
        return out
    try:
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            p = str(r.get("provider", "?"))
            d = out.setdefault(p, {"calls": 0, "prompt": 0, "completion": 0, "total": 0})
            d["calls"] += 1
            d["prompt"] += int(r.get("prompt", 0) or 0)
            d["completion"] += int(r.get("completion", 0) or 0)
            d["total"] += int(r.get("total", 0) or 0)
    except OSError:
        pass
    return out
