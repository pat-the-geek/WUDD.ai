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
from .tools.keywords import (
    tool_add_keyword,
    tool_delete_keyword,
    tool_get_keyword_articles,
    tool_list_keywords,
    tool_update_keyword,
)
from .tools.sources import (
    tool_add_source,
    tool_delete_source,
    tool_list_sources,
    tool_toggle_source,
    tool_update_source,
)
from .tools.watched_entities import (
    tool_get_watched_entity_articles,
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
            "avant une timeline ou un agrégat. Le moteur normalise casse, accents "
            "et apostrophes côté requête, et peut enrichir la requête via "
            "expanded_terms pour certaines abréviations. include_structural=1 "
            "expose aussi les types structurels (DATE, MONEY, ...)."
        ),
    )
    def search_entities(q: str | None = None, include_structural: bool = False) -> dict:
        return tool_search_entities(client, q=q, include_structural=include_structural)

    @server.tool(
        name="get_entity_dashboard",
        description=(
            "Retourne les statistiques NER globales. include_structural=1 ajoute "
            "les types structurels (DATE, MONEY, ...), masqués par défaut. "
            "duckdb_stats expose aussi sentiment_7j comme échantillon documenté "
            "et enrichment_7j comme taux de complétude du pipeline RSS."
        ),
    )
    def get_entity_dashboard(include_structural: bool = False) -> dict:
        return tool_get_entity_dashboard(client, include_structural=include_structural)

    @server.tool(
        name="get_entity_articles",
        description=(
            "Retourne les articles liés à une entité. Supporte les modes strict, "
            "canonical, contains et aggregate, avec all_types pour agréger plusieurs "
            "types NER. compact=1 retire surtout le champ Titre mais conserve les "
            "champs éditoriaux déjà enrichis (sentiment, ton, score_source, "
            "enrichissement_statut). sort_by accepte date, score_source, score_ton "
            "ou relevance."
        ),
    )
    def get_entity_articles(
        type: str | None = None,
        value: str | None = None,
        max_articles: int = 100,
        compact: bool = True,
        sort_by: str = "date",
        match_mode: str | None = None,
        all_types: bool = False,
    ) -> dict:
        return tool_get_entity_articles(
            client,
            entity_type=type,
            value=value,
            max_articles=max_articles,
            compact=compact,
            sort_by=sort_by,
            match_mode=match_mode,
            all_types=all_types,
        )

    @server.tool(
        name="get_entity_timeline",
        description=(
            "Retourne la timeline des mentions d'entités. Le matching peut être strict, "
            "canonical, contains ou aggregate, avec all_types pour une vue cross-type. "
            "include_structural=1 ajoute DATE, MONEY et autres types structurels."
        ),
    )
    def get_entity_timeline(
        days: int = 30,
        top: int = 30,
        entity: str | None = None,
        type: str | None = None,
        match_mode: str | None = None,
        all_types: bool = False,
        include_structural: bool = False,
    ) -> dict:
        return tool_get_entity_timeline(
            client,
            days=days,
            top=top,
            entity=entity,
            entity_type=type,
            match_mode=match_mode,
            all_types=all_types,
            include_structural=include_structural,
        )

    @server.tool(
        name="get_entity_cooccurrences",
        description=(
            "Construit le graphe de cooccurrences d'une entité. days filtre les "
            "articles source du graphe, depth=2 active le niveau 2 avec limit_l2, "
            "et total_count représente la couverture corpus du nœud plutôt que le "
            "poids local de l'arête."
        ),
    )
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

    @server.tool(
        name="list_annotations",
        description=(
            "Liste les annotations d'articles, y compris les statuts éditoriaux "
            "et le flag is_hidden lorsqu'ils sont présents."
        ),
    )
    def list_annotations(url: str | None = None) -> dict:
        return tool_list_annotations(client, url=url)

    @server.tool(
        name="create_annotation",
        description=(
            "Crée ou met à jour une annotation. wf_status accepte '', 'À traiter', "
            "'En cours' et 'Archivé'. is_hidden masque l'annotation sans la supprimer."
        ),
    )
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

    @server.tool(
        name="watch_entity",
        description=(
            "Ajoute une entité à la watchlist et vérifie la persistance par relecture "
            "immédiate. La réponse expose persisted=true/false, le nombre de lectures "
            "de vérification et les tentatives POST effectuées."
        ),
    )
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

    @server.tool(
        name="get_watched_entity_articles",
        description=(
            "Retourne les articles du jour (ou d'une date donnée, YYYY-MM-DD, "
            "défaut J-1) mentionnant une entité. Lecture seule : l'entité n'a "
            "pas besoin d'être sur la watchlist. Chaque article inclut un "
            "wudd_article_id stable."
        ),
    )
    def get_watched_entity_articles(
        entity_name: str | None = None,
        date: str | None = None,
        type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict:
        return tool_get_watched_entity_articles(
            client,
            entity_name=entity_name,
            date=date,
            entity_type=type,
            limit=limit,
            offset=offset,
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

    # ── Sources RSS (API v1) ──────────────────────────────────────────────
    @server.tool(
        name="list_sources",
        description=(
            "Liste les sources RSS configurées (WUDD.opml). "
            "include_inactive=true expose aussi les sources désactivées ; "
            "tag filtre par tag exact (insensible à la casse)."
        ),
    )
    def list_sources(
        include_inactive: bool = False,
        tag: str | None = None,
    ) -> dict:
        return tool_list_sources(client, include_inactive=include_inactive, tag=tag)

    @server.tool(
        name="add_source",
        description=(
            "Ajoute une source RSS. url (obligatoire) doit être http(s). Si nom "
            "n'est pas fourni, le titre du flux est récupéré automatiquement. "
            "tags est une liste libre, bypass_quota retire la source du quota."
        ),
    )
    def add_source(
        url: str | None = None,
        nom: str | None = None,
        tags: list[str] | None = None,
        actif: bool | None = None,
        bypass_quota: bool | None = None,
        html_url: str | None = None,
    ) -> dict:
        return tool_add_source(
            client,
            config,
            url=url,
            nom=nom,
            tags=tags,
            actif=actif,
            bypass_quota=bypass_quota,
            html_url=html_url,
        )

    @server.tool(
        name="update_source",
        description=(
            "Met à jour les champs modifiables d'une source RSS (nom, tags, "
            "actif, bypass_quota, html_url). Identifié par source_id."
        ),
    )
    def update_source(
        source_id: str | None = None,
        nom: str | None = None,
        tags: list[str] | None = None,
        actif: bool | None = None,
        bypass_quota: bool | None = None,
        html_url: str | None = None,
    ) -> dict:
        return tool_update_source(
            client,
            config,
            source_id=source_id,
            nom=nom,
            tags=tags,
            actif=actif,
            bypass_quota=bypass_quota,
            html_url=html_url,
        )

    @server.tool(
        name="toggle_source",
        description=(
            "Active ou désactive une source. Si actif n'est pas fourni, "
            "bascule l'état actuel."
        ),
    )
    def toggle_source(
        source_id: str | None = None,
        actif: bool | None = None,
    ) -> dict:
        return tool_toggle_source(client, config, source_id=source_id, actif=actif)

    @server.tool(
        name="delete_source",
        description=(
            "Désactive (soft) une source. hard=true supprime définitivement "
            "l'entrée OPML (irréversible)."
        ),
    )
    def delete_source(source_id: str | None = None, hard: bool = False) -> dict:
        return tool_delete_source(client, config, source_id=source_id, hard=hard)

    # ── Mots-clés thématiques (API v1) ────────────────────────────────────
    @server.tool(
        name="list_keywords",
        description=(
            "Liste les mots-clés thématiques surveillés (filtres sémantiques "
            "multi-mots au-delà du NER). tag filtre par tag exact."
        ),
    )
    def list_keywords(tag: str | None = None) -> dict:
        return tool_list_keywords(client, tag=tag)

    @server.tool(
        name="add_keyword",
        description=(
            "Ajoute un mot-clé surveillé. expression est l'expression à matcher. "
            "ou=synonymes/variantes, et=termes obligatoires de contexte. "
            "tags pour grouper, seuil_alerte=nombre d'occurrences avant alerte."
        ),
    )
    def add_keyword(
        expression: str | None = None,
        tags: list[str] | None = None,
        seuil_alerte: int | None = None,
        ou: list[str] | None = None,
        et: list[str] | None = None,
    ) -> dict:
        return tool_add_keyword(
            client,
            config,
            expression=expression,
            tags=tags,
            seuil_alerte=seuil_alerte,
            ou=ou,
            et=et,
        )

    @server.tool(
        name="update_keyword",
        description="Met à jour un mot-clé. Identifié par keyword_id.",
    )
    def update_keyword(
        keyword_id: str | None = None,
        expression: str | None = None,
        tags: list[str] | None = None,
        seuil_alerte: int | None = None,
        ou: list[str] | None = None,
        et: list[str] | None = None,
    ) -> dict:
        return tool_update_keyword(
            client,
            config,
            keyword_id=keyword_id,
            expression=expression,
            tags=tags,
            seuil_alerte=seuil_alerte,
            ou=ou,
            et=et,
        )

    @server.tool(
        name="delete_keyword",
        description="Supprime un mot-clé surveillé.",
    )
    def delete_keyword(keyword_id: str | None = None) -> dict:
        return tool_delete_keyword(client, config, keyword_id=keyword_id)

    @server.tool(
        name="get_keyword_articles",
        description=(
            "Retourne les articles matchés par un mot-clé. days=N restreint à "
            "la fenêtre temporelle des N derniers jours."
        ),
    )
    def get_keyword_articles(
        keyword_id: str | None = None,
        days: int | None = None,
    ) -> dict:
        return tool_get_keyword_articles(client, keyword_id=keyword_id, days=days)
