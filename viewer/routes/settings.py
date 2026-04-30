"""
viewer/routes/settings.py — Blueprint Flask pour les paramètres et la configuration.

Routes :
  GET/POST      /api/keywords
  GET           /api/rss-feeds
  POST          /api/rss-feeds/check
  POST          /api/rss-feeds/resolve
  POST          /api/rss-feeds/save
  GET           /api/rss-feeds/stats
  GET           /api/web-sources
  POST          /api/web-sources/save
  POST          /api/web-sources/check
  POST          /api/web-sources/resolve
  GET           /api/web-sources/state
  GET/POST      /api/flux-sources
  GET/POST      /api/env
  DELETE        /api/env/<key>
  GET           /api/ai-providers
  POST          /api/ai-check
  GET           /api/ollama/status
  POST          /api/ollama/check
  GET           /api/ollama/models
  POST          /api/backup/check-dir
"""
import json
import os

from flask import Blueprint, jsonify, request, abort
from pathlib import Path

from viewer.helpers import PROJECT_ROOT, require_json_body

settings_bp = Blueprint("settings", __name__)

# ── Variables d'environnement ─────────────────────────────────────────────────
_ENV_FILE = PROJECT_ROOT / ".env"
_SENSITIVE_KEYS = {"bearer", "SMTP_PASSWORD", "NTFY_TOKEN", "ANTHROPIC_API_KEY"}
_READONLY_KEYS = set()  # clés qu'on refuse de modifier


def _parse_env_file(path: Path) -> list[dict]:
    """Parse .env ligne par ligne → [{key, value, masked, comment, raw}]."""
    entries = []
    if not path.exists():
        return entries
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            entries.append({"key": None, "value": None, "raw": line, "comment": True})
            continue
        if "=" in stripped:
            key, _, val = stripped.partition("=")
            key = key.strip()
            val = val.strip()
            # Supprimer les guillemets éventuels
            if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                val = val[1:-1]
            masked = key.lower() in {k.lower() for k in _SENSITIVE_KEYS}
            entries.append({"key": key, "value": val, "masked": masked, "comment": False})
        else:
            entries.append({"key": None, "value": None, "raw": line, "comment": True})
    return entries


def _serialize_env(entries: list[dict]) -> str:
    """Reconstruit le contenu .env depuis la liste d'entrées."""
    lines = []
    for e in entries:
        if e.get("comment"):
            lines.append(e.get("raw", ""))
        else:
            key = e["key"]
            val = e.get("value", "")
            # Mettre entre guillemets si la valeur contient des espaces ou des caractères spéciaux
            if " " in val or "#" in val or ";" in val:
                val = f'"{val}"'
            lines.append(f"{key}={val}")
    return "\n".join(lines) + "\n"


@settings_bp.route("/api/keywords", methods=["GET"])
def api_get_keywords():
    path = PROJECT_ROOT / "config" / "keyword-to-search.json"
    if not path.exists():
        return jsonify([])
    try:
        return jsonify(json.loads(path.read_text(encoding="utf-8")))
    except json.JSONDecodeError:
        return jsonify([])


@settings_bp.route("/api/keywords", methods=["POST"])
def api_save_keywords():
    data = request.get_json(force=True)
    if not isinstance(data, list):
        abort(400, "Format invalide : tableau attendu")
    path = PROJECT_ROOT / "config" / "keyword-to-search.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return jsonify({"ok": True})


