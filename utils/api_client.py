"""Module client API pour l'interaction avec EurIA (Infomaniak) et Claude (Anthropic).

Fournit :
- EurIAClient  : client pour l'API EurIA/Qwen3 d'Infomaniak
- ClaudeClient : client pour l'API Anthropic Claude
- FallbackClient : wrapper qui essaie le client primaire, puis le secondaire en cas d'échec
- get_ai_client() : factory qui retourne le(s) client(s) selon AI_PROVIDER dans .env
"""

import json
import os
import re
import time
import threading
import unicodedata
import requests
from typing import Optional
from .logging import default_logger
from .config import get_config


EURIA_DEFAULT_MODEL = "openai/gpt-oss-120b"
_EURIA_REASONING_RETRY_SYSTEM = (
    "Réponds uniquement avec la réponse finale utile dans le champ content. "
    "N'inclus aucun raisonnement, aucune balise <think>, aucun commentaire méta."
)


def get_euria_model() -> str:
    """Retourne le modèle EurIA effectif."""
    model = os.environ.get("EURIA_MODEL", "").strip()
    return model or EURIA_DEFAULT_MODEL


def _extract_chat_text(value) -> str:
    """Normalise les formats de contenu OpenAI-compatibles en texte brut."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
                continue
            if not isinstance(item, dict):
                continue
            text = item.get("text")
            if isinstance(text, str):
                parts.append(text)
                continue
            inner_text = item.get("content")
            if isinstance(inner_text, str):
                parts.append(inner_text)
        return "".join(parts)
    return ""


def _extract_reasoning_text(message_or_delta: dict) -> str:
    """Extrait un éventuel champ de raisonnement sans l'exposer au frontend."""
    if not isinstance(message_or_delta, dict):
        return ""
    for key in ("reasoning", "reasoning_content", "thinking"):
        text = _extract_chat_text(message_or_delta.get(key))
        if text:
            return text
    return ""


# ── Circuit Breaker ───────────────────────────────────────────────────────────

class CircuitBreaker:
    """Circuit breaker thread-safe pour les appels API externes.

    États :
      CLOSED     — appels autorisés (fonctionnement normal)
      OPEN       — appels bloqués pendant la fenêtre de grâce (grace_seconds)
      HALF-OPEN  — un appel de sonde autorisé pour tester le rétablissement
      OPEN_QUOTA — quota API dépassé (HTTP 429) ; grâce jusqu'à minuit UTC
      OPEN_AUTH  — authentification invalide (HTTP 401/403) ; blocage permanent
                   jusqu'à appel explicite de reset()

    Optimisation 2.3 : les erreurs sont différenciées par catégorie afin
    d'appliquer une grâce adaptée (timeout ≠ quota ≠ auth).

    Transitions :
      CLOSED      → OPEN       : après N échecs transients consécutifs
      CLOSED      → OPEN_QUOTA : sur erreur 429 (quota dépassé)
      CLOSED      → OPEN_AUTH  : sur erreur 401/403 (authentification invalide)
      OPEN        → HALF-OPEN  : après grace_seconds secondes
      OPEN_QUOTA  → CLOSED     : automatiquement à minuit UTC (lazy reset)
      OPEN_AUTH   → CLOSED     : uniquement via reset() explicite
      HALF-OPEN   → CLOSED     : succès de la sonde
      HALF-OPEN   → OPEN       : échec de la sonde
    """

    _STATE_CLOSED     = "CLOSED"
    _STATE_OPEN       = "OPEN"
    _STATE_HALF_OPEN  = "HALF-OPEN"
    _STATE_OPEN_QUOTA = "OPEN_QUOTA"
    _STATE_OPEN_AUTH  = "OPEN_AUTH"

    def __init__(
        self,
        name: str = "api",
        failure_threshold: int = 5,
        grace_seconds: float = 300.0,
    ) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.grace_seconds = grace_seconds
        self._lock = threading.Lock()
        self._state = self._STATE_CLOSED
        self._failure_count = 0
        self._opened_at: float = 0.0
        self._quota_reset_date: Optional[str] = None  # date ISO "YYYY-MM-DD"

    @property
    def state(self) -> str:
        return self._state

    def _transition(self, new_state: str) -> None:
        if new_state != self._state:
            default_logger.info(
                f"[CircuitBreaker:{self.name}] {self._state} → {new_state}"
            )
            self._state = new_state

    def allow_request(self) -> bool:
        """Retourne True si l'appel est autorisé selon l'état du circuit."""
        with self._lock:
            if self._state == self._STATE_CLOSED:
                return True

            if self._state == self._STATE_OPEN:
                elapsed = time.monotonic() - self._opened_at
                if elapsed >= self.grace_seconds:
                    self._transition(self._STATE_HALF_OPEN)
                    return True  # Laisse passer la sonde
                return False

            if self._state == self._STATE_OPEN_QUOTA:
                # Reset automatique à minuit UTC (lazy)
                today = time.strftime("%Y-%m-%d", time.gmtime())
                if self._quota_reset_date and today > self._quota_reset_date:
                    default_logger.info(
                        f"[CircuitBreaker:{self.name}] Nouveau jour — reset quota automatique."
                    )
                    self._failure_count = 0
                    self._transition(self._STATE_CLOSED)
                    return True
                return False

            if self._state == self._STATE_OPEN_AUTH:
                # Blocage permanent — nécessite reset() explicite
                return False

            # HALF-OPEN : un seul appel de sonde autorisé
            return True

    def record_success(self) -> None:
        """À appeler après un appel réussi."""
        with self._lock:
            if self._state == self._STATE_HALF_OPEN:
                self._transition(self._STATE_CLOSED)
                default_logger.info(
                    f"[CircuitBreaker:{self.name}] Rétablissement confirmé — circuit fermé."
                )
            self._failure_count = 0

    def record_failure(self, error_category: str = "transient") -> None:
        """À appeler après un échec d'appel.

        Args:
            error_category : catégorie d'erreur pour adapter la grâce :
                - "transient" (défaut) : timeout, connexion — comportement standard
                - "quota"              : HTTP 429 — blocage jusqu'à minuit UTC
                - "auth"               : HTTP 401/403 — blocage permanent jusqu'à reset()
        """
        with self._lock:
            if error_category == "quota":
                self._quota_reset_date = time.strftime("%Y-%m-%d", time.gmtime())
                self._transition(self._STATE_OPEN_QUOTA)
                default_logger.warning(
                    f"[CircuitBreaker:{self.name}] Quota API dépassé (429) — "
                    f"circuit OPEN_QUOTA jusqu'à minuit UTC ({self._quota_reset_date})."
                )
                return

            if error_category == "auth":
                self._transition(self._STATE_OPEN_AUTH)
                default_logger.error(
                    f"[CircuitBreaker:{self.name}] Authentification invalide (401/403) — "
                    f"circuit OPEN_AUTH. Vérifiez vos credentials et appelez reset()."
                )
                return

            # Comportement standard (transient)
            self._failure_count += 1
            if self._state == self._STATE_HALF_OPEN:
                self._opened_at = time.monotonic()
                self._transition(self._STATE_OPEN)
                default_logger.warning(
                    f"[CircuitBreaker:{self.name}] Sonde échouée — circuit rouvert "
                    f"pour {self.grace_seconds:.0f}s."
                )
            elif self._failure_count >= self.failure_threshold:
                self._opened_at = time.monotonic()
                self._transition(self._STATE_OPEN)
                default_logger.warning(
                    f"[CircuitBreaker:{self.name}] {self._failure_count} échecs consécutifs "
                    f"— circuit ouvert pour {self.grace_seconds:.0f}s."
                )

    def reset(self) -> None:
        """Réinitialise le circuit breaker vers l'état CLOSED.

        À utiliser après correction d'une erreur d'authentification (OPEN_AUTH)
        ou manuellement pour forcer la réouverture.
        """
        with self._lock:
            self._failure_count = 0
            self._quota_reset_date = None
            self._transition(self._STATE_CLOSED)
            default_logger.info(f"[CircuitBreaker:{self.name}] Reset manuel — circuit fermé.")


# Instances partagées par client (une par fournisseur)
_euria_breaker  = CircuitBreaker(name="EurIA",  failure_threshold=5, grace_seconds=300)
_claude_breaker = CircuitBreaker(name="Claude", failure_threshold=5, grace_seconds=300)

# ── Extraction d'entités nommées (NER) ───────────────────────────────────────

# Partie statique (instructions) — mise en cache côté Claude via cache_control
_NER_SYSTEM_INSTRUCTIONS = """Tu es un extracteur d'entités nommées (NER).

Retourne UNIQUEMENT un objet JSON valide, sans aucun commentaire ni texte avant ou après.
Omets les catégories qui ne contiennent aucune entité.
Chaque valeur est un tableau de chaînes dédupliquées.

Catégories :
- PERSON : personnes physiques nommées
- NORP : nationalités, groupes religieux ou politiques
- ORG : organisations, entreprises, institutions
- GPE : pays, villes, régions géopolitiques
- LOC : lieux géographiques non géopolitiques
- FAC : bâtiments, aéroports, monuments nommés
- PRODUCT : produits, services, technologies nommés
- EVENT : événements nommés (conférences, sommets, crises…)
- WORK_OF_ART : titres d'œuvres (livres, films, rapports…)
- LAW : lois, règlements, articles de loi nommés
- LANGUAGE : langues nommées
- DATE : dates et périodes explicites
- TIME : heures et moments de la journée
- PERCENT : pourcentages et fractions
- MONEY : montants monétaires
- QUANTITY : quantités mesurables
- ORDINAL : ordinaux (premier, troisième…)
- CARDINAL : nombres cardinaux significatifs

Règles de désambiguïsation importantes :
- Classe les lois, règlements, amendements, conventions et licences nommées en LAW, pas en ORG, EVENT ou PRODUCT.
- Classe les montants explicites en MONEY en ne gardant que le montant lui-même (ex. "30 milliards de dollars"), jamais la phrase contextuelle complète.
- Classe les films, livres, séries, albums et rapports nommés en WORK_OF_ART ; réserve PRODUCT aux logiciels, appareils, services et technologies.
- Si une valeur n'est qu'une année, une date ou une période explicite (ex. "2026", "janvier 2026"), classe-la en DATE, pas en GPE, ORG ou EVENT.
- Un événement peut garder son année dans EVENT (ex. "WWDC 2026"), mais l'année seule ne doit pas être reclassée dans un autre type.

Exemples attendus :
- "Cloud Act" → LAW
- "30 milliards de dollars" → MONEY
- "Dune" → WORK_OF_ART
- "ChatGPT" → PRODUCT
- "2026" → DATE"""

# Partie statique sentiment (mise en cache côté Claude)
_SENTIMENT_SYSTEM_INSTRUCTIONS = (
    "Tu es un analyseur de ton éditorial journalistique. "
    "Réponds UNIQUEMENT avec un objet JSON valide, sans commentaire ni texte autour.\n\n"
    "Champs attendus :\n"
    '- "sentiment" : une des valeurs exactes : "positif", "neutre", "négatif"\n'
    '- "score_sentiment" : entier entre 1 (très négatif) et 5 (très positif), 3=neutre\n'
    '- "ton_editorial" : une des valeurs exactes : "factuel", "alarmiste", "promotionnel", "critique", "analytique"\n'
    '- "score_ton" : entier entre 1 (très biaisé/sensationnaliste) et 5 (très factuel/neutre)'
)

# Prompt EurIA complet (NER + sentiment) — instructions + variable dans un seul bloc
_PROMPT_ENTITIES = _NER_SYSTEM_INSTRUCTIONS + "\n\nTexte à analyser :\n{resume}"

_ENTITY_TYPES = [
    "PERSON", "NORP", "ORG", "GPE", "LOC", "FAC",
    "PRODUCT", "EVENT", "WORK_OF_ART", "LAW", "LANGUAGE",
    "DATE", "TIME", "PERCENT", "MONEY", "QUANTITY", "ORDINAL", "CARDINAL",
]

