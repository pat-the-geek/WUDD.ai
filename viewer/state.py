"""
WUDD.ai Viewer — état global partagé entre les blueprints Flask.
"""

import os
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

# Cache TTL en mémoire pour /api/files
_files_manifest_lock = threading.Lock()
_files_manifest_cache: dict = {"data": None, "ts": 0.0, "count": 0}
_FILES_MANIFEST_TTL = max(1, int(os.environ.get("VIEWER_FILES_CACHE_TTL", "30")))
_FILES_MANIFEST_DOUBLE_SCAN_FALLBACK = os.environ.get(
    "VIEWER_FILES_DOUBLE_SCAN_FALLBACK", "1"
).strip().lower() not in {"0", "false", "no", "off"}
_FILES_MANIFEST_DROP_RATIO = min(
    max(float(os.environ.get("VIEWER_FILES_CACHE_DROP_RATIO", "0.85")), 0.0),
    1.0,
)
_FILES_MANIFEST_DROP_TOLERANCE = max(
    1, int(os.environ.get("VIEWER_FILES_CACHE_DROP_TOLERANCE", "5"))
)


def _invalidate_bias_cache() -> None:
    """Invalide le cache /api/sources/bias.

    À appeler après toute modification d'un fichier JSON dans data/ susceptible
    de contenir des champs sentiment/score_sentiment/ton_editorial.
    """
    _bias_cache["data"] = None
    _bias_cache["ts"] = 0.0


def _invalidate_files_manifest_cache() -> None:
    """Invalide le cache du manifeste /api/files."""
    with _files_manifest_lock:
        _files_manifest_cache["data"] = None
        _files_manifest_cache["ts"] = 0.0


def _get_files_manifest(builder, fallback_builder=None):
    """Retourne le manifeste /api/files depuis le cache TTL ou le reconstruit.

    builder doit retourner la liste de fichiers triée par date de modification.
    fallback_builder, s'il est fourni, est déclenché lorsque le scan simple semble
    anormalement incomplet par rapport au manifeste précédent.
    """
    now = _time.time()
    cached = _files_manifest_cache["data"]
    if cached is not None and (now - _files_manifest_cache["ts"]) < _FILES_MANIFEST_TTL:
        return cached

    with _files_manifest_lock:
        now = _time.time()
        cached = _files_manifest_cache["data"]
        if cached is not None and (now - _files_manifest_cache["ts"]) < _FILES_MANIFEST_TTL:
            return cached

        previous_count = int(_files_manifest_cache.get("count") or 0)
        files = builder()
        current_count = len(files)

        if (
            fallback_builder is not None
            and _FILES_MANIFEST_DOUBLE_SCAN_FALLBACK
            and previous_count > 0
            and current_count + _FILES_MANIFEST_DROP_TOLERANCE < previous_count
            and current_count < int(previous_count * _FILES_MANIFEST_DROP_RATIO)
        ):
            files = fallback_builder(files)
            current_count = len(files)

        _files_manifest_cache["data"] = files
        _files_manifest_cache["ts"] = now
        _files_manifest_cache["count"] = current_count
        return files
