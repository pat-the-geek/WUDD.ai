"""Module de scoring de pertinence des articles.

Calcule un score composite (0–100) pour chaque article selon :
  - Fraîcheur           : pénalité exponentielle basée sur l'âge (24h=100, 7j=~20)
  - Richesse NER        : nombre et diversité des entités nommées
  - Densité mots-clés   : occurrences des mots-clés de surveillance dans le résumé
  - Complétude          : présence d'un résumé valide et d'une image
  - Multiplicateur source : score composite de crédibilité (v2)
  - Triangulation       : bonus si plusieurs sources crédibles couvrent le même événement
  - Régularité source   : malus si la source publie de façon erratique
"""

import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .logging import default_logger


# ── Constantes ──────────────────────────────────────────────────────────────

_ENTITY_WEIGHT: dict[str, float] = {
    "PERSON": 1.5,
    "ORG": 1.3,
    "GPE": 1.2,
    "PRODUCT": 1.2,
    "EVENT": 1.1,
    "NORP": 1.0,
    "LOC": 0.9,
    "MONEY": 0.8,
    "PERCENT": 0.5,
    "CARDINAL": 0.3,
    "DATE": 0.3,
    "TIME": 0.3,
}

_ERROR_PREFIXES = (
    "désolé",
    "je n'ai pas pu",
    "erreur",
    "échec",
    "aucune information",
)

# Seuil Jaccard bigrammes pour la triangulation (proximité thématique)
_TRIANGULATION_JACCARD_THRESHOLD = 0.35
# Score minimal d'une source pour compter dans la triangulation
_TRIANGULATION_MIN_SOURCE_SCORE = 75
# Nombre minimal d'articles d'une source sur 30 jours pour le critère régularité
_REGULARITY_MIN_ARTICLES = 10