_MONTH_NAMES = (
    "janvier", "fevrier", "février", "mars", "avril", "mai", "juin",
    "juillet", "aout", "août", "septembre", "octobre", "novembre", "decembre",
    "décembre", "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
)
_MONTH_NAMES_RE = "|".join(sorted({re.escape(name) for name in _MONTH_NAMES}, key=len, reverse=True))
_MONEY_RE = re.compile(
    rf"(?i)([$€£]\s*\d[\d\s.,]*(?:\s*(?:million(?:s)?|milliard(?:s)?|billion(?:s)?))?"
    rf"|\b\d[\d\s.,]*(?:\s*(?:million(?:s)?|milliard(?:s)?|billion(?:s)?))?"
    rf"(?:\s*(?:de|d['’]))?\s*(?:euros?|dollars?|francs?\s+suisses?|usd|eur|chf|gbp|livres?)\b)"
)
_LAW_RE = re.compile(
    r"(?i)\b("
    r"act|law|loi|regulation|reglement|règlement|directive|code|constitution|"
    r"amendment|amendement|amendements?|convention|trait[ée]|treaty|license|licence|"
    r"section\s+\d+|article\s+\d+|gdpr|rgpd|dmca|dma|hipaa|fisa|ieepa|"
    r"cloud act|ai act|apache(?:\s+license)?\s+2\.0|defense production act|"
    r"digital markets act|digital services act|first amendment|premier amendement|"
    r"25(?:th|e)\s+amend(?:ment|ement)|conventions?\s+de\s+gen[eè]ve|"
    r"geneva conventions?|nlpd|lpd|aimp|lmp"
    r")\b"
)
_YEAR_RE = re.compile(r"^(?:19|20)\d{2}$")
_DATE_RE = re.compile(
    rf"(?i)^(?:{_MONTH_NAMES_RE})\s+(?:19|20)\d{{2}}$|^\d{{1,2}}[/-]\d{{1,2}}[/-]\d{{2,4}}$"
)
_LEADING_DETERMINER_RE = re.compile(r"(?i)^(?:l['’]|le\s+|la\s+|les\s+|the\s+|of\s+)")
_TRAILING_DETERMINER_RE = re.compile(r"(?i),\s*(?:le|la|les|the)$")
_PERSON_NON_HUMAN_OVERRIDES = {
    "openai": ("ORG", "OpenAI"),
    "anthropic": ("ORG", "Anthropic"),
    "chatgpt": ("PRODUCT", "ChatGPT"),
    "maison-blanche": ("FAC", "Maison-Blanche"),
    "blanche, maison": ("FAC", "Maison-Blanche"),
    "iran": ("GPE", "Iran"),
    "chine": ("GPE", "Chine"),
    "lebanon": ("GPE", "Lebanon"),
    "etats-unis": ("GPE", "États-Unis"),
    "etats unis": ("GPE", "États-Unis"),
    "united states": ("GPE", "United States"),
    "americans": ("NORP", "Americans"),
}
_EXACT_ENTITY_OVERRIDES = {
    ("GPE", "trump"): ("PERSON", "Donald Trump"),
    ("NORP", "trump"): ("PERSON", "Donald Trump"),
    ("DATE", "trump"): ("PERSON", "Donald Trump"),
    ("PERSON", "conseil federal"): ("ORG", "Conseil Fédéral"),
}


def _fold_entity_value(value: str) -> str:
    normalized = " ".join((value or "").strip().split())
    normalized = (
        normalized.replace("’", "'")
        .replace("`", "'")
        .replace("´", "'")
        .replace("–", "-")
        .replace("—", "-")
    )
    normalized = unicodedata.normalize("NFKD", normalized)
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return normalized.lower()


def _normalize_money_value(value: str) -> str | None:
    match = _MONEY_RE.search(value)
    if not match:
        return None
    normalized = " ".join(match.group(0).split())
    normalized = normalized.replace(" d' ", " d'")
    return normalized.strip(" ,.;:()[]{}")


def _is_date_like(value: str) -> bool:
    cleaned = value.strip()
    return bool(_YEAR_RE.match(cleaned) or _DATE_RE.match(cleaned))


def _is_law_like(value: str) -> bool:
    return bool(_LAW_RE.search(value))


def _strip_entity_determiners(value: str) -> str:
    value = _LEADING_DETERMINER_RE.sub("", value).strip()
    value = _TRAILING_DETERMINER_RE.sub("", value).strip()
    return value


def _normalize_person_candidate(value: str) -> tuple[str, str]:
    folded = _fold_entity_value(value)
    override = _PERSON_NON_HUMAN_OVERRIDES.get(folded)
    if override:
        return override

    # Corrige un artefact fréquent "Nom, Mot" -> teste aussi la forme inversée.
    if "," in value:
        parts = [part.strip() for part in value.split(",") if part.strip()]
        if len(parts) == 2:
            flipped = f"{parts[1]}-{parts[0]}"
            override = _PERSON_NON_HUMAN_OVERRIDES.get(_fold_entity_value(flipped))
            if override:
                return override

    return "PERSON", value


def _normalize_entity_candidate(entity_type: str, entity_value: str) -> tuple[str, str]:
    cleaned_type = (entity_type or "").strip().upper()
    cleaned_value = " ".join((entity_value or "").strip().split())
    if not cleaned_type or not cleaned_value:
        return cleaned_type, cleaned_value

    if cleaned_type in {"PERSON", "NORP", "GPE", "LOC", "FAC"}:
        cleaned_value = _strip_entity_determiners(cleaned_value)
        if not cleaned_value:
            return cleaned_type, cleaned_value

    if cleaned_type == "PERSON":
        cleaned_type, cleaned_value = _normalize_person_candidate(cleaned_value)

    exact_override = _EXACT_ENTITY_OVERRIDES.get((cleaned_type, _fold_entity_value(cleaned_value)))
    if exact_override:
        return exact_override

    money_value = _normalize_money_value(cleaned_value)
    if money_value:
        return "MONEY", money_value

    if _is_date_like(cleaned_value):
        return "DATE", cleaned_value

    if cleaned_type != "LAW" and _is_law_like(cleaned_value):
        return "LAW", cleaned_value

    return cleaned_type, cleaned_value


def _parse_entities_response(raw: str) -> Optional[dict]:
    """Extrait un dict d'entités depuis une réponse brute de l'API.

    Gère les blocs ```json … ```, les balises <think>…</think> (Qwen3)
    et les réponses contenant du texte parasite autour du JSON.

    Retourne :
      - dict (éventuellement vide {}) si le parsing réussit
      - None si la réponse ne contient aucun JSON valide (erreur de parsing)
    """
    # Supprimer les blocs <think>…</think>
    text = re.sub(r"<think>[\s\S]*?</think>", "", raw, flags=re.IGNORECASE).strip()

    # Extraire le contenu d'un bloc ```json … ``` ou ``` … ```
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()

    # Tentative de parsing direct
    try:
        raw_entities = json.loads(text)
    except json.JSONDecodeError:
        # Dernier recours : extraire le premier objet JSON du texte
        obj_match = re.search(r"\{[\s\S]*\}", text)
        if not obj_match:
            default_logger.warning("Impossible d'extraire du JSON depuis la réponse NER")
            return None  # echec_parse : pas de JSON du tout
        try:
            raw_entities = json.loads(obj_match.group(0))
        except json.JSONDecodeError:
            default_logger.warning("JSON NER invalide après extraction")
            return None  # echec_parse : JSON malformé

    if not isinstance(raw_entities, dict):
        return {}

    # Normaliser : garder uniquement les types connus, dédupliquer et corriger
    # quelques cas NER évidents (MONEY, DATE, LAW) pour fiabiliser l'index.
    result = {}
    seen_by_type: dict[str, set[str]] = {etype: set() for etype in _ENTITY_TYPES}
    for etype in _ENTITY_TYPES:
        values = raw_entities.get(etype, [])
        if not isinstance(values, list):
            continue
        for v in values:
            if not isinstance(v, str) or not v.strip():
                continue
            normalized_type, normalized_value = _normalize_entity_candidate(etype, v)
            if normalized_type not in seen_by_type or not normalized_value:
                continue
            if normalized_value in seen_by_type[normalized_type]:
                continue
            seen_by_type[normalized_type].add(normalized_value)
            result.setdefault(normalized_type, []).append(normalized_value)

    return result  # {} = réponse valide mais aucune entité trouvée


_SENTIMENT_VALUES = {"positif", "neutre", "négatif"}
_TON_VALUES = {"factuel", "alarmiste", "promotionnel", "critique", "analytique"}

_PROMPT_SENTIMENT_TEMPLATE = _SENTIMENT_SYSTEM_INSTRUCTIONS + "\n\nTexte :\n{resume}"

_CHINESE_CHAR_RE = re.compile(
    r"[\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF\U00020000-\U0002EBEF]"
)
_SUMMARY_REGEN_MAX_ATTEMPTS = 2


def _contains_chinese_chars(text: str) -> bool:
    """Détecte la présence de caractères chinois (CJK Han) dans un texte."""
    if not isinstance(text, str) or not text:
        return False
    return _CHINESE_CHAR_RE.search(text) is not None


def _strip_summary_heading(text: str) -> str:
    """Supprime les titres markdown de type '# Résumé' ajoutés par certains modèles."""
    if not isinstance(text, str):
        return ""
    return re.sub(r'^#{1,3}\s*[Rr]é[sc]?umé\s*[:\-]?\s*\n?', '', text).strip()


def _build_summary_prompt(text_truncated: str, max_lines: int, language: str, retry: bool = False) -> str:
    """Construit un prompt de résumé avec contrainte stricte de langue française."""
    constraints = (
        "Contrainte obligatoire: réponds uniquement en français. "
        "N'utilise aucun caractère chinois (hanzi). "
        "Ne donne que le résumé, sans commentaire ni remarque."
    )
    if retry:
        constraints = (
            "Le résumé précédent contenait des caractères chinois. "
            "Corrige impérativement en produisant une version 100% en français, "
            "sans aucun caractère chinois. "
            "Ne donne que le résumé, sans commentaire ni remarque."
        )
    return (
        f"Faire un résumé de ce texte sur maximum {max_lines} lignes en {language}. "
        f"{constraints} Texte : {text_truncated}"
    )


def _build_combined_user_prompt(text_truncated: str, max_lines: int, language: str, retry: bool = False) -> str:
    """Construit le message utilisateur pour le mode combiné résumé+sentiment."""
    if retry:
        return (
            f"Le résumé précédent contenait des caractères chinois. "
            f"Régénère le champ \"resume\" en maximum {max_lines} lignes en {language}, "
            "strictement en français, sans aucun caractère chinois. "
            "Conserve le format JSON demandé et ne retourne rien d'autre.\n\n"
            f"Texte à analyser :\n{text_truncated}"
        )
    return (
        f"Résumé en maximum {max_lines} lignes en {language}. "
        "Le champ \"resume\" doit être rédigé uniquement en français, "
        "sans aucun caractère chinois.\n\n"
        f"Texte à analyser :\n{text_truncated}"
    )


