"""Module d'enrichissement automatique des sources — WUDD.ai v2.3.

Enrichit les entrées de config/sources_credibility.json avec trois signaux
automatisés calculés à partir de sources publiques :

  1. Âge du domaine       (WHOIS via python-whois)
  2. Transparence éditoriale (scraping HTTP des pages légales)
  3. Rating MBFC           (scrape mediabiasfactcheck.com)

Usage :
    from utils.source_enricher import enrich_source, run_enrichment

    # Enrichir une source unique
    entry = {"score": 92, "biais": "centre-gauche", ...}
    enriched = enrich_source("Le Monde", entry, domain="lemonde.fr")

    # Enrichir toutes les sources manquantes dans sources_credibility.json
    run_enrichment(project_root)
"""

import re
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import requests

from .logging import default_logger

# ── Constantes ────────────────────────────────────────────────────────────────

_HTTP_TIMEOUT = 8  # secondes par requête
_MBFC_SEARCH_URL = "https://mediabiasfactcheck.com/?s={query}"
_MBFC_RATING_PATTERNS = [
    (re.compile(r"VERY\s+HIGH", re.I), "VERY HIGH"),
    (re.compile(r"HIGH\s+FACTUAL", re.I), "HIGH"),
    (re.compile(r"\bHIGH\b", re.I), "HIGH"),
    (re.compile(r"MOSTLY\s+FACTUAL", re.I), "MOSTLY FACTUAL"),
    (re.compile(r"\bMIXED\b", re.I), "MIXED"),
    (re.compile(r"VERY\s+LOW", re.I), "VERY LOW"),
    (re.compile(r"\bLOW\b", re.I), "LOW"),
]

# Chemins canoniques testés pour la transparence éditoriale
_TRANSPARENCY_PATHS = [
    ["/mentions-legales", "/mentions_legales", "/legal", "/mentions-légales"],
    ["/about", "/qui-sommes-nous", "/a-propos", "/apropos", "/about-us"],
    ["/cgu", "/conditions", "/conditions-generales", "/terms"],
    ["/contact", "/redaction", "/nous-contacter", "/contactez-nous"],
]

# Correspondance âge → score
_AGE_SCORE_TABLE = [
    (20, 100),
    (10, 85),
    (5,  70),
    (3,  50),
    (2,  30),
    (1,  15),
    (0,  0),
]

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; WUDD.ai/2.3; +https://github.com/wudd-ai)"
    )
}


# ── Utilitaires ───────────────────────────────────────────────────────────────

def _normalize(text: str) -> str:
    """Minuscules, sans accents, sans ponctuation."""
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9\s]", " ", t.lower()).strip()


def _age_to_score(age_years: float) -> int:
    """Convertit un âge de domaine (années) en score 0–100."""
    for threshold, score in _AGE_SCORE_TABLE:
        if age_years >= threshold:
            return score
    return 0


def _extract_domain_from_db(source_name: str, db: dict) -> Optional[str]:
    """Tente de déduire le domaine depuis les URLs stockées dans la DB."""
    entry = db.get(source_name, {})
    url = entry.get("url") or entry.get("URL") or entry.get("website")
    if url:
        parsed = urlparse(url if "://" in url else "https://" + url)
        return parsed.netloc.lstrip("www.")
    return None


# ── Enrichissement âge du domaine ─────────────────────────────────────────────

def enrich_domain_age(domain: str) -> Optional[float]:
    """Retourne l'âge du domaine en années via WHOIS.

    Args:
        domain : nom de domaine sans protocole (ex: "lemonde.fr")

    Returns:
        Âge en années (float) ou None si WHOIS échoue.
    """
    try:
        import whois  # python-whois
        w = whois.whois(domain)
        creation = w.creation_date
        if isinstance(creation, list):
            creation = creation[0]
        if creation is None:
            return None
        if not isinstance(creation, datetime):
            return None
        if creation.tzinfo is None:
            creation = creation.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        age = (now - creation).days / 365.25
        return round(max(0.0, age), 1)
    except ImportError:
        default_logger.warning(
            "python-whois non installé — critère âge domaine désactivé. "
            "Installez-le : pip install python-whois"
        )
        return None
    except Exception as exc:
        default_logger.debug(f"WHOIS {domain} : {exc}")
        return None


# ── Enrichissement transparence éditoriale ────────────────────────────────────

