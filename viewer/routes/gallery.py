"""
viewer/routes/gallery.py — Blueprint Flask pour la galerie d'images article.
"""

from __future__ import annotations

import ipaddress
import json
import socket
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

import requests
from flask import Blueprint, Response, abort, jsonify, request

from utils.article_index import get_article_index
from utils.http_utils import extract_top_n_largest_images
from viewer.helpers import PROJECT_ROOT


gallery_bp = Blueprint("gallery", __name__)

# Fichiers rolling-window régénérés périodiquement : on ne les réécrit pas
# lors de la persistance de la galerie (évite de relire/réécrire de gros fichiers).
_ROLLING_WINDOW_NAMES: frozenset[str] = frozenset({"48-heures.json"})


# Cache mémoire court pour éviter les fetchs HTTP répétés sur la même URL.
_GALLERY_RUNTIME_CACHE_TTL_SECONDS = 600
_gallery_runtime_cache: dict[str, tuple[float, list[dict]]] = {}

_URL_SAFETY_CACHE_TTL_SECONDS = 3600
_url_safety_cache: dict[str, tuple[float, bool]] = {}


def _runtime_cache_key(article_url: str, max_images: int) -> str:
    return f"{_normalize_url(article_url)}::{int(max_images)}"


def _runtime_cache_get(article_url: str, max_images: int) -> list[dict] | None:
    key = _runtime_cache_key(article_url, max_images)
    entry = _gallery_runtime_cache.get(key)
    if not entry:
        return None
    ts, payload = entry
    if (time.time() - ts) > _GALLERY_RUNTIME_CACHE_TTL_SECONDS:
        _gallery_runtime_cache.pop(key, None)
        return None
    return payload


def _runtime_cache_set(article_url: str, max_images: int, gallery: list[dict]) -> None:
    key = _runtime_cache_key(article_url, max_images)
    _gallery_runtime_cache[key] = (time.time(), gallery)


def _url_safety_cache_get(host: str) -> bool | None:
    entry = _url_safety_cache.get(host)
    if not entry:
        return None
    ts, allowed = entry
    if (time.time() - ts) > _URL_SAFETY_CACHE_TTL_SECONDS:
        _url_safety_cache.pop(host, None)
        return None
    return allowed


def _url_safety_cache_set(host: str, allowed: bool) -> None:
    _url_safety_cache[host] = (time.time(), allowed)


def _normalize_url(url: str) -> str:
    return (url or "").strip().rstrip("/").lower()


def _is_basic_allowed_url(url: str) -> bool:
    """Validation légère et rapide: schéma HTTP(S) + hôte non local/privé."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return False

    if parsed.scheme not in ("http", "https"):
        return False

    host = (parsed.hostname or "").strip().lower()
    if not host:
        return False

    if host in {"localhost", "127.0.0.1", "::1"}:
        return False

    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return True

    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _is_public_http_url(url: str) -> bool:
    """Valide schéma + hôte public (bloque loopback, LAN, link-local, etc.)."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return False

    if parsed.scheme not in ("http", "https"):
        return False

    host = (parsed.hostname or "").strip().lower()
    if not host:
        return False

    cached = _url_safety_cache_get(host)
    if cached is not None:
        return cached

    if host in {"localhost", "127.0.0.1", "::1"}:
        _url_safety_cache_set(host, False)
        return False

    def _is_forbidden_ip(ip_str: str) -> bool:
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            return False
        return (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        )

    if _is_forbidden_ip(host):
        _url_safety_cache_set(host, False)
        return False

    # Résolution DNS défensive : aucun endpoint local/réservé autorisé
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        _url_safety_cache_set(host, False)
        return False

    for info in infos:
        ip_str = info[4][0]
        if _is_forbidden_ip(ip_str):
            _url_safety_cache_set(host, False)
            return False

    _url_safety_cache_set(host, True)
    return True


_IMAGE_PROXY_MAX_BYTES = 15 * 1024 * 1024  # 15 Mo
_IMAGE_PROXY_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
}