def _parse_sentiment_response(raw: str) -> Optional[dict]:
    """Extrait un dict sentiment/ton depuis une réponse brute de l'API.

    Retourne :
      - dict (éventuellement vide {}) si le parsing réussit
      - None si la réponse ne contient aucun JSON valide (erreur de parsing)
    """
    text = re.sub(r"<think>[\s\S]*?</think>", "", raw, flags=re.IGNORECASE).strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()

    def _extract_sentiment_fields(candidate: str) -> dict:
        result = {}

        sentiment_match = re.search(
            r'"sentiment"\s*:\s*"(positif|neutre|négatif|negatif)"',
            candidate,
            flags=re.IGNORECASE,
        )
        if sentiment_match:
            sentiment = sentiment_match.group(1).strip().lower().replace("negatif", "négatif")
            if sentiment in _SENTIMENT_VALUES:
                result["sentiment"] = sentiment

        score_s_match = re.search(r'"score_sentiment"\s*:\s*([1-5])\b', candidate, flags=re.IGNORECASE)
        if score_s_match:
            result["score_sentiment"] = int(score_s_match.group(1))
            if "sentiment" not in result:
                if result["score_sentiment"] <= 2:
                    result["sentiment"] = "négatif"
                elif result["score_sentiment"] == 3:
                    result["sentiment"] = "neutre"
                else:
                    result["sentiment"] = "positif"

        ton_match = re.search(
            r'"ton_editorial"\s*:\s*"(factuel|alarmiste|promotionnel|critique|analytique)"',
            candidate,
            flags=re.IGNORECASE,
        )
        if ton_match:
            ton = ton_match.group(1).strip().lower()
            if ton in _TON_VALUES:
                result["ton_editorial"] = ton

        score_t_match = re.search(r'"score_ton"\s*:\s*([1-5])\b', candidate, flags=re.IGNORECASE)
        if score_t_match:
            result["score_ton"] = int(score_t_match.group(1))

        return result

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        obj = re.search(r"\{[\s\S]*\}", text)
        if not obj:
            fallback = _extract_sentiment_fields(text)
            if fallback:
                default_logger.debug("Réponse sentiment partielle — extraction par regex réussie")
                return fallback
            default_logger.warning("Impossible d'extraire du JSON depuis la réponse sentiment")
            return None  # echec_parse : pas de JSON du tout
        try:
            data = json.loads(obj.group(0))
        except json.JSONDecodeError:
            fallback = _extract_sentiment_fields(obj.group(0))
            if fallback:
                default_logger.debug("JSON sentiment tronqué — extraction par regex réussie")
                return fallback
            default_logger.warning("JSON sentiment invalide après extraction")
            return None  # echec_parse : JSON malformé
    if not isinstance(data, dict):
        return {}
    result = {}
    has_explicit_sentiment = "sentiment" in data
    sentiment = str(data.get("sentiment", "")).strip().lower()
    if sentiment in _SENTIMENT_VALUES:
        result["sentiment"] = sentiment
    score_s = data.get("score_sentiment")
    if isinstance(score_s, (int, float)) and 1 <= score_s <= 5:
        result["score_sentiment"] = int(score_s)
        if "sentiment" not in result and not has_explicit_sentiment:
            if result["score_sentiment"] <= 2:
                result["sentiment"] = "négatif"
            elif result["score_sentiment"] == 3:
                result["sentiment"] = "neutre"
            else:
                result["sentiment"] = "positif"
    ton = str(data.get("ton_editorial", "")).strip().lower()
    if ton in _TON_VALUES:
        result["ton_editorial"] = ton
    score_t = data.get("score_ton")
    if isinstance(score_t, (int, float)) and 1 <= score_t <= 5:
        result["score_ton"] = int(score_t)
    return result


# ── Prompt combiné résumé + sentiment (1 seul appel IA) ──────────────────────

# Partie statique (cacheable pour Claude) — sans max_lines ni texte variable
_COMBINED_SYSTEM_INSTRUCTIONS = (
    "Tu es un analyseur de contenu journalistique. "
    "Retourne UNIQUEMENT un objet JSON valide — aucun texte avant ou après le JSON.\n\n"
    "Le champ \"resume\" doit être rédigé exclusivement en français, "
    "sans aucun caractère chinois (hanzi).\n\n"
    "Champs attendus :\n"
    '- "resume" : résumé du texte (nombre de lignes indiqué dans le message utilisateur), '
    'sans commentaire ni remarque\n'
    '- "sentiment" : une des valeurs exactes : "positif", "neutre", "négatif"\n'
    '- "score_sentiment" : entier entre 1 (très négatif) et 5 (très positif), 3=neutre\n'
    '- "ton_editorial" : une des valeurs exactes : "factuel", "alarmiste", "promotionnel", '
    '"critique", "analytique"\n'
    '- "score_ton" : entier entre 1 (très biaisé/sensationnaliste) et 5 (très factuel/neutre)'
)


def _parse_summary_sentiment_response(raw: str) -> Optional[dict]:
    """Extrait {resume, sentiment, score_sentiment, ton_editorial, score_ton} depuis la réponse IA.

    Retourne :
      - dict avec au moins "resume" si le parsing réussit
      - None si aucun JSON valide trouvé
    """
    text = re.sub(r"<think>[\s\S]*?</think>", "", raw, flags=re.IGNORECASE).strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        obj = re.search(r"\{[\s\S]*\}", text)
        if not obj:
            # Dernier recours : format markdown bullet (ex. qwen2.5:7b sur texte long)
            md_result = _parse_summary_sentiment_from_markdown(text)
            if md_result:
                default_logger.debug("Réponse résumé+sentiment au format markdown bullet — parsé avec succès")
                return md_result
            default_logger.warning("Impossible d'extraire du JSON depuis la réponse résumé+sentiment")
            return None
        try:
            data = json.loads(obj.group(0))
        except json.JSONDecodeError:
            # JSON tronqué : tenter le format markdown bullet
            md_result = _parse_summary_sentiment_from_markdown(text)
            if md_result:
                default_logger.debug("JSON résumé+sentiment tronqué — fallback markdown bullet réussi")
                return md_result
            default_logger.warning("JSON résumé+sentiment invalide après extraction")
            return None
    if not isinstance(data, dict):
        return None
    result: dict = {}
    # Résumé
    resume = data.get("resume", "")
    if isinstance(resume, str) and resume.strip():
        result["resume"] = re.sub(r'^#{1,3}\s*[Rr]é[sc]?umé\s*[:\-]?\s*\n?', '', resume).strip()
    # Sentiment (optionnel — on ne rejette pas si absent)
    sentiment = str(data.get("sentiment", "")).strip().lower()
    if sentiment in _SENTIMENT_VALUES:
        result["sentiment"] = sentiment
    score_s = data.get("score_sentiment")
    if isinstance(score_s, (int, float)) and 1 <= score_s <= 5:
        result["score_sentiment"] = int(score_s)
    ton = str(data.get("ton_editorial", "")).strip().lower()
    if ton in _TON_VALUES:
        result["ton_editorial"] = ton
    score_t = data.get("score_ton")
    if isinstance(score_t, (int, float)) and 1 <= score_t <= 5:
        result["score_ton"] = int(score_t)
    return result


def _extract_resume_from_raw(raw: str) -> str:
    """Extrait la valeur du champ 'resume' depuis un texte brut ou JSON partiel.

    Utilisé comme dernier recours quand tous les parsers structurés ont échoué.
    Tente d'extraire uniquement le texte du résumé (sans les métadonnées).
    """
    # Format JSON : chercher "resume": "valeur" (JSON tronqué ou mal formaté)
    json_match = re.search(r'"resume"\s*:\s*"((?:[^"\\]|\\.)*)"', raw, re.DOTALL)
    if json_match:
        return json_match.group(1).replace('\\"', '"').replace('\\n', '\n').strip()

    # Déléguer au parser markdown/mixed qui est plus robuste
    parsed = _parse_summary_sentiment_from_markdown(raw)
    if parsed and parsed.get("resume"):
        return parsed["resume"]

    # Dernier recours : retourner le texte brut nettoyé
    return raw.strip()


def _parse_summary_sentiment_from_markdown(text: str) -> Optional[dict]:
    """Extrait résumé+sentiment depuis un texte non-JSON (markdown bullet ou format mixte).

    Gère 3 formats courants produits par des LLM locaux (ex. qwen2.5:7b) :
    1. Markdown bullet strict : - "resume" : texte\\n- "sentiment" : neutre
    2. Format mixte           : {génère un résumé... : texte\\n\\n- "sentiment": neutre
    3. Texte libre suivi de bullets de métadonnées

    Stratégie : détecter où commencent les champs de métadonnées, extraire
    tout ce qui précède comme résumé, nettoyer le préfixe.
    """
    result: dict = {}

    # Trouver le début du premier champ de métadonnée (sentiment / score_* / ton_editorial)
    _META_PATTERN = re.compile(
        r'(?:^|\n)\s*[-*]?\s*["\']?(?:sentiment|score_sentiment|ton_editorial|score_ton)["\']?\s*[:\-]',
        re.IGNORECASE
    )
    meta_m = _META_PATTERN.search(text)

    if meta_m:
        resume_raw = text[:meta_m.start()].strip()
        meta_text = text[meta_m.start():]
    else:
        resume_raw = text.strip()
        meta_text = text

    # Nettoyer le préfixe du résumé
    # 1. Supprimer le { d'ouverture JSON suivi d'un texte avant ':' (format mixte)
    resume_raw = re.sub(r'^\{[^:"]{0,80}:\s*', '', resume_raw).strip()
    # 2. Supprimer - "resume" : ou resume :
    resume_raw = re.sub(r'^[-*]?\s*["\']?resume["\']?\s*[:\-]\s*', '', resume_raw, flags=re.IGNORECASE)
    # 3. Supprimer les guillemets entourants et artefacts de fin
    resume_raw = resume_raw.strip('"\'').rstrip(',').strip()
    # 4. Supprimer les titres Résumé/Resume en début
    resume_raw = re.sub(r'^#{1,3}\s*[Rr]é[sc]?umé\s*[:\-]?\s*\n?', '', resume_raw).strip()

    if resume_raw:
        result["resume"] = resume_raw

    # Extraire les champs de métadonnées (recherche globale dans tout le texte)
    sent_m = re.search(r'["\']?sentiment["\']?\s*[:\-]\s*["\']?(positif|neutre|négatif)["\']?', meta_text, re.IGNORECASE)
    if sent_m:
        result["sentiment"] = sent_m.group(1).lower()

    ss_m = re.search(r'score_sentiment["\']?\s*[:\-]\s*(\d)', meta_text, re.IGNORECASE)
    if ss_m:
        v = int(ss_m.group(1))
        if 1 <= v <= 5:
            result["score_sentiment"] = v

    ton_m = re.search(r'ton_editorial["\']?\s*[:\-]\s*["\']?(factuel|alarmiste|promotionnel|critique|analytique)["\']?', meta_text, re.IGNORECASE)
    if ton_m:
        result["ton_editorial"] = ton_m.group(1).lower()

    st_m = re.search(r'score_ton["\']?\s*[:\-]\s*(\d)', meta_text, re.IGNORECASE)
    if st_m:
        v = int(st_m.group(1))
        if 1 <= v <= 5:
            result["score_ton"] = v

    return result if result else None


