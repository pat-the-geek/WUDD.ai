"""
utils/metrics.py — Métriques Prometheus pour WUDD.ai

Expose des compteurs et histogrammes pour instrumenter :
  - les appels API EurIA / Claude / Ollama
  - le traitement d'articles (NER, sentiment, résumés)
  - les endpoints Flask (durée et statut HTTP)
  - les flux RSS et sources web

Usage (instrumentation Flask) :
    from utils.metrics import record_http_request, record_http_request_duration
    from flask import Flask, request, g
    import time

    app = Flask(__name__)

    @app.before_request
    def _start_timer():
        g._metrics_start = time.perf_counter()

    @app.after_request
    def _record_metrics(response):
        elapsed = time.perf_counter() - g.get("_metrics_start", time.perf_counter())
        record_http_request(request.method, request.endpoint or "unknown", response.status_code)
        record_http_request_duration(request.method, request.endpoint or "unknown", elapsed)
        return response

Usage (instrumentation API IA) :
    from utils.metrics import record_ai_call

    try:
        result = client.ask(prompt)
        record_ai_call(provider="euria", operation="summary", status="success")
    except Exception:
        record_ai_call(provider="euria", operation="summary", status="error")

Endpoint Prometheus :
    GET /metrics  →  texte au format Exposition Prometheus
"""

from __future__ import annotations

try:
    from prometheus_client import (
        REGISTRY,
        Counter,
        Gauge,
        Histogram,
        generate_latest,
        CONTENT_TYPE_LATEST,
    )
    _PROMETHEUS_AVAILABLE = True
except ImportError:  # pragma: no cover
    _PROMETHEUS_AVAILABLE = False


# ─────────────────────────────────────────────────────────────────────────────
# Compteurs et histogrammes (singletons — créés une seule fois)
# ─────────────────────────────────────────────────────────────────────────────

def _make_counter(name: str, documentation: str, labelnames: list[str]) -> "Counter | None":
    if not _PROMETHEUS_AVAILABLE:
        return None  # pragma: no cover
    return Counter(name, documentation, labelnames)


def _make_histogram(
    name: str,
    documentation: str,
    labelnames: list[str],
    buckets: tuple[float, ...] | None = None,
) -> "Histogram | None":
    if not _PROMETHEUS_AVAILABLE:
        return None  # pragma: no cover
    kwargs: dict = {}
    if buckets is not None:
        kwargs["buckets"] = buckets
    return Histogram(name, documentation, labelnames, **kwargs)


def _make_gauge(name: str, documentation: str, labelnames: list[str]) -> "Gauge | None":
    if not _PROMETHEUS_AVAILABLE:
        return None  # pragma: no cover
    return Gauge(name, documentation, labelnames)


# ── Appels IA (EurIA / Claude / Ollama) ───────────────────────────────────────
AI_CALLS_TOTAL = _make_counter(
    "wudd_ai_calls_total",
    "Nombre total d'appels aux fournisseurs IA (par provider, opération et statut).",
    ["provider", "operation", "status"],
)

AI_CALL_DURATION_SECONDS = _make_histogram(
    "wudd_ai_call_duration_seconds",
    "Durée des appels IA en secondes.",
    ["provider", "operation"],
    buckets=(0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0),
)

AI_TOKENS_TOTAL = _make_counter(
    "wudd_ai_tokens_total",
    "Tokens consommés par les appels IA (quand disponible).",
    ["provider", "operation", "token_type"],
)

# ── Articles traités ──────────────────────────────────────────────────────────
ARTICLES_PROCESSED_TOTAL = _make_counter(
    "wudd_articles_processed_total",
    "Nombre total d'articles traités (par flux et opération).",
    ["flux", "operation", "status"],
)

ARTICLES_DEDUPLICATED_TOTAL = _make_counter(
    "wudd_articles_deduplicated_total",
    "Nombre total d'articles dédupliqués (ignorés car doublons).",
    ["flux", "reason"],
)

# ── Quota ─────────────────────────────────────────────────────────────────────
QUOTA_EXHAUSTED_TOTAL = _make_counter(
    "wudd_quota_exhausted_total",
    "Nombre de fois où une limite de quota a bloqué le traitement.",
    ["quota_type"],
)

QUOTA_USAGE_RATIO = _make_gauge(
    "wudd_quota_usage_ratio",
    "Ratio d'utilisation du quota global (0-1). Mis à jour après chaque article.",
    [],  # Sans label — accès direct via .set() / ._value.get()
) if _PROMETHEUS_AVAILABLE else None

