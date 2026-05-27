"""viewer/routes/api_v1.py — API REST publique v1 pour agents IA / MCP.

Contrat stable, versionné, découplé de l'UI viewer. Documenté dans
docs/API_V1.md.

Authentification :
  - Si la variable WUDD_API_TOKEN est définie dans .env, toutes les
    requêtes doivent inclure le header `Authorization: Bearer <token>`.
  - Si WUDD_API_TOKEN est vide/absente, l'API est ouverte (dev local).

Routes :

  Sources RSS (Extension 1)
    GET    /api/v1/sources                — liste les sources (?include_inactive=1)
    POST   /api/v1/sources                — ajoute une source RSS
    PATCH  /api/v1/sources/<id>           — met à jour une source
    DELETE /api/v1/sources/<id>           — soft delete (actif=false)

  Mots-clés (Extension 2)
    GET    /api/v1/keywords               — liste les mots-clés surveillés
    POST   /api/v1/keywords               — ajoute un mot-clé
    PATCH  /api/v1/keywords/<id>          — met à jour un mot-clé
    DELETE /api/v1/keywords/<id>          — supprime un mot-clé
    GET    /api/v1/keywords/<id>/articles — articles matchant le mot-clé (?days=N)
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path
from urllib.parse import urlparse

from flask import Blueprint, jsonify, request

from viewer.helpers import PROJECT_ROOT, require_json_body

api_v1_bp = Blueprint("api_v1", __name__, url_prefix="/api/v1")

_OPML_PATH = PROJECT_ROOT / "data" / "WUDD.opml"
_KEYWORDS_PATH = PROJECT_ROOT / "config" / "keyword-to-search.json"
_RSS_ARTICLES_DIR = PROJECT_ROOT / "data" / "articles-from-rss"


# ── Auth ──────────────────────────────────────────────────────────────────────


def _require_token(f):
    """Vérifie le bearer token si WUDD_API_TOKEN est défini."""

    @wraps(f)
    def decorated(*args, **kwargs):
        expected = os.getenv("WUDD_API_TOKEN", "").strip()
        if not expected:
            return f(*args, **kwargs)
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"error": "Token manquant"}), 401
        provided = auth_header[7:].strip()
        if provided != expected:
            return jsonify({"error": "Token invalide"}), 401
        return f(*args, **kwargs)

    return decorated


# ── Helpers communs ───────────────────────────────────────────────────────────


def _stable_id(value: str) -> str:
    """ID stable (12 chars hex) dérivé d'une chaîne — réversible côté serveur via index."""
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:12]


def _normalize_tags(raw) -> list[str]:
    """Accepte list[str] ou str séparé par virgules, retourne une liste propre."""
    if raw is None:
        return []
    if isinstance(raw, list):
        items = raw
    else:
        items = str(raw).split(",")
    return [str(t).strip() for t in items if str(t).strip()]


# ── Sources (OPML) ────────────────────────────────────────────────────────────


def _read_opml_outlines() -> tuple[ET.Element, list[ET.Element]]:
    """Retourne (root, outlines RSS) — crée un OPML vide si absent."""
    if not _OPML_PATH.exists():
        root = ET.Element("opml", version="2.0")
        head = ET.SubElement(root, "head")
        ET.SubElement(head, "title").text = "WUDD.ai"
        ET.SubElement(root, "body")
        _OPML_PATH.parent.mkdir(parents=True, exist_ok=True)
        ET.ElementTree(root).write(
            _OPML_PATH, encoding="UTF-8", xml_declaration=True
        )
    tree = ET.parse(_OPML_PATH)
    root = tree.getroot()
    return root, root.findall(".//outline[@type='rss']")


def _outline_to_dict(o: ET.Element) -> dict:
    xml_url = o.get("xmlUrl") or ""
    title = o.get("title") or o.get("text") or urlparse(xml_url).netloc
    return {
        "id": _stable_id(xml_url),
        "nom": title,
        "url": xml_url,
        "html_url": o.get("htmlUrl") or "",
        "tags": _normalize_tags(o.get("tags")),
        "actif": (o.get("actif") or "true").lower() != "false",
        "bypass_quota": (o.get("bypassQuota") or "false").lower() == "true",
    }