class EurIAClient:
    """Client pour l'API EurIA (Qwen3) d'Infomaniak.
    
    Gère les requêtes vers l'API avec retry automatique, timeouts configurables,
    et validation des réponses.
    
    Attributes:
        url: URL de l'endpoint API
        headers: Headers HTTP incluant l'authentification
        model: Nom du modèle IA à utiliser
        enable_web_search: Active la recherche web pour le contexte
    """

    _provider_label: str = "EurIA"
    
    def __init__(
        self,
        url: Optional[str] = None,
        bearer: Optional[str] = None,
        model: Optional[str] = None,
        enable_web_search: bool = True
    ):
        """Initialise le client API.
        
        Args:
            url: URL de l'API (utilise la config si None)
            bearer: Token d'authentification (utilise la config si None)
            model: Nom du modèle IA à utiliser (défaut: modèle EurIA courant)
            enable_web_search: Active la recherche web (défaut: True)
        """
        config = get_config()
        
        self.url = url or config.url
        self.bearer = bearer or config.bearer
        self.model = model or get_euria_model()
        self.enable_web_search = enable_web_search
        
        self.headers = {
            'Authorization': f'Bearer {self.bearer}',
            'Content-Type': 'application/json',
        }
        
        if not self.url or not self.bearer:
            raise ValueError("URL et bearer token requis pour le client API")

    def _build_payload(
        self,
        messages: list,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        enable_web_search: Optional[bool] = None,
        stream: bool = False,
    ) -> dict:
        payload = {
            "messages": messages,
            "model": model or self.model,
        }
        if stream:
            payload["stream"] = True
        _enable_web_search = self.enable_web_search if enable_web_search is None else enable_web_search
        if "/euria/" in self.url and _enable_web_search:
            payload["enable_web_search"] = True
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        return payload

    def _complete_messages(
        self,
        messages: list,
        max_attempts: int = 3,
        timeout: int = 60,
        backoff_factor: float = 2.0,
        max_tokens: Optional[int] = None,
        enable_web_search: Optional[bool] = None,
        model: Optional[str] = None,
    ) -> str:
        """Appel non-stream OpenAI-compatible avec retry et garde-fou reasoning-only."""
        last_error = None
        saw_reasoning_only = False
        active_model = model or self.model

        if not _euria_breaker.allow_request():
            raise RuntimeError(
                f"[EurIA] Circuit OPEN — appels bloqués pendant la fenêtre de grâce "
                f"({_euria_breaker.grace_seconds:.0f}s). Dernière erreur : {_euria_breaker.name}"
            )

        for attempt in range(max_attempts):
            try:
                attempt_messages = list(messages)
                if saw_reasoning_only:
                    attempt_messages = [
                        {"role": "system", "content": _EURIA_REASONING_RETRY_SYSTEM},
                        *attempt_messages,
                    ]
                data = self._build_payload(
                    messages=attempt_messages,
                    model=active_model,
                    max_tokens=max_tokens,
                    enable_web_search=enable_web_search,
                    stream=False,
                )

                default_logger.info(
                    f"Envoi de prompt à l'API (tentative {attempt + 1}/{max_attempts}, "
                    f"timeout={timeout}s)"
                )

                response = requests.post(
                    self.url,
                    json=data,
                    headers=self.headers,
                    timeout=timeout
                )
                response.raise_for_status()
                json_data = response.json()

                if 'choices' not in json_data or len(json_data['choices']) == 0:
                    raise ValueError("Réponse API invalide : champ 'choices' manquant ou vide")

                choice = json_data['choices'][0] or {}
                message = choice.get('message') or {}
                content = _extract_chat_text(message.get('content')).strip()

                if content:
                    usage = json_data.get("usage", {})
                    if usage:
                        default_logger.info(
                            f"[{self._provider_label}] Usage — prompt: {usage.get('prompt_tokens', '?')} tokens, "
                            f"completion: {usage.get('completion_tokens', '?')} tokens, "
                            f"total: {usage.get('total_tokens', '?')} tokens"
                        )
                    default_logger.info(f"Réponse reçue de l'API: {len(content)} caractères")
                    _euria_breaker.record_success()
                    return content

                reasoning = _extract_reasoning_text(message) or _extract_reasoning_text(choice)
                if reasoning:
                    saw_reasoning_only = True
                    raise ValueError("Réponse reasoning tronquée sans contenu final")

                raise ValueError("Réponse API vide")

            except requests.exceptions.Timeout:
                last_error = f"Timeout après {timeout}s"
                default_logger.warning(
                    f"Timeout lors de la tentative {attempt + 1}/{max_attempts}"
                )
                _euria_breaker.record_failure()

            except requests.exceptions.HTTPError as e:
                status_code = e.response.status_code if e.response is not None else 'inconnu'
                last_error = f"Erreur HTTP {status_code}"
                default_logger.error(
                    f"Erreur HTTP {status_code} lors de la tentative {attempt + 1}/{max_attempts}"
                )

                if status_code == 429:
                    _euria_breaker.record_failure(error_category="quota")
                    break
                if status_code in [401, 403]:
                    _euria_breaker.record_failure(error_category="auth")
                    break
                if status_code not in [400, 404]:
                    _euria_breaker.record_failure()
                else:
                    break

            except requests.exceptions.ConnectionError as e:
                last_error = "Erreur de connexion"
                default_logger.error(
                    f"Erreur de connexion lors de la tentative {attempt + 1}/{max_attempts}: {e}"
                )
                _euria_breaker.record_failure()

            except (ValueError, KeyError, TypeError) as e:
                last_error = f"Erreur de format de réponse: {e}"
                default_logger.error(
                    f"Erreur de parsing de la réponse lors de la tentative "
                    f"{attempt + 1}/{max_attempts}: {e}"
                )

            except Exception as e:
                last_error = f"Erreur inattendue: {type(e).__name__}: {e}"
                default_logger.error(
                    f"Erreur inattendue lors de la tentative {attempt + 1}/{max_attempts}: {e}"
                )
                _euria_breaker.record_failure()

            if attempt < max_attempts - 1:
                wait_time = backoff_factor ** attempt
                default_logger.info(f"Attente de {wait_time:.1f}s avant nouvelle tentative...")
                time.sleep(wait_time)

        error_message = (
            f"Échec après {max_attempts} tentatives. "
            f"Dernière erreur: {last_error}"
        )
        default_logger.error(error_message)
        raise RuntimeError(f"Échec API après {max_attempts} tentatives. {last_error}")
    
    def ask(
        self,
        prompt: str,
        max_attempts: int = 3,
        timeout: int = 60,
        backoff_factor: float = 2.0,
        max_tokens: Optional[int] = None,
        enable_web_search: Optional[bool] = None,
        system_message: Optional[str] = None,
    ) -> str:
        """Envoie un prompt à l'API EurIA et retourne la réponse.

        Cette fonction interroge l'API EurIA avec retry automatique en cas d'échec.
        Un backoff exponentiel est appliqué entre les tentatives.

        Args:
            prompt: Le texte du prompt à envoyer à l'API
            max_attempts: Nombre maximal de tentatives en cas d'échec (défaut: 3)
            timeout: Délai d'attente maximal en secondes pour chaque requête (défaut: 60)
            backoff_factor: Facteur multiplicateur pour le backoff entre tentatives (défaut: 2.0)
            max_tokens: Nombre maximal de tokens en sortie (None = valeur par défaut de l'API)
            enable_web_search: Surcharge l'activation de la recherche web (None = valeur de l'instance)
            system_message: Message système optionnel à préfixer avant le message utilisateur
                            (rôle "system"). Utile pour imposer une contrainte de langue aux
                            modèles locaux (ex. Ollama).
        
        Returns:
            La réponse textuelle de l'API, nettoyée des espaces superflus.
            En cas d'échec après toutes les tentatives, retourne un message d'erreur.
        
        Example:
            >>> client = EurIAClient()
            >>> reponse = client.ask("Résume cet article: ...")
            >>> print(reponse)
        """
        if not prompt or not isinstance(prompt, str):
            default_logger.error("Prompt invalide ou vide")
            return "Erreur: Prompt invalide"
        
        messages = []
        if system_message:
            messages.append({"role": "system", "content": system_message})
        messages.append({"content": prompt, "role": "user"})
        return self._complete_messages(
            messages=messages,
            max_attempts=max_attempts,
            timeout=timeout,
            backoff_factor=backoff_factor,
            max_tokens=max_tokens,
            enable_web_search=enable_web_search,
        )

    def stream(
        self,
        prompt: str,
        model: Optional[str] = None,
        system: Optional[str] = None,
        max_tokens: int = 2048,
        timeout: int = 120,
        messages: Optional[list] = None,
        enable_web_search: Optional[bool] = None,
    ):
        """Envoie un appel EurIA en streaming SSE normalisé.

        Si le flux ne contient que du reasoning avec `content=null`, effectue
        un fallback non-stream et réémet la réponse sous forme SSE.
        """
        active_model = model or self.model
        base_messages = list(messages) if messages is not None else [{"role": "user", "content": prompt}]
        if system:
            base_messages = [{"role": "system", "content": system}, *base_messages]

        saw_reasoning_only = False
        try:
            data = self._build_payload(
                messages=base_messages,
                model=active_model,
                max_tokens=max_tokens,
                enable_web_search=enable_web_search,
                stream=True,
            )
            r = requests.post(self.url, json=data, headers=self.headers, stream=True, timeout=timeout)
            r.raise_for_status()
            saw_content = False
            for line in r.iter_lines():
                if not line:
                    continue
                decoded = line.decode("utf-8")
                if not decoded.startswith("data:"):
                    continue
                raw = decoded[5:].strip()
                if not raw:
                    continue
                if raw == "[DONE]":
                    if saw_content:
                        _euria_breaker.record_success()
                        yield "data: [DONE]\n\n"
                        return
                    break
                try:
                    evt = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                choice = (evt.get("choices") or [{}])[0] or {}
                delta = choice.get("delta") or {}
                content = _extract_chat_text(delta.get("content"))
                if content:
                    if content.strip():
                        saw_content = True
                    normalized = json.dumps(
                        {"choices": [{"delta": {"content": content}, "finish_reason": choice.get("finish_reason")}]},
                        ensure_ascii=False,
                    )
                    yield f"data: {normalized}\n\n"
                    continue
                reasoning = _extract_reasoning_text(delta) or _extract_reasoning_text(choice)
                if reasoning:
                    saw_reasoning_only = True

            fallback_text = self._complete_messages(
                messages=base_messages,
                max_attempts=2 if saw_reasoning_only else 1,
                timeout=timeout,
                max_tokens=max_tokens,
                enable_web_search=enable_web_search,
                model=active_model,
            )
            if fallback_text:
                normalized = json.dumps(
                    {"choices": [{"delta": {"content": fallback_text}, "finish_reason": "stop"}]},
                    ensure_ascii=False,
                )
                yield f"data: {normalized}\n\n"
                yield "data: [DONE]\n\n"
                return
            raise RuntimeError("Réponse streaming vide")

        except requests.exceptions.HTTPError as exc:
            body = ""
            try:
                body = exc.response.text[:800] if exc.response is not None else ""
            except Exception:
                pass
            error_msg = f"{exc}" + (f" — Détail API: {body}" if body else "")
            yield f'data: {json.dumps({"error": error_msg})}\n\n'
        except Exception as exc:
            yield f'data: {json.dumps({"error": str(exc)})}\n\n'
    
    def generate_summary(
        self,
        text: str,
        max_lines: Optional[int] = None,
        language: str = "français",
        timeout: int = 60
    ) -> str:
        """Génère un résumé d'un texte via l'API IA.

        Args:
            text: Le texte à résumer
            max_lines: Nombre maximal de lignes pour le résumé.
                       Si None, utilise config.summary_max_lines (quota.json), défaut 20.
            language: Langue du résumé (défaut: français)
            timeout: Timeout en secondes (défaut: 60)

        Returns:
            Le résumé généré par l'IA
        """
        if max_lines is None:
            max_lines = get_config().summary_max_lines
        # Tronquer le texte à 15 000 chars pour rester dans les limites de l'API
        text_truncated = text[:15000]
        prompt = _build_summary_prompt(text_truncated, max_lines, language, retry=False)
        result = _strip_summary_heading(self.ask(prompt, timeout=timeout, max_tokens=600))

        for regen_attempt in range(1, _SUMMARY_REGEN_MAX_ATTEMPTS + 1):
            if not _contains_chinese_chars(result):
                break
            default_logger.warning(
                f"Résumé contient des caractères chinois — régénération {regen_attempt}/{_SUMMARY_REGEN_MAX_ATTEMPTS}"
            )
            retry_prompt = _build_summary_prompt(text_truncated, max_lines, language, retry=True)
            result = _strip_summary_heading(self.ask(retry_prompt, timeout=timeout, max_tokens=600))

        return result

    def generate_entities(
        self,
        resume: str,
        timeout: int = 60
    ) -> Optional[dict]:
        """Extrait les entités nommées (NER) d'un texte via l'API IA.

        Args:
            resume: Texte à analyser (typiquement le champ "Résumé" d'un article)
            timeout: Timeout en secondes (défaut : 60)

        Returns:
            Dictionnaire { type_entité: [valeur, …] } en cas de succès (peut être {}).
            None si le parsing de la réponse échoue (echec_parse).
            {} si l'appel API lui-même échoue (echec_api).
        """
        if not resume or not isinstance(resume, str) or not resume.strip():
            return {}

        prompt = _PROMPT_ENTITIES.format(resume=resume.strip())
        try:
            raw = self.ask(prompt, max_attempts=3, timeout=timeout, max_tokens=500, enable_web_search=False)
            return _parse_entities_response(raw)  # None = echec_parse, {} = no entities
        except Exception as e:
            default_logger.warning(f"Extraction NER échouée : {e}")
            return {}  # echec_api : l'appel réseau a échoué

    def generate_sentiment(
        self,
        resume: str,
        timeout: int = 30
    ) -> Optional[dict]:
        """Analyse le sentiment et le ton éditorial d'un article.

        Args:
            resume  : Résumé ou texte de l'article (champ "Résumé")
            timeout : Timeout en secondes (défaut: 30)

        Returns:
            Dict avec les champs sentiment/score_sentiment/ton_editorial/score_ton.
            None si le parsing de la réponse échoue (echec_parse).
            {} si l'appel API lui-même échoue (echec_api).
        """
        if not resume or not isinstance(resume, str) or not resume.strip():
            return {}

        prompt = _PROMPT_SENTIMENT_TEMPLATE.format(resume=resume.strip()[:3000])
        try:
            raw = self.ask(
                prompt,
                max_attempts=2,
                timeout=timeout,
                max_tokens=300,
                enable_web_search=False,
                system_message=_EURIA_REASONING_RETRY_SYSTEM,
            )
            return _parse_sentiment_response(raw)  # None = echec_parse
        except Exception as e:
            default_logger.warning(f"Analyse sentiment échouée : {e}")
            return {}  # echec_api : l'appel réseau a échoué

    def generate_summary_with_sentiment(
        self,
        text: str,
        max_lines: Optional[int] = None,
        language: str = "français",
        timeout: int = 75,
    ) -> dict:
        """Génère résumé + sentiment + ton éditorial en un seul appel API EurIA.

        Économise 1 appel IA par article par rapport à generate_summary()
        + generate_sentiment() distincts. Utilisé à l'ingestion de nouveaux articles.

        Args:
            text      : Texte brut de l'article (tronqué à 15 000 chars)
            max_lines : Nombre max de lignes du résumé (défaut: config.summary_max_lines)
            language  : Langue du résumé (défaut: français)
            timeout   : Timeout en secondes (défaut: 75)

        Returns:
            Dict avec les champs : resume, et optionnellement sentiment, score_sentiment,
            ton_editorial, score_ton.
            En cas d'échec du parsing JSON, retourne {"resume": <texte brut>} (fallback sûr).

        Raises:
            RuntimeError: Si l'appel API échoue complètement après retentatives.
        """
        if max_lines is None:
            max_lines = get_config().summary_max_lines
        text_truncated = text[:15000]
        prompt = f"{_COMBINED_SYSTEM_INSTRUCTIONS}\n\n{_build_combined_user_prompt(text_truncated, max_lines, language)}"
        raw = self.ask(prompt, timeout=timeout, max_tokens=600)
        result = _parse_summary_sentiment_response(raw)
        if not result or "resume" not in result:
            # Fallback : extraire intelligemment la valeur 'resume' depuis le texte brut
            default_logger.warning(
                "Parsing JSON combiné échoué — extraction du champ resume depuis réponse brute"
            )
            raw_clean = _extract_resume_from_raw(raw)
            raw_clean = _strip_summary_heading(raw_clean)
            result = {"resume": raw_clean}

        result["resume"] = _strip_summary_heading(result.get("resume", ""))

        for regen_attempt in range(1, _SUMMARY_REGEN_MAX_ATTEMPTS + 1):
            if not _contains_chinese_chars(result.get("resume", "")):
                break
            default_logger.warning(
                f"Résumé combiné contient des caractères chinois — régénération {regen_attempt}/{_SUMMARY_REGEN_MAX_ATTEMPTS}"
            )
            retry_prompt = (
                f"{_COMBINED_SYSTEM_INSTRUCTIONS}\n\n"
                f"{_build_combined_user_prompt(text_truncated, max_lines, language, retry=True)}"
            )
            retry_raw = self.ask(retry_prompt, timeout=timeout, max_tokens=600)
            retry_result = _parse_summary_sentiment_response(retry_raw)
            if not retry_result or "resume" not in retry_result:
                retry_resume = _strip_summary_heading(_extract_resume_from_raw(retry_raw))
                retry_result = {"resume": retry_resume}
            retry_result["resume"] = _strip_summary_heading(retry_result.get("resume", ""))
            result = retry_result

        return result

    def synthesize_topic(
        self,
        topic: str,
        articles: list,
        timeout: int = 120,
    ) -> str:
        """Génère une synthèse comparative multi-sources sur un sujet ou une entité.

        Construit un prompt consolidé depuis N résumés d'articles et demande à
        Qwen3 une analyse structurée : convergences, divergences, sources favorables/critiques.

        Args:
            topic    : Sujet ou entité centrale (ex: "OpenAI", "Emmanuel Macron")
            articles : Liste de dicts article avec au moins "Résumé", "Sources", "Date de publication"
            timeout  : Timeout en secondes (défaut: 120)

        Returns:
            Texte Markdown de la synthèse.
        """
        if not articles:
            return "Aucun article disponible pour cette synthèse."

        # Construire le bloc source
        sources_block = ""
        for i, a in enumerate(articles[:20], 1):  # Limiter à 20 articles
            source = a.get("Sources", "Source inconnue")
            date = a.get("Date de publication", "")
            resume = (a.get("Résumé") or "")[:800]
            sources_block += f"\n--- Article {i} ({source}, {date}) ---\n{resume}\n"

        prompt = (
            f"Tu es un analyste de presse. Voici {len(articles[:20])} articles de sources différentes "
            f"traitant du sujet : **{topic}**.\n\n"
            "Génère une synthèse comparative structurée en Markdown comprenant :\n"
            "1. **Résumé de la situation** (2-3 phrases)\n"
            "2. **Points de convergence** entre les sources\n"
            "3. **Points de divergence ou contradictions**\n"
            "4. **Positionnement éditorial** : quelles sources sont favorables, neutres ou critiques\n"
            "5. **Éléments clés manquants** (ce que les articles ne couvrent pas)\n\n"
            "Cite les sources (nom + date) à chaque point. Sois concis et factuel.\n\n"
            f"Articles :\n{sources_block}"
        )
        return self.ask(prompt, max_attempts=2, timeout=timeout, max_tokens=2048)

    def generate_report(
        self,
        json_content: str,
        filename: str,
        timeout: int = 300
    ) -> str:
        """Génère un rapport synthétique à partir de données JSON.

        Args:
            json_content: Contenu JSON des articles
            filename: Nom du fichier source
            timeout: Timeout en secondes (défaut: 300)

        Returns:
            Rapport formaté en Markdown
        """
        prompt = f"""
Analyse le fichier ce fichier JSON et fait une synthèse des actualités.
Affiche la date de publication et les sources lorsque tu cites un article.
Groupe les articles par catégories que tu auras identifiées.
En fin de synthèse fait un tableau avec les références (date de publication, sources et URL)
pour chaque article dans la rubrique "Images" il y a des liens d'images.
Lorsque cela est possible, publie le lien de l'image sous la forme <img src='{{URL}}' /> sur une nouvelle ligne en fin de paragraphe de catégorie. N'utilise qu'une image par paragraphe et assure-toi qu'une même URL d'image n'apparaisse qu'une seule fois dans tout le rapport.

Filename: {filename}
File contents:
----- BEGIN FILE CONTENTS -----
{json_content}
----- END FILE CONTENTS -----
"""
        return self.ask(prompt, max_attempts=3, timeout=timeout, max_tokens=4096)