@settings_bp.route("/api/keywords/suggest", methods=["POST"])
def api_suggest_semantic_field():
    """Demande à l'IA des propositions de champ sémantique pour un mot-clé."""
    data = request.get_json(force=True)
    keyword = (data.get("keyword") or "").strip()
    if not keyword:
        abort(400, "Mot-clé manquant")

    provider = os.environ.get("AI_PROVIDER", "euria").lower()
    api_url  = os.environ.get("URL", "")
    bearer   = os.environ.get("bearer", "")

    prompt = (
        f"Pour un système de veille d'actualités, je surveille le mot-clé : \"{keyword}\".\n\n"
        f"Ce mot peut être ambigu ou avoir plusieurs sens selon le contexte.\n\n"
        f"Génère deux listes de mots en français pour affiner la détection :\n"
        f"1. **ou** : synonymes, variantes orthographiques, abréviations, noms de personnes/marques associés "
        f"qui permettent de trouver des articles sur ce sujet même sans le mot exact.\n"
        f"2. **et** : termes du champ sémantique qui doivent être présents dans le titre pour s'assurer "
        f"que l'article traite bien du bon contexte (pas un autre sens du mot).\n\n"
        f"Réponds UNIQUEMENT en JSON valide, sans commentaire, sans balise <think>, sans markdown :\n"
        f"{{\"ou\": [\"terme1\", \"terme2\", ...], \"et\": [\"terme1\", \"terme2\", ...]}}\n\n"
        f"Maximum 15 termes par liste. Termes courts et précis, adaptés aux titres d'articles de presse."
    )

    try:
        if provider == "claude":
            from utils.api_client import ClaudeClient
            client = ClaudeClient(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
            full_text = ""
            for chunk in client.stream(prompt=prompt, timeout=60):
                if chunk.startswith("data: "):
                    try:
                        obj = json.loads(chunk[6:])
                        full_text += obj.get("choices", [{}])[0].get("delta", {}).get("content", "")
                    except Exception:
                        pass
        else:
            if not api_url or not bearer:
                return jsonify({"error": "URL ou bearer manquant dans .env"}), 503
            from utils.api_client import EurIAClient
            client = EurIAClient(url=api_url, bearer=bearer)
            full_text = client.ask(prompt, timeout=60, enable_web_search=False)

        # Extraire le JSON de la réponse (robuste aux balises markdown)
        import re
        match = re.search(r'\{[^{}]*"ou"[^{}]*"et"[^{}]*\}|\{[^{}]*"et"[^{}]*"ou"[^{}]*\}', full_text, re.DOTALL)
        if not match:
            # Essai avec bloc ```json ... ```
            match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', full_text, re.DOTALL)
            raw = match.group(1) if match else full_text.strip()
        else:
            raw = match.group(0)

        result = json.loads(raw)
        return jsonify({"ou": result.get("ou", []), "et": result.get("et", [])})

    except json.JSONDecodeError as e:
        return jsonify({"error": f"Réponse IA non parseable : {e}", "raw": full_text[:500]}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@settings_bp.route("/api/rss-feeds", methods=["GET"])
def api_get_rss_feeds():
    """Parse le fichier OPML Reeder et retourne les flux RSS triés alphabétiquement."""
    import xml.etree.ElementTree as ET
    opml_path = PROJECT_ROOT / "data" / "WUDD.opml"
    if not opml_path.exists():
        return jsonify([])
    try:
        tree = ET.parse(opml_path)
        root = tree.getroot()
        feeds = []
        for o in root.findall(".//outline[@type='rss']"):
            title   = o.get("title") or o.get("text") or ""
            xml_url = o.get("xmlUrl") or ""
            html_url = o.get("htmlUrl") or ""
            bypass_quota = o.get("bypassQuota", "false").lower() == "true"
            if xml_url:
                feeds.append({"title": title, "xmlUrl": xml_url, "htmlUrl": html_url, "bypassQuota": bypass_quota})
        feeds.sort(key=lambda f: f["title"].lower())
        return jsonify(feeds)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@settings_bp.route("/api/rss-feeds/check", methods=["POST"])
def api_check_rss_feed():
    """Vérifie si une URL RSS répond. Body JSON: {"url": "..."}

    Stratégie : essaie HEAD en premier (rapide), puis GET en fallback si
    HEAD retourne 405 ou 403 — certains CDN/WAF refusent les requêtes HEAD.
    Utilise un Chrome User-Agent pour passer les filtres bot basiques.
    """
    import requests as req
    data = request.get_json(force=True) or {}
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"ok": False, "error": "URL manquante"}), 400
    _headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*;q=0.8",
    }
    try:
        r = req.head(url, timeout=8, allow_redirects=True, headers=_headers)
        # Fallback GET si le serveur refuse HEAD (405) ou renvoie un faux 403 anti-bot
        if r.status_code in (403, 405):
            r = req.get(url, timeout=10, allow_redirects=True, headers=_headers)
        ok = r.status_code < 400
        return jsonify({"ok": ok, "status": r.status_code})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@settings_bp.route("/api/rss-feeds/resolve", methods=["POST"])
