"""
viewer/routes/gallery.py — Blueprint Flask pour la galerie d'images article.
"""

from __future__ import annotations

import ipaddress
import json
import socket
from pathlib import Path
from urllib.parse import urlparse

from flask import Blueprint, jsonify, request

from utils.article_index import get_article_index
from utils.http_utils import extract_top_n_largest_images
from viewer.helpers import PROJECT_ROOT


gallery_bp = Blueprint("gallery", __name__)


def _normalize_url(url: str) -> str:
    return (url or "").strip().rstrip("/").lower()


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

    if host in {"localhost", "127.0.0.1", "::1"}:
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
        return False

    # Résolution DNS défensive : aucun endpoint local/réservé autorisé
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        return False

    for info in infos:
        ip_str = info[4][0]
        if _is_forbidden_ip(ip_str):
            return False

    return True


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


def _collect_target_files(article_url: str, file_hint: str = "") -> list[Path]:
    """Utilise l'index d'articles pour trouver rapidement les fichiers à mettre à jour."""
    targets: list[Path] = []

    hint_target = _safe_json_file(file_hint)
    if hint_target and _article_exists_in_file(hint_target, article_url):
        targets.append(hint_target)

    index = get_article_index(PROJECT_ROOT)
    url_norm = _normalize_url(article_url)
    for entry in index.get_articles():
        if _normalize_url(entry.get("url", "")) != url_norm:
            continue
        rel_file = (entry.get("file") or "").strip()
        if not rel_file:
            continue
        candidate = (PROJECT_ROOT / rel_file).resolve()
        if not str(candidate).startswith(str(PROJECT_ROOT) + "/"):
            continue
        if candidate.suffix.lower() != ".json" or not candidate.exists():
            continue
        if candidate not in targets:
            targets.append(candidate)

    return sorted(targets)


def _persist_gallery(article_url: str, gallery: list[dict], force_refresh: bool, file_hint: str = "") -> list[str]:
    updated_files: list[str] = []

    for target in _collect_target_files(article_url, file_hint=file_hint):
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
            if isinstance(existing, list) and existing and not force_refresh:
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
        if isinstance(existing, list) and existing:
            return existing
        return None

    return None


def _find_existing_gallery(article_url: str, file_hint: str = "") -> list[dict] | None:
    for target in _collect_target_files(article_url, file_hint=file_hint):
        existing = _find_existing_gallery_in_target(target, article_url)
        if existing:
            return existing
    return None


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

    if not article_url or not _is_public_http_url(article_url):
        return jsonify({"error": "article_url invalide ou non autorisée"}), 400

    # Limiter aux URLs connues du corpus pour éviter un fetch arbitraire.
    # Fallback: accepter aussi l'URL si elle est présente dans le fichier JSON courant.
    index_hit = get_article_index(PROJECT_ROOT).get_by_url(article_url) is not None
    hint_target = _safe_json_file(file_path)
    hint_hit = bool(hint_target and _article_exists_in_file(hint_target, article_url))
    if not index_hit and not hint_hit:
        return jsonify({"error": "article introuvable dans l'index"}), 404

    # 1) Réutilisation directe si la galerie existe déjà et sans force refresh
    if not force_refresh:
        existing = _find_existing_gallery(article_url, file_hint=file_path)
        if existing:
            return jsonify({
                "ok": True,
                "gallery": existing,
                "cached": True,
                "updated_files": [],
            })

    # 2) Extraction des images (algorithme projet : tri par surface, grandes images)
    images = extract_top_n_largest_images(article_url, n=max_images, min_width=500, timeout=12)
    if not isinstance(images, list):
        images = []

    gallery = _normalize_gallery(images)

    # 3) Persistance dans les JSON contenant l'article
    updated_files = _persist_gallery(article_url, gallery, force_refresh=force_refresh, file_hint=file_path)

    return jsonify({
        "ok": True,
        "gallery": gallery,
        "cached": False,
        "updated_files": updated_files,
    })
