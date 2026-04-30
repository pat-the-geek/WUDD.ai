"""
utils/openapi.py — Génération automatique de spec OpenAPI 3.0 pour WUDD.ai

Génère une spec OpenAPI 3.0 complète en introspectant les routes enregistrées
dans l'application Flask, avec enrichissement manuel des descriptions, paramètres
et exemples de réponse pour les endpoints critiques.

Usage dans viewer/app.py :
    from utils.openapi import register_openapi_endpoints
    register_openapi_endpoints(app)

Endpoints exposés :
    GET /api/openapi.json  — Spec OpenAPI 3.0 JSON (machine-readable)
    GET /api/docs          — Swagger UI (interface interactive)
"""

from __future__ import annotations

import re
from typing import Any

# ─────────────────────────────────────────────────────────────────────────────
# Métadonnées enrichies par endpoint (description, paramètres, exemples)
# ─────────────────────────────────────────────────────────────────────────────

_ROUTE_META: dict[str, dict[str, Any]] = {
    # ── Runtime ───────────────────────────────────────────────────────────────
    "GET /api/runtime-info": {
        "summary": "Informations de runtime",
        "description": "Retourne le port actif du viewer, la racine du projet et les paramètres d'exécution courants.",
        "tags": ["Système"],
        "response_200": {
            "viewer_port": 5050,
            "project_root": "/home/user/WUDD.ai",
        },
    },
    "GET /metrics": {
        "summary": "Métriques Prometheus",
        "description": "Exposition des métriques WUDD.ai au format texte Prometheus (v0.0.4). Compatible Grafana, Netdata, Prometheus scrape.",
        "tags": ["Système"],
        "produces": "text/plain",
    },
    # ── Fichiers ──────────────────────────────────────────────────────────────
    "GET /api/files": {
        "summary": "Liste des fichiers",
        "description": "Retourne la liste des fichiers JSON et Markdown disponibles dans data/ et rapports/.",
        "tags": ["Fichiers"],
        "response_200": [
            {"name": "articles_2026-01.json", "path": "data/articles/IA/articles_2026-01-01_2026-01-31.json", "type": "json"}
        ],
    },
    "GET /api/content": {
        "summary": "Contenu d'un fichier",
        "description": "Retourne le contenu JSON ou texte d'un fichier. Le chemin doit être relatif à la racine du projet. Protection contre la traversée de répertoire.",
        "tags": ["Fichiers"],
        "params": [{"name": "path", "in": "query", "required": True, "description": "Chemin relatif du fichier", "schema": {"type": "string"}}],
    },
    "GET /api/download": {
        "summary": "Télécharger un fichier",
        "description": "Télécharge un fichier sous forme d'attachement. Le chemin doit être relatif et sécurisé.",
        "tags": ["Fichiers"],
        "params": [{"name": "path", "in": "query", "required": True, "schema": {"type": "string"}}],
    },
    "DELETE /api/files": {
        "summary": "Supprimer un fichier",
        "description": "Supprime un fichier dans data/ ou rapports/. Requiert un body JSON avec le champ `path`.",
        "tags": ["Fichiers"],
        "request_body": {"path": "data/articles/IA/fichier.json"},
    },
    "GET /api/search": {
        "summary": "Recherche plein texte",
        "description": "Recherche dans le contenu des fichiers JSON et Markdown.",
        "tags": ["Fichiers"],
        "params": [{"name": "q", "in": "query", "required": True, "schema": {"type": "string"}}],
        "response_200": {"results": [{"file": "...", "line": 42, "excerpt": "..."}]},
    },
    # ── Quota ─────────────────────────────────────────────────────────────────
    "GET /api/quota/config": {
        "summary": "Configuration du quota",
        "description": "Retourne la configuration courante des quotas journaliers (global, par-keyword, par-source, par-entité).",
        "tags": ["Quota"],
        "response_200": {
            "enabled": True,
            "global_daily_limit": 500,
            "per_keyword_daily_limit": 50,
            "per_source_daily_limit": 10,
            "per_entity_daily_limit": 10,
        },
    },
    "POST /api/quota/config": {
        "summary": "Mettre à jour la configuration du quota",
        "description": "Met à jour un ou plusieurs paramètres de quota. Les champs non fournis conservent leur valeur.",
        "tags": ["Quota"],
        "request_body": {"global_daily_limit": 600},
    },
    "GET /api/quota/stats": {
        "summary": "Statistiques d'utilisation du quota",
        "description": "Retourne l'utilisation courante des quotas journaliers.",
        "tags": ["Quota"],
        "response_200": {
            "global": {"count": 123, "limit": 500},
            "keywords": {"Intelligence-artificielle": {"count": 45, "limit": 50}},
        },
    },
    "POST /api/quota/reset": {
        "summary": "Réinitialiser les compteurs de quota",
        "description": "Remet à zéro tous les compteurs de quota (comme un reset en début de journée).",
        "tags": ["Quota"],
    },
    # ── Entités ───────────────────────────────────────────────────────────────
    "GET /api/entities/dashboard": {
        "summary": "Tableau de bord des entités nommées",
        "description": "Statistiques agrégées des entités (PERSON, ORG, GPE, PRODUCT…) cross-flux. Résultat mis en cache 1h.",
        "tags": ["Entités"],
    },
    "POST /api/entities/dashboard/invalidate": {
        "summary": "Invalider le cache du dashboard entités",
        "description": "Force la reconstruction du dashboard entités au prochain appel.",
        "tags": ["Entités"],
    },
    "GET /api/entities/timeline": {
        "summary": "Timeline des entités",
        "description": "Série chronologique des mentions d'entités. Source : data/entity_timeline.json.",
        "tags": ["Entités"],
    },
    "GET /api/entities/search": {
        "summary": "Rechercher une entité",
        "description": "Recherche d'entités par nom (partiel ou exact).",
        "tags": ["Entités"],
        "params": [{"name": "q", "in": "query", "required": True, "schema": {"type": "string"}}],
    },
    "GET /api/entities/export": {
        "summary": "Exporter les entités",
        "description": "Export JSON de toutes les entités indexées.",
        "tags": ["Entités"],
    },
    "GET /api/watched-entities": {
        "summary": "Entités surveillées",
        "description": "Retourne la liste des entités sur liste de surveillance.",
        "tags": ["Entités"],
    },
    "POST /api/watched-entities": {
        "summary": "Ajouter une entité surveillée",
        "description": "Ajoute une entité à la liste de surveillance.",
        "tags": ["Entités"],
        "request_body": {"entity": "OpenAI", "type": "ORG"},
    },
    "DELETE /api/watched-entities": {
        "summary": "Supprimer une entité surveillée",
        "description": "Retire une entité de la liste de surveillance.",
        "tags": ["Entités"],
    },
    "GET /api/annotations": {
        "summary": "Annotations manuelles",
        "description": "Retourne les annotations manuelles d'articles.",
        "tags": ["Entités"],
    },
    "POST /api/annotations": {
        "summary": "Créer une annotation",
        "description": "Ajoute une annotation manuelle à un article.",
        "tags": ["Entités"],
        "request_body": {"url": "https://...", "note": "À vérifier", "tags": ["ia", "société"]},
    },
    "DELETE /api/annotations": {
        "summary": "Supprimer une annotation",
        "description": "Supprime une annotation manuelle.",
        "tags": ["Entités"],
    },
    # ── Analytiques ───────────────────────────────────────────────────────────
    "GET /api/alerts": {
        "summary": "Alertes actives",
        "description": "Retourne les alertes détectées par trend_detector.py (data/alertes.json).",
        "tags": ["Analytiques"],
    },
    "GET /api/articles/top": {
        "summary": "Top articles",
        "description": "Articles classés par score de pertinence (ScoringEngine). Top 20 par défaut.",
        "tags": ["Analytiques"],
        "params": [
            {"name": "limit", "in": "query", "required": False, "schema": {"type": "integer", "default": 20}},
        ],
    },
    "GET /api/sources/bias": {
        "summary": "Biais éditoriaux par source",
        "description": "Distribution des tons éditoriaux (positif/négatif/factuel) par source.",
        "tags": ["Analytiques"],
    },
    "GET /api/sources/credibility": {
        "summary": "Crédibilité des sources",
        "description": "Scores de crédibilité (0-100) de toutes les sources configurées.",
        "tags": ["Analytiques"],
    },
    "GET /api/cross-flux": {
        "summary": "Analyse cross-flux",
        "description": "Entités mentionnées dans plusieurs flux distincts. Source : cross_flux_analysis.py.",
        "tags": ["Analytiques"],
    },
    "GET /api/data-quality": {
        "summary": "Rapport qualité des données",
        "description": "Statistiques qualité : articles sans résumé, sans NER, avec erreurs API.",
        "tags": ["Analytiques"],
    },
    # ── Paramètres ────────────────────────────────────────────────────────────
    "GET /api/keywords": {
        "summary": "Liste des mots-clés RSS",
        "description": "Retourne les mots-clés configurés dans keyword-to-search.json.",
        "tags": ["Configuration"],
    },
    "GET /api/ai-providers": {
        "summary": "Fournisseurs IA disponibles",
        "description": "Retourne les providers IA configurés (euria, claude, ollama) et leurs statuts.",
        "tags": ["Configuration"],
    },
    "GET /api/env": {
        "summary": "Variables d'environnement (masquées)",
        "description": "Retourne les variables d'environnement actives. Les secrets (bearer, clés API) sont masqués.",
        "tags": ["Configuration"],
    },
    "GET /api/flux-sources": {
        "summary": "Sources de flux configurées",
        "description": "Retourne le contenu de config/flux_json_sources.json.",
        "tags": ["Configuration"],
    },
    "GET /api/rss-feeds": {
        "summary": "Flux RSS (OPML)",
        "description": "Retourne les feeds RSS du fichier OPML (data/WUDD.opml).",
        "tags": ["Configuration"],
    },
    "GET /api/web-sources": {
        "summary": "Sources web (sitemap)",
        "description": "Retourne la configuration des sources web sans RSS (config/web_sources.json).",
        "tags": ["Configuration"],
    },
    "GET /api/ollama/status": {
        "summary": "Statut Ollama",
        "description": "Vérifie si Ollama est accessible et retourne les modèles disponibles.",
        "tags": ["Configuration"],
    },
}