def enrich_transparency(domain: str) -> int:
    """Vérifie la présence des pages légales sur le domaine.

    Teste 4 catégories de chemins. Chaque catégorie trouvée vaut 1 point.

    Args:
        domain : nom de domaine sans protocole (ex: "lemonde.fr")

    Returns:
        Score de transparence entre 0 et 4.
    """
    base = f"https://{domain}"
    score = 0
    session = requests.Session()
    session.headers.update(_HEADERS)

    for category_paths in _TRANSPARENCY_PATHS:
        found = False
        for path in category_paths:
            if found:
                break
            url = base + path
            try:
                resp = session.head(url, timeout=_HTTP_TIMEOUT, allow_redirects=True)
                if resp.status_code == 200:
                    found = True
                elif resp.status_code == 405:
                    # HEAD non supporté — essayer GET
                    resp2 = session.get(url, timeout=_HTTP_TIMEOUT, allow_redirects=True)
                    if resp2.status_code == 200:
                        found = True
            except Exception:
                continue
        if found:
            score += 1

    return score


# ── Enrichissement MBFC ───────────────────────────────────────────────────────

def enrich_mbfc(source_name: str) -> Optional[str]:
    """Scrape MBFC pour obtenir le rating factuel d'une source.

    Args:
        source_name : nom affiché de la source (ex: "Le Monde")

    Returns:
        Rating MBFC string ou None si non trouvé.
        Valeurs : "VERY HIGH", "HIGH", "MOSTLY FACTUAL", "MIXED", "LOW", "VERY LOW"
    """
    query = re.sub(r"\s+", "+", source_name.strip())
    url = _MBFC_SEARCH_URL.format(query=query)
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=_HTTP_TIMEOUT)
        if resp.status_code != 200:
            return None
        text = resp.text

        # Chercher le nom de la source dans la page
        norm_name = _normalize(source_name)
        if norm_name not in _normalize(text):
            return None

        # Extraire le bloc de texte autour de la première occurrence
        idx = _normalize(text).find(norm_name)
        excerpt = text[max(0, idx - 200): idx + 500]

        for pattern, rating in _MBFC_RATING_PATTERNS:
            if pattern.search(excerpt):
                return rating
        return None
    except Exception as exc:
        default_logger.debug(f"MBFC {source_name} : {exc}")
        return None


# ── Orchestrateur principal ───────────────────────────────────────────────────