# ── Endpoints Flask (HTTP) ────────────────────────────────────────────────────
HTTP_REQUESTS_TOTAL = _make_counter(
    "wudd_http_requests_total",
    "Nombre total de requêtes HTTP reçues par le viewer Flask.",
    ["method", "endpoint", "http_status"],
)

HTTP_REQUEST_DURATION_SECONDS = _make_histogram(
    "wudd_http_request_duration_seconds",
    "Durée des requêtes HTTP Flask en secondes.",
    ["method", "endpoint"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)

# ── Cache ─────────────────────────────────────────────────────────────────────
CACHE_HITS_TOTAL = _make_counter(
    "wudd_cache_hits_total",
    "Nombre de hits du cache API (réponse servie depuis le cache).",
    ["namespace"],
)

CACHE_MISSES_TOTAL = _make_counter(
    "wudd_cache_misses_total",
    "Nombre de misses du cache API (appel réseau nécessaire).",
    ["namespace"],
)

# ── Index ─────────────────────────────────────────────────────────────────────
INDEX_REBUILD_TOTAL = _make_counter(
    "wudd_index_rebuild_total",
    "Nombre de reconstructions des indexes (article_index, entity_index).",
    ["index_type", "trigger"],
)

INDEX_SIZE = _make_gauge(
    "wudd_index_size",
    "Nombre d'entrées dans un index donné.",
    ["index_type"],
)


# ─────────────────────────────────────────────────────────────────────────────
# Fonctions d'instrumentation publiques (avec no-op si prometheus absent)
# ─────────────────────────────────────────────────────────────────────────────

def record_ai_call(
    provider: str,
    operation: str,
    status: str = "success",
    duration: float | None = None,
    tokens_prompt: int | None = None,
    tokens_completion: int | None = None,
) -> None:
    """Enregistre un appel IA.

    Args:
        provider:    "euria" | "claude" | "ollama"
        operation:   "summary" | "entities" | "sentiment" | "report" | "synthesis"
        status:      "success" | "error" | "circuit_open" | "cache_hit"
        duration:    Durée de l'appel en secondes (optionnel)
        tokens_prompt: Tokens d'entrée (optionnel, si le provider l'expose)
        tokens_completion: Tokens de sortie (optionnel)
    """
    if not _PROMETHEUS_AVAILABLE:
        return  # pragma: no cover
    AI_CALLS_TOTAL.labels(provider=provider, operation=operation, status=status).inc()
    if duration is not None and duration >= 0:
        AI_CALL_DURATION_SECONDS.labels(provider=provider, operation=operation).observe(duration)
    if tokens_prompt is not None:
        AI_TOKENS_TOTAL.labels(provider=provider, operation=operation, token_type="prompt").inc(tokens_prompt)
    if tokens_completion is not None:
        AI_TOKENS_TOTAL.labels(
            provider=provider, operation=operation, token_type="completion"
        ).inc(tokens_completion)


def record_article_processed(flux: str, operation: str, status: str = "success") -> None:
    """Enregistre le traitement d'un article.

    Args:
        flux:      Nom du flux (ex : "Intelligence-artificielle")
        operation: "summary" | "ner" | "sentiment" | "images"
        status:    "success" | "error" | "skipped"
    """
    if not _PROMETHEUS_AVAILABLE:
        return  # pragma: no cover
    ARTICLES_PROCESSED_TOTAL.labels(flux=flux, operation=operation, status=status).inc()


def record_article_deduplicated(flux: str, reason: str = "url") -> None:
    """Enregistre un article ignoré comme doublon.

    Args:
        flux:   Nom du flux
        reason: "url" | "summary_md5" | "jaccard"
    """
    if not _PROMETHEUS_AVAILABLE:
        return  # pragma: no cover
    ARTICLES_DEDUPLICATED_TOTAL.labels(flux=flux, reason=reason).inc()


def record_quota_exhausted(quota_type: str) -> None:
    """Enregistre un blocage par quota.

    Args:
        quota_type: "global" | "keyword" | "source" | "entity"
    """
    if not _PROMETHEUS_AVAILABLE:
        return  # pragma: no cover
    QUOTA_EXHAUSTED_TOTAL.labels(quota_type=quota_type).inc()


def update_quota_usage_ratio(ratio: float) -> None:
    """Met à jour le gauge du ratio d'utilisation global du quota (0.0 – 1.0)."""
    if not _PROMETHEUS_AVAILABLE or QUOTA_USAGE_RATIO is None:
        return  # pragma: no cover
    QUOTA_USAGE_RATIO.set(max(0.0, min(1.0, ratio)))


def record_http_request(method: str, endpoint: str, status_code: int) -> None:
    """Enregistre une requête HTTP Flask reçue."""
    if not _PROMETHEUS_AVAILABLE:
        return  # pragma: no cover
    HTTP_REQUESTS_TOTAL.labels(
        method=method, endpoint=endpoint, http_status=str(status_code)
    ).inc()


def record_http_request_duration(method: str, endpoint: str, duration: float) -> None:
    """Enregistre la durée d'une requête HTTP Flask."""
    if not _PROMETHEUS_AVAILABLE:
        return  # pragma: no cover
    HTTP_REQUEST_DURATION_SECONDS.labels(method=method, endpoint=endpoint).observe(duration)


def record_cache_hit(namespace: str = "default") -> None:
    """Enregistre un hit de cache API."""
    if not _PROMETHEUS_AVAILABLE:
        return  # pragma: no cover
    CACHE_HITS_TOTAL.labels(namespace=namespace).inc()


def record_cache_miss(namespace: str = "default") -> None:
    """Enregistre un miss de cache API."""
    if not _PROMETHEUS_AVAILABLE:
        return  # pragma: no cover
    CACHE_MISSES_TOTAL.labels(namespace=namespace).inc()


def record_index_rebuild(index_type: str, trigger: str = "manual") -> None:
    """Enregistre une reconstruction d'index.

    Args:
        index_type: "article" | "entity"
        trigger:    "startup" | "manual" | "stale" | "forced"
    """
    if not _PROMETHEUS_AVAILABLE:
        return  # pragma: no cover
    INDEX_REBUILD_TOTAL.labels(index_type=index_type, trigger=trigger).inc()


def update_index_size(index_type: str, size: int) -> None:
    """Met à jour le gauge de taille d'un index."""
    if not _PROMETHEUS_AVAILABLE:
        return  # pragma: no cover
    INDEX_SIZE.labels(index_type=index_type).set(size)


# ─────────────────────────────────────────────────────────────────────────────
# Exposition Flask (endpoint /metrics)
# ─────────────────────────────────────────────────────────────────────────────

def register_metrics_endpoint(app) -> None:
    """Enregistre l'endpoint /metrics dans l'application Flask donnée.

    À appeler une seule fois dans viewer/app.py :
        from utils.metrics import register_metrics_endpoint
        register_metrics_endpoint(app)

    Le endpoint expose toutes les métriques WUDD.ai au format Prometheus texte
    (compatible Prometheus + Grafana + Netdata).

    Sécurité : aucune authentification par défaut. Pour exposer uniquement sur
    l'interface locale, configurer un reverse-proxy (nginx) ou restreindre
    l'accès par IP au niveau réseau.
    """
    if not _PROMETHEUS_AVAILABLE:  # pragma: no cover
        import logging as _logging
        _logging.getLogger(__name__).warning(
            "prometheus_client non disponible — endpoint /metrics désactivé. "
            "Installez-le via : pip install prometheus_client"
        )
        return

    from flask import Response

    @app.route("/metrics")
    def prometheus_metrics():
        """Endpoint Prometheus — format texte exposition v0.0.4."""
        return Response(
            generate_latest(REGISTRY),
            status=200,
            mimetype=CONTENT_TYPE_LATEST,
        )


def register_flask_instrumentation(app) -> None:
    """Ajoute des hooks before/after_request pour mesurer durée et statut HTTP.

    À appeler une seule fois après register_metrics_endpoint(app).

    À NE PAS appeler pendant les tests (risque de compteurs résiduels inter-tests).
    Utiliser la variable d'environnement WUDD_SKIP_METRICS=1 pour désactiver.
    """
    import os as _os

    if not _PROMETHEUS_AVAILABLE or _os.getenv("WUDD_SKIP_METRICS") == "1":
        return  # pragma: no cover

    import time as _time
    from flask import g as _g, request as _request

    @app.before_request
    def _start_timer():
        _g._metrics_t0 = _time.perf_counter()

    @app.after_request
    def _record_response(response):
        elapsed = _time.perf_counter() - _g.get("_metrics_t0", _time.perf_counter())
        endpoint = _request.endpoint or "unknown"
        record_http_request(_request.method, endpoint, response.status_code)
        record_http_request_duration(_request.method, endpoint, elapsed)
        return response