# Tags avec descriptions
_TAGS = [
    {"name": "Système",       "description": "Endpoints système : runtime, métriques Prometheus, santé."},
    {"name": "Fichiers",      "description": "Navigation, lecture, recherche et suppression de fichiers JSON/Markdown."},
    {"name": "Quota",         "description": "Gestion des quotas journaliers d'appels API IA."},
    {"name": "Entités",       "description": "Entités nommées (NER) : dashboard, timeline, recherche, annotations, surveillance."},
    {"name": "Analytiques",   "description": "Alertes, top articles, biais éditoriaux, qualité des données, analyse cross-flux."},
    {"name": "Configuration", "description": "Mots-clés, sources, fournisseurs IA, variables d'environnement."},
    {"name": "Autres",        "description": "Endpoints divers non classés."},
]


# ─────────────────────────────────────────────────────────────────────────────
# Générateur de spec
# ─────────────────────────────────────────────────────────────────────────────

def _flask_rule_to_openapi_path(rule: str) -> str:
    """Convertit une règle Flask `/api/item/<int:id>` en chemin OpenAPI `/api/item/{id}`."""
    return re.sub(r"<(?:[^:>]+:)?([^>]+)>", r"{\1}", rule)


def _method_object(method: str, rule: str, meta: dict) -> dict:
    """Construit l'objet opération OpenAPI pour une méthode+route."""
    key = f"{method} {rule}"
    m = meta.get(key, {})

    op: dict[str, Any] = {
        "summary": m.get("summary", f"{method} {rule}"),
        "operationId": re.sub(r"[^a-zA-Z0-9]", "_", f"{method}_{rule}").strip("_"),
        "tags": m.get("tags", ["Autres"]),
    }

    if "description" in m:
        op["description"] = m["description"]

    # Paramètres
    params = m.get("params", [])
    if params:
        op["parameters"] = [
            {
                "name": p["name"],
                "in": p.get("in", "query"),
                "required": p.get("required", False),
                "description": p.get("description", ""),
                "schema": p.get("schema", {"type": "string"}),
            }
            for p in params
        ]

    # Request body
    if "request_body" in m:
        op["requestBody"] = {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {"type": "object"},
                    "example": m["request_body"],
                }
            },
        }

    # Responses
    produces = m.get("produces", "application/json")
    responses: dict[str, Any] = {}

    if "response_200" in m:
        responses["200"] = {
            "description": "Succès",
            "content": {
                produces: {
                    "schema": {"type": "object"},
                    "example": m["response_200"],
                }
            },
        }
    else:
        responses["200"] = {"description": "Succès"}

    responses["400"] = {"description": "Paramètre manquant ou invalide"}
    responses["403"] = {"description": "Accès refusé (path traversal, permissions)"}
    responses["404"] = {"description": "Ressource introuvable"}
    responses["500"] = {"description": "Erreur interne du serveur"}

    op["responses"] = responses
    return op


