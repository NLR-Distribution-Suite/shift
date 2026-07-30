"""Routing strategies for distribution network graph construction.

This module provides pluggable routing algorithms that determine how
terminal nodes (substations, transformers, loads) are connected through
a candidate graph (e.g., road network or mesh grid).

References
----------
- Steiner tree: Current SHIFT default (Mehlhorn approximation)
- Weighted Steiner: Distance-based weights per Ali et al. 2023, Caetano et al. 2026
- Shortest-path tree: Full road graph routing per Ali et al. 2023
- MST: Minimum spanning tree over terminals
- Cost-optimized: MILP formulation per Trpovski et al. 2018 (placeholder)
"""

from abc import ABC, abstractmethod
from collections.abc import Callable

import networkx as nx
from networkx.algorithms import approximation as ax

from shift.data_model import GeoLocation
from shift.exceptions import InvalidInputError
from shift.utils.split_network_edges import get_distance_between_points


class RoutingStrategy(ABC):
    """Abstract base class for routing strategies.

    A routing strategy determines how a subset of terminal nodes
    are connected through a candidate network graph, producing a
    tree subgraph that connects all terminals.
    """

    @abstractmethod
    def route(self, graph: nx.Graph, terminal_nodes: list[str]) -> nx.Graph:
        """Connect terminal nodes through the candidate graph.

        Parameters
        ----------
        graph : nx.Graph
            Candidate network graph with node attributes 'x' and 'y'
            representing longitude and latitude respectively.
        terminal_nodes : list[str]
            List of node names that must be connected in the result.

        Returns
        -------
        nx.Graph
            A connected subgraph (tree) containing all terminal nodes.
        """


def _geodesic_weight(graph: nx.Graph, u: str, v: str) -> float:
    """Default weight function using geodesic distance between nodes."""
    from_point = GeoLocation(graph.nodes[u]["x"], graph.nodes[u]["y"])
    to_point = GeoLocation(graph.nodes[v]["x"], graph.nodes[v]["y"])
    return get_distance_between_points(from_point, to_point).to("m").magnitude


def _segments_intersect(ax, ay, bx, by, cx, cy, dx, dy) -> bool:
    """Check if line segment AB intersects segment CD (proper crossing only)."""

    def _cross(ox, oy, px, py, qx, qy):
        return (px - ox) * (qy - oy) - (py - oy) * (qx - ox)

    d1 = _cross(cx, cy, dx, dy, ax, ay)
    d2 = _cross(cx, cy, dx, dy, bx, by)
    d3 = _cross(ax, ay, bx, by, cx, cy)
    d4 = _cross(ax, ay, bx, by, dx, dy)

    if ((d1 > 0 and d2 < 0) or (d1 < 0 and d2 > 0)) and (
        (d3 > 0 and d4 < 0) or (d3 < 0 and d4 > 0)
    ):
        return True
    return False


class SteinerTreeStrategy(RoutingStrategy):
    """Steiner tree with uniform edge weights (current default behavior).

    Produces the Steiner tree approximation using the Mehlhorn method
    with all edges weighted equally at 1. This preserves the original
    SHIFT behavior for backward compatibility.
    """

    def route(self, graph: nx.Graph, terminal_nodes: list[str]) -> nx.Graph:
        nx.set_edge_attributes(graph, 1, "weight")
        return ax.steiner_tree(graph, terminal_nodes, method="mehlhorn")


