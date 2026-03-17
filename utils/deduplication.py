"""Module de déduplication d'articles pour WUDD.ai.

Priorité 1 — Déduplication de contenu
======================================
Détecte les articles quasi-identiques (même événement, sources différentes)
en combinant :
  - Empreinte d'URL exacte  (doublons stricts)
  - Similarité de titre     (Jaccard sur bigrammes de mots)
  - Empreinte de résumé     (MD5 des 200 premiers caractères normalisés)

Usage :
    from utils.deduplication import Deduplicator

    dedup = Deduplicator(title_threshold=0.80)
    unique_articles = dedup.deduplicate(articles)

    # Ou pour ne vérifier qu'un seul article contre un lot existant :
    if not dedup.is_duplicate(new_article, existing_articles):
        existing_articles.append(new_article)
"""

import hashlib
import re
import unicodedata
from typing import Optional

from .logging import default_logger

# ── Constantes ───────────────────────────────────────────────────────────────

# Seuil par défaut de similarité Jaccard entre titres (0–1)
DEFAULT_TITLE_THRESHOLD: float = 0.80

# Seuils adaptatifs selon la longueur du texte (optimisation 2.5)
# Les textes courts (brèves) tolèrent un seuil plus bas car leurs bigrammes
# sont peu nombreux et le moindre mot commun gonfle le score.
# Les textes longs exigent plus de similarité pour éviter les faux positifs.
_ADAPTIVE_THRESHOLD_SHORT: float = 0.70   # résumés < 80 mots
_ADAPTIVE_THRESHOLD_MEDIUM: float = 0.80  # résumés 80–200 mots (= valeur historique)
_ADAPTIVE_THRESHOLD_LONG: float = 0.85    # résumés > 200 mots

# Longueur du préfixe de résumé utilisé pour l'empreinte MD5
_RESUME_FINGERPRINT_LEN: int = 200

# Mots vides français et anglais à ignorer pour la similarité
_STOPWORDS: frozenset = frozenset(
    [
        "le", "la", "les", "un", "une", "des", "du", "de", "et", "en",
        "au", "aux", "que", "qui", "se", "sa", "son", "ses", "ce", "cet",
        "cette", "ces", "par", "sur", "pour", "dans", "avec", "à", "il",
        "elle", "ils", "elles", "on", "nous", "vous", "je", "tu",
        "the", "a", "an", "of", "in", "to", "and", "is", "it",
    ]
)


# ── Fonctions utilitaires ────────────────────────────────────────────────────

def _normalize(text: str) -> str:
    """Normalise un texte : minuscules, sans accents, sans ponctuation."""
    # Unicode → ASCII (enlève les accents)
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", errors="ignore").decode("ascii")
    # Minuscules
    text = text.lower()
    # Supprimer les caractères non alphanumériques (garder les espaces)
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    # Normaliser les espaces
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _tokenize(text: str) -> list[str]:
    """Découpe un texte normalisé en tokens, sans mots vides."""
    return [w for w in text.split() if w not in _STOPWORDS and len(w) > 1]


def _bigrams(tokens: list[str]) -> frozenset:
    """Retourne l'ensemble des bigrammes de tokens.

    Retourne un frozenset vide si moins de 2 tokens (titre trop court pour
    comparaison fiable).
    """
    if len(tokens) < 2:
        return frozenset()
    return frozenset(zip(tokens, tokens[1:]))


def compute_title_similarity(title1: str, title2: str) -> float:
    """Calcule la similarité Jaccard (sur bigrammes de tokens) entre deux titres.

    Retourne un float entre 0.0 (aucune similarité) et 1.0 (identiques).

    >>> compute_title_similarity("IA générative : les défis", "IA générative : défis majeurs")
    0.5  # environ
    """
    t1_norm = _normalize(title1)
    t2_norm = _normalize(title2)

    # Cas triviaux
    if not t1_norm and not t2_norm:
        return 0.0  # deux titres vides ne sont pas "identiques"
    if t1_norm == t2_norm:
        return 1.0
    if not t1_norm or not t2_norm:
        return 0.0

    bg1 = _bigrams(_tokenize(t1_norm))
    bg2 = _bigrams(_tokenize(t2_norm))

    # Si les bigrammes sont vides (titre trop court), pas de comparaison fiable
    if not bg1 or not bg2:
        return 0.0

    intersection = len(bg1 & bg2)
    union = len(bg1 | bg2)
    return intersection / union if union > 0 else 0.0


def compute_resume_fingerprint(resume: str) -> str:
    """Retourne l'empreinte MD5 des N premiers caractères normalisés du résumé."""
    prefix = _normalize(resume)[:_RESUME_FINGERPRINT_LEN]
    return hashlib.md5(prefix.encode("utf-8")).hexdigest()


def _adaptive_jaccard_threshold(text: str) -> float:
    """Retourne le seuil Jaccard adaptatif selon la longueur du texte.

    Optimisation 2.5 : un seuil unique de 0.80 génère des faux positifs sur
    les brèves courtes et des faux négatifs sur les textes longs reformulés.

    Args:
        text : Texte de référence (titre ou résumé)

    Returns:
        Seuil Jaccard flottant entre 0.70 et 0.85.
    """
    word_count = len(text.split())
    if word_count < 80:
        return _ADAPTIVE_THRESHOLD_SHORT
    elif word_count <= 200:
        return _ADAPTIVE_THRESHOLD_MEDIUM
    else:
        return _ADAPTIVE_THRESHOLD_LONG