def _write_opml(root: ET.Element) -> None:
    ET.indent(ET.ElementTree(root), space="  ")
    with open(_OPML_PATH, "wb") as fh:
        ET.ElementTree(root).write(fh, encoding="UTF-8", xml_declaration=True)


def _find_outline_by_id(outlines: list[ET.Element], source_id: str) -> ET.Element | None:
    for o in outlines:
        if _stable_id(o.get("xmlUrl") or "") == source_id:
            return o
    return None


def _resolve_feed_title(url: str) -> str:
    """Récupère le titre du flux RSS via une requête HTTP — fallback domaine si échec."""
    import requests as _req

    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; WUDD.ai-api-v1)",
        "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*;q=0.8",
    }
    try:
        r = _req.get(url, timeout=10, allow_redirects=True, headers=headers)
        if r.status_code < 400:
            root = ET.fromstring(r.content)
            channel = root.find("channel")
            if channel is not None:
                title_el = channel.find("title")
                if title_el is not None and title_el.text:
                    return title_el.text.strip()
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            t = root.find("atom:title", ns) or root.find("title")
            if t is not None and t.text:
                return t.text.strip()
    except Exception:
        pass
    return urlparse(url).netloc or url


@api_v1_bp.route("/sources", methods=["GET"])
@_require_token
def list_sources():
    """Liste les sources RSS. Query: include_inactive=1, tag=<tag>."""
    include_inactive = request.args.get("include_inactive", "").lower() in ("1", "true", "yes")
    tag_filter = (request.args.get("tag") or "").strip().lower()

    _, outlines = _read_opml_outlines()
    items = [_outline_to_dict(o) for o in outlines]
    if not include_inactive:
        items = [it for it in items if it["actif"]]
    if tag_filter:
        items = [it for it in items if tag_filter in [t.lower() for t in it["tags"]]]
    items.sort(key=lambda x: x["nom"].lower())
    return jsonify({"items": items, "total": len(items)})


@api_v1_bp.route("/sources", methods=["POST"])
@_require_token
def create_source():
    """Ajoute une source RSS. Body: {url, nom?, tags?, actif?, bypass_quota?, html_url?}."""
    body = require_json_body(required_fields=["url"])
    url = str(body.get("url", "")).strip()
    if not url.startswith("http"):
        return jsonify({"error": "url doit être http(s)"}), 400

    root, outlines = _read_opml_outlines()
    source_id = _stable_id(url)
    if _find_outline_by_id(outlines, source_id) is not None:
        return jsonify({"error": "Source déjà existante", "id": source_id}), 409

    nom = str(body.get("nom") or "").strip() or _resolve_feed_title(url)
    tags = _normalize_tags(body.get("tags"))
    actif = body.get("actif", True) is not False
    bypass_quota = bool(body.get("bypass_quota", False))
    html_url = str(body.get("html_url") or "").strip()

    attrs = {
        "type": "rss",
        "title": nom,
        "text": nom,
        "xmlUrl": url,
        "htmlUrl": html_url,
    }
    if tags:
        attrs["tags"] = ",".join(tags)
    if not actif:
        attrs["actif"] = "false"
    if bypass_quota:
        attrs["bypassQuota"] = "true"

    body_el = root.find("body")
    if body_el is None:
        body_el = ET.SubElement(root, "body")
    ET.SubElement(body_el, "outline", **attrs)
    _write_opml(root)

    _, refreshed = _read_opml_outlines()
    created = _find_outline_by_id(refreshed, source_id)
    return jsonify(_outline_to_dict(created)), 201