class WeightedSteinerTreeStrategy(RoutingStrategy):
    """Steiner tree with distance-based edge weights and optional crossing penalty.

    Uses geodesic distance as edge weights for the Steiner tree approximation.
    Optionally penalizes edges that would cross other edges in the graph,
    encouraging non-crossing topologies.

    Parameters
    ----------
    weight_fn : Callable[[nx.Graph, str, str], float], optional
        Custom weight function. Defaults to geodesic distance in meters.
    crossing_penalty : float, optional
        Multiplicative penalty applied for each crossing detected.
        Default 1.0 (no penalty). Values > 1 discourage crossings.
        Typical values: 2.0–5.0 for moderate penalty.

    References
    ----------
    - Ali et al. 2023: distance-based power line routing
    - Caetano et al. 2026: distance-zone weighting concept
    """

    def __init__(
        self,
        weight_fn: Callable[[nx.Graph, str, str], float] | None = None,
        crossing_penalty: float = 1.0,
    ):
        self.weight_fn = weight_fn or _geodesic_weight
        self.crossing_penalty = crossing_penalty

    def route(self, graph: nx.Graph, terminal_nodes: list[str]) -> nx.Graph:
        if isinstance(graph, (nx.MultiGraph, nx.MultiDiGraph)):
            graph = nx.Graph(graph)

        # Pre-compute all edge segments for crossing detection
        edge_segments = []
        if self.crossing_penalty > 1.0:
            for u, v in graph.edges():
                ux, uy = graph.nodes[u]["x"], graph.nodes[u]["y"]
                vx, vy = graph.nodes[v]["x"], graph.nodes[v]["y"]
                edge_segments.append((ux, uy, vx, vy))

        for u, v in graph.edges():
            base_weight = self.weight_fn(graph, u, v)

            if self.crossing_penalty > 1.0 and edge_segments:
                # Count how many other edges this edge crosses
                ux, uy = graph.nodes[u]["x"], graph.nodes[u]["y"]
                vx, vy = graph.nodes[v]["x"], graph.nodes[v]["y"]
                crossings = sum(
                    1
                    for ax, ay, bx, by in edge_segments
                    if _segments_intersect(ux, uy, vx, vy, ax, ay, bx, by)
                )
                base_weight *= self.crossing_penalty**crossings

            graph[u][v]["weight"] = base_weight

        return ax.steiner_tree(graph, terminal_nodes, weight="weight", method="mehlhorn")


class ShortestPathTreeStrategy(RoutingStrategy):
    """Shortest-path tree from a source node to all other terminals.

    Builds a tree by computing shortest paths (Dijkstra) from the first
    terminal node (typically the source/substation) to all other terminals,
    using geodesic distance as edge weights. The result follows roads
    naturally, producing a star/trunk topology.

    Parameters
    ----------
    weight_fn : Callable[[nx.Graph, str, str], float], optional
        Custom weight function. Defaults to geodesic distance.

    References
    ----------
    - Ali et al. 2023: full road graph routing where power lines = road paths
    """

    def __init__(self, weight_fn: Callable[[nx.Graph, str, str], float] | None = None):
        self.weight_fn = weight_fn or _geodesic_weight

    def route(self, graph: nx.Graph, terminal_nodes: list[str]) -> nx.Graph:
        if isinstance(graph, (nx.MultiGraph, nx.MultiDiGraph)):
            graph = nx.Graph(graph)
        for u, v in graph.edges():
            graph[u][v]["weight"] = self.weight_fn(graph, u, v)

        source = terminal_nodes[0]
        tree = nx.Graph()

        for target in terminal_nodes[1:]:
            path = nx.shortest_path(graph, source, target, weight="weight")
            for i in range(len(path) - 1):
                u, v = path[i], path[i + 1]
                if not tree.has_node(u):
                    tree.add_node(u, **graph.nodes[u])
                if not tree.has_node(v):
                    tree.add_node(v, **graph.nodes[v])
                if not tree.has_edge(u, v):
                    tree.add_edge(u, v, **graph[u][v])

        # Ensure source node is present even if terminal_nodes has only one entry
        if not tree.has_node(source):
            tree.add_node(source, **graph.nodes[source])

        return tree


