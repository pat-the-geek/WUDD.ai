"""Module de crédibilité des sources médiatiques pour WUDD.ai.

Priorité 4 — Score de crédibilité des sources
==============================================
Attribue un score de crédibilité (0–100) à chaque source d'article en se basant
sur une base de données configurable (config/sources_credibility.json).

Le score influence le calcul de pertinence dans `utils/scoring.py` via un
multiplicateur.

v2 — Score composite dynamique
-------------------------------
Si les champs d'enrichissement automatique sont présents dans la base
(domain_age_years, transparence, mbfc_rating), un score composite est calculé :

    score_composite = score_statique    × 0.60
                    + score_age_domaine × 0.15
                    + score_transparence × 0.10
                    + score_mbfc         × 0.15

En l'absence de ces champs (sources non encore enrichies), le score statique
est retourné tel quel — aucune pénalité (fallback gracieux).

Usage :
    from utils.source_credibility import CredibilityEngine

    engine = CredibilityEngine(project_root)
    score      = engine.get_score("Le Monde")           # 92 (statique)
    composite  = engine.get_composite_score("Le Monde") # 94.2 (si enrichi)
    multiplier = engine.get_multiplier("BFM TV")        # basé sur composite
    rated      = engine.rate_articles(articles)         # ajoute "score_source"
"""

import json
import re
import unicodedata
from pathlib import Path
from typing import Optional

from .logging import default_logger

# ── Constantes ───────────────────────────────────────────────────────────────

_CREDIBILITY_FILE = "config/sources_credibility.json"

# Score par défaut pour les sources inconnues
_DEFAULT_SCORE: int = 50

# Bornes du multiplicateur de scoring (évite des valeurs extrêmes)
_MULTIPLIER_MIN: float = 0.60
_MULTIPLIER_MAX: float = 1.20

# Conversion rating MBFC → score numérique
_MBFC_SCORES: dict[str, int] = {
    "VERY HIGH":     100,
    "HIGH":           85,
    "MOSTLY FACTUAL": 65,
    "MIXED":          40,
    "LOW":            15,
    "VERY LOW":        0,
}

# Conversion âge domaine (années) → score — miroir de source_enricher.py
_AGE_SCORE_TABLE = [
    (20, 100), (10, 85), (5, 70), (3, 50), (2, 30), (1, 15), (0, 0),
]


def _age_to_score(age_years: float) -> int:
    for threshold, score in _AGE_SCORE_TABLE:
        if age_years >= threshold:
            return score
    return 0


# ── Normalisation ─────────────────────────────────────────────────────────────

