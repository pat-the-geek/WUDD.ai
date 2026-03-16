"""
WUDD.ai Viewer — état global partagé entre les blueprints Flask.
"""

import threading
import time as _time

# Verrou pour les annotations manuelles (data/annotations.json)
# Partagé entre entities.py et export.py
_annotations_lock = threading.Lock()

# Suivi du process RSS keyword (un seul à la fois)
_rss_job: dict = {
    "process": None,
    "lock": threading.Lock(),
    "last_run": None,        # ISO 8601 UTC — horodatage de la dernière fin d'exécution
    "last_returncode": None, # Code retour de la dernière exécution
}

# Cache TTL en mémoire pour /api/sources/bias (5 minutes)
_bias_cache: dict = {"data": None, "ts": 0.0}
_BIAS_CACHE_TTL = 300  # secondes


def _invalidate_bias_cache() -> None:
    """Invalide le cache /api/sources/bias.

    À appeler après toute modification d'un fichier JSON dans data/ susceptible
    de contenir des champs sentiment/score_sentiment/ton_editorial.
    """
    _bias_cache["data"] = None
    _bias_cache["ts"] = 0.0
