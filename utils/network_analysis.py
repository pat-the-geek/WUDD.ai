"""utils/network_analysis.py — Analyse de réseaux de sources/entités avec NetworkX.

Construction du graphe bipartite sources ↔ entités, pondéré par co-mentions,
puis détection de communautés avec l'algorithme de Louvain (python-louvain).

Si python-louvain ou networkx ne sont pas installés, les fonctions dégradent
gracieusement en retournant des structures vides ou un partitionnement trivial.

Dépendances optionnelles :
  pip install networkx python-louvain
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path


def _load_articles(project_root: Path, days: int = 30) -> list[dict]:
    """Charge tous les articles des derniers `days` jours."""
    from utils.date_utils import parse_article_date as parse_date

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    articles: list[dict] = []

    for base_dir in [
        project_root / "data" / "articles",
        project_root / "data" / "articles-from-rss",
    ]:
        if not base_dir.exists():
            continue
        pattern = "*.json" if base_dir.name == "articles-from-rss" else "**/*.json"
        for json_file in base_dir.glob(pattern):
            if "cache" in json_file.parts:
                continue
            try:
                data = json.loads(json_file.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    articles.extend(data)
            except Exception:
                pass

    result = []
    for art in articles:
        raw_date = art.get("Date de publication", "")
        try:
            d = parse_date(raw_date)
            if d.tzinfo is None:
                d = d.replace(tzinfo=timezone.utc)
            if d >= cutoff:
                result.append(art)
        except Exception:
            pass

    return result


def build_source_graph(articles: list[dict]):
    """Construit un graphe non-orienté sources ↔ sources pondéré par
    le nombre d'entités co-mentionnées.

    Retourne un objet networkx.Graph (ou None si networkx non disponible).
    """
    try:
        import networkx as nx
    except ImportError:
        return None

    # Construire le mapping source → set(entités)
    source_entities: dict[str, set[str]] = defaultdict(set)
    for art in articles:
        source = (art.get("Sources") or "").strip()
        if not source:
            continue
        ents = art.get("entities") or {}
        if not isinstance(ents, dict):
            continue
        for etype, vals in ents.items():
            if not isinstance(vals, list):
                continue
            for v in vals:
                if isinstance(v, str) and v.strip():
                    source_entities[source].add(f"{etype}:{v.strip().lower()}")

    sources = list(source_entities.keys())
    G = nx.Graph()
    G.add_nodes_from(sources)

    for i, src_a in enumerate(sources):
        for src_b in sources[i+1:]:
            common = source_entities[src_a] & source_entities[src_b]
            if common:
                G.add_edge(src_a, src_b, weight=len(common))

    return G


def detect_communities(G) -> dict[str, int]:
    """Applique l'algorithme de Louvain sur G.

    Retourne un dict {node_id: community_id}.
    Dégradation gracieuse si python-louvain ou networkx non disponibles.
    """
    if G is None:
        return {}
    try:
        import community as community_louvain  # python-louvain
        partition = community_louvain.best_partition(G, weight="weight")
        return partition
    except ImportError:
        # Dégradation : chaque nœud dans sa propre communauté (id croissant)
        return {node: i for i, node in enumerate(G.nodes())}
    except Exception:
        return {node: 0 for node in G.nodes()}


def find_hubs(G, top_n: int = 10) -> list[dict]:
    """Retourne les top_n nœuds selon leur degré pondéré (betweenness centrality).

    Dégradation gracieuse si networkx non disponible.
    """
    if G is None:
        return []
    try:
        import networkx as nx
    except ImportError:
        return []

    try:
        centrality = nx.betweenness_centrality(G, weight="weight", normalized=True)
    except Exception:
        centrality = {n: G.degree(n) for n in G.nodes()}

    degree = dict(G.degree(weight="weight"))
    sorted_nodes = sorted(centrality, key=lambda n: centrality[n], reverse=True)
    return [
        {
            "id": n,
            "centrality": round(centrality.get(n, 0), 4),
            "degree": degree.get(n, 0),
        }
        for n in sorted_nodes[:top_n]
    ]


def build_influence_report(project_root: Path, days: int = 30) -> dict:
    """Construit le rapport complet d'analyse du réseau d'influence.

    Retourne :
    {
      "generated_at":  "<ISO-8601>",
      "days_window":   30,
      "nodes_count":   N,
      "edges_count":   E,
      "communities":   [{id, label, sources[], size}],
      "hubs":          [{id, centrality, degree, community}],
      "edges":         [{source, target, weight}],    # les 200 plus lourdes
    }
    """
    articles = _load_articles(project_root, days=days)
    G = build_source_graph(articles)

    if G is None or G.number_of_nodes() == 0:
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "days_window": days,
            "nodes_count": 0,
            "edges_count": 0,
            "communities": [],
            "hubs": [],
            "edges": [],
            "error": "networkx non disponible ou aucune donnée" if G is None else "Aucune donnée",
        }

    partition = detect_communities(G)
    hubs_raw = find_hubs(G, top_n=20)

    # Communautés : regrouper les sources par community_id
    community_map: dict[int, list[str]] = defaultdict(list)
    for node, comm_id in partition.items():
        community_map[comm_id].append(node)

    communities_out = []
    for comm_id, members in sorted(community_map.items(), key=lambda x: -len(x[1])):
        communities_out.append({
            "id": comm_id,
            "label": f"Communauté {comm_id + 1}",
            "sources": sorted(members),
            "size": len(members),
        })

    # Enrichir les hubs avec leur communauté
    for hub in hubs_raw:
        hub["community"] = partition.get(hub["id"], -1)

    # Edges (top 200 par poids)
    edges_raw = sorted(
        [{"source": u, "target": v, "weight": d["weight"]} for u, v, d in G.edges(data=True)],
        key=lambda e: -e["weight"],
    )[:200]

    # Nodes avec leur communauté et centralité
    try:
        import networkx as nx
        centrality = nx.betweenness_centrality(G, weight="weight", normalized=True)
    except Exception:
        centrality = {}
    degree_map = dict(G.degree(weight="weight"))
    nodes_out = [
        {
            "id": n,
            "community": partition.get(n, -1),
            "centrality": round(centrality.get(n, 0), 4),
            "degree": degree_map.get(n, 0),
        }
        for n in G.nodes()
    ]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "days_window": days,
        "nodes_count": G.number_of_nodes(),
        "edges_count": G.number_of_edges(),
        "communities": communities_out,
        "hubs": hubs_raw,
        "nodes": nodes_out,
        "edges": edges_raw,
    }