# ── Client Anthropic Claude ───────────────────────────────────────────────────

CLAUDE_API_URL = "https://api.anthropic.com/v1/messages"
CLAUDE_API_VERSION = "2023-06-01"


class ClaudeClient:
    """Client pour l'API Anthropic Claude.

    Utilise deux modèles distincts selon le type de tâche :
    - model_batch     (Haiku) : tâches volumineuses — résumé, NER, sentiment
    - model_synthesis (Sonnet): synthèses user-facing — rapport, RAG, encyclopédique

    Fournit les mêmes méthodes publiques qu'EurIAClient pour une substituabilité totale.
    """

    def __init__(self, api_key: Optional[str] = None):
        import os as _os
        # Lire directement depuis os.environ pour refléter les mises à jour dynamiques
        # (l'UI peut modifier .env et os.environ sans recharger le singleton Config).
        self.api_key = api_key or _os.environ.get("ANTHROPIC_API_KEY", "") or get_config().anthropic_api_key
        self.model_batch = (
            _os.environ.get("CLAUDE_MODEL_BATCH", "").strip()
            or get_config().claude_model_batch
        )
        self.model_synthesis = (
            _os.environ.get("CLAUDE_MODEL_SYNTHESIS", "").strip()
            or get_config().claude_model_synthesis
        )
        self.headers = {
            "x-api-key": self.api_key,
            "anthropic-version": CLAUDE_API_VERSION,
            "Content-Type": "application/json",
        }
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY requis pour le client Claude")

    def ask(
        self,
        prompt: str,
        model: Optional[str] = None,
        max_attempts: int = 3,
        timeout: int = 60,
        backoff_factor: float = 2.0,
        max_tokens: int = 2048,
    ) -> str:
        """Envoie un prompt à l'API Claude et retourne la réponse texte.

        Args:
            prompt      : Texte du prompt
            model       : Modèle à utiliser (None = model_synthesis par défaut)
            max_attempts: Nombre maximal de tentatives
            timeout     : Timeout en secondes
            backoff_factor: Facteur de backoff exponentiel
            max_tokens  : Nombre maximal de tokens en sortie (obligatoire pour Claude).
                          Au-delà de 8192, le beta extended output est activé automatiquement.

        Returns:
            Réponse texte nettoyée.

        Raises:
            RuntimeError: Après épuisement de toutes les tentatives.
        """
        if not prompt or not isinstance(prompt, str):
            default_logger.error("Prompt invalide ou vide")
            return "Erreur: Prompt invalide"

        active_model = model or self.model_synthesis
        data = {
            "model": active_model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        last_error = None

        if not _claude_breaker.allow_request():
            raise RuntimeError(
                f"[Claude] Circuit OPEN — appels bloqués pendant la fenêtre de grâce "
                f"({_claude_breaker.grace_seconds:.0f}s)."
            )

        # Activer le beta extended output si max_tokens > 8192
        headers = dict(self.headers)
        if max_tokens > 8192:
            headers["anthropic-beta"] = "output-128k-2025-02-19"

        for attempt in range(max_attempts):
            try:
                default_logger.info(
                    f"[Claude/{active_model}] Envoi prompt (tentative {attempt + 1}/{max_attempts}, "
                    f"timeout={timeout}s, max_tokens={max_tokens})"
                )
                response = requests.post(
                    CLAUDE_API_URL, json=data, headers=headers, timeout=timeout
                )
                response.raise_for_status()
                json_data = response.json()

                content_blocks = json_data.get("content", [])
                if not content_blocks:
                    raise ValueError("Réponse Claude vide (aucun bloc content)")
                content = content_blocks[0].get("text", "")
                if not content:
                    raise ValueError("Texte Claude vide")

                usage = json_data.get("usage", {})
                if usage:
                    default_logger.info(
                        f"[Claude/{active_model}] Usage — input: {usage.get('input_tokens', '?')} tokens, "
                        f"output: {usage.get('output_tokens', '?')} tokens"
                    )
                default_logger.info(f"[Claude] Réponse reçue : {len(content)} caractères")
                _claude_breaker.record_success()
                return content.strip()

            except requests.exceptions.Timeout:
                last_error = f"Timeout après {timeout}s"
                default_logger.warning(f"[Claude] Timeout tentative {attempt + 1}/{max_attempts}")
                _claude_breaker.record_failure()

            except requests.exceptions.HTTPError as e:
                status_code = e.response.status_code if e.response is not None else "inconnu"
                last_error = f"Erreur HTTP {status_code}"
                default_logger.error(f"[Claude] Erreur HTTP {status_code}")
                # Catégoriser l'erreur pour le circuit breaker (optimisation 2.3)
                if status_code == 429:
                    _claude_breaker.record_failure(error_category="quota")
                    break
                elif status_code in [401, 403]:
                    _claude_breaker.record_failure(error_category="auth")
                    break
                elif status_code == 400:
                    break  # Erreur client — pas de circuit breaker
                else:
                    _claude_breaker.record_failure()

            except requests.exceptions.ConnectionError as e:
                last_error = "Erreur de connexion"
                default_logger.error(f"[Claude] Erreur de connexion : {e}")
                _claude_breaker.record_failure()

            except (ValueError, KeyError, TypeError) as e:
                last_error = f"Erreur de format de réponse: {e}"
                default_logger.error(f"[Claude] Erreur parsing : {e}")

            except Exception as e:
                last_error = f"Erreur inattendue: {type(e).__name__}: {e}"
                default_logger.error(f"[Claude] Erreur inattendue : {e}")
                _claude_breaker.record_failure()

            if attempt < max_attempts - 1:
                wait_time = backoff_factor ** attempt
                default_logger.info(f"[Claude] Attente {wait_time:.1f}s avant prochaine tentative…")
                time.sleep(wait_time)

        raise RuntimeError(f"Échec Claude après {max_attempts} tentatives. {last_error}")

    def ask_with_cached_system(
        self,
        system_text: str,
        user_text: str,
        model: Optional[str] = None,
        max_attempts: int = 3,
        timeout: int = 60,
        max_tokens: int = 800,
    ) -> str:
        """Envoie un appel Claude avec le system prompt mis en cache (prompt caching).

        La partie `system_text` est marquée avec cache_control ephemeral :
        Anthropic la cache pendant 5 minutes, facturée à ~10% du prix normal
        en lecture de cache. Idéal pour les instructions NER/sentiment répétées.

        Args:
            system_text : Instructions statiques à mettre en cache
            user_text   : Contenu variable (texte à analyser)
            model       : Modèle à utiliser (None = model_batch)
            max_attempts: Nombre maximal de tentatives
            timeout     : Timeout en secondes
            max_tokens  : Tokens maximum en sortie

        Returns:
            Réponse texte nettoyée.
        """
        active_model = model or self.model_batch
        data = {
            "model": active_model,
            "max_tokens": max_tokens,
            "system": [
                {
                    "type": "text",
                    "text": system_text,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            "messages": [{"role": "user", "content": user_text}],
        }
        headers = dict(self.headers)
        # Le prompt caching nécessite le header beta
        headers["anthropic-beta"] = "prompt-caching-2024-07-31"

        last_error = None

        if not _claude_breaker.allow_request():
            raise RuntimeError(
                f"[Claude] Circuit OPEN — appels bloqués pendant la fenêtre de grâce "
                f"({_claude_breaker.grace_seconds:.0f}s)."
            )

        for attempt in range(max_attempts):
            try:
                default_logger.info(
                    f"[Claude/{active_model}] Appel avec cache system (tentative {attempt + 1}/{max_attempts})"
                )
                response = requests.post(CLAUDE_API_URL, json=data, headers=headers, timeout=timeout)
                response.raise_for_status()
                json_data = response.json()
                content_blocks = json_data.get("content", [])
                if not content_blocks:
                    raise ValueError("Réponse Claude vide (aucun bloc content)")
                content = content_blocks[0].get("text", "")
                if not content:
                    raise ValueError("Texte Claude vide")
                usage = json_data.get("usage", {})
                if usage:
                    default_logger.info(
                        f"[Claude/{active_model}] Usage (cached) — input: {usage.get('input_tokens', '?')} tokens, "
                        f"output: {usage.get('output_tokens', '?')} tokens, "
                        f"cache_read: {usage.get('cache_read_input_tokens', 0)} tokens"
                    )
                default_logger.info(f"[Claude] Réponse reçue : {len(content)} caractères")
                _claude_breaker.record_success()
                return content.strip()
            except requests.exceptions.Timeout:
                last_error = f"Timeout après {timeout}s"
                default_logger.warning(f"[Claude] Timeout tentative {attempt + 1}/{max_attempts}")
                _claude_breaker.record_failure()
            except requests.exceptions.HTTPError as e:
                status_code = e.response.status_code if e.response is not None else "inconnu"
                last_error = f"Erreur HTTP {status_code}"
                default_logger.error(f"[Claude] Erreur HTTP {status_code}")
                if status_code == 429:
                    _claude_breaker.record_failure(error_category="quota")
                    break
                elif status_code in [401, 403]:
                    _claude_breaker.record_failure(error_category="auth")
                    break
                elif status_code == 400:
                    break
                else:
                    _claude_breaker.record_failure()
            except requests.exceptions.ConnectionError as e:
                last_error = "Erreur de connexion"
                default_logger.error(f"[Claude] Erreur de connexion : {e}")
                _claude_breaker.record_failure()
            except (ValueError, KeyError, TypeError) as e:
                last_error = f"Erreur de format : {e}"
                default_logger.error(f"[Claude] Erreur parsing : {e}")
            except Exception as e:
                last_error = f"Erreur inattendue: {type(e).__name__}: {e}"
                default_logger.error(f"[Claude] Erreur inattendue : {e}")
                _claude_breaker.record_failure()
            if attempt < max_attempts - 1:
                wait_time = 2.0 ** attempt
                default_logger.info(f"[Claude] Attente {wait_time:.1f}s…")
                time.sleep(wait_time)

        raise RuntimeError(f"Échec Claude (cached system) après {max_attempts} tentatives. {last_error}")

    def generate_summary(
        self,
        text: str,
        max_lines: Optional[int] = None,
        language: str = "français",
        timeout: int = 60,
    ) -> str:
        """Résumé d'article — utilise Haiku (tâche batch).

        Args:
            max_lines: Nombre maximal de lignes. Si None, utilise config.summary_max_lines.
        """
        if max_lines is None:
            max_lines = get_config().summary_max_lines
        text_truncated = text[:15000]
        prompt = _build_summary_prompt(text_truncated, max_lines, language, retry=False)
        result = _strip_summary_heading(
            self.ask(prompt, model=self.model_batch, timeout=timeout, max_tokens=600)
        )

        for regen_attempt in range(1, _SUMMARY_REGEN_MAX_ATTEMPTS + 1):
            if not _contains_chinese_chars(result):
                break
            default_logger.warning(
                f"[Claude] Résumé contient des caractères chinois — régénération {regen_attempt}/{_SUMMARY_REGEN_MAX_ATTEMPTS}"
            )
            retry_prompt = _build_summary_prompt(text_truncated, max_lines, language, retry=True)
            result = _strip_summary_heading(
                self.ask(retry_prompt, model=self.model_batch, timeout=timeout, max_tokens=600)
            )

        return result

    def generate_entities(self, resume: str, timeout: int = 60) -> Optional[dict]:
        """Extraction NER — utilise Haiku avec prompt caching sur les instructions.

        Returns:
            Dict d'entités, {} si aucune entité trouvée, None si echec_parse,
            {} si echec_api (exception réseau).
        """
        if not resume or not isinstance(resume, str) or not resume.strip():
            return {}
        try:
            raw = self.ask_with_cached_system(
                system_text=_NER_SYSTEM_INSTRUCTIONS,
                user_text=f"Texte à analyser :\n{resume.strip()}",
                max_attempts=3,
                timeout=timeout,
                max_tokens=500,
            )
            return _parse_entities_response(raw)  # None = echec_parse
        except Exception as e:
            default_logger.warning(f"[Claude] Extraction NER échouée : {e}")
            return {}  # echec_api : l'appel réseau a échoué

    def generate_sentiment(self, resume: str, timeout: int = 30) -> Optional[dict]:
        """Sentiment & ton éditorial — utilise Haiku avec prompt caching sur les instructions.

        Returns:
            Dict sentiment/ton, {} si echec_api, None si echec_parse.
        """
        if not resume or not isinstance(resume, str) or not resume.strip():
            return {}
        try:
            raw = self.ask_with_cached_system(
                system_text=_SENTIMENT_SYSTEM_INSTRUCTIONS,
                user_text=f"Texte :\n{resume.strip()[:3000]}",
                max_attempts=2,
                timeout=timeout,
                max_tokens=150,
            )
            return _parse_sentiment_response(raw)  # None = echec_parse
        except Exception as e:
            default_logger.warning(f"[Claude] Analyse sentiment échouée : {e}")
            return {}  # echec_api : l'appel réseau a échoué

    def generate_summary_with_sentiment(
        self,
        text: str,
        max_lines: Optional[int] = None,
        language: str = "français",
        timeout: int = 75,
    ) -> dict:
        """Génère résumé + sentiment + ton éditorial en un seul appel Claude (Haiku + cache système).

        Économise 1 appel IA par article. Les instructions statiques sont mises en cache
        côté Anthropic (prompt caching), réduisant également le coût token.

        Returns:
            Dict avec les champs : resume, et optionnellement sentiment, score_sentiment,
            ton_editorial, score_ton.
            En cas d'échec du parsing JSON, retourne {"resume": <texte brut>} (fallback sûr).

        Raises:
            RuntimeError: Si l'appel API échoue complètement après retentatives.
        """
        if max_lines is None:
            max_lines = get_config().summary_max_lines
        text_truncated = text[:15000]
        try:
            raw = self.ask_with_cached_system(
                system_text=_COMBINED_SYSTEM_INSTRUCTIONS,
                user_text=_build_combined_user_prompt(text_truncated, max_lines, language),
                max_attempts=2,
                timeout=timeout,
                max_tokens=600,
            )
            result = _parse_summary_sentiment_response(raw)
            if not result or "resume" not in result:
                default_logger.warning(
                    "[Claude] Parsing JSON combiné échoué — extraction du champ resume depuis réponse brute"
                )
                raw_clean = _extract_resume_from_raw(raw)
                raw_clean = _strip_summary_heading(raw_clean)
                result = {"resume": raw_clean}

            result["resume"] = _strip_summary_heading(result.get("resume", ""))

            for regen_attempt in range(1, _SUMMARY_REGEN_MAX_ATTEMPTS + 1):
                if not _contains_chinese_chars(result.get("resume", "")):
                    break
                default_logger.warning(
                    f"[Claude] Résumé combiné contient des caractères chinois — régénération {regen_attempt}/{_SUMMARY_REGEN_MAX_ATTEMPTS}"
                )
                retry_raw = self.ask_with_cached_system(
                    system_text=_COMBINED_SYSTEM_INSTRUCTIONS,
                    user_text=_build_combined_user_prompt(
                        text_truncated,
                        max_lines,
                        language,
                        retry=True,
                    ),
                    max_attempts=2,
                    timeout=timeout,
                    max_tokens=600,
                )
                retry_result = _parse_summary_sentiment_response(retry_raw)
                if not retry_result or "resume" not in retry_result:
                    retry_result = {"resume": _strip_summary_heading(_extract_resume_from_raw(retry_raw))}
                retry_result["resume"] = _strip_summary_heading(retry_result.get("resume", ""))
                result = retry_result

            return result
        except Exception as e:
            default_logger.warning(f"[Claude] Résumé+sentiment combiné échoué : {e}")
            raise

    def synthesize_topic(self, topic: str, articles: list, timeout: int = 120) -> str:
        """Synthèse RAG multi-sources — utilise Sonnet (user-facing)."""
        if not articles:
            return "Aucun article disponible pour cette synthèse."
        sources_block = ""
        for i, a in enumerate(articles[:20], 1):
            source = a.get("Sources", "Source inconnue")
            date = a.get("Date de publication", "")
            resume = (a.get("Résumé") or "")[:800]
            sources_block += f"\n--- Article {i} ({source}, {date}) ---\n{resume}\n"
        prompt = (
            f"Tu es un analyste de presse. Voici {len(articles[:20])} articles de sources différentes "
            f"traitant du sujet : **{topic}**.\n\n"
            "Génère une synthèse comparative structurée en Markdown comprenant :\n"
            "1. **Résumé de la situation** (2-3 phrases)\n"
            "2. **Points de convergence** entre les sources\n"
            "3. **Points de divergence ou contradictions**\n"
            "4. **Positionnement éditorial** : quelles sources sont favorables, neutres ou critiques\n"
            "5. **Éléments clés manquants** (ce que les articles ne couvrent pas)\n\n"
            "Cite les sources (nom + date) à chaque point. Sois concis et factuel.\n\n"
            f"Articles :\n{sources_block}"
        )
        return self.ask(prompt, model=self.model_synthesis, max_attempts=2, timeout=timeout, max_tokens=2048)

    # ── Batch API (optimisation 2.8) ─────────────────────────────────────────

    def generate_entities_batch(
        self,
        resumes: list[str],
        poll_interval: int = 15,
        max_polls: int = 120,
    ) -> list[Optional[dict]]:
        """Extraction NER en batch via l'API Anthropic Message Batches.

        Envoie jusqu'à 10 000 résumés en une seule requête batch.
        Retourne les résultats dans le même ordre que l'entrée.
        Économies : ~50% sur le coût par token (prix batch Anthropic).

        Nécessite le package `anthropic` : pip install anthropic>=0.40.0

        Args:
            resumes       : Liste de résumés à analyser
            poll_interval : Secondes entre chaque sondage du statut (défaut: 15)
            max_polls     : Nombre maximal de sondages avant abandon (défaut: 120 = 30 min)

        Returns:
            Liste de dicts d'entités dans le même ordre que `resumes`.
            None pour les entrées ayant échoué.
        """
        try:
            import anthropic as _anthropic
        except ImportError:
            default_logger.error(
                "[Claude Batch] Package 'anthropic' non installé. "
                "Installez avec : pip install anthropic>=0.40.0"
            )
            return [None] * len(resumes)

        if not resumes:
            return []

        client = _anthropic.Anthropic(api_key=self.api_key)

        # Construire les requêtes batch
        requests_list = []
        for i, resume in enumerate(resumes):
            if not resume or not isinstance(resume, str) or not resume.strip():
                requests_list.append(None)
                continue
            requests_list.append({
                "custom_id": str(i),
                "params": {
                    "model": self.model_batch,
                    "max_tokens": 500,
                    "system": _NER_SYSTEM_INSTRUCTIONS,
                    "messages": [
                        {"role": "user", "content": f"Texte à analyser :\n{resume.strip()}"}
                    ],
                },
            })

        valid_requests = [r for r in requests_list if r is not None]
        if not valid_requests:
            return [None] * len(resumes)

        default_logger.info(f"[Claude Batch NER] Envoi de {len(valid_requests)} requêtes batch…")

        try:
            batch = client.messages.batches.create(requests=valid_requests)
            batch_id = batch.id
            default_logger.info(f"[Claude Batch NER] Batch créé : {batch_id}")
        except Exception as e:
            default_logger.error(f"[Claude Batch NER] Création batch échouée : {e}")
            return [None] * len(resumes)

        # Polling jusqu'à completion
        for poll in range(max_polls):
            time.sleep(poll_interval)
            try:
                batch_status = client.messages.batches.retrieve(batch_id)
            except Exception as e:
                default_logger.warning(f"[Claude Batch NER] Sondage #{poll + 1} échoué : {e}")
                continue

            processing_status = getattr(batch_status, "processing_status", None)
            default_logger.debug(f"[Claude Batch NER] Sondage #{poll + 1} — statut : {processing_status}")

            if processing_status == "ended":
                break
        else:
            default_logger.error(f"[Claude Batch NER] Timeout après {max_polls} sondages.")
            return [None] * len(resumes)

        # Récupérer les résultats
        results: dict[int, Optional[dict]] = {}
        try:
            for result in client.messages.batches.results(batch_id):
                idx = int(result.custom_id)
                if result.result.type == "succeeded":
                    raw = result.result.message.content[0].text if result.result.message.content else ""
                    results[idx] = _parse_entities_response(raw)
                else:
                    results[idx] = None
        except Exception as e:
            default_logger.error(f"[Claude Batch NER] Récupération résultats échouée : {e}")

        default_logger.info(
            f"[Claude Batch NER] Terminé — {len(results)}/{len(valid_requests)} résultats récupérés."
        )

        # Remettre dans l'ordre original (les entrées None restent None)
        return [results.get(i) for i in range(len(resumes))]

    def generate_sentiment_batch(
        self,
        resumes: list[str],
        poll_interval: int = 15,
        max_polls: int = 120,
    ) -> list[Optional[dict]]:
        """Analyse sentiment & ton éditorial en batch via l'API Anthropic Message Batches.

        Args:
            resumes       : Liste de résumés à analyser
            poll_interval : Secondes entre chaque sondage (défaut: 15)
            max_polls     : Nombre maximal de sondages (défaut: 120 = 30 min)

        Returns:
            Liste de dicts {sentiment, score_sentiment, ton_editorial, score_ton}
            dans le même ordre que `resumes`. None pour les échecs.
        """
        try:
            import anthropic as _anthropic
        except ImportError:
            default_logger.error(
                "[Claude Batch] Package 'anthropic' non installé. "
                "Installez avec : pip install anthropic>=0.40.0"
            )
            return [None] * len(resumes)

        if not resumes:
            return []

        client = _anthropic.Anthropic(api_key=self.api_key)

        requests_list = []
        for i, resume in enumerate(resumes):
            if not resume or not isinstance(resume, str) or not resume.strip():
                requests_list.append(None)
                continue
            requests_list.append({
                "custom_id": str(i),
                "params": {
                    "model": self.model_batch,
                    "max_tokens": 150,
                    "system": _SENTIMENT_SYSTEM_INSTRUCTIONS,
                    "messages": [
                        {"role": "user", "content": f"Texte :\n{resume.strip()[:3000]}"}
                    ],
                },
            })

        valid_requests = [r for r in requests_list if r is not None]
        if not valid_requests:
            return [None] * len(resumes)

        default_logger.info(f"[Claude Batch Sentiment] Envoi de {len(valid_requests)} requêtes batch…")

        try:
            batch = client.messages.batches.create(requests=valid_requests)
            batch_id = batch.id
            default_logger.info(f"[Claude Batch Sentiment] Batch créé : {batch_id}")
        except Exception as e:
            default_logger.error(f"[Claude Batch Sentiment] Création batch échouée : {e}")
            return [None] * len(resumes)

        for poll in range(max_polls):
            time.sleep(poll_interval)
            try:
                batch_status = client.messages.batches.retrieve(batch_id)
            except Exception as e:
                default_logger.warning(f"[Claude Batch Sentiment] Sondage #{poll + 1} échoué : {e}")
                continue

            processing_status = getattr(batch_status, "processing_status", None)
            if processing_status == "ended":
                break
        else:
            default_logger.error(f"[Claude Batch Sentiment] Timeout après {max_polls} sondages.")
            return [None] * len(resumes)

        results: dict[int, Optional[dict]] = {}
        try:
            for result in client.messages.batches.results(batch_id):
                idx = int(result.custom_id)
                if result.result.type == "succeeded":
                    raw = result.result.message.content[0].text if result.result.message.content else ""
                    results[idx] = _parse_sentiment_response(raw)
                else:
                    results[idx] = None
        except Exception as e:
            default_logger.error(f"[Claude Batch Sentiment] Récupération résultats échouée : {e}")

        default_logger.info(
            f"[Claude Batch Sentiment] Terminé — {len(results)}/{len(valid_requests)} résultats."
        )

        return [results.get(i) for i in range(len(resumes))]

    def generate_report(self, json_content: str, filename: str, timeout: int = 300) -> str:
        """Rapport synthétique Markdown — utilise Sonnet (user-facing)."""
        prompt = f"""
Analyse le fichier ce fichier JSON et fait une synthèse des actualités.
Affiche la date de publication et les sources lorsque tu cites un article.
Groupe les articles par catégories que tu auras identifiées.
En fin de synthèse fait un tableau avec les références (date de publication, sources et URL)
pour chaque article dans la rubrique "Images" il y a des liens d'images.
Lorsque cela est possible, publie le lien de l'image sous la forme <img src='{{URL}}' /> sur une nouvelle ligne en fin de paragraphe de catégorie. N'utilise qu'une image par paragraphe et assure-toi qu'une même URL d'image n'apparaisse qu'une seule fois dans tout le rapport.

Filename: {filename}
File contents:
----- BEGIN FILE CONTENTS -----
{json_content}
----- END FILE CONTENTS -----
"""
        return self.ask(prompt, model=self.model_synthesis, max_attempts=3, timeout=timeout, max_tokens=4096)

    def stream(
        self,
        prompt: str,
        model: Optional[str] = None,
        system: Optional[str] = None,
        max_tokens: int = 2048,
        timeout: int = 120,
        messages: Optional[list] = None,
    ):
        """Envoie un appel Claude en streaming et yield les événements SSE normalisés.

        Centralise la logique SSE pour les routes viewer (entities/info,
        synthesize-topic, chatbot). Chaque yield est une ligne SSE complète
        au format OpenAI (compatible avec le frontend React existant) :
          data: {"choices": [{"delta": {"content": "..."}, "finish_reason": null}]}
        ou la ligne de fin :
          data: [DONE]

        Args:
            prompt   : Prompt utilisateur (ignoré si messages est fourni)
            model    : Modèle à utiliser (None = model_synthesis)
            system   : Contenu du system prompt (optionnel)
            max_tokens: Tokens maximum en sortie
            timeout  : Timeout en secondes
            messages : Liste complète de messages [{"role":..,"content":..}].
                       Si fourni, remplace prompt.

        Yields:
            str — lignes SSE normalisées (terminées par \\n\\n)
        """
        active_model = model or self.model_synthesis
        if messages is None:
            messages = [{"role": "user", "content": prompt}]

        data: dict = {
            "model": active_model,
            "max_tokens": max_tokens,
            "stream": True,
            "messages": messages,
        }
        if system:
            data["system"] = system

        headers = dict(self.headers)

        try:
            r = requests.post(CLAUDE_API_URL, json=data, headers=headers, stream=True, timeout=timeout)
            r.raise_for_status()
            for line in r.iter_lines():
                if not line:
                    continue
                decoded = line.decode("utf-8")
                # Ignorer les lignes event:
                if decoded.startswith("event:"):
                    continue
                if not decoded.startswith("data:"):
                    continue
                raw = decoded[5:].strip()
                if not raw:
                    continue
                try:
                    evt = json.loads(raw)
                    evt_type = evt.get("type", "")
                    if evt_type == "content_block_delta":
                        text = evt.get("delta", {}).get("text", "")
                        if text:
                            normalized = json.dumps({
                                "choices": [{"delta": {"content": text}, "finish_reason": None}]
                            })
                            yield f"data: {normalized}\n\n"
                    elif evt_type == "message_stop":
                        yield "data: [DONE]\n\n"
                except (json.JSONDecodeError, KeyError):
                    continue
        except requests.exceptions.HTTPError as exc:
            body = ""
            try:
                body = exc.response.text[:800] if exc.response is not None else ""
            except Exception:
                pass
            error_msg = f"{exc}" + (f" — Détail API: {body}" if body else "")
            yield f'data: {json.dumps({"error": error_msg})}\n\n'
        except Exception as exc:
            yield f'data: {json.dumps({"error": str(exc)})}\n\n'


# ── Fallback Client ───────────────────────────────────────────────────────────

class FallbackClient:
    """Client IA avec fallback automatique : tente le client primaire,
    puis le secondaire si le primaire échoue avec une RuntimeError ou retourne None.

    Les deux clients doivent exposer les mêmes méthodes publiques :
    generate_summary, generate_entities, generate_sentiment,
    synthesize_topic, generate_report.
    """

    def __init__(self, primary, secondary):
        self._primary = primary
        self._secondary = secondary
        _name_p = type(primary).__name__
        _name_s = type(secondary).__name__
        default_logger.info(f"[FallbackClient] primaire={_name_p}, secondaire={_name_s}")

    def _call(self, method_name: str, *args, fallback_on_none: bool = False, **kwargs):
        """Appelle method_name sur le client primaire, bascule sur le secondaire
        en cas d'exception ou (si fallback_on_none=True) si le résultat est None."""
        try:
            result = getattr(self._primary, method_name)(*args, **kwargs)
            if fallback_on_none and result is None:
                default_logger.warning(
                    f"[FallbackClient] {type(self._primary).__name__}.{method_name} "
                    f"a retourné None (JSON invalide ?) — bascule sur {type(self._secondary).__name__}"
                )
                return getattr(self._secondary, method_name)(*args, **kwargs)
            return result
        except (RuntimeError, Exception) as exc:
            default_logger.warning(
                f"[FallbackClient] {type(self._primary).__name__}.{method_name} "
                f"échoué ({exc}) — bascule sur {type(self._secondary).__name__}"
            )
            return getattr(self._secondary, method_name)(*args, **kwargs)

    def generate_summary(self, *args, **kwargs):
        return self._call("generate_summary", *args, **kwargs)

    def generate_entities(self, *args, **kwargs):
        # fallback_on_none=True : si Ollama retourne None (JSON absent), retry cloud
        return self._call("generate_entities", *args, fallback_on_none=True, **kwargs)

    def generate_sentiment(self, *args, **kwargs):
        # fallback_on_none=True : si Ollama retourne None (JSON absent), retry cloud
        return self._call("generate_sentiment", *args, fallback_on_none=True, **kwargs)

    def synthesize_topic(self, *args, **kwargs):
        return self._call("synthesize_topic", *args, **kwargs)

    def generate_report(self, *args, **kwargs):
        return self._call("generate_report", *args, **kwargs)

    def generate_summary_with_sentiment(self, *args, **kwargs):
        # fallback_on_none=True : si Ollama retourne None (JSON absent), retry cloud
        return self._call("generate_summary_with_sentiment", *args, fallback_on_none=True, **kwargs)

    def ask(self, *args, **kwargs):
        return self._call("ask", *args, **kwargs)


# ── Client Ollama (local) ─────────────────────────────────────────────────────

class OllamaClient(EurIAClient):
    """Client Ollama — API OpenAI-compatible, inférence locale.

    Hérite de EurIAClient car Ollama expose exactement la même interface
    /v1/chat/completions. Seules différences :
      - Endpoint local  : http://localhost:11434/v1/chat/completions
      - Pas d'authentification (bearer="ollama" factice)
      - enable_web_search forcé à False (pas d'accès internet)
      - Marqueur "ollama" dans tous les logs pour identification claire

    Utilisation recommandée : generate_entities() et generate_sentiment()
    (tâches NER/structured-output, ~21% des tokens journaliers).
    Les synthèses encyclopédiques et rapports restent sur le cloud.
    """

    _DEFAULT_MODEL = "qwen2.5:7b"
    _provider_label: str = "Ollama"

    @staticmethod
    def _is_running_in_docker() -> bool:
        import os as _os
        return _os.path.exists("/.dockerenv") or _os.environ.get("RUNNING_IN_DOCKER") == "1"

    @staticmethod
    def _ollama_host() -> str:
        """Retourne l'hôte Ollama selon le contexte d'exécution.

        Priorité :
        - `OLLAMA_HOST_DOCKER` dans un conteneur
        - `OLLAMA_HOST_LOCAL` sur l'hôte
        - `OLLAMA_HOST` pour compatibilité descendante
        - fallback implicite (`host.docker.internal` dans Docker, sinon `localhost`)
        """
        import os as _os
        if OllamaClient._is_running_in_docker():
            return (
                _os.environ.get("OLLAMA_HOST_DOCKER", "").strip()
                or _os.environ.get("OLLAMA_HOST", "").strip()
                or "host.docker.internal"
            )

        return (
            _os.environ.get("OLLAMA_HOST_LOCAL", "").strip()
            or _os.environ.get("OLLAMA_HOST", "").strip()
            or "localhost"
        )

    @classmethod
    def _default_url(cls) -> str:
        return f"http://{cls._ollama_host()}:11434/v1/chat/completions"

    def __init__(self, model: str = _DEFAULT_MODEL):
        url = self._default_url()
        # Initialise EurIAClient avec l'endpoint Ollama local
        super().__init__(
            url=url,
            bearer="ollama",           # Ollama n'authentifie pas — valeur factice
            enable_web_search=False,   # Pas d'internet local
            model=model,
        )
        self._ollama_model = model
        default_logger.info(f"[OllamaClient] Initialisé — modèle={model}, endpoint={url}")

    # Message système injecté dans tous les appels Ollama pour forcer le français
    _SYSTEM_FRENCH = (
        "Tu réponds toujours en français, quelle que soit la langue du texte analysé."
    )

    # ── Surcharge ask() pour tracer les appels dans les logs ─────────────────

    def ask(
        self,
        prompt: str,
        max_attempts: int = 3,
        timeout: int = 60,
        max_tokens: int = 800,
        enable_web_search: Optional[bool] = None,
        system_message: Optional[str] = None,
    ) -> str:
        default_logger.info(
            f"[Ollama/{self._ollama_model}] ask() — {len(prompt)} cars, "
            f"max_tokens={max_tokens}, timeout={timeout}s"
        )
        # Injecter le message système français si aucun message système n'est fourni
        effective_system = system_message if system_message is not None else self._SYSTEM_FRENCH
        result = super().ask(
            prompt,
            max_attempts=max_attempts,
            timeout=timeout,
            max_tokens=max_tokens,
            enable_web_search=False,   # Toujours False pour Ollama
            system_message=effective_system,
        )
        default_logger.info(
            f"[Ollama/{self._ollama_model}] Réponse reçue — {len(result)} cars"
        )
        return result

    def generate_entities(self, resume: str, timeout: int = 60) -> Optional[dict]:
        default_logger.info(f"[Ollama/{self._ollama_model}] generate_entities() — NER local")
        return super().generate_entities(resume, timeout=timeout)

    def generate_sentiment(self, resume: str, timeout: int = 30) -> Optional[dict]:
        default_logger.info(f"[Ollama/{self._ollama_model}] generate_sentiment() — sentiment local")
        return super().generate_sentiment(resume, timeout=timeout)

    def generate_summary_with_sentiment(
        self,
        text: str,
        max_lines: Optional[int] = None,
        language: str = "français",
        timeout: int = 90,
    ) -> dict:
        """Surcharge avec max_tokens=800 (Ollama local, pas de coût API) et timeout 90s."""
        default_logger.info(f"[Ollama/{self._ollama_model}] generate_summary_with_sentiment() — local")
        if max_lines is None:
            max_lines = get_config().summary_max_lines
        text_truncated = text[:15000]
        prompt = f"{_COMBINED_SYSTEM_INSTRUCTIONS}\n\n{_build_combined_user_prompt(text_truncated, max_lines, language)}"
        # max_tokens=800 au lieu de 600 : Ollama est local, pas de surcoût
        # self.ask() (et non EurIAClient.ask()) pour bénéficier du message système français
        raw = self.ask(prompt, timeout=timeout, max_tokens=800)
        default_logger.info(f"[Ollama/{self._ollama_model}] Réponse brute résumé+sentiment — {len(raw)} cars")
        result = _parse_summary_sentiment_response(raw)
        if not result or "resume" not in result:
            default_logger.warning(
                f"[Ollama/{self._ollama_model}] Parsing JSON combiné échoué "
                "— extraction du champ resume depuis réponse brute"
            )
            raw_clean = _extract_resume_from_raw(raw)
            raw_clean = _strip_summary_heading(raw_clean)
            result = {"resume": raw_clean}

        result["resume"] = _strip_summary_heading(result.get("resume", ""))

        for regen_attempt in range(1, _SUMMARY_REGEN_MAX_ATTEMPTS + 1):
            if not _contains_chinese_chars(result.get("resume", "")):
                break
            default_logger.warning(
                f"[Ollama/{self._ollama_model}] Résumé combiné contient des caractères chinois "
                f"— régénération {regen_attempt}/{_SUMMARY_REGEN_MAX_ATTEMPTS}"
            )
            retry_prompt = (
                f"{_COMBINED_SYSTEM_INSTRUCTIONS}\n\n"
                f"{_build_combined_user_prompt(text_truncated, max_lines, language, retry=True)}"
            )
            retry_raw = self.ask(retry_prompt, timeout=timeout, max_tokens=800)
            retry_result = _parse_summary_sentiment_response(retry_raw)
            if not retry_result or "resume" not in retry_result:
                retry_result = {"resume": _strip_summary_heading(_extract_resume_from_raw(retry_raw))}
            retry_result["resume"] = _strip_summary_heading(retry_result.get("resume", ""))
            result = retry_result

        return result

    @classmethod
    def is_available(cls) -> bool:
        """Vérifie que le serveur Ollama répond sur l'hôte résolu."""
        import requests as _req
        try:
            r = _req.get(f"http://{cls._ollama_host()}:11434/api/tags", timeout=3)
            return r.status_code == 200
        except Exception:
            return False

    @classmethod
    def list_models(cls) -> list[str]:
        """Retourne la liste des modèles disponibles localement."""
        import requests as _req
        try:
            r = _req.get(f"http://{cls._ollama_host()}:11434/api/tags", timeout=5)
            if r.status_code == 200:
                return [m["name"] for m in r.json().get("models", [])]
        except Exception:
            pass
        return []


# ── Factory ───────────────────────────────────────────────────────────────────

def get_ai_client(fallback: bool = True):
    """Retourne le client IA selon AI_PROVIDER dans .env.

    Si fallback=True (défaut) et que les deux IAs sont configurées,
    retourne un FallbackClient (primaire → secondaire sur erreur).

    Args:
        fallback: Si True, active le fallback automatique vers l'autre IA.
    Returns:
        FallbackClient si les deux IA sont configurées et fallback=True,
        EurIAClient si AI_PROVIDER=euria (ou non défini),
        ClaudeClient si AI_PROVIDER=claude,
        OllamaClient si AI_PROVIDER=ollama.
    """
    config = get_config()
    provider = config.ai_provider

    import os as _os
    euria_ok  = bool(_os.environ.get("URL", "").strip() and _os.environ.get("bearer", "").strip())
    claude_ok = bool(_os.environ.get("ANTHROPIC_API_KEY", "").strip())

    # Ollama local — pas de credentials, juste le serveur qui tourne
    if provider == "ollama":
        model = _os.environ.get("OLLAMA_MODEL", OllamaClient._DEFAULT_MODEL).strip()
        default_logger.info(f"[get_ai_client] Fournisseur=Ollama (local), modèle={model}")
        return OllamaClient(model=model)

    if fallback and euria_ok and claude_ok:
        if provider == "claude":
            return FallbackClient(ClaudeClient(), EurIAClient())
        else:
            return FallbackClient(EurIAClient(), ClaudeClient())

    if provider == "claude":
        return ClaudeClient()
    return EurIAClient()


def get_ner_client():
    """Retourne le client IA dédié au NER/sentiment batch (Option A Ollama).

    Si AI_PROVIDER_NER=ollama et que le serveur Ollama est disponible,
    retourne un OllamaClient. Sinon, bascule sur le client principal
    (EurIA ou Claude selon AI_PROVIDER).

    Cette séparation permet d'utiliser Ollama uniquement pour les tâches
    structurées (NER, sentiment) tout en conservant le cloud pour les
    résumés, rapports et synthèses encyclopédiques.
    """
    get_config()  # Garantit que load_dotenv() est appelé avant la lecture des vars d'env
    import os as _os
    ner_provider = _os.environ.get("AI_PROVIDER_NER", "").strip().lower()

    if ner_provider == "ollama":
        if OllamaClient.is_available():
            model = _os.environ.get("OLLAMA_MODEL", OllamaClient._DEFAULT_MODEL).strip()
            default_logger.info(
                f"[get_ner_client] NER → Ollama local (modèle={model}) "
                f"avec fallback cloud si résultat None ou exception"
            )
            # FallbackClient : bascule automatique sur cloud si Ollama retourne
            # None (JSON invalide) ou lève une exception inattendue.
            return FallbackClient(OllamaClient(model=model), get_ai_client(fallback=False))
        else:
            default_logger.warning(
                "[get_ner_client] AI_PROVIDER_NER=ollama mais serveur Ollama injoignable "
                "— bascule sur le client cloud principal."
            )

    # Fallback transparent sur le client cloud principal
    return get_ai_client(fallback=True)


def get_summary_client():
    """Retourne le client IA dédié à la génération de résumés (Option B Ollama).

    Si AI_PROVIDER_SUMMARY=ollama et que le serveur Ollama est disponible,
    retourne un FallbackClient(OllamaClient, cloud) pour les résumés.
    Sinon, retourne le client cloud principal.

    Différence avec get_ner_client() : les résumés sont du texte libre —
    le fallback sur None n'est pas activé pour generate_summary() car
    une réponse brute reste acceptable. Il l'est pour
    generate_summary_with_sentiment() car le format JSON est attendu.
    """
    get_config()  # Garantit que load_dotenv() est appelé avant la lecture des vars d'env
    import os as _os
    summary_provider = _os.environ.get("AI_PROVIDER_SUMMARY", "").strip().lower()

    if summary_provider == "ollama":
        if OllamaClient.is_available():
            model = _os.environ.get("OLLAMA_MODEL", OllamaClient._DEFAULT_MODEL).strip()
            default_logger.info(
                f"[get_summary_client] Résumés → Ollama local (modèle={model}) "
                f"avec fallback cloud sur exception"
            )
            # FallbackClient : bascule sur cloud si exception (Ollama crash, timeout…)
            # Note : fallback_on_none=False pour generate_summary (texte brut OK)
            #        fallback_on_none=True  pour generate_summary_with_sentiment (JSON attendu)
            return FallbackClient(OllamaClient(model=model), get_ai_client(fallback=False))
        else:
            default_logger.warning(
                "[get_summary_client] AI_PROVIDER_SUMMARY=ollama mais serveur Ollama injoignable "
                "— bascule sur le client cloud principal."
            )

    # Fallback transparent sur le client cloud principal
    return get_ai_client(fallback=True)