def _parse_date(date_str: str) -> Optional[datetime]:
    """Tente de parser une date depuis les formats connus du projet."""
    if not date_str:
        return None
    for fmt in (
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d",
        "%d/%m/%Y",
    ):
        try:
            return datetime.strptime(date_str, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    # RFC 822 (articles-from-rss)
    try:
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(date_str).astimezone(timezone.utc)
    except Exception:
        pass
    return None


def _freshness_score(date_str: str, now: datetime) -> float:
    """Retourne un score de fraîcheur entre 0 et 100.

    Décroissance exponentielle : 100 à t=0, ~50 à t=24h, ~20 à t=7j, ~5 à t=30j.
    """
    dt = _parse_date(date_str)
    if dt is None:
        return 20.0  # Score neutre si date inconnue
    age_hours = (now - dt).total_seconds() / 3600.0
    age_hours = max(0.0, age_hours)
    # Paramètre de décroissance : half-life ≈ 24h
    return 100.0 * math.exp(-0.693 * age_hours / 24.0)


def _entity_score(entities: dict) -> float:
    """Retourne un score basé sur la richesse des entités (0–100)."""
    if not isinstance(entities, dict):
        return 0.0
    total = 0.0
    for etype, values in entities.items():
        if not isinstance(values, list):
            continue
        weight = _ENTITY_WEIGHT.get(etype, 0.7)
        total += len(values) * weight
    # Normalise : 10 entités bien pondérées ≈ 100
    return min(100.0, total * 7.0)


def _keyword_score(resume: str, keywords: list[str]) -> float:
    """Retourne un score de densité mots-clés (0–100)."""
    if not resume or not keywords:
        return 0.0
    resume_lower = resume.lower()
    hits = sum(1 for kw in keywords if kw.lower() in resume_lower)
    # 3 mots-clés présents → score 100
    return min(100.0, hits * 33.3)


def _bigrams(text: str) -> set:
    """Retourne l'ensemble des bigrammes de mots d'un texte normalisé."""
    words = re.sub(r"[^\w\s]", " ", text.lower()).split()
    return {(words[i], words[i + 1]) for i in range(len(words) - 1)}


def _jaccard(set_a: set, set_b: set) -> float:
    """Similarité de Jaccard entre deux ensembles."""
    if not set_a or not set_b:
        return 0.0
    inter = len(set_a & set_b)
    union = len(set_a | set_b)
    return inter / union if union > 0 else 0.0


def _triangulation_bonus(article: dict, corpus: list[dict], credibility) -> float:
    """Calcule le bonus de triangulation inter-sources (0–10 pts).

    Compte le nombre de sources distinctes (score composite ≥ 75) qui couvrent
    le même événement que l'article dans les 48h (similarité Jaccard ≥ 0.35).

    Args:
        article     : article à évaluer
        corpus      : liste d'articles de référence (fenêtre 48h)
        credibility : instance de CredibilityEngine (ou None)

    Returns:
        Bonus entre 0 et 10.
    """
    if not corpus or credibility is None:
        return 0.0

    resume_a = article.get("Résumé") or article.get("resume") or ""
    if len(resume_a) < 50:
        return 0.0

    source_a = str(article.get("Sources") or article.get("source") or "")
    bigrams_a = _bigrams(resume_a)
    if not bigrams_a:
        return 0.0

    confirming_sources: set[str] = set()

    for other in corpus:
        source_b = str(other.get("Sources") or other.get("source") or "")
        if source_b == source_a:
            continue
        # Vérifier que la source B est crédible
        if credibility.get_composite_score(source_b) < _TRIANGULATION_MIN_SOURCE_SCORE:
            continue
        resume_b = other.get("Résumé") or other.get("resume") or ""
        if len(resume_b) < 50:
            continue
        bigrams_b = _bigrams(resume_b)
        if _jaccard(bigrams_a, bigrams_b) >= _TRIANGULATION_JACCARD_THRESHOLD:
            confirming_sources.add(source_b)

    n = len(confirming_sources)
    if n >= 4:
        return 10.0
    if n == 3:
        return 7.0
    if n == 2:
        return 4.0
    return 0.0


def _regularity_malus(source: str, articles_by_source: dict) -> float:
    """Calcule le malus de régularité de publication (0 à -10 pts).

    Basé sur l'écart-type des intervalles entre publications sur 30 jours.
    Ne s'applique qu'aux sources avec ≥ 10 articles dans la fenêtre.

    Args:
        source           : nom de la source
        articles_by_source : dict {source → [dates triées]}

    Returns:
        Malus négatif entre -10 et 0.
    """
    dates = articles_by_source.get(source, [])
    if len(dates) < _REGULARITY_MIN_ARTICLES:
        return 0.0

    dates_sorted = sorted(dates)
    intervals = [
        (dates_sorted[i + 1] - dates_sorted[i]) / 3600.0
        for i in range(len(dates_sorted) - 1)
    ]
    if not intervals:
        return 0.0

    mean = sum(intervals) / len(intervals)
    variance = sum((x - mean) ** 2 for x in intervals) / len(intervals)
    std = variance ** 0.5

    if std < 24:
        return 0.0
    if std < 72:
        return -3.0
    if std < 120:
        return -6.0
    return -10.0


def _completeness_score(article: dict) -> float:
    """Retourne un score de complétude (0–100)."""
    score = 0.0
    resume = article.get("Résumé", "")
    if isinstance(resume, str) and len(resume) > 100:
        # Pénaliser les résumés d'erreur
        if not any(resume.lower().startswith(p) for p in _ERROR_PREFIXES):
            score += 50.0
    # Bonus si images présentes
    images = article.get("Images", [])
    if isinstance(images, list) and images:
        score += 25.0
    # Bonus si sentiment présent (enrichissement v2)
    if article.get("sentiment"):
        score += 12.5
    # Bonus si entités présentes
    if isinstance(article.get("entities"), dict) and article["entities"]:
        score += 12.5
    return score


def _extract_keywords_flat(keyword_config: list) -> list[str]:
    """Extrait la liste plate des mots-clés depuis keyword-to-search.json."""
    flat = []
    for entry in keyword_config:
        if not isinstance(entry, dict):
            continue
        for field in ("or", "and", "keyword"):
            vals = entry.get(field)
            if isinstance(vals, list):
                flat.extend([v for v in vals if isinstance(v, str)])
            elif isinstance(vals, str):
                flat.append(vals)
    return flat


class ScoringEngine:
    """Moteur de scoring de pertinence des articles.

    Usage :
        engine = ScoringEngine(project_root)
        score = engine.score_article(article)
        articles_scored = engine.score_and_sort(articles)
    """

    def __init__(self, project_root: Optional[Path] = None):
        if project_root is None:
            project_root = Path(__file__).parent.parent
        self.project_root = project_root
        self._keywords: list[str] = self._load_keywords()
        self._credibility = self._load_credibility()

    def _load_keywords(self) -> list[str]:
        kw_file = self.project_root / "config" / "keyword-to-search.json"
        if not kw_file.exists():
            return []
        try:
            data = json.loads(kw_file.read_text(encoding="utf-8"))
            return _extract_keywords_flat(data)
        except Exception as e:
            default_logger.warning(f"Impossible de charger les mots-clés pour scoring : {e}")
            return []

    def _load_credibility(self):
        """Charge le moteur de crédibilité des sources (optionnel)."""
        try:
            from .source_credibility import CredibilityEngine
            return CredibilityEngine(self.project_root)
        except Exception:
            return None

    def score_article(
        self,
        article: dict,
        now: Optional[datetime] = None,
        weights: Optional[dict] = None,
        corpus: Optional[list] = None,
        articles_by_source: Optional[dict] = None,
    ) -> float:
        """Calcule le score de pertinence d'un article (0–100).

        Intègre :
          - Multiplicateur de crédibilité composite (score composite v2)
          - Bonus de triangulation inter-sources (0–10 pts, si corpus fourni)
          - Malus de régularité de publication (0 à −10 pts, si articles_by_source fourni)

        Args:
            article            : dict article (format interne WUDD.ai)
            now                : horodatage de référence (default: maintenant UTC)
            weights            : poids optionnels pour chaque composante
            corpus             : liste d'articles pour la triangulation (fenêtre 48h)
            articles_by_source : dict {source → [timestamps epoch]} pour la régularité

        Returns:
            Score flottant entre 0 et 100.
        """
        if now is None:
            now = datetime.now(timezone.utc)

        w = {
            "freshness": 0.35,
            "entities": 0.25,
            "keywords": 0.25,
            "completeness": 0.15,
        }
        if weights:
            w.update(weights)

        freshness    = _freshness_score(article.get("Date de publication", ""), now)
        entities     = _entity_score(article.get("entities", {}))
        keywords     = _keyword_score(article.get("Résumé", ""), self._keywords)
        completeness = _completeness_score(article)

        score = (
            freshness * w["freshness"]
            + entities * w["entities"]
            + keywords * w["keywords"]
            + completeness * w["completeness"]
        )

        source = str(article.get("Sources") or article.get("source") or "")

        # Multiplicateur de crédibilité composite (v2)
        if self._credibility is not None:
            multiplier = self._credibility.get_multiplier(source)
            score *= multiplier

        # Bonus triangulation inter-sources
        if corpus is not None and self._credibility is not None:
            score += _triangulation_bonus(article, corpus, self._credibility)

        # Malus régularité de publication
        if articles_by_source is not None:
            score += _regularity_malus(source, articles_by_source)

        return round(min(100.0, max(0.0, score)), 1)

    def _build_articles_by_source(
        self, articles: list[dict]
    ) -> dict:
        """Construit un index {source → [timestamps epoch]} sur 30 jours."""
        from datetime import timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(days=30)
        result: dict[str, list] = {}
        for a in articles:
            source = str(a.get("Sources") or a.get("source") or "")
            if not source:
                continue
            dt = _parse_date(a.get("Date de publication", ""))
            if dt and dt >= cutoff:
                result.setdefault(source, []).append(dt.timestamp())
        return result

    def score_and_sort(
        self,
        articles: list[dict],
        now: Optional[datetime] = None,
        top_n: Optional[int] = None,
    ) -> list[dict]:
        """Calcule et attache le score à chaque article, les trie par score décroissant.

        Le champ `score_pertinence` est ajouté en place dans chaque article.
        Intègre automatiquement la triangulation et la régularité si le corpus
        contient suffisamment d'articles (≥ 2).
        Retourne la liste triée (et tronquée si top_n est fourni).
        """
        if now is None:
            now = datetime.now(timezone.utc)

        # Pré-calcul des index pour triangulation et régularité
        corpus = articles if len(articles) >= 2 else None
        articles_by_source = (
            self._build_articles_by_source(articles) if articles else None
        )

        for article in articles:
            article["score_pertinence"] = self.score_article(
                article, now,
                corpus=corpus,
                articles_by_source=articles_by_source,
            )
        articles.sort(key=lambda a: a.get("score_pertinence", 0), reverse=True)
        return articles[:top_n] if top_n else articles

    def get_top_articles(
        self,
        top_n: int = 10,
        hours: int = 48,
        include_rss: bool = True,
    ) -> list[dict]:
        """Agrège tous les articles récents et retourne les N meilleurs scorés.

        Args:
            top_n       : nombre d'articles à retourner
            hours       : fenêtre temporelle en heures (0 = pas de filtre)
            include_rss : inclure articles-from-rss/ en plus de articles/

        Returns:
            Liste d'articles triés par score décroissant, avec le chemin source ajouté.
        """
        now = datetime.now(timezone.utc)
        cutoff = None
        if hours > 0:
            from datetime import timedelta
            cutoff = now - timedelta(hours=hours)

        scan_dirs: list[Path] = [self.project_root / "data" / "articles"]
        if include_rss:
            scan_dirs.append(self.project_root / "data" / "articles-from-rss")

        seen_urls: set[str] = set()
        all_articles: list[dict] = []
        for scan_dir in scan_dirs:
            if not scan_dir.exists():
                continue
            for json_file in scan_dir.rglob("*.json"):
                if "cache" in json_file.relative_to(scan_dir).parts:
                    continue
                try:
                    data = json.loads(json_file.read_text(encoding="utf-8", errors="replace"))
                    if not isinstance(data, list):
                        continue
                    rel_path = str(json_file.relative_to(self.project_root)).replace("\\", "/")
                    for article in data:
                        url = article.get("URL") or article.get("url", "")
                        if url and url in seen_urls:
                            continue
                        if cutoff:
                            dt = _parse_date(article.get("Date de publication", ""))
                            if dt and dt < cutoff:
                                continue
                        article.setdefault("_source_file", rel_path)
                        all_articles.append(article)
                        if url:
                            seen_urls.add(url)
                except (json.JSONDecodeError, OSError):
                    continue

        return self.score_and_sort(all_articles, now=now, top_n=top_n)

    def get_top_articles_from_index(
        self,
        top_n: int = 10,
        hours: int = 48,
        include_rss: bool = True,
    ) -> list[dict]:
        """Variante de get_top_articles() utilisant l'ArticleIndex pour éviter le scan complet.

        Charge uniquement les fichiers contenant des articles récents, identifiés
        via l'index léger (data/article_index.json) sans rglob sur data/.

        Retourne les N articles les mieux scorés. Bascule automatiquement sur
        get_top_articles() si l'index n'est pas disponible.
        """
        try:
            from .article_index import get_article_index
        except ImportError:
            return self.get_top_articles(top_n=top_n, hours=hours, include_rss=include_rss)

        idx = get_article_index(self.project_root)
        recent_entries = idx.get_recent(hours=hours)

        if not recent_entries:
            # Index vide ou inexistant — fallback sur le scan complet
            return self.get_top_articles(top_n=top_n, hours=hours, include_rss=include_rss)

        if not include_rss:
            recent_entries = [
                e for e in recent_entries
                if not e.get("file", "").startswith("data/articles-from-rss")
            ]

        all_articles = idx.load_articles(recent_entries)

        now = datetime.now(timezone.utc)
        return self.score_and_sort(all_articles, now=now, top_n=top_n)


# ── Singleton ScoringEngine ──────────────────────────────────────────────────
# Évite de relire keyword-to-search.json et sources_credibility.json à chaque
# instanciation (plusieurs scripts l'instancient indépendamment dans la même journée).

import threading as _threading

_engine_instances: dict[Path, tuple["ScoringEngine", float]] = {}
_engine_lock = _threading.Lock()


def get_scoring_engine(project_root: Optional[Path] = None) -> "ScoringEngine":
    """Retourne un ScoringEngine singleton pour project_root.

    L'instance est recréée automatiquement si les fichiers de configuration
    ont été modifiés depuis la dernière instanciation.
    """
    if project_root is None:
        project_root = Path(__file__).parent.parent
    project_root = project_root.resolve()

    config_files = [
        project_root / "config" / "keyword-to-search.json",
        project_root / "config" / "sources_credibility.json",
    ]
    current_mtime = max(
        (f.stat().st_mtime for f in config_files if f.exists()),
        default=0.0,
    )

    with _engine_lock:
        cached = _engine_instances.get(project_root)
        if cached is None or cached[1] < current_mtime:
            _engine_instances[project_root] = (ScoringEngine(project_root), current_mtime)
        return _engine_instances[project_root][0]