def generate_openapi_spec(app) -> dict:
    """Génère une spec OpenAPI 3.0 complète à partir des routes Flask de `app`.

    Args:
        app: Instance Flask avec tous les blueprints enregistrés.

    Returns:
        Dictionnaire Python représentant la spec OpenAPI 3.0.
    """
    paths: dict[str, Any] = {}
    _SKIP_METHODS = {"HEAD", "OPTIONS"}
    _SKIP_RULES = {"/static/<path:filename>", "/"}

    for rule in app.url_map.iter_rules():
        if rule.rule in _SKIP_RULES:
            continue
        openapi_path = _flask_rule_to_openapi_path(rule.rule)

        if openapi_path not in paths:
            paths[openapi_path] = {}

        methods = {m for m in rule.methods if m not in _SKIP_METHODS}
        for method in sorted(methods):
            paths[openapi_path][method.lower()] = _method_object(
                method, rule.rule, _ROUTE_META
            )

    # Trier les paths pour reproductibilité
    paths = dict(sorted(paths.items()))

    spec: dict[str, Any] = {
        "openapi": "3.0.3",
        "info": {
            "title": "WUDD.ai Viewer API",
            "description": (
                "API REST du viewer local WUDD.ai — navigation de fichiers, "
                "entités nommées, analytiques, quota et configuration.\n\n"
                "**Base URL :** `http://localhost:5050`\n\n"
                "**Auth :** Aucune authentification requise (accès local uniquement). "
                "Pour exposer publiquement, configurer un reverse-proxy avec authentification."
            ),
            "version": "2.4.0",
            "contact": {
                "name": "Patrick Ostertag",
                "email": "patrick.ostertag@gmail.com",
            },
            "license": {
                "name": "MIT",
                "url": "https://opensource.org/licenses/MIT",
            },
        },
        "servers": [
            {"url": "http://localhost:5050", "description": "Développement local"},
            {"url": "http://localhost:5173", "description": "Dev server Vite (frontend)"},
        ],
        "tags": _TAGS,
        "paths": paths,
        "components": {
            "schemas": {
                "Article": {
                    "type": "object",
                    "description": "Article avec résumé IA et métadonnées.",
                    "properties": {
                        "Date de publication": {"type": "string", "example": "23/01/2025"},
                        "Sources": {"type": "string", "example": "Le Monde"},
                        "URL": {"type": "string", "format": "uri"},
                        "Résumé": {"type": "string", "description": "Résumé IA en français (max 20 lignes)"},
                        "Images": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "URL": {"type": "string", "format": "uri"},
                                    "Width": {"type": "integer"},
                                },
                            },
                        },
                        "entities": {
                            "type": "object",
                            "description": "Entités nommées (NER) par type.",
                            "example": {
                                "PERSON": ["Emmanuel Macron"],
                                "ORG": ["OpenAI"],
                                "GPE": ["France"],
                            },
                        },
                        "sentiment": {"type": "string", "enum": ["positif", "négatif", "neutre"]},
                        "score_sentiment": {"type": "integer", "minimum": 1, "maximum": 5},
                    },
                },
                "ErrorResponse": {
                    "type": "object",
                    "properties": {
                        "error": {"type": "string", "example": "Paramètre 'path' manquant"},
                    },
                },
            }
        },
        "externalDocs": {
            "description": "Documentation complète WUDD.ai",
            "url": "https://github.com/wudd-ai/wudd.ai/tree/main/docs",
        },
    }
    return spec