def compute_url_fingerprint(url: str) -> str:
    """Retourne l'empreinte MD5 de l'URL normalisée (sans fragment ni trailing slash)."""
    url_clean = url.strip().rstrip("/").lower().split("#")[0]
    return hashlib.md5(url_clean.encode("utf-8")).hexdigest()


# ── Classe principale ────────────────────────────────────────────────────────

class Deduplicator:
    """Détecteur de doublons et quasi-doublons pour une liste d'articles WUDD.ai.

    Combine trois signaux :
    1. URL exacte (même après normalisation)
    2. Similarité de titre Jaccard ≥ threshold
    3. Empreinte de résumé MD5 identique (si résumés présents)

    Attributes:
        title_threshold : seuil de similarité Jaccard (défaut : 0.80)

    Example::

        dedup = Deduplicator(title_threshold=0.80)
        unique = dedup.deduplicate(articles)
        stats = dedup.stats  # {"total": 100, "unique": 87, "removed": 13}
    """

    def __init__(self, title_threshold: float = DEFAULT_TITLE_THRESHOLD):
        self.title_threshold = title_threshold
        self._seen_urls: set[str] = set()
        self._seen_resume_fps: set[str] = set()
        self._seen_titles: list[str] = []  # pour comparaison par similarité
        self.stats: dict[str, int] = {"total": 0, "unique": 0, "removed": 0}

    def reset(self) -> None:
        """Réinitialise l'état interne (utile pour réutiliser l'instance)."""
        self._seen_urls.clear()
        self._seen_resume_fps.clear()
        self._seen_titles.clear()
        self.stats = {"total": 0, "unique": 0, "removed": 0}

    def is_duplicate(self, article: dict) -> bool:
        """Vérifie si un article est un doublon par rapport à l'état courant.

        N'enregistre PAS l'article dans l'état (utiliser `register` pour cela).

        Returns:
            True si l'article est un doublon, False sinon.
        """
        # Signal 1 : URL
        url = (article.get("URL") or article.get("url") or "").strip()
        if url:
            url_fp = compute_url_fingerprint(url)
            if url_fp in self._seen_urls:
                return True

        # Signal 2 : empreinte de résumé
        resume = article.get("Résumé") or article.get("resume") or ""
        if isinstance(resume, str) and len(resume) > 50:
            res_fp = compute_resume_fingerprint(resume)
            if res_fp in self._seen_resume_fps:
                return True

        # Signal 3 : similarité de titre (seuil adaptatif selon longueur — optimisation 2.5)
        title = (article.get("Titre") or article.get("titre") or "").strip()
        if title:
            threshold = _adaptive_jaccard_threshold(title) if self.title_threshold == DEFAULT_TITLE_THRESHOLD \
                else self.title_threshold  # respecter le seuil explicite si non-défaut
            for seen_title in self._seen_titles:
                if compute_title_similarity(title, seen_title) >= threshold:
                    return True

        return False

    def register(self, article: dict) -> None:
        """Enregistre un article comme « vu » dans l'état interne."""
        url = (article.get("URL") or article.get("url") or "").strip()
        if url:
            self._seen_urls.add(compute_url_fingerprint(url))

        resume = article.get("Résumé") or article.get("resume") or ""
        if isinstance(resume, str) and len(resume) > 50:
            self._seen_resume_fps.add(compute_resume_fingerprint(resume))

        title = (article.get("Titre") or article.get("titre") or "").strip()
        if title:
            self._seen_titles.append(title)

    def deduplicate(self, articles: list[dict]) -> list[dict]:
        """Déduplique une liste d'articles en conservant le premier occurrence.

        Traite les articles dans l'ordre de la liste.  Le premier article rencontré
        est toujours conservé ; les suivants jugés doublons sont écartés.

        Args:
            articles : liste d'articles au format interne WUDD.ai

        Returns:
            Liste des articles uniques, dans leur ordre d'apparition d'origine.
        """
        self.reset()
        unique: list[dict] = []

        for article in articles:
            self.stats["total"] += 1
            if self.is_duplicate(article):
                self.stats["removed"] += 1
                default_logger.debug(
                    f"Doublon supprimé : {(article.get('Titre') or article.get('URL') or '')[:80]}"
                )
            else:
                self.register(article)
                unique.append(article)
                self.stats["unique"] += 1

        if self.stats["removed"] > 0:
            default_logger.info(
                f"Déduplication : {self.stats['total']} articles → "
                f"{self.stats['unique']} uniques "
                f"({self.stats['removed']} doublons supprimés)"
            )
        return unique

    def deduplicate_incremental(
        self, new_articles: list[dict], existing_articles: list[dict]
    ) -> list[dict]:
        """Filtre `new_articles` en excluant les doublons déjà présents dans `existing_articles`.

        Utile pour les mises à jour incrémentales d'un fichier JSON existant.

        Args:
            new_articles      : nouveaux articles à ajouter
            existing_articles : articles déjà présents dans le fichier

        Returns:
            Sous-liste de `new_articles` sans les doublons.
        """
        self.reset()
        # Enregistrer l'existant
        for article in existing_articles:
            self.register(article)

        # Filtrer les nouveaux
        filtered: list[dict] = []
        for article in new_articles:
            self.stats["total"] += 1
            if self.is_duplicate(article):
                self.stats["removed"] += 1
            else:
                self.register(article)
                filtered.append(article)
                self.stats["unique"] += 1

        return filtered