@gallery_bp.route("/api/image-proxy")
def image_proxy():
    """
    Proxy same-origin pour images distantes — permet l'analyse pixel côté
    navigateur (détection visage/sujet) sur les CDN sans en-têtes CORS.

    Récupère l'image côté serveur (gardes SSRF + plafond de taille) et la
    renvoie en same-origin, donc le canvas n'est pas « tainted ».
    """
    url = (request.args.get("url") or "").strip()
    if not url or not _is_public_http_url(url):
        abort(400)

    try:
        resp = requests.get(
            url, headers=_IMAGE_PROXY_HEADERS, timeout=10, stream=True
        )
    except requests.RequestException:
        abort(502)

    if resp.status_code != 200:
        resp.close()
        abort(resp.status_code if 400 <= resp.status_code < 600 else 502)

    ctype = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
    if not ctype.startswith("image/"):
        resp.close()
        abort(415)  # pas une image

    chunks: list[bytes] = []
    total = 0
    try:
        for chunk in resp.iter_content(64 * 1024):
            if not chunk:
                continue
            total += len(chunk)
            if total > _IMAGE_PROXY_MAX_BYTES:
                resp.close()
                abort(413)  # image trop volumineuse
            chunks.append(chunk)
    except requests.RequestException:
        abort(502)
    finally:
        resp.close()

    out = Response(b"".join(chunks), content_type=ctype)
    out.headers["Cache-Control"] = "public, max-age=86400"
    out.headers["Access-Control-Allow-Origin"] = "*"
    return out


def _normalize_gallery(images: list[dict]) -> list[dict]:
    gallery: list[dict] = []
    seen: set[str] = set()

    for img in images:
        url = (img.get("url") or img.get("URL") or "").strip()
        if not url or url in seen:
            continue

        width = int(img.get("width") or img.get("Width") or 0)
        height = int(img.get("height") or img.get("Height") or 0)

        raw_area = img.get("area")
        if raw_area is None:
            raw_area = img.get("Area")
        area = int(raw_area) if isinstance(raw_area, (int, float, str)) and str(raw_area).strip() else (width * height)

        title = (img.get("title") or "").strip()
        alt = (img.get("alt") or "").strip()

        gallery.append({
            "URL": url,
            "width": width,
            "height": height,
            "area": area,
            "title": title,
            "alt": alt,
            # fallback "copyright" en l'absence de méta dédiée dans l'extracteur
            "copyright": title if "©" in title else (alt if "©" in alt else ""),
        })
        seen.add(url)

    gallery.sort(key=lambda x: int(x.get("area") or 0), reverse=True)
    return gallery


def _safe_json_file(candidate_path: str) -> Path | None:
    """Résout un chemin utilisateur vers un JSON du workspace, sinon None."""
    if not candidate_path:
        return None

    try:
        candidate = Path(candidate_path)
        if not candidate.is_absolute():
            candidate = PROJECT_ROOT / candidate
        resolved = candidate.resolve()
    except (OSError, RuntimeError, ValueError):
        return None

    root = str(PROJECT_ROOT.resolve())
    if not str(resolved).startswith(root + "/"):
        return None
    if resolved.suffix.lower() != ".json" or not resolved.exists():
        return None
    return resolved


def _article_exists_in_file(target: Path, article_url: str) -> bool:
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False

    if not isinstance(data, list):
        return False

    url_norm = _normalize_url(article_url)
    for article in data:
        if not isinstance(article, dict):
            continue
        if _normalize_url(article.get("URL") or "") == url_norm:
            return True
    return False