@api_v1_bp.route("/sources/<source_id>", methods=["PATCH"])
@_require_token
def update_source(source_id: str):
    """Met à jour une source. Body: subset of {nom, tags, actif, bypass_quota, html_url}."""
    body = require_json_body(expected_type=dict)
    root, outlines = _read_opml_outlines()
    outline = _find_outline_by_id(outlines, source_id)
    if outline is None:
        return jsonify({"error": "Source introuvable"}), 404

    if "nom" in body:
        nom = str(body["nom"] or "").strip()
        if nom:
            outline.set("title", nom)
            outline.set("text", nom)
    if "tags" in body:
        tags = _normalize_tags(body["tags"])
        if tags:
            outline.set("tags", ",".join(tags))
        elif "tags" in outline.attrib:
            del outline.attrib["tags"]
    if "actif" in body:
        if body["actif"] is False:
            outline.set("actif", "false")
        else:
            outline.attrib.pop("actif", None)
    if "bypass_quota" in body:
        if body["bypass_quota"]:
            outline.set("bypassQuota", "true")
        else:
            outline.attrib.pop("bypassQuota", None)
    if "html_url" in body:
        outline.set("htmlUrl", str(body["html_url"] or ""))

    _write_opml(root)
    return jsonify(_outline_to_dict(outline))


@api_v1_bp.route("/sources/<source_id>", methods=["DELETE"])
@_require_token
def delete_source(source_id: str):
    """Soft delete : marque la source actif=false. Query hard=1 pour supprimer définitivement."""
    hard = request.args.get("hard", "").lower() in ("1", "true", "yes")
    root, outlines = _read_opml_outlines()
    outline = _find_outline_by_id(outlines, source_id)
    if outline is None:
        return jsonify({"error": "Source introuvable"}), 404

    if hard:
        body_el = root.find("body")
        if body_el is not None:
            body_el.remove(outline)
        _write_opml(root)
        return jsonify({"ok": True, "id": source_id, "mode": "hard"})

    outline.set("actif", "false")
    _write_opml(root)
    return jsonify(_outline_to_dict(outline))


# ── Keywords ──────────────────────────────────────────────────────────────────


