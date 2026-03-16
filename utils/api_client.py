"""Module client API pour l'interaction avec EurIA (Infomaniak) et Claude (Anthropic).

Fournit :
- EurIAClient  : client pour l'API EurIA/Qwen3 d'Infomaniak
- ClaudeClient : client pour l'API Anthropic Claude
- FallbackClient : wrapper qui essaie le client primaire, puis le secondaire en cas d'échec
- get_ai_client() : factory qui retourne le(s) client(s) selon AI_PROVIDER dans .env
"""

import json
import re
import time
import threading
import requests
from typing import Optional
from .logging import default_logger
from .config import get_config


# ── Circuit Breaker ───────────────────────────────────────────────────────────

class CircuitBreaker:
    """Circuit breaker thread-safe pour les appels API externes.

    États :
      CLOSED    — appels autorisés (fonctionnement normal)
      OPEN      — appels bloqués pendant la fenêtre de grâce (grace_seconds)
      HALF-OPEN — un appel de sonde autorisé pour tester le rétablissement

    Transitions :
      CLOSED  → OPEN       : après N échecs consécutifs
      OPEN    → HALF-OPEN  : après grace_seconds secondes
      HALF-OPEN → CLOSED   : succès de la sonde
      HALF-OPEN → OPEN     : échec de la sonde (réinitialise le timer)
    """

    _STATE_CLOSED    = "CLOSED"
    _STATE_OPEN      = "OPEN"
    _STATE_HALF_OPEN = "HALF-OPEN"

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

    def record_failure(self) -> None:
        """À appeler après un échec d'appel."""
        with self._lock:
            self._failure_count += 1
            if self._state == self._STATE_HALF_OPEN:
                # La sonde a échoué — rouvrir
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
- CARDINAL : nombres cardinaux significatifs"""

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

    # Normaliser : garder uniquement les types connus, dédupliquer
    result = {}
    for etype in _ENTITY_TYPES:
        values = raw_entities.get(etype, [])
        if not isinstance(values, list):
            continue
        seen: set[str] = set()
        dedup = []
        for v in values:
            if isinstance(v, str) and v.strip() and v.strip() not in seen:
                seen.add(v.strip())
                dedup.append(v.strip())
        if dedup:
            result[etype] = dedup

    return result  # {} = réponse valide mais aucune entité trouvée


_SENTIMENT_VALUES = {"positif", "neutre", "négatif"}
_TON_VALUES = {"factuel", "alarmiste", "promotionnel", "critique", "analytique"}

_PROMPT_SENTIMENT_TEMPLATE = _SENTIMENT_SYSTEM_INSTRUCTIONS + "\n\nTexte :\n{resume}"


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
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        obj = re.search(r"\{[\s\S]*\}", text)
        if not obj:
            default_logger.warning("Impossible d'extraire du JSON depuis la réponse sentiment")
            return None  # echec_parse : pas de JSON du tout
        try:
            data = json.loads(obj.group(0))
        except json.JSONDecodeError:
            default_logger.warning("JSON sentiment invalide après extraction")
            return None  # echec_parse : JSON malformé
    if not isinstance(data, dict):
        return {}
    result = {}
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
    
    def __init__(
        self,
        url: Optional[str] = None,
        bearer: Optional[str] = None,
        model: str = "qwen3",
        enable_web_search: bool = True
    ):
        """Initialise le client API.
        
        Args:
            url: URL de l'API (utilise la config si None)
            bearer: Token d'authentification (utilise la config si None)
            model: Nom du modèle IA à utiliser (défaut: qwen3)
            enable_web_search: Active la recherche web (défaut: True)
        """
        config = get_config()
        
        self.url = url or config.url
        self.bearer = bearer or config.bearer
        self.model = model
        self.enable_web_search = enable_web_search
        
        self.headers = {
            'Authorization': f'Bearer {self.bearer}',
            'Content-Type': 'application/json',
        }
        
        if not self.url or not self.bearer:
            raise ValueError("URL et bearer token requis pour le client API")
    
    def ask(
        self,
        prompt: str,
        max_attempts: int = 3,
        timeout: int = 60,
        backoff_factor: float = 2.0,
        max_tokens: Optional[int] = None
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
        
        data = {
            "messages": [{"content": prompt, "role": "user"}],
            "model": self.model,
            "enable_web_search": self.enable_web_search
        }
        if max_tokens is not None:
            data["max_tokens"] = max_tokens
        
        last_error = None

        if not _euria_breaker.allow_request():
            raise RuntimeError(
                f"[EurIA] Circuit OPEN — appels bloqués pendant la fenêtre de grâce "
                f"({_euria_breaker.grace_seconds:.0f}s). Dernière erreur : {_euria_breaker.name}"
            )

        for attempt in range(max_attempts):
            try:
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

                # Valider la structure de la réponse
                if 'choices' not in json_data or len(json_data['choices']) == 0:
                    raise ValueError("Réponse API invalide : champ 'choices' manquant ou vide")

                content = json_data['choices'][0]['message']['content']

                if not content:
                    raise ValueError("Réponse API vide")

                default_logger.info(f"Réponse reçue de l'API: {len(content)} caractères")
                _euria_breaker.record_success()
                return content.strip()

            except requests.exceptions.Timeout as e:
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

                # Ne pas retry pour certains codes d'erreur
                if status_code in [400, 401, 403, 404]:
                    default_logger.error("Erreur non récupérable, arrêt des tentatives")
                    break
                _euria_breaker.record_failure()

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

            # Backoff exponentiel avant la prochaine tentative
            if attempt < max_attempts - 1:
                wait_time = backoff_factor ** attempt
                default_logger.info(f"Attente de {wait_time:.1f}s avant nouvelle tentative...")
                time.sleep(wait_time)

        # Toutes les tentatives ont échoué
        error_message = (
            f"Échec après {max_attempts} tentatives. "
            f"Dernière erreur: {last_error}"
        )
        default_logger.error(error_message)

        raise RuntimeError(f"Échec API après {max_attempts} tentatives. {last_error}")
    
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
        prompt = (
            f"Faire un résumé de ce texte sur maximum {max_lines} lignes en {language}, "
            f"ne donne que le résumé, sans commentaire ni remarque : {text_truncated}"
        )
        result = self.ask(prompt, timeout=timeout)
        # Supprimer le préfixe de titre Markdown que certains modèles ajoutent (ex: "# Résumé\n")
        result = re.sub(r'^#{1,3}\s*[Rr]é[sc]?umé\s*[:\-]?\s*\n?', '', result).strip()
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
            raw = self.ask(prompt, max_attempts=3, timeout=timeout, max_tokens=800)
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
            raw = self.ask(prompt, max_attempts=2, timeout=timeout, max_tokens=150)
            return _parse_sentiment_response(raw)  # None = echec_parse
        except Exception as e:
            default_logger.warning(f"Analyse sentiment échouée : {e}")
            return {}  # echec_api : l'appel réseau a échoué

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
        return self.ask(prompt, max_attempts=2, timeout=timeout)

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
        return self.ask(prompt, max_attempts=3, timeout=timeout)


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
                if status_code in [400, 401, 403]:
                    break
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
                if status_code in [400, 401, 403]:
                    break
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
        prompt = (
            f"Faire un résumé de ce texte sur maximum {max_lines} lignes en {language}, "
            f"ne donne que le résumé, sans commentaire ni remarque : {text_truncated}"
        )
        result = self.ask(prompt, model=self.model_batch, timeout=timeout, max_tokens=512)
        # Supprimer le préfixe de titre Markdown que certains modèles ajoutent (ex: "# Résumé\n")
        result = re.sub(r'^#{1,3}\s*[Rr]é[sc]?umé\s*[:\-]?\s*\n?', '', result).strip()
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
                max_tokens=800,
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
    puis le secondaire si le primaire échoue avec une RuntimeError.

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

    def _call(self, method_name: str, *args, **kwargs):
        try:
            result = getattr(self._primary, method_name)(*args, **kwargs)
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
        return self._call("generate_entities", *args, **kwargs)

    def generate_sentiment(self, *args, **kwargs):
        return self._call("generate_sentiment", *args, **kwargs)

    def synthesize_topic(self, *args, **kwargs):
        return self._call("synthesize_topic", *args, **kwargs)

    def generate_report(self, *args, **kwargs):
        return self._call("generate_report", *args, **kwargs)

    def ask(self, *args, **kwargs):
        return self._call("ask", *args, **kwargs)


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
        ClaudeClient si AI_PROVIDER=claude.
    """
    config = get_config()
    provider = config.ai_provider

    # Vérifier la disponibilité des credentials
    import os as _os
    euria_ok = bool(_os.environ.get("URL", "").strip() and _os.environ.get("bearer", "").strip())
    claude_ok = bool(_os.environ.get("ANTHROPIC_API_KEY", "").strip())

    if fallback and euria_ok and claude_ok:
        # Les deux IAs sont configurées : activer le fallback
        if provider == "claude":
            return FallbackClient(ClaudeClient(), EurIAClient())
        else:
            return FallbackClient(EurIAClient(), ClaudeClient())

    # Un seul fournisseur disponible
    if provider == "claude":
        return ClaudeClient()
    return EurIAClient()