def enrich_source(
    name: str,
    entry: dict,
    domain: Optional[str] = None,
    delay: float = 1.5,
) -> dict:
    """Enrichit une entrée de source avec les 3 critères automatisés.

    Args:
        name   : nom de la source (ex: "Le Monde")
        entry  : dict existant depuis sources_credibility.json
        domain : domaine forcé (sinon tenté depuis entry["url"])
        delay  : pause entre requêtes HTTP (secondes)

    Returns:
        Copie de l'entrée enrichie avec les nouveaux champs.
    """
    result = dict(entry)

    # ── 1. Âge du domaine ─────────────────────────────────────────────────────
    if domain:
        age = enrich_domain_age(domain)
        if age is not None:
            result["domain_age_years"] = age
            result["domain_age_score"] = _age_to_score(age)
            default_logger.info(f"  [{name}] âge domaine : {age} ans → score {result['domain_age_score']}")
        time.sleep(delay)

    # ── 2. Transparence éditoriale ────────────────────────────────────────────
    if domain:
        transp = enrich_transparency(domain)
        result["transparence"] = transp
        default_logger.info(f"  [{name}] transparence : {transp}/4")
        time.sleep(delay)

    # ── 3. MBFC rating ────────────────────────────────────────────────────────
    mbfc = enrich_mbfc(name)
    result["mbfc_rating"] = mbfc
    default_logger.info(f"  [{name}] MBFC : {mbfc or 'non répertorié'}")

    result["enrich_date"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return result


# ── Runner batch ──────────────────────────────────────────────────────────────

def run_enrichment(
    project_root: Path,
    force: bool = False,
    source_filter: Optional[str] = None,
    delay: float = 2.0,
    dry_run: bool = False,
) -> dict:
    """Enrichit les sources de sources_credibility.json manquant de données v2.

    Args:
        project_root  : racine du projet
        force         : re-enrichir même les sources déjà enrichies
        source_filter : si fourni, enrichir uniquement cette source
        delay         : pause entre requêtes (secondes)
        dry_run       : simuler sans écrire

    Returns:
        Dictionnaire de résultats : {"enriched": N, "skipped": N, "failed": N}
    """
    db_path = project_root / "config" / "sources_credibility.json"
    if not db_path.exists():
        default_logger.error(f"sources_credibility.json introuvable : {db_path}")
        return {"enriched": 0, "skipped": 0, "failed": 0}

    import json
    db = json.loads(db_path.read_text(encoding="utf-8"))

    stats = {"enriched": 0, "skipped": 0, "failed": 0}

    # Construire un index domaine → source depuis les URL connues des articles
    # (permet de deviner le domaine si non renseigné dans la DB)
    domain_hints = _build_domain_hints(project_root)

    for name, entry in list(db.items()):
        if name == "_comment":
            continue
        if source_filter and name.lower() != source_filter.lower():
            continue

        already_enriched = "domain_age_years" in entry and "mbfc_rating" in entry
        if already_enriched and not force:
            stats["skipped"] += 1
            continue

        default_logger.info(f"Enrichissement : {name}")

        domain = (
            entry.get("domain")
            or domain_hints.get(_normalize(name))
            or _guess_domain(name)
        )

        try:
            enriched = enrich_source(name, entry, domain=domain, delay=delay)
            if not dry_run:
                db[name] = enriched
            stats["enriched"] += 1
        except Exception as exc:
            default_logger.warning(f"  [{name}] échec enrichissement : {exc}")
            stats["failed"] += 1

        time.sleep(delay)

    if not dry_run:
        db_path.write_text(
            json.dumps(db, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        default_logger.info(
            f"sources_credibility.json mis à jour : "
            f"{stats['enriched']} enrichies, {stats['skipped']} ignorées, {stats['failed']} en échec"
        )

    return stats


def sync_new_sources(
    project_root: Path,
    dry_run: bool = False,
) -> dict:
    """Synchronise sources_credibility.json avec les sources surveillées.

    Collecte toutes les sources actives (OPML + web_sources.json + articles
    existants) via ``utils.source_registry``, puis ajoute à
    sources_credibility.json celles qui n'y figurent pas encore avec un score
    par défaut de 50 (neutre — ni bonus ni malus sur le classement).

    Cette fonction est conçue pour être appelée avant ``run_enrichment()`` :
    elle ne fait aucune requête HTTP et s'exécute en quelques secondes.

    Args:
        project_root : racine du projet
        dry_run      : afficher les nouvelles sources sans écrire

    Returns:
        {"added": N, "already_known": N, "total_registry": N}
    """
    import json as _json
    from .source_registry import collect_sources

    db_path = project_root / "config" / "sources_credibility.json"
    if not db_path.exists():
        default_logger.error(f"sources_credibility.json introuvable : {db_path}")
        return {"added": 0, "already_known": 0, "total_registry": 0}

    db = _json.loads(db_path.read_text(encoding="utf-8"))
    registry = collect_sources(project_root)

    stats = {"added": 0, "already_known": 0, "total_registry": len(registry)}

    # Index normalisé des sources déjà présentes (insensible à la casse/accents)
    known_normalized = {_normalize(k): k for k in db if k != "_comment"}

    for source_name in sorted(registry):
        if _normalize(source_name) in known_normalized:
            stats["already_known"] += 1
            continue

        # Nouvelle source — entrée minimale, score neutre
        default_entry = {
            "score": 50,
            "biais": "inconnu",
            "type": "inconnu",
            "pays": "inconnu",
            "fiabilite": "non évaluée",
            "fact_checking": False,
        }
        default_logger.info(f"  [sync] Nouvelle source : {source_name}")
        if not dry_run:
            db[source_name] = default_entry
        stats["added"] += 1

    if not dry_run and stats["added"] > 0:
        db_path.write_text(
            _json.dumps(db, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        default_logger.info(
            f"[sync] sources_credibility.json : "
            f"{stats['added']} ajoutées, {stats['already_known']} déjà connues "
            f"(registre : {stats['total_registry']})"
        )
    elif stats["added"] == 0:
        default_logger.info(
            f"[sync] Aucune nouvelle source — {stats['already_known']} déjà connues"
        )

    return stats


def _build_domain_hints(project_root: Path) -> dict:
    """Construit un index source normalisée → domaine depuis les articles existants."""
    import json
    hints = {}
    data_dirs = [
        project_root / "data" / "articles",
        project_root / "data" / "articles-from-rss",
    ]
    for data_dir in data_dirs:
        if not data_dir.exists():
            continue
        for json_file in list(data_dir.rglob("*.json"))[:50]:  # limiter le scan
            if "cache" in json_file.parts:
                continue
            try:
                articles = json.loads(json_file.read_text(encoding="utf-8", errors="replace"))
                if not isinstance(articles, list):
                    continue
                for article in articles[:20]:
                    source = str(article.get("Sources") or article.get("source") or "")
                    url = str(article.get("URL") or article.get("url") or "")
                    if source and url and "://" in url:
                        norm = _normalize(source)
                        if norm not in hints:
                            try:
                                domain = urlparse(url).netloc.lstrip("www.")
                                if domain:
                                    hints[norm] = domain
                            except Exception:
                                pass
            except Exception:
                continue
    return hints


def _guess_domain(source_name: str) -> Optional[str]:
    """Tente de deviner un domaine depuis le nom de la source.

    Heuristiques simples pour les sources francophones communes.
    """
    # Normalisation basique : "Le Monde" → "lemonde.fr"
    clean = _normalize(source_name)
    clean = re.sub(r"\s+", "", clean)
    # Supprimer articles
    for article in ("le", "la", "les", "l", "the"):
        if clean.startswith(article):
            clean = clean[len(article):]
            break
    if not clean:
        return None
    # Essayer .fr puis .com
    return f"{clean}.fr"