def _collect_target_files(article_url: str, file_hint: str = "", include_all_matches: bool = False) -> list[Path]:
    """Trouve les fichiers JSON qui contiennent l'article.

    Par défaut, privilégie les accès rapides (hint + index O(1)).
    Si include_all_matches=True, parcourt aussi l'index complet pour couvrir
    d'éventuels doublons de la même URL dans plusieurs fichiers.
    """
    targets: list[Path] = []
    seen: set[Path] = set()

    def _add_candidate(candidate: Path) -> None:
        if not str(candidate).startswith(str(PROJECT_ROOT) + "/"):
            return
        if candidate.suffix.lower() != ".json" or not candidate.exists():
            return
        if candidate in seen:
            return
        targets.append(candidate)
        seen.add(candidate)

    hint_target = _safe_json_file(file_hint)
    if hint_target:
        _add_candidate(hint_target)

    index = get_article_index(PROJECT_ROOT)
    direct_entry = index.get_by_url(article_url)
    if direct_entry:
        rel_file = (direct_entry.get("file") or "").strip()
        if rel_file:
            _add_candidate((PROJECT_ROOT / rel_file).resolve())

    if include_all_matches:
        url_norm = _normalize_url(article_url)
        for entry in index.get_articles():
            if _normalize_url(entry.get("url", "")) != url_norm:
                continue
            rel_file = (entry.get("file") or "").strip()
            if not rel_file:
                continue
            _add_candidate((PROJECT_ROOT / rel_file).resolve())

    return sorted(targets)