def api_resolve_rss_feed():
    """Résout une URL RSS : vérifie qu'elle répond et extrait le titre du canal."""
    import requests as req
    import xml.etree.ElementTree as ET
    from urllib.parse import urlparse
    data = request.get_json(force=True) or {}
    url = data.get("url", "").strip()
    if not url or not url.startswith("http"):
        return jsonify({"ok": False, "error": "URL invalide"}), 400
    _headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*;q=0.8",
        "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    try:
        r = req.get(url, timeout=10, allow_redirects=True, headers=_headers)
        if r.status_code >= 400:
            return jsonify({"ok": False, "error": f"HTTP {r.status_code}"})
        title = ""
        html_url = ""
        try:
            root = ET.fromstring(r.content)
            # RSS 2.0
            chan = root.find("channel")
            if chan is not None:
                t = chan.find("title")
                if t is not None and t.text:
                    title = t.text.strip()
                lk = chan.find("link")
                if lk is not None and lk.text:
                    html_url = lk.text.strip()
            # Atom
            if not title:
                ns = {"atom": "http://www.w3.org/2005/Atom"}
                t = root.find("atom:title", ns) or root.find("title")
                if t is not None and t.text:
                    title = t.text.strip()
                lk = root.find("atom:link", ns)
                if lk is not None:
                    html_url = lk.get("href", "")
        except Exception:
            pass
        if not title:
            title = urlparse(url).netloc
        return jsonify({"ok": True, "title": title, "xmlUrl": url, "htmlUrl": html_url, "bypassQuota": False})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@settings_bp.route("/api/rss-feeds/save", methods=["POST"])
