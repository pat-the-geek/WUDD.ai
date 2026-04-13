"""
viewer/routes/gallery.py — Blueprint Flask pour la galerie d'images article.

Route :
  POST /api/article/gallery

Fonctionnalités :
  - Réutilise la galerie existante (champ "galerie") si déjà présente
  - Extrait les grandes images d'un article (width > 500px)
  - Ajoute des métadonnées (dimensions, surface, alt/title, copyright)
  - Persiste la galerie dans le(s) fichier(s) JSON article(s)
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from flask import Blueprint, jsonify, request

from utils.http_utils import extract_top_n_largest_images
from viewer.helpers import PROJECT_ROOT


gallery_bp = Blueprint("gallery", __name__)

_ALLOWED_ROOTS = ("data/", "samples/")


def _is_allowed_rel_path(rel_path: str) -> bool:
    return any(rel_path.startswith(prefix) for prefix in _ALLOWED_ROOTS)


def _resolve_target(rel_path: str) -> Path | None:
    if not rel_path or not _is_allowed_rel_path(rel_path):
        return None
    target = (PROJECT_ROOT / rel_path).resolve()
    if not str(target).startswith(str(PROJECT_ROOT) + "/"):
        return None
    if not target.exists() or target.suffix.lower() != ".json":
        return None
    return target


def _extract_copyright_map(article_url: str, timeout: int = 12) -> dict[str, str]:
    """Construit un mapping URL image → copyright/credit depuis le HTML source."""
    headers = {"User-Agent": "Mozilla/5.0 (compatible; WUDD.ai/2.4; +https://wudd.ai)"}
    try:
        resp = requests.get(article_url, timeout=timeout, headers=headers)
        resp.raise_for_status()
    except requests.RequestException:
        return {}

    soup = BeautifulSoup(resp.content, "html.parser")
    out: dict[str, str] = {}

    for img in soup.find_all("img", src=True):
        src = (img.get("src") or "").strip()
        if not src:
            continue
        full_url = urljoin(article_url, src)
        if not full_url.startswith(("http://", "https://")):
            continue

        copyright_val = ""
        for attr in (
            "copyright", "data-copyright", "credit", "data-credit",
            "author", "data-author", "byline", "data-byline",
        ):
            v = (img.get(attr) or "").strip()
            if v:
                copyright_val = v
                break

        if not copyright_val:
            fig = img.find_parent("figure")
            if fig:
                cap = fig.find("figcaption")
                if cap:
                    txt = " ".join(cap.get_text(" ", strip=True).split())
                    if txt:
                        copyright_val = txt[:240]

        if copyright_val and full_url not in out:
            out[full_url] = copyright_val

    return out


def _normalize_gallery(images: list[dict], copyright_map: dict[str, str]) -> list[dict]:
    gallery: list[dict] = []
    seen: set[str] = set()

    for img in images:
        url = (img.get("url") or img.get("URL") or "").strip()
        if not url or url in seen:
            continue

        width = int(img.get("width") or img.get("Width") or 0)
        height = int(img.get("height") or img.get("Height") or 0)
        area = int(img.get("area") or img.get("Area") or (width * height))

        gallery.append({
            "URL": url,
            "width": width,
            "height": height,
            "area": area,
            "title": (img.get("title") or "").strip(),
            "alt": (img.get("alt") or "").strip(),
            "copyright": (copyright_map.get(url) or "").strip(),
        })
        seen.add(url)

    gallery.sort(key=lambda x: int(x.get("area") or 0), reverse=True)
    return gallery


def _iter_persist_targets(primary: Path | None) -> list[Path]:
    """Retourne les fichiers JSON susceptibles de contenir l'article à mettre à jour."""
    targets: list[Path] = []
    if primary:
        targets.append(primary)

    rss_root = PROJECT_ROOT / "data" / "articles-from-rss"
    if rss_root.exists():
        for f in sorted(rss_root.rglob("*.json")):
            if f not in targets:
                targets.append(f)

    return targets


def _persist_gallery(article_url: str, gallery: list[dict], primary: Path | None) -> list[str]:
    updated_files: list[str] = []

    for target in _iter_persist_targets(primary):
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
            if (article.get("URL") or "").strip() != article_url:
                continue
            # Si déjà présent et non vide, on ne remplace pas.
            if isinstance(article.get("galerie"), list) and article.get("galerie"):
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


@gallery_bp.route("/api/article/gallery", methods=["POST"])
def api_article_gallery():
    body = request.get_json(force=True, silent=True) or {}

    article_url = (body.get("article_url") or body.get("url") or "").strip()
    rel_path = (body.get("file_path") or "").strip()
    max_images = body.get("max", 12)

    try:
        max_images = max(1, min(int(max_images), 30))
    except (TypeError, ValueError):
        max_images = 12

    if not article_url or not article_url.startswith(("http://", "https://")):
        return jsonify({"error": "article_url invalide"}), 400

    target = _resolve_target(rel_path) if rel_path else None

    # 1) Réutiliser directement la galerie existante dans le fichier source
    if target:
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = None

        if isinstance(data, list):
            for article in data:
                if not isinstance(article, dict):
                    continue
                if (article.get("URL") or "").strip() != article_url:
                    continue
                existing = article.get("galerie")
                if isinstance(existing, list) and existing:
                    return jsonify({
                        "ok": True,
                        "gallery": existing,
                        "cached": True,
                        "updated_files": [],
                    })
                break

    # 2) Extraction des images (algorithme projet : tri par surface, grandes images)
    images = extract_top_n_largest_images(article_url, n=max_images, min_width=500, timeout=12)
    if not isinstance(images, list):
        images = []

    copyright_map = _extract_copyright_map(article_url, timeout=12)
    gallery = _normalize_gallery(images, copyright_map)

    # 3) Persistance dans les JSON contenant l'article
    updated_files = _persist_gallery(article_url, gallery, target)

    return jsonify({
        "ok": True,
        "gallery": gallery,
        "cached": False,
        "updated_files": updated_files,
    })