def _persist_gallery(article_url: str, gallery: list[dict], force_refresh: bool, file_hint: str = "") -> list[str]:
    updated_files: list[str] = []

    for target in _collect_target_files(article_url, file_hint=file_hint, include_all_matches=True):
        # Exclure les rolling windows (48-heures.json) : ils sont régénérés périodiquement
        # et les réécrire est coûteux sans gain durable.
        if target.name in _ROLLING_WINDOW_NAMES:
            continue
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue

        if not isinstance(data, list):
            continue

        changed = False
        for article in data:
            if not isinstance(article, dict):
                continue
            if _normalize_url(article.get("URL") or "") != _normalize_url(article_url):
                continue
            existing = article.get("galerie")
            if isinstance(existing, list) and not force_refresh:
                continue
            article["galerie"] = gallery
            changed = True

        if not changed:
            continue

        try:
            tmp = target.with_suffix(target.suffix + ".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(target)
            updated_files.append(str(target.relative_to(PROJECT_ROOT)).replace("\\", "/"))
        except OSError:
            continue

    return updated_files


def _find_existing_gallery_in_target(target: Path, article_url: str) -> list[dict] | None:
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    if not isinstance(data, list):
        return None

    url_norm = _normalize_url(article_url)
    for article in data:
        if not isinstance(article, dict):
            continue
        if _normalize_url(article.get("URL") or "") != url_norm:
            continue
        existing = article.get("galerie")
        if isinstance(existing, list):
            return existing
        return None

    return None


def _find_existing_gallery(article_url: str, file_hint: str = "") -> list[dict] | None:
    for target in _collect_target_files(article_url, file_hint=file_hint, include_all_matches=False):
        existing = _find_existing_gallery_in_target(target, article_url)
        if existing is not None:
            return existing
    return None


def _find_existing_images_in_target(target: Path, article_url: str) -> list[dict] | None:
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    if not isinstance(data, list):
        return None

    url_norm = _normalize_url(article_url)
    for article in data:
        if not isinstance(article, dict):
            continue
        if _normalize_url(article.get("URL") or "") != url_norm:
            continue
        raw_images = article.get("Images")
        if isinstance(raw_images, list) and raw_images:
            normalized = _normalize_gallery(raw_images)
            return normalized if normalized else None
        return None

    return None


def _find_existing_images(article_url: str, file_hint: str = "") -> list[dict] | None:
    for target in _collect_target_files(article_url, file_hint=file_hint, include_all_matches=False):
        existing = _find_existing_images_in_target(target, article_url)
        if existing is not None:
            return existing
    return None


def _find_article_data(article_url: str, file_hint: str = "") -> tuple["list[dict] | None", "list[dict] | None"]:
    """Lit le fichier source une seule fois et retourne (galerie, images_normalisées).

    Remplace les appels séparés à _find_existing_gallery + _find_existing_images
    pour éviter de relire un gros JSON deux fois de suite.
    """
    for target in _collect_target_files(article_url, file_hint=file_hint, include_all_matches=False):
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue

        if not isinstance(data, list):
            continue

        url_norm = _normalize_url(article_url)
        for article in data:
            if not isinstance(article, dict):
                continue
            if _normalize_url(article.get("URL") or "") != url_norm:
                continue

            galerie = article.get("galerie")
            galerie_result = galerie if isinstance(galerie, list) else None

            raw_images = article.get("Images")
            images_result = None
            if isinstance(raw_images, list) and raw_images:
                normalized = _normalize_gallery(raw_images)
                images_result = normalized if normalized else None

            return galerie_result, images_result

    return None, None


def _persist_gallery_background(article_url: str, gallery: list[dict], force_refresh: bool, file_hint: str = "") -> None:
    """Lance la persistance dans un thread daemon pour ne pas bloquer la réponse HTTP."""
    def _run() -> None:
        try:
            _persist_gallery(article_url, gallery, force_refresh, file_hint)
        except Exception:
            pass  # erreur de persistance silencieuse — ne doit jamais crasher le worker

    threading.Thread(target=_run, daemon=True).start()


@gallery_bp.route("/api/article/gallery", methods=["POST"])
def api_article_gallery():
    body = request.get_json(force=True, silent=True) or {}

    article_url = (body.get("article_url") or body.get("url") or "").strip()
    file_path = (body.get("file_path") or "").strip()
    max_images = body.get("max", 12)
    force_refresh = bool(body.get("force_refresh", False))

    try:
        max_images = max(1, min(int(max_images), 30))
    except (TypeError, ValueError):
        max_images = 12

    if not article_url or not _is_basic_allowed_url(article_url):
        return jsonify({"error": "article_url invalide ou non autorisée"}), 400

    # Limiter strictement aux URLs connues du corpus pour éviter un fetch arbitraire.
    index_hit = get_article_index(PROJECT_ROOT).get_by_url(article_url) is not None
    hint_target = _safe_json_file(file_path)
    hint_hit = bool(hint_target and (index_hit or _article_exists_in_file(hint_target, article_url)))
    if not index_hit and not hint_hit:
        return jsonify({"error": "article introuvable dans l'index"}), 404

    # 1) Cache runtime en mémoire (plus chaud que le disque)
    if not force_refresh:
        runtime_cached = _runtime_cache_get(article_url, max_images)
        if runtime_cached is not None:
            return jsonify({
                "ok": True,
                "gallery": runtime_cached,
                "cached": True,
                "runtime_cached": True,
                "updated_files": [],
            })

    # 2) Lecture unique du fichier source : galerie persistée OU Images de l'article
    if not force_refresh:
        galerie, fallback_images = _find_article_data(article_url, file_hint=file_path)

        # 2a) Galerie déjà persistée
        if galerie is not None:
            if galerie:
                _runtime_cache_set(article_url, max_images, galerie)
                return jsonify({
                    "ok": True,
                    "gallery": galerie,
                    "cached": True,
                    "updated_files": [],
                })
            # Galerie vide persistée → tenter le fallback Images (sans repersister)
            if fallback_images:
                _runtime_cache_set(article_url, max_images, fallback_images)
                return jsonify({
                    "ok": True,
                    "gallery": fallback_images,
                    "cached": True,
                    "from_images_field": True,
                    "updated_files": [],
                })

        # 2b) Pas de galerie → utiliser le champ Images directement (réponse instantanée)
        # Pas de persistance ici : les images viennent déjà du JSON source, le runtime
        # cache couvre les appels répétés dans la session.
        if fallback_images:
            _runtime_cache_set(article_url, max_images, fallback_images)
            return jsonify({
                "ok": True,
                "gallery": fallback_images,
                "cached": True,
                "from_images_field": True,
                "updated_files": [],
            })

    # 3) Dernier recours : fetch HTTP de la page article
    images = extract_top_n_largest_images(article_url, n=max_images, min_width=500, timeout=8)
    if not isinstance(images, list):
        images = []

    gallery = _normalize_gallery(images)
    _runtime_cache_set(article_url, max_images, gallery)
    _persist_gallery_background(article_url, gallery, force_refresh=force_refresh, file_hint=file_path)

    return jsonify({
        "ok": True,
        "gallery": gallery,
        "cached": False,
        "updated_files": [],
    })