def api_save_rss_feeds():
    """Sauvegarde la liste de flux dans data/WUDD.opml en respectant le format OPML."""
    import xml.etree.ElementTree as ET
    feeds = require_json_body(expected_type=list)
    opml_path = PROJECT_ROOT / "data" / "WUDD.opml"
    try:
        root = ET.Element("opml", version="2.0")
        head = ET.SubElement(root, "head")
        ET.SubElement(head, "title").text = "Reeder"
        body = ET.SubElement(root, "body")
        for f in feeds:
            attrs = {
                "type": "rss",
                "title": f.get("title", ""),
                "text": f.get("title", ""),
                "xmlUrl": f.get("xmlUrl", ""),
                "htmlUrl": f.get("htmlUrl", ""),
            }
            if f.get("bypassQuota"):
                attrs["bypassQuota"] = "true"
            ET.SubElement(body, "outline", **attrs)
        tree = ET.ElementTree(root)
        ET.indent(tree, space="  ")
        with open(opml_path, "wb") as fh:
            tree.write(fh, encoding="UTF-8", xml_declaration=True)
        return jsonify({"ok": True, "count": len(feeds)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@settings_bp.route("/api/rss-feeds/stats", methods=["GET"])
def api_rss_feeds_stats():
    """Retourne le nombre d'articles et la date de dernière publication par domaine."""
    from urllib.parse import urlparse
    from email.utils import parsedate_to_datetime
    from datetime import datetime

    rss_dir = PROJECT_ROOT / "data" / "articles-from-rss"
    stats = {}  # domain -> {count, lastDate}

    if not rss_dir.exists():
        return jsonify({})

    for json_file in rss_dir.glob("*.json"):
        try:
            articles = json.loads(json_file.read_text(encoding="utf-8"))
            if not isinstance(articles, list):
                continue
            for article in articles:
                url = article.get("URL", "")
                date_str = article.get("Date de publication", "")
                if not url:
                    continue
                try:
                    hostname = urlparse(url).hostname or ""
                    domain = hostname.removeprefix("www.")
                except Exception:
                    continue
                if not domain:
                    continue
                entry = stats.setdefault(domain, {"count": 0, "lastDate": None})
                entry["count"] += 1
                if date_str:
                    dt = None
                    try:
                        dt = parsedate_to_datetime(date_str)
                    except Exception:
                        pass
                    if dt is None:
                        try:
                            dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                        except Exception:
                            pass
                    if dt is not None:
                        dt_iso = dt.isoformat()
                        if entry["lastDate"] is None or dt_iso > entry["lastDate"]:
                            entry["lastDate"] = dt_iso
        except Exception:
            continue

    return jsonify(stats)


@settings_bp.route("/api/web-sources", methods=["GET"])
def api_get_web_sources():
    """Retourne la liste des sources web depuis config/web_sources.json."""
    path = PROJECT_ROOT / "config" / "web_sources.json"
    if not path.exists():
        return jsonify([])
    try:
        return jsonify(json.loads(path.read_text(encoding="utf-8")))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@settings_bp.route("/api/web-sources/save", methods=["POST"])
def api_save_web_sources():
    """Sauvegarde la liste des sources web dans config/web_sources.json."""
    sources = require_json_body(expected_type=list)
    path = PROJECT_ROOT / "config" / "web_sources.json"
    try:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(sources, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
        return jsonify({"ok": True, "count": len(sources)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@settings_bp.route("/api/web-sources/check", methods=["POST"])
def api_check_web_source():
    """Vérifie si une URL de sitemap ou de site est accessible. Body JSON: {"url": "..."}"""
    import requests as req
    data = require_json_body(required_fields=["url"])
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"ok": False, "error": "URL manquante"}), 400
    try:
        r = req.head(url, timeout=8, allow_redirects=True,
                     headers={"User-Agent": "WUDD.ai/2.2"})
        ok = r.status_code < 400
        return jsonify({"ok": ok, "status": r.status_code})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@settings_bp.route("/api/web-sources/resolve", methods=["POST"])
def api_resolve_web_source():
    """Résout une URL de site web : extrait le titre et détecte le sitemap.

    Body JSON: {"url": "https://example.com"}
    Retourne: {ok, title, base_url, sitemap_url, html_url}
    """
    import requests as req
    from bs4 import BeautifulSoup
    from urllib.parse import urlparse, urljoin

    data = require_json_body(required_fields=["url"])
    url = data.get("url", "").strip()
    if not url or not url.startswith("http"):
        return jsonify({"ok": False, "error": "URL invalide"}), 400

    headers = {"User-Agent": "Mozilla/5.0 (compatible; WUDD.ai/2.2)"}
    try:
        r = req.get(url, timeout=10, allow_redirects=True, headers=headers)
        if r.status_code >= 400:
            return jsonify({"ok": False, "error": f"HTTP {r.status_code}"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

    soup = BeautifulSoup(r.content, "html.parser")
    parsed = urlparse(r.url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"

    # Titre du site
    title = ""
    og = soup.find("meta", property="og:site_name")
    if og:
        title = og.get("content", "").strip()
    if not title:
        og = soup.find("meta", property="og:title")
        if og:
            title = og.get("content", "").strip()
    if not title:
        t = soup.find("title")
        if t:
            title = t.get_text(strip=True)
    if not title:
        title = parsed.netloc.replace("www.", "")

    # Détection du sitemap
    sitemap_url = ""
    # 1. Balise <link rel="sitemap">
    link_tag = soup.find("link", rel=lambda v: v and "sitemap" in (v if isinstance(v, str) else " ".join(v)).lower())
    if link_tag:
        sitemap_url = urljoin(base_url, link_tag.get("href", ""))

    # 2. Essai /sitemap.xml
    if not sitemap_url:
        candidates = ["/sitemap.xml", "/sitemap_index.xml", "/sitemap.xml.gz"]
        for cand in candidates:
            try:
                test_url = base_url + cand
                tr = req.head(test_url, timeout=5, headers=headers, allow_redirects=True)
                if tr.status_code < 400:
                    sitemap_url = test_url
                    break
            except Exception:
                continue

    return jsonify({
        "ok": True,
        "title": title,
        "base_url": base_url,
        "sitemap_url": sitemap_url,
        "html_url": r.url,
    })


@settings_bp.route("/api/web-sources/state", methods=["GET"])
def api_web_sources_state():
    """Retourne l'état du web_watcher : nombre d'URLs traitées par source."""
    state_path = PROJECT_ROOT / "data" / "web_watcher_state.json"
    if not state_path.exists():
        return jsonify({})
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        summary = {
            name: len(v.get("processed_urls", []))
            for name, v in state.items()
        }
        return jsonify(summary)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@settings_bp.route("/api/flux-sources", methods=["GET"])
def api_get_flux_sources():
    path = PROJECT_ROOT / "config" / "flux_json_sources.json"
    if not path.exists():
        # Retourner le fichier exemple si disponible
        example = PROJECT_ROOT / "config" / "flux_json_sources.example.json"
        if example.exists():
            try:
                return jsonify(json.loads(example.read_text(encoding="utf-8")))
            except json.JSONDecodeError:
                pass
        return jsonify([])
    try:
        return jsonify(json.loads(path.read_text(encoding="utf-8")))
    except json.JSONDecodeError:
        return jsonify([])


@settings_bp.route("/api/flux-sources", methods=["POST"])
def api_save_flux_sources():
    data = require_json_body(expected_type=list)
    path = PROJECT_ROOT / "config" / "flux_json_sources.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return jsonify({"ok": True})


@settings_bp.route("/api/env", methods=["GET"])
def api_env_get():
    """Retourne la liste des variables d'environnement depuis .env.

    Les valeurs des clés sensibles sont masquées (remplacées par '***').
    """
    entries = _parse_env_file(_ENV_FILE)
    result = []
    for e in entries:
        if e.get("comment"):
            result.append({"type": "comment", "raw": e.get("raw", "")})
        else:
            display_val = "***" if e.get("masked") else e["value"]
            result.append({
                "type": "var",
                "key": e["key"],
                "value": display_val,
                "masked": e.get("masked", False),
            })
    return jsonify(result)


@settings_bp.route("/api/env", methods=["POST"])
def api_env_post():
    """Crée ou met à jour une variable dans .env.

    Body JSON : { key: str, value: str }
    """
    body = require_json_body(required_fields=["key", "value"])
    key = (body.get("key") or "").strip()
    value = str(body.get("value") or "")

    if not key or not key.replace("_", "").isalnum():
        return jsonify({"error": "Clé invalide (alphanumérique + underscore uniquement)"}), 400

    entries = _parse_env_file(_ENV_FILE)

    # Mise à jour si la clé existe déjà
    found = False
    for e in entries:
        if not e.get("comment") and e.get("key") == key:
            e["value"] = value
            found = True
            break

    if not found:
        entries.append({"key": key, "value": value, "masked": False, "comment": False})

    # Écriture directe : l'écriture atomique (rename) échoue en Docker car
    # .env est un bind mount et os.rename() lève OSError sur un mount point.
    content = _serialize_env(entries)
    try:
        # Essai atomique d'abord (hors Docker / dev local)
        tmp = _ENV_FILE.parent / (_ENV_FILE.name + ".tmp")
        tmp.write_text(content, encoding="utf-8")
        tmp.replace(_ENV_FILE)
    except OSError:
        # Fallback : écriture directe (compatible Docker bind mount)
        _ENV_FILE.write_text(content, encoding="utf-8")
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass

    # Recharger dans l'environnement courant du processus Flask
    os.environ[key] = value

    # Recharger TOUT le .env avec override=True pour que les variables modifiées
    # via l'UI (ex. ANTHROPIC_API_KEY) soient visibles immédiatement dans os.environ,
    # même si elles étaient absentes ou vides au démarrage du conteneur Docker.
    try:
        from dotenv import load_dotenv as _load_dotenv
        _load_dotenv(_ENV_FILE, override=True)
    except Exception:
        pass

    # Invalider le singleton Config pour que les prochains appels get_config()
    # voient les nouvelles valeurs (ANTHROPIC_API_KEY, CLAUDE_MODEL_*, etc.)
    try:
        from utils.config import get_config as _get_config
        _get_config(force_reload=True)
    except Exception:
        pass

    return jsonify({"ok": True, "key": key})


@settings_bp.route("/api/env/<key>", methods=["DELETE"])
def api_env_delete(key: str):
    """Supprime une variable de .env."""
    if not key or not key.replace("_", "").isalnum():
        return jsonify({"error": "Clé invalide"}), 400

    entries = _parse_env_file(_ENV_FILE)
    entries = [e for e in entries if e.get("comment") or e.get("key") != key]

    content = _serialize_env(entries)
    try:
        tmp = _ENV_FILE.parent / (_ENV_FILE.name + ".tmp")
        tmp.write_text(content, encoding="utf-8")
        tmp.replace(_ENV_FILE)
    except OSError:
        _ENV_FILE.write_text(content, encoding="utf-8")
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass

    os.environ.pop(key, None)
    try:
        from dotenv import load_dotenv as _load_dotenv
        _load_dotenv(_ENV_FILE, override=True)
    except Exception:
        pass
    try:
        from utils.config import get_config as _get_config
        _get_config(force_reload=True)
    except Exception:
        pass
    return jsonify({"ok": True, "key": key})


@settings_bp.route("/api/ai-providers")
def api_ai_providers():
    """Retourne la liste des fournisseurs IA dont les credentials sont configurés.

    Retourne : { providers: ["euria"|"claude", ...], active: str }
    """
    available = []
    if os.environ.get("URL", "").strip() and os.environ.get("bearer", "").strip():
        available.append("euria")
    if os.environ.get("ANTHROPIC_API_KEY", "").strip():
        available.append("claude")
    # Ollama : inclus si configuré explicitement comme provider principal, résumés ou NER
    ai_provider = os.environ.get("AI_PROVIDER", "").strip().lower()
    ai_summary  = os.environ.get("AI_PROVIDER_SUMMARY", "").strip().lower()
    ai_ner      = os.environ.get("AI_PROVIDER_NER", "").strip().lower()
    if ai_provider == "ollama" or ai_summary == "ollama" or ai_ner == "ollama":
        available.append("ollama")
    active = os.environ.get("AI_PROVIDER", "euria").strip().lower()
    # Si ollama est disponible mais n'est pas le provider principal,
    # le mettre par défaut (cas AI_PROVIDER_SUMMARY ou AI_PROVIDER_NER = ollama)
    if "ollama" in available and active != "ollama":
        active = "ollama"
    return jsonify({"providers": available, "active": active})


@settings_bp.route("/api/ai-check", methods=["POST"])
def api_ai_check():
    """Vérifie la connexion à un fournisseur IA en envoyant un prompt minimal.

    Body JSON : { "provider": "euria" | "claude" | "ollama" }
    Retourne  : { ok: bool, message: str, latency_ms: int, active_model?: str }
    """
    import time as _time
    body = request.get_json(force=True, silent=True) or {}
    provider = (body.get("provider") or "").strip().lower()
    if provider not in ("euria", "claude", "ollama"):
        return jsonify({"error": "provider doit être 'euria', 'claude' ou 'ollama'"}), 400

    try:
        from utils.api_client import EurIAClient, ClaudeClient, OllamaClient
    except ImportError as e:
        return jsonify({"ok": False, "message": f"Import impossible : {e}", "latency_ms": 0}), 500

    prompt = "Réponds uniquement par 'OK'."
    t0 = _time.monotonic()
    try:
        if provider == "euria":
            url = os.environ.get("URL", "").strip()
            bearer = os.environ.get("bearer", "").strip()
            if not url or not bearer:
                return jsonify({"ok": False, "message": "URL ou bearer non configuré.", "latency_ms": 0})
            client = EurIAClient(url=url, bearer=bearer)
            result = client.ask(prompt, timeout=10)
            active_model = client.model
        elif provider == "claude":
            api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
            if not api_key:
                return jsonify({"ok": False, "message": "ANTHROPIC_API_KEY non configurée.", "latency_ms": 0})
            client = ClaudeClient(api_key=api_key)
            result = client.ask(prompt, max_tokens=16, timeout=10)
            active_model = None
        else:  # ollama
            if not OllamaClient.is_available():
                return jsonify({"ok": False, "message": "Serveur Ollama injoignable (localhost:11434). Démarrez-le : brew services start ollama", "latency_ms": 0})
            model = os.environ.get("OLLAMA_MODEL", OllamaClient._DEFAULT_MODEL).strip()
            client = OllamaClient(model=model)
            result = client.ask(prompt, max_tokens=16, timeout=30)
            active_model = model

        latency_ms = int((_time.monotonic() - t0) * 1000)
        ok = bool(result and len(result.strip()) > 0)
        return jsonify({
            "ok": ok,
            "message": result.strip() if ok else "Réponse vide.",
            "latency_ms": latency_ms,
            "active_model": active_model,
        })

    except Exception as exc:
        latency_ms = int((_time.monotonic() - t0) * 1000)
        return jsonify({"ok": False, "message": str(exc), "latency_ms": latency_ms})


@settings_bp.route("/api/ollama/status", methods=["GET"])
def api_ollama_status():
    """Retourne le statut du serveur Ollama et la liste des modèles disponibles.

    Retourne : { available: bool, models: [str], active_model: str, ner_provider: str }
    """
    try:
        from utils.api_client import OllamaClient
        available = OllamaClient.is_available()
        models = OllamaClient.list_models() if available else []
    except Exception:
        available = False
        models = []

    ner_provider  = os.environ.get("AI_PROVIDER_NER", "").strip().lower()
    active_model  = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b").strip()
    return jsonify({
        "available": available,
        "models":    models,
        "active_model": active_model,
        "ner_provider": ner_provider,
    })


@settings_bp.route("/api/ollama/models", methods=["GET"])
def api_ollama_models():
    """Retourne uniquement la liste des modèles Ollama disponibles localement."""
    try:
        from utils.api_client import OllamaClient
        if OllamaClient.is_available():
            return jsonify({"models": OllamaClient.list_models()})
    except Exception:
        pass
    return jsonify({"models": []})


@settings_bp.route("/api/backup/check-dir", methods=["POST"])
def api_backup_check_dir():
    """Vérifie qu'un répertoire existe et est accessible en écriture.

    Body JSON : { "path": str }
    Retourne  : { ok: bool, message: str }
    """
    import stat as _stat
    body = request.get_json(force=True, silent=True) or {}
    path_str = (body.get("path") or "").strip()
    if not path_str:
        return jsonify({"ok": False, "message": "Chemin vide"}), 400

    p = Path(path_str)
    try:
        if p.exists():
            if not p.is_dir():
                return jsonify({"ok": False, "message": "Ce chemin n'est pas un répertoire"})
            if not os.access(str(p), os.W_OK):
                return jsonify({"ok": False, "message": "Répertoire non inscriptible"})
            try:
                usage = _stat.os.statvfs(str(p))
                free_gb = (usage.f_bavail * usage.f_frsize) / (1024 ** 3)
                return jsonify({"ok": True, "message": f"Accessible · {free_gb:.1f} Go libres"})
            except Exception:
                return jsonify({"ok": True, "message": "Accessible en écriture"})
        else:
            # Le répertoire n'existe pas encore — vérifier que le parent est accessible
            parent = p.parent
            if not parent.exists():
                return jsonify({"ok": False, "message": f"Répertoire parent introuvable : {parent}"})
            if not os.access(str(parent), os.W_OK):
                return jsonify({"ok": False, "message": f"Répertoire parent non inscriptible : {parent}"})
            return jsonify({"ok": True, "message": "Répertoire sera créé automatiquement"})
    except Exception as exc:
        return jsonify({"ok": False, "message": str(exc)})