def _read_keywords() -> list[dict]:
    if not _KEYWORDS_PATH.exists():
        return []
    try:
        data = json.loads(_KEYWORDS_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _write_keywords(items: list[dict]) -> None:
    tmp = _KEYWORDS_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(_KEYWORDS_PATH)


def _keyword_to_dict(kw: dict) -> dict:
    expression = str(kw.get("keyword", "")).strip()
    return {
        "id": _stable_id(expression),
        "expression": expression,
        "tags": _normalize_tags(kw.get("tags")),
        "seuil_alerte": kw.get("seuil_alerte"),
        "ou": list(kw.get("or", []) or []),
        "et": list(kw.get("and", []) or []),
    }


def _dict_to_keyword(item: dict, base: dict | None = None) -> dict:
    """Convertit la forme API → format de stockage (préserve ou/et existants si base fourni)."""
    out: dict = dict(base or {})
    out["keyword"] = str(item.get("expression", "")).strip()
    if "ou" in item:
        out["or"] = list(item.get("ou") or [])
    elif "or" not in out:
        out["or"] = []
    if "et" in item:
        out["and"] = list(item.get("et") or [])
    elif "and" not in out:
        out["and"] = []
    tags = _normalize_tags(item.get("tags"))
    if tags:
        out["tags"] = tags
    elif "tags" in out and not item.get("tags"):
        out.pop("tags", None)
    if "seuil_alerte" in item:
        if item["seuil_alerte"] is None:
            out.pop("seuil_alerte", None)
        else:
            out["seuil_alerte"] = item["seuil_alerte"]
    return out


@api_v1_bp.route("/keywords", methods=["GET"])
@_require_token
def list_keywords():
    """Liste les mots-clés. Query: tag=<tag>."""
    tag_filter = (request.args.get("tag") or "").strip().lower()
    items = [_keyword_to_dict(k) for k in _read_keywords()]
    if tag_filter:
        items = [it for it in items if tag_filter in [t.lower() for t in it["tags"]]]
    items.sort(key=lambda x: x["expression"].lower())
    return jsonify({"items": items, "total": len(items)})


@api_v1_bp.route("/keywords", methods=["POST"])
@_require_token
def create_keyword():
    """Ajoute un mot-clé. Body: {expression, tags?, seuil_alerte?, ou?, et?}."""
    body = require_json_body(required_fields=["expression"])
    expression = str(body.get("expression", "")).strip()
    if not expression:
        return jsonify({"error": "expression vide"}), 400

    items = _read_keywords()
    kw_id = _stable_id(expression)
    for kw in items:
        if _stable_id(str(kw.get("keyword", "")).strip()) == kw_id:
            return jsonify({"error": "Mot-clé déjà existant", "id": kw_id}), 409

    new_kw = _dict_to_keyword(body)
    items.append(new_kw)
    _write_keywords(items)
    return jsonify(_keyword_to_dict(new_kw)), 201


@api_v1_bp.route("/keywords/<keyword_id>", methods=["PATCH"])
@_require_token
def update_keyword(keyword_id: str):
    """Met à jour un mot-clé. Body: subset of {expression, tags, seuil_alerte, ou, et}."""
    body = require_json_body(expected_type=dict)
    items = _read_keywords()
    for i, kw in enumerate(items):
        if _stable_id(str(kw.get("keyword", "")).strip()) == keyword_id:
            patched = _dict_to_keyword(
                {**{"expression": kw.get("keyword", "")}, **body},
                base=kw,
            )
            items[i] = patched
            _write_keywords(items)
            return jsonify(_keyword_to_dict(patched))
    return jsonify({"error": "Mot-clé introuvable"}), 404


@api_v1_bp.route("/keywords/<keyword_id>", methods=["DELETE"])
@_require_token
def delete_keyword(keyword_id: str):
    items = _read_keywords()
    for i, kw in enumerate(items):
        if _stable_id(str(kw.get("keyword", "")).strip()) == keyword_id:
            removed = items.pop(i)
            _write_keywords(items)
            return jsonify({"ok": True, "id": keyword_id, "expression": removed.get("keyword", "")})
    return jsonify({"error": "Mot-clé introuvable"}), 404


@api_v1_bp.route("/keywords/<keyword_id>/articles", methods=["GET"])
@_require_token
def keyword_articles(keyword_id: str):
    """Retourne les articles matchant le mot-clé (filename = expression sans crochets).

    Query : days=N (limite par fenêtre temporelle, défaut: aucune limite).
    """
    items = _read_keywords()
    target = next(
        (k for k in items if _stable_id(str(k.get("keyword", "")).strip()) == keyword_id),
        None,
    )
    if target is None:
        return jsonify({"error": "Mot-clé introuvable"}), 404

    expression = str(target.get("keyword", "")).strip()
    # Le fichier de stockage est généralement <keyword sans crochets>.json
    clean = re.sub(r"[\[\]]", "", expression).strip()
    candidates = [
        _RSS_ARTICLES_DIR / f"{clean}.json",
        _RSS_ARTICLES_DIR / f"{expression}.json",
    ]
    articles_path = next((p for p in candidates if p.exists()), None)
    if articles_path is None:
        return jsonify({"expression": expression, "items": [], "total": 0})

    try:
        articles = json.loads(articles_path.read_text(encoding="utf-8"))
        if not isinstance(articles, list):
            articles = []
    except Exception:
        articles = []

    days = request.args.get("days")
    if days:
        try:
            cutoff = datetime.now() - timedelta(days=int(days))
            kept: list[dict] = []
            for a in articles:
                date_str = str(a.get("Date de publication", "")).strip()
                try:
                    dt = datetime.strptime(date_str, "%d/%m/%Y")
                    if dt >= cutoff:
                        kept.append(a)
                except ValueError:
                    continue
            articles = kept
        except ValueError:
            return jsonify({"error": "days doit être un entier"}), 400

    return jsonify({
        "expression": expression,
        "items": articles,
        "total": len(articles),
    })