class MinimumSpanningTreeStrategy(RoutingStrategy):
    """Minimum spanning tree over terminal nodes using shortest-path distances.

    Computes pairwise shortest-path distances between all terminals in the
    candidate graph, builds a complete distance graph, finds its MST, then
    maps each MST edge back to the actual shortest path in the original graph.
    Produces realistic trunk-branch topology.

    Parameters
    ----------
    weight_fn : Callable[[nx.Graph, str, str], float], optional
        Custom weight function for the candidate graph edges.
        Defaults to geodesic distance.
    """

    def __init__(self, weight_fn: Callable[[nx.Graph, str, str], float] | None = None):
        self.weight_fn = weight_fn or _geodesic_weight

    def route(self, graph: nx.Graph, terminal_nodes: list[str]) -> nx.Graph:  # noqa: C901
        if isinstance(graph, (nx.MultiGraph, nx.MultiDiGraph)):
            graph = nx.Graph(graph)
        for u, v in graph.edges():
            graph[u][v]["weight"] = self.weight_fn(graph, u, v)

        # Compute pairwise shortest paths between terminals
        paths: dict[tuple[str, str], list[str]] = {}
        distances: dict[tuple[str, str], float] = {}
        for i, src in enumerate(terminal_nodes):
            sp_lengths, sp_paths = nx.single_source_dijkstra(graph, src, weight="weight")
            for dst in terminal_nodes[i + 1 :]:
                paths[(src, dst)] = sp_paths[dst]
                distances[(src, dst)] = sp_lengths[dst]

        # Build complete graph over terminals with shortest-path distances
        complete = nx.Graph()
        for (src, dst), dist in distances.items():
            complete.add_edge(src, dst, weight=dist)

        # Find MST of complete graph
        mst = nx.minimum_spanning_tree(complete, weight="weight")

        # Map MST edges back to actual paths
        tree = nx.Graph()
        for u, v in mst.edges():
            key = (u, v) if (u, v) in paths else (v, u)
            path = paths[key]
            for i in range(len(path) - 1):
                a, b = path[i], path[i + 1]
                if not tree.has_node(a):
                    tree.add_node(a, **graph.nodes[a])
                if not tree.has_node(b):
                    tree.add_node(b, **graph.nodes[b])
                if not tree.has_edge(a, b):
                    tree.add_edge(a, b, **graph[a][b])

        return tree


class FullRoadGraphStrategy(RoutingStrategy):
    """Uses the road network graph directly without reduction.

    Instead of computing a Steiner tree or MST, this strategy returns
    the full candidate graph (typically the road network) as-is. The
    assumption is that power lines follow road paths directly.

    The resulting graph is pruned to only include nodes reachable from
    the first terminal (connected component), ensuring connectivity.

    References
    ----------
    - Ali et al. 2023: "power lines follow road paths" — road network
      = power line topology directly
    """

    def route(self, graph: nx.Graph, terminal_nodes: list[str]) -> nx.Graph:
        if not terminal_nodes:
            raise InvalidInputError("terminal_nodes cannot be empty.")

        missing = [node for node in terminal_nodes if node not in graph]
        if missing:
            raise InvalidInputError(f"terminal nodes not found in graph: {missing}")

        # Ensure we return the connected component containing all terminals.
        source = terminal_nodes[0]
        component_nodes = nx.node_connected_component(graph, source)
        missing_terminals = [node for node in terminal_nodes if node not in component_nodes]
        if missing_terminals:
            raise InvalidInputError(
                "not all terminal nodes are connected to source terminal "
                f"{source}. Missing terminals: {missing_terminals}"
            )
        return graph.subgraph(component_nodes).copy()


class CostOptimizedStrategy(RoutingStrategy):
    """Cost-optimized routing via MILP (placeholder).

        Based on the formulation by Trpovski et al. 2018, this strategy
        conceptually uses binary edge-decision variables to minimize
        investment and operating costs under radiality and power-flow
        constraints.

    This is a placeholder that documents the interface. Full implementation
    requires an external MILP solver (e.g., PuLP, scipy.optimize, or Pyomo).

    References
    ----------
    - Trpovski, Recalde, Hamacher. "Synthetic Distribution Grid Generation
      Using Power System Planning: Case Study of Singapore." IEEE 2018.
    """

    def route(self, graph: nx.Graph, terminal_nodes: list[str]) -> nx.Graph:
        raise NotImplementedError(
            "CostOptimizedStrategy requires an external MILP solver. "
            "See Trpovski et al. 2018 for the formulation. "
            "Contributions welcome — implement using PuLP or Pyomo."
        )
