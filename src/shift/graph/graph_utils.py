"""Graph analysis utilities for distribution network graphs."""

from __future__ import annotations


def compute_graph_metrics(graph) -> dict[str, float | int | bool]:
    """Compute summary metrics for a distribution graph.

    Classifies edges as primary, secondary, or transformer based on the
    network topology (DFS from source through transformer hint nodes).

    Parameters
    ----------
    graph : DistributionGraph
        A built distribution graph instance.

    Returns
    -------
    dict
        Keys include node_count, edge_count, total_length_m,
        transformer_hint_count, load_node_count, is_radial,
        primary_edges, primary_length_m, secondary_edges,
        secondary_length_m, transformer_edges.
    """
    import networkx as _nx

    total_length_m = 0.0
    primary_edges = 0
    secondary_edges = 0
    transformer_edges = 0
    primary_length_m = 0.0
    secondary_length_m = 0.0

    transformers = 0
    loads = 0
    source_nodes = 0
    transformer_nodes = set()

    for node in graph.get_nodes():
        assets = node.assets or set()
        for asset in assets:
            name = getattr(asset, "__name__", str(asset))
            if name == "DistributionLoad":
                loads += 1
            if name == "DistributionVoltageSource":
                source_nodes += 1
        if node.name.endswith("_ht"):
            transformers += 1
            transformer_nodes.add(node.name)

    dfs_tree = graph.get_dfs_tree()
    secondary_node_set = set()
    for tr_node in transformer_nodes:
        descendants = _nx.descendants(dfs_tree, tr_node)
        secondary_node_set.update(descendants)
        secondary_node_set.add(tr_node)

    for from_name, to_name, edge in graph.get_edges():
        length = float(edge.length.to("m").magnitude) if edge.length is not None else 0.0
        total_length_m += length
        edge_type = getattr(edge.edge_type, "__name__", str(edge.edge_type))
        if edge_type == "DistributionTransformer":
            transformer_edges += 1
        elif from_name in secondary_node_set or to_name in secondary_node_set:
            secondary_edges += 1
            secondary_length_m += length
        else:
            primary_edges += 1
            primary_length_m += length

    node_count = len(list(graph.get_nodes()))
    edge_count = len(list(graph.get_edges()))
    is_radial = edge_count == node_count - 1

    return {
        "node_count": node_count,
        "edge_count": edge_count,
        "total_length_m": round(total_length_m, 2),
        "transformer_hint_count": transformers,
        "load_node_count": loads,
        "is_radial": is_radial,
        "primary_edges": primary_edges,
        "primary_length_m": round(primary_length_m, 2),
        "secondary_edges": secondary_edges,
        "secondary_length_m": round(secondary_length_m, 2),
        "transformer_edges": transformer_edges,
    }


def extract_graph_geometry(graph) -> dict[str, list]:
    """Extract node positions and edge segments for map rendering.

    Parameters
    ----------
    graph : DistributionGraph
        A built distribution graph instance.

    Returns
    -------
    dict
        ``{"nodes": [...], "edges": [...]}`` where each node has name,
        location (lon/lat), and asset names, and each edge has from/to
        locations, type, and name.
    """
    node_map: dict[str, dict[str, float]] = {}
    nodes_out: list[dict] = []
    for node in graph.get_nodes():
        loc = {"longitude": node.location.x, "latitude": node.location.y}
        node_map[node.name] = loc
        assets = []
        if node.assets:
            assets = [getattr(a, "__name__", str(a)) for a in node.assets]
        nodes_out.append({"name": node.name, "location": loc, "assets": assets})

    edges_out: list[dict] = []
    for from_name, to_name, edge in graph.get_edges():
        from_loc = node_map.get(from_name)
        to_loc = node_map.get(to_name)
        if from_loc and to_loc:
            edge_type = getattr(edge.edge_type, "__name__", str(edge.edge_type))
            edges_out.append(
                {
                    "from": from_loc,
                    "to": to_loc,
                    "type": edge_type,
                    "name": edge.name,
                }
            )
    return {"nodes": nodes_out, "edges": edges_out}
