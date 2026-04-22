"""utils/async_enricher.py — Enrichissement asynchrone via asyncio + aiohttp.

Optimisation 2.4 : remplace le ThreadPoolExecutor pour les enrichissements
I/O-bound (NER, sentiment) par asyncio + aiohttp qui gère mieux les
centaines de petites requêtes HTTP en parallèle.

Dépendance optionnelle :
    pip install aiohttp>=3.9.0

Fallback automatique vers le client synchrone si aiohttp n'est pas installé.

Usage :
    from utils.async_enricher import AsyncEnricher

    enricher = AsyncEnricher(concurrency=15)

    # Enrichissement NER de N articles en batch
    results = enricher.enrich_entities_batch(articles)

    # Enrichissement sentiment
    results = enricher.enrich_sentiment_batch(articles)
"""

import asyncio
import json
import time
from typing import Any, Optional

from .logging import default_logger

# ── Import optionnel aiohttp ──────────────────────────────────────────────────

try:
    import aiohttp as _aiohttp
    _AIOHTTP_AVAILABLE = True
except ImportError:
    _aiohttp = None  # type: ignore
    _AIOHTTP_AVAILABLE = False


# ── Classe principale ─────────────────────────────────────────────────────────

class AsyncEnricher:
    """Enrichisseur asynchrone pour NER et sentiment sur des listes d'articles.

    Utilise asyncio + aiohttp pour paralléliser les appels API sans les
    limitations du GIL Python sur les threads I/O.

    Si aiohttp n'est pas disponible, délègue automatiquement au client
    synchrone via utils.parallel (ThreadPoolExecutor).

    Args:
        concurrency : Nombre maximal d'appels API simultanés (défaut : 10).
                      Augmenter jusqu'à 20 si l'API le permet, réduire en cas
                      de quotas stricts.
        provider    : Fournisseur IA — None = lit AI_PROVIDER depuis .env.
    """

    def __init__(self, concurrency: int = 10, provider: Optional[str] = None):
        self.concurrency = concurrency
        self._provider = provider
        self.available = _AIOHTTP_AVAILABLE

        if not self.available:
            default_logger.warning(
                "[AsyncEnricher] aiohttp non installé — fallback sur ThreadPoolExecutor. "
                "Installez avec : pip install aiohttp>=3.9.0"
            )

    # ── Méthodes synchrones publiques ────────────────────────────────────────

    def enrich_entities_batch(
        self,
        articles: list[dict],
        timeout_per_request: int = 60,
    ) -> list[dict]:
        """Enrichit une liste d'articles avec les entités NER (batch async).

        Chaque article doit posséder un champ "Résumé".
        Les articles déjà enrichis (champ "entities" présent) sont ignorés.

        Args:
            articles            : Liste d'articles au format WUDD.ai
            timeout_per_request : Timeout par requête API en secondes

        Returns:
            Liste des articles avec le champ "entities" ajouté ou mis à jour.
            Les articles sans "Résumé" sont retournés inchangés.
        """
        if self.available:
            return asyncio.run(
                self._async_enrich_batch(
                    articles,
                    task_type="entities",
                    timeout=timeout_per_request,
                )
            )
        return self._sync_fallback_entities(articles)

    def enrich_sentiment_batch(
        self,
        articles: list[dict],
        timeout_per_request: int = 30,
    ) -> list[dict]:
        """Enrichit une liste d'articles avec le sentiment et le ton éditorial.

        Les articles déjà enrichis (champ "sentiment" présent) sont ignorés.

        Args:
            articles            : Liste d'articles au format WUDD.ai
            timeout_per_request : Timeout par requête API en secondes

        Returns:
            Liste des articles avec les champs sentiment ajoutés.
        """
        if self.available:
            return asyncio.run(
                self._async_enrich_batch(
                    articles,
                    task_type="sentiment",
                    timeout=timeout_per_request,
                )
            )
        return self._sync_fallback_sentiment(articles)

    # ── Cœur asyncio ────────────────────────────────────────────────────────

    async def _async_enrich_batch(
        self,
        articles: list[dict],
        task_type: str,
        timeout: int,
    ) -> list[dict]:
        """Exécute le batch d'enrichissement de façon asynchrone."""
        from .config import get_config
        import os as _os

        config = get_config()
        provider = self._provider or _os.environ.get("AI_PROVIDER", "euria").strip().lower()

        semaphore = asyncio.Semaphore(self.concurrency)
        enriched = list(articles)  # copie superficielle

        # Préparer les sessions HTTP
        conn_timeout = _aiohttp.ClientTimeout(total=timeout + 5, sock_read=timeout)

        async with _aiohttp.ClientSession(timeout=conn_timeout) as session:
            tasks = []
            for i, article in enumerate(articles):
                resume = article.get("Résumé") or article.get("resume") or ""
                if not resume or not isinstance(resume, str) or not resume.strip():
                    tasks.append(asyncio.create_task(asyncio.sleep(0)))  # no-op
                    continue

                # Ignorer les articles déjà enrichis
                if task_type == "entities" and article.get("entities") is not None:
                    tasks.append(asyncio.create_task(asyncio.sleep(0)))
                    continue
                if task_type == "sentiment" and article.get("sentiment") is not None:
                    tasks.append(asyncio.create_task(asyncio.sleep(0)))
                    continue

                task = asyncio.create_task(
                    self._enrich_one(
                        session=session,
                        semaphore=semaphore,
                        article_idx=i,
                        resume=resume.strip(),
                        task_type=task_type,
                        config=config,
                        provider=provider,
                        timeout=timeout,
                    )
                )
                tasks.append(task)

            results = await asyncio.gather(*tasks, return_exceptions=True)

        # Appliquer les résultats
        success = 0
        errors = 0
        for result in results:
            if isinstance(result, Exception):
                errors += 1
                continue
            if isinstance(result, tuple):
                idx, enrichment = result
                if enrichment and isinstance(enrichment, dict):
                    enriched[idx].update(enrichment)
                    success += 1

        default_logger.info(
            f"[AsyncEnricher:{task_type}] Terminé — {success} succès, {errors} erreurs "
            f"sur {len(articles)} articles."
        )
        return enriched

    async def _enrich_one(
        self,
        session: Any,
        semaphore: asyncio.Semaphore,
        article_idx: int,
        resume: str,
        task_type: str,
        config: Any,
        provider: str,
        timeout: int,
    ) -> tuple[int, Optional[dict]]:
        """Enrichit un seul article de façon asynchrone."""
        async with semaphore:
            try:
                if provider == "claude":
                    return (article_idx, await self._call_claude_async(
                        session, resume, task_type, config, timeout
                    ))
                else:
                    return (article_idx, await self._call_euria_async(
                        session, resume, task_type, config, timeout
                    ))
            except Exception as e:
                default_logger.debug(
                    f"[AsyncEnricher] Article #{article_idx} — échec {task_type} : {e}"
                )
                return (article_idx, None)

    async def _call_euria_async(
        self,
        session: Any,
        resume: str,
        task_type: str,
        config: Any,
        timeout: int,
    ) -> Optional[dict]:
        """Appel API EurIA asynchrone."""
        from .api_client import _PROMPT_ENTITIES, _PROMPT_SENTIMENT_TEMPLATE
        from .api_client import _extract_chat_text, _extract_reasoning_text, get_euria_model
        from .api_client import _parse_entities_response, _parse_sentiment_response

        if task_type == "entities":
            prompt = _PROMPT_ENTITIES.format(resume=resume)
            max_tokens = 800
        else:
            prompt = _PROMPT_SENTIMENT_TEMPLATE.format(resume=resume[:3000])
            max_tokens = 150

        headers = config.get_api_headers()

        raw = ""
        for attempt in range(2):
            messages = [{"content": prompt, "role": "user"}]
            if attempt == 1:
                messages = [{
                    "role": "system",
                    "content": "Réponds uniquement avec le résultat final, sans reasoning et sans balise <think>.",
                }, *messages]
            payload = {
                "messages": messages,
                "model": get_euria_model(),
                "max_tokens": max_tokens,
            }

            async with session.post(
                config.url,
                json=payload,
                headers=headers,
                timeout=_aiohttp.ClientTimeout(total=timeout),
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()
                message = ((data.get("choices") or [{}])[0] or {}).get("message") or {}
                raw = _extract_chat_text(message.get("content")).strip()
                if raw:
                    break
                if not _extract_reasoning_text(message):
                    break

        if not raw:
            return None

        if task_type == "entities":
            return _parse_entities_response(raw)
        else:
            return _parse_sentiment_response(raw)

    async def _call_claude_async(
        self,
        session: Any,
        resume: str,
        task_type: str,
        config: Any,
        timeout: int,
    ) -> Optional[dict]:
        """Appel API Claude asynchrone avec prompt caching."""
        from .api_client import (
            CLAUDE_API_URL, CLAUDE_API_VERSION,
            _NER_SYSTEM_INSTRUCTIONS, _SENTIMENT_SYSTEM_INSTRUCTIONS,
            _parse_entities_response, _parse_sentiment_response,
        )
        import os as _os

        if task_type == "entities":
            system_text = _NER_SYSTEM_INSTRUCTIONS
            user_text = f"Texte à analyser :\n{resume}"
            max_tokens = 800
        else:
            system_text = _SENTIMENT_SYSTEM_INSTRUCTIONS
            user_text = f"Texte :\n{resume[:3000]}"
            max_tokens = 150

        api_key = _os.environ.get("ANTHROPIC_API_KEY", "") or config.anthropic_api_key
        model = _os.environ.get("CLAUDE_MODEL_BATCH", "").strip() or config.claude_model_batch

        headers = {
            "x-api-key": api_key,
            "anthropic-version": CLAUDE_API_VERSION,
            "Content-Type": "application/json",
            "anthropic-beta": "prompt-caching-2024-07-31",
        }
        payload = {
            "model": model,
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

        async with session.post(
            CLAUDE_API_URL,
            json=payload,
            headers=headers,
            timeout=_aiohttp.ClientTimeout(total=timeout),
        ) as resp:
            resp.raise_for_status()
            data = await resp.json()
            raw = data["content"][0]["text"]

        if task_type == "entities":
            return _parse_entities_response(raw)
        else:
            return _parse_sentiment_response(raw)

    # ── Fallbacks synchrones ─────────────────────────────────────────────────

    def _sync_fallback_entities(self, articles: list[dict]) -> list[dict]:
        """Fallback : enrichissement NER synchrone via ThreadPoolExecutor."""
        from .parallel import run_parallel
        from .api_client import get_ner_client

        client = get_ner_client()
        enriched = list(articles)

        def _process(item: tuple[int, dict]) -> tuple[int, Optional[dict]]:
            idx, article = item
            resume = article.get("Résumé") or ""
            if not resume or article.get("entities") is not None:
                return (idx, None)
            result = client.generate_entities(resume)
            return (idx, result)

        indexed = list(enumerate(articles))
        results = run_parallel(_process, indexed)

        for idx, result in results:
            if result and isinstance(result, dict):
                enriched[idx]["entities"] = result

        return enriched

    def _sync_fallback_sentiment(self, articles: list[dict]) -> list[dict]:
        """Fallback : enrichissement sentiment synchrone via ThreadPoolExecutor."""
        from .parallel import run_parallel
        from .api_client import get_ner_client

        client = get_ner_client()
        enriched = list(articles)

        def _process(item: tuple[int, dict]) -> tuple[int, Optional[dict]]:
            idx, article = item
            resume = article.get("Résumé") or ""
            if not resume or article.get("sentiment") is not None:
                return (idx, None)
            result = client.generate_sentiment(resume)
            return (idx, result)

        indexed = list(enumerate(articles))
        results = run_parallel(_process, indexed)

        for idx, result in results:
            if result and isinstance(result, dict):
                enriched[idx].update(result)

        return enriched


# ── Instance globale ──────────────────────────────────────────────────────────

_default_enricher: Optional[AsyncEnricher] = None


def get_async_enricher(concurrency: int = 10) -> AsyncEnricher:
    """Retourne l'instance globale d'AsyncEnricher (singleton)."""
    global _default_enricher
    if _default_enricher is None:
        _default_enricher = AsyncEnricher(concurrency=concurrency)
    return _default_enricher