# ─────────────────────────────────────────────────────────────────────────────
# Swagger UI HTML (CDN)
# ─────────────────────────────────────────────────────────────────────────────

_SWAGGER_UI_HTML = """\
<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>WUDD.ai — API Docs</title>
  <link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css" />
  <style>
    body {{ margin: 0; }}
    .topbar {{ display: none; }}
  </style>
</head>
<body>
  <div id="swagger-ui"></div>
  <script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
  <script>
    window.onload = () => {{
      SwaggerUIBundle({{
        url: "/api/openapi.json",
        dom_id: "#swagger-ui",
        presets: [SwaggerUIBundle.presets.apis, SwaggerUIBundle.SwaggerUIStandalonePreset],
        layout: "StandaloneLayout",
        deepLinking: true,
        tryItOutEnabled: true,
      }});
    }};
  </script>
</body>
</html>
"""


# ─────────────────────────────────────────────────────────────────────────────
# Enregistrement dans Flask
# ─────────────────────────────────────────────────────────────────────────────

def register_openapi_endpoints(app) -> None:
    """Enregistre les endpoints /api/openapi.json et /api/docs dans l'app Flask.

    À appeler une seule fois dans viewer/app.py :
        from utils.openapi import register_openapi_endpoints
        register_openapi_endpoints(app)

    Endpoints créés :
        GET /api/openapi.json  — Spec OpenAPI 3.0 (JSON)
        GET /api/docs          — Interface Swagger UI (CDN)
    """
    import json as _json
    from flask import Response, jsonify

    # Cache lazy — généré à la première requête
    _spec_cache: list[dict] = []

    @app.route("/api/openapi.json")
    def openapi_spec():
        """Spec OpenAPI 3.0 de l'API WUDD.ai Viewer."""
        if not _spec_cache:
            _spec_cache.append(generate_openapi_spec(app))
        return jsonify(_spec_cache[0])

    @app.route("/api/docs")
    def swagger_ui():
        """Interface Swagger UI pour explorer l'API WUDD.ai."""
        return Response(_SWAGGER_UI_HTML, status=200, mimetype="text/html")