def _normalize_source(name: str) -> str:
    """Normalise un nom de source pour la comparaison (minuscules, sans accents)."""
    text = unicodedata.normalize("NFKD", name)
    text = text.encode("ascii", errors="ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


# ── Moteur de crédibilité ────────────────────────────────────────────────────

class CredibilityEngine:
    """Évalue la crédibilité des sources d'articles WUDD.ai.

    Utilise une base de données configurable chargée depuis
    ``config/sources_credibility.json``. Les sources inconnues reçoivent
    le score par défaut (50/100).

    Args:
        project_root : racine du projet (auto-détectée si None)

    Example::

        engine = CredibilityEngine(project_root)
        score = engine.get_score("Le Monde")      # 92
        mult  = engine.get_multiplier("Le Monde") # 1.18
    """

    def __init__(self, project_root: Optional[Path] = None):
        if project_root is None:
            project_root = Path(__file__).parent.parent
        self.project_root = project_root
        self._db: dict[str, dict] = self._load_db()
        # Index normalisé → clé originale
        self._index: dict[str, str] = {
            _normalize_source(k): k for k in self._db
        }

    def _load_db(self) -> dict[str, dict]:
        """Charge config/sources_credibility.json."""
        path = self.project_root / _CREDIBILITY_FILE
        if not path.exists():
            default_logger.warning(
                f"Base de crédibilité introuvable : {path}. "
                "Score par défaut utilisé pour toutes les sources."
            )
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
            default_logger.warning("Format de sources_credibility.json invalide (attendu: dict).")
            return {}
        except json.JSONDecodeError as exc:
            default_logger.error(f"Erreur de lecture sources_credibility.json : {exc}")
            return {}

    def _lookup(self, source: str) -> Optional[dict]:
        """Recherche une source par nom normalisé. Retourne None si inconnue."""
        norm = _normalize_source(source)
        # Correspondance exacte
        if norm in self._index:
            return self._db[self._index[norm]]
        # Correspondance partielle : la source contient-elle un nom connu ?
        for norm_key, orig_key in self._index.items():
            if norm_key in norm or norm in norm_key:
                return self._db[orig_key]
        return None

    def get_score(self, source: str) -> int:
        """Retourne le score de crédibilité (0–100) d'une source.

        Args:
            source : nom de la source (ex: "Le Monde", "BFM TV")

        Returns:
            Entier entre 0 et 100. 50 si source inconnue.
        """
        if not source or not source.strip():
            return _DEFAULT_SCORE
        entry = self._lookup(source.strip())
        if entry is None:
            return _DEFAULT_SCORE
        return int(entry.get("score", _DEFAULT_SCORE))

    def get_composite_score(self, source: str) -> float:
        """Retourne le score composite (0–100) intégrant les signaux automatisés v2.

        Formule complète (si tous les champs d'enrichissement sont présents) :
            score_composite = score_statique    × 0.60
                            + score_age_domaine × 0.15
                            + score_transparence × 0.10
                            + score_mbfc         × 0.15

        Fallback gracieux : si les champs v2 sont absents, retourne le score
        statique pur. La pondération est ajustée proportionnellement selon les
        champs disponibles (aucune pénalité pour les sources non enrichies).

        Returns:
            Float entre 0 et 100.
        """
        if not source or not source.strip():
            return float(_DEFAULT_SCORE)

        entry = self._lookup(source.strip())
        if entry is None:
            return float(_DEFAULT_SCORE)

        score_static = float(entry.get("score", _DEFAULT_SCORE))

        has_age   = "domain_age_years" in entry
        has_transp = "transparence" in entry
        has_mbfc  = "mbfc_rating" in entry and entry["mbfc_rating"] is not None

        # Si aucun champ v2 → score statique pur
        if not has_age and not has_transp and not has_mbfc:
            return score_static

        # Calcul progressif selon les champs disponibles
        weight_static = 0.60
        total_w = weight_static
        score = score_static * weight_static

        if has_age:
            age_score = float(_age_to_score(entry["domain_age_years"]))
            score += age_score * 0.15
            total_w += 0.15

        if has_transp:
            transp_score = float(entry["transparence"]) / 4.0 * 100.0
            score += transp_score * 0.10
            total_w += 0.10

        if has_mbfc:
            mbfc_score = float(_MBFC_SCORES.get(entry["mbfc_rating"], 50))
            score += mbfc_score * 0.15
            total_w += 0.15

        # Normaliser sur les poids disponibles
        composite = score / total_w * (weight_static + 0.15 + 0.10 + 0.15) / 1.0
        # Recalcul propre : ramener sur la somme totale des poids actifs
        composite = score / total_w * (0.60 + (0.15 if has_age else 0) +
                                        (0.10 if has_transp else 0) +
                                        (0.15 if has_mbfc else 0)) / total_w * total_w
        # Formule directe simplifiée
        composite = score / total_w * 1.0

        return round(min(100.0, max(0.0, composite)), 1)

    def get_multiplier(self, source: str) -> float:
        """Retourne le multiplicateur de scoring (0.60–1.20) pour une source.

        Utilise le score composite (v2) si disponible, score statique sinon.
        → score 100 → 1.20, score 50 → 0.90, score 0 → 0.60

        Returns:
            Float entre _MULTIPLIER_MIN et _MULTIPLIER_MAX.
        """
        score = self.get_composite_score(source) / 100.0
        mult = _MULTIPLIER_MIN + score * (_MULTIPLIER_MAX - _MULTIPLIER_MIN)
        return round(mult, 3)

    def get_metadata(self, source: str) -> dict:
        """Retourne toutes les métadonnées d'une source (score, biais, type…).

        Inclut les champs v2 (domain_age_years, transparence, mbfc_rating,
        score_composite) si disponibles.
        """
        entry = self._lookup(source.strip()) if source else None
        if entry is None:
            return {
                "score":           _DEFAULT_SCORE,
                "score_composite": float(_DEFAULT_SCORE),
                "biais":           "inconnu",
                "type":            "inconnu",
                "pays":            "inconnu",
                "fiabilite":       "non évalué",
                "fact_checking":   False,
                "enrichi":         False,
            }
        meta = {
            "score":           entry.get("score", _DEFAULT_SCORE),
            "score_composite": self.get_composite_score(source),
            "biais":           entry.get("biais", "inconnu"),
            "type":            entry.get("type", "inconnu"),
            "pays":            entry.get("pays", "inconnu"),
            "fiabilite":       entry.get("fiabilite", "non évalué"),
            "fact_checking":   entry.get("fact_checking", False),
            "enrichi":         "enrich_date" in entry,
        }
        # Champs v2 optionnels
        for field in ("domain_age_years", "domain_age_score", "transparence",
                      "mbfc_rating", "enrich_date"):
            if field in entry:
                meta[field] = entry[field]
        return meta

    def rate_articles(self, articles: list[dict]) -> list[dict]:
        """Ajoute le champ ``score_source`` à chaque article.

        Le champ contient le score composite (0–100) si la source est enrichie,
        le score statique sinon. La liste est modifiée en place et retournée.

        Args:
            articles : liste d'articles au format interne WUDD.ai

        Returns:
            La même liste avec ``score_source`` ajouté.
        """
        for article in articles:
            source = article.get("Sources") or article.get("source") or ""
            article["score_source"] = round(self.get_composite_score(str(source)))
        return articles

    def reload(self) -> None:
        """Recharge la base de crédibilité depuis le disque."""
        self._db = self._load_db()
        self._index = {_normalize_source(k): k for k in self._db}
        default_logger.info(
            f"Base de crédibilité rechargée : {len(self._db)} sources"
        )
