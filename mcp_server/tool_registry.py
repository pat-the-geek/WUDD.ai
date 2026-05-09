"""Enregistrement des tools MCP WUDD.ai."""

from __future__ import annotations

from fastmcp import FastMCP

from .config import MCPConfig
from .viewer_client import ViewerClient
from .tools.analytics import (
    tool_get_alerts,
    tool_get_cross_flux_analysis,
    tool_get_data_quality,
    tool_get_top_articles,
)
from .tools.annotations import (
    tool_create_annotation,
    tool_delete_annotation,
    tool_list_annotations,
)
from .tools.entities import (
    tool_get_entity_articles,
    tool_get_entity_cooccurrences,
    tool_get_entity_dashboard,
    tool_get_entity_timeline,
    tool_search_entities,
)
from .tools.export import tool_export_dataset
from .tools.files import (
    tool_list_corpus_files,
    tool_read_corpus_file,
    tool_search_corpus,
)
from .tools.health import tool_wudd_health
from .tools.watched_entities import (
    tool_list_watched_entities,
    tool_unwatch_entity,
    tool_watch_entity,
)


def register_tools(server: FastMCP, client: ViewerClient, config: MCPConfig) -> None:
    """Enregistre tous les tools V1 du serveur MCP."""

    @server.tool(name="wudd_health", description="Vérifie la disponibilité du MCP et du Viewer.")
    def wudd_health() -> dict:
        return tool_wudd_health(client, config)

    @server.tool(name="list_corpus_files", description="Liste les fichiers JSON et Markdown exposés.")
    def list_corpus_files(type: str | None = None, limit: int = 100) -> dict:
        return tool_list_corpus_files(client, file_type=type, limit=limit)

    @server.tool(name="read_corpus_file", description="Lit le contenu d'un fichier autorisé du corpus.")
    def read_corpus_file(path: str | None = None) -> dict:
        return tool_read_corpus_file(client, path=path)

    @server.tool(name="search_corpus", description="Recherche plein texte dans le corpus WUDD.ai.")
    def search_corpus(
        q: str | None = None,
        type: str | None = None,
        sentiment: str | None = None,
        source: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> dict:
        return tool_search_corpus(
            client,
            q=q,
            file_type=type,
            sentiment=sentiment,
            source=source,
            date_from=date_from,
            date_to=date_to,
        )

    @server.tool(name="get_alerts", description="Retourne les alertes actives.")
    def get_alerts(niveau: str | None = None, type: str | None = None) -> dict:
        return tool_get_alerts(client, niveau=niveau, alert_type=type)

    @server.tool(name="get_top_articles", description="Retourne les articles les mieux scorés.")
    def get_top_articles(n: int = 10, hours: int = 48) -> dict:
        return tool_get_top_articles(client, n=n, hours=hours)

    @server.tool(name="get_data_quality", description="Retourne le rapport de qualité des données.")
    def get_data_quality(dir: str = "all") -> dict:
        return tool_get_data_quality(client, dir_name=dir)

    @server.tool(name="get_cross_flux_analysis", description="Analyse les entités communes à plusieurs flux.")
    def get_cross_flux_analysis(days: int = 30, min_flux: int = 2, top: int = 30) -> dict:
        return tool_get_cross_flux_analysis(client, days=days, min_flux=min_flux, top=top)

    @server.tool(
        name="search_entities",
        description=(
            "Recherche des entités par nom pour cartographier les variantes disponibles "
            "avant une timeline ou un agrégat. include_structural=1 expose aussi "
            "les types structurels (DATE, MONEY, ...)."
        ),
    )
    def search_entities(q: str | None = None, include_structural: bool = False) -> dict:
        return tool_search_entities(client, q=q, include_structural=include_structural)

    @server.tool(
        name="get_entity_dashboard",
        description=(
            "Retourne les statistiques NER globales. include_structural=1 ajoute "
            "les types structurels (DATE, MONEY, ...), masqués par défaut."
        ),
    )
    def get_entity_dashboard(include_structural: bool = False) -> dict:
        return tool_get_entity_dashboard(client, include_structural=include_structural)

    @server.tool(
        name="get_entity_articles",
        description=(
            "Retourne les articles liés à une entité. Supporte les modes strict, "
            "canonical, contains et aggregate, avec all_types pour agréger plusieurs "
            "types NER."
        ),
    )
    def get_entity_articles(
        type: str | None = None,
        value: str | None = None,
        max_articles: int = 100,
        compact: bool = True,
        match_mode: str | None = None,
        all_types: bool = False,
    ) -> dict:
        return tool_get_entity_articles(
            client,
            entity_type=type,
            value=value,
            max_articles=max_articles,
            compact=compact,
            match_mode=match_mode,
            all_types=all_types,
        )

    @server.tool(
        name="get_entity_timeline",
        description=(
            "Retourne la timeline des mentions d'entités. Le matching peut être strict, "
            "canonical, contains ou aggregate, avec all_types pour une vue cross-type."
        ),
    )
    def get_entity_timeline(
        days: int = 30,
        top: int = 30,
        entity: str | None = None,
        type: str | None = None,
        match_mode: str | None = None,
        all_types: bool = False,
    ) -> dict:
        return tool_get_entity_timeline(
            client,
            days=days,
            top=top,
            entity=entity,
            entity_type=type,
            match_mode=match_mode,
            all_types=all_types,
        )

    @server.tool(name="get_entity_cooccurrences", description="Construit le graphe de cooccurrences d'une entité.")
    def get_entity_cooccurrences(
        type: str | None = None,
        value: str | None = None,
        limit: int = 40,
        depth: int = 1,
        limit_l2: int = 4,
        days: int = 0,
    ) -> dict:
        return tool_get_entity_cooccurrences(
            client,
            entity_type=type,
            value=value,
            limit=limit,
            depth=depth,
            limit_l2=limit_l2,
            days=days,
        )

    @server.tool(name="list_annotations", description="Liste les annotations d'articles.")
    def list_annotations(url: str | None = None) -> dict:
        return tool_list_annotations(client, url=url)

    @server.tool(name="create_annotation", description="Crée ou met à jour une annotation.")
    def create_annotation(
        url: str | None = None,
        is_important: bool | None = None,
        is_read: bool | None = None,
        is_hidden: bool | None = None,
        tags: list[str] | None = None,
        notes: str | None = None,
        wf_status: str | None = None,
    ) -> dict:
        return tool_create_annotation(
            client,
            config,
            url=url,
            is_important=is_important,
            is_read=is_read,
            is_hidden=is_hidden,
            tags=tags,
            notes=notes,
            wf_status=wf_status,
        )

    @server.tool(name="delete_annotation", description="Supprime une annotation.")
    def delete_annotation(url: str | None = None) -> dict:
        return tool_delete_annotation(client, config, url=url)

    @server.tool(name="list_watched_entities", description="Liste les entités surveillées.")
    def list_watched_entities() -> dict:
        return tool_list_watched_entities(client)

    @server.tool(name="watch_entity", description="Ajoute une entité à la watchlist.")
    def watch_entity(
        type: str | None = None,
        value: str | None = None,
        notes: str | None = None,
    ) -> dict:
        return tool_watch_entity(
            client,
            config,
            entity_type=type,
            value=value,
            notes=notes,
        )

    @server.tool(name="unwatch_entity", description="Retire une entité de la watchlist.")
    def unwatch_entity(type: str | None = None, value: str | None = None) -> dict:
        return tool_unwatch_entity(
            client,
            config,
            entity_type=type,
            value=value,
        )

    @server.tool(name="export_dataset", description="Retourne une URL d'export Atom, CSV ou XLSX.")
    def export_dataset(
        format: str | None = None,
        path: str | None = None,
        flux: str | None = None,
        keyword: str | None = None,
        max_entries: int = 50,
    ) -> dict:
        return tool_export_dataset(
            client,
            format=format,
            path=path,
            flux=flux,
            keyword=keyword,
            max_entries=max_entries,
        )
