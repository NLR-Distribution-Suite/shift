"""Secondary network strategies for distribution graph construction.

This module provides pluggable algorithms for building the secondary
(low-voltage) distribution network that connects individual loads
to their serving transformer.

References
----------
- Mesh + Steiner: Current SHIFT default (rectangular grid + Steiner tree)
- Radial: Direct star connection (most common distribution topology)
- Delaunay: Triangulation-based organic layout
- OpenStreet: Road-aware secondary routing
- Hub-line: k-NN consumer assignment per Ali et al. 2023
"""

from abc import ABC, abstractmethod
import uuid

import networkx as nx
from shapely import MultiPoint, Point
from infrasys.quantities import Distance

from shift.data_model import GroupModel, GeoLocation
from shift.exceptions import EmptyGraphError
from shift.graph.routing import RoutingStrategy, WeightedSteinerTreeStrategy
from shift.utils.mesh_network import get_mesh_network
from shift.utils.nearest_points import get_nearest_points
from shift.utils.split_network_edges import get_distance_between_points


class SecondaryNetworkStrategy(ABC):
    """Abstract base class for secondary network construction strategies.

    A secondary network strategy determines how load points within a
    group (cluster) are connected to their serving transformer location.
    """

    @abstractmethod
    def build(self, group: GroupModel) -> nx.Graph:
        """Build the secondary network for a group of loads.

        Parameters
        ----------
        group : GroupModel
            Group containing load points and a center (transformer location).

        Returns
        -------
        nx.Graph
            A connected graph with node attributes 'x' and 'y'
            representing the secondary network topology.
        """


class MeshSteinerStrategy(SecondaryNetworkStrategy):
    """Rectangular mesh grid + Steiner tree (current default behavior).

    Builds a 2D rectangular grid within the bounding box of the group's
    points, then computes a Steiner tree connecting the nearest grid nodes
    to each load point.

    Parameters
    ----------
    spacing : Distance, optional
        Grid spacing. Defaults to 50 meters.
    """

    def __init__(self, spacing: Distance = Distance(50, "m")):
        self.spacing = spacing

    def build(self, group: GroupModel) -> nx.Graph:
        from networkx.algorithms import approximation as ax

        if len(group.points) == 1:
            sec_graph = nx.Graph()
            node_name = str(uuid.uuid4())
            sec_graph.add_node(node_name, x=group.center[0], y=group.center[1])
            return sec_graph

        minx, miny, maxx, maxy = MultiPoint([Point(*point) for point in group.points]).bounds
        sec_network = get_mesh_network(
            lower_left=GeoLocation(minx, miny),
            upper_right=GeoLocation(maxx, maxy),
            spacing=self.spacing,
        )
        nearest_nodes = _get_nearest_nodes_from_graph(sec_network, group.points)
        if len(set(nearest_nodes)) == 1:
            return nx.Graph(sec_network.subgraph(nearest_nodes))

        nx.set_edge_attributes(sec_network, 1, "weight")
        reduced_network = ax.steiner_tree(sec_network, nearest_nodes, method="mehlhorn")

        if not reduced_network.nodes:
            raise EmptyGraphError("Reduced secondary network is empty.")

        return reduced_network


class RadialStrategy(SecondaryNetworkStrategy):
    """Direct radial (star) connection from transformer to each load.

    Connects each load point directly to the group center (transformer
    location) with a straight-line edge. This is the most common
    topology for residential distribution laterals and eliminates
    the jagged mesh artifacts.

    References
    ----------
    - All papers confirm radial = most common distribution topology
    """

    def build(self, group: GroupModel) -> nx.Graph:
        sec_graph = nx.Graph()
        center_name = str(uuid.uuid4())
        sec_graph.add_node(center_name, x=group.center[0], y=group.center[1])

        if len(group.points) == 1:
            return sec_graph

        for point in group.points:
            node_name = str(uuid.uuid4())
            sec_graph.add_node(node_name, x=point[0], y=point[1])
            sec_graph.add_edge(center_name, node_name)

        return sec_graph


class DelaunayStrategy(SecondaryNetworkStrategy):
    """Delaunay triangulation of load points + MST pruning.

    Builds a Delaunay triangulation of the group points (including the
    center), then prunes it to a minimum spanning tree using geodesic
    distance as edge weights. Produces organic, non-grid layouts.
    """

    def build(self, group: GroupModel) -> nx.Graph:
        from scipy.spatial import Delaunay
        import numpy as np

        if len(group.points) == 1:
            sec_graph = nx.Graph()
            node_name = str(uuid.uuid4())
            sec_graph.add_node(node_name, x=group.center[0], y=group.center[1])
            return sec_graph

        # Collect all points including center
        all_points = [group.center] + list(group.points)
        coords = np.array([[p[0], p[1]] for p in all_points])

        # Need at least 3 non-collinear points for Delaunay
        if len(coords) < 3:
            # Fall back to radial for 2 points
            return RadialStrategy().build(group)

        # Generate node names
        node_names = [str(uuid.uuid4()) for _ in all_points]

        # Build triangulation graph
        try:
            tri = Delaunay(coords)
        except Exception:
            # Collinear points or other degenerate case — fall back to radial
            return RadialStrategy().build(group)

        tri_graph = nx.Graph()
        for i, (name, point) in enumerate(zip(node_names, all_points)):
            tri_graph.add_node(name, x=point[0], y=point[1])

        for simplex in tri.simplices:
            for i in range(3):
                for j in range(i + 1, 3):
                    u, v = node_names[simplex[i]], node_names[simplex[j]]
                    if not tri_graph.has_edge(u, v):
                        weight = (
                            get_distance_between_points(
                                GeoLocation(coords[simplex[i]][0], coords[simplex[i]][1]),
                                GeoLocation(coords[simplex[j]][0], coords[simplex[j]][1]),
                            )
                            .to("m")
                            .magnitude
                        )
                        tri_graph.add_edge(u, v, weight=weight)

        # MST pruning
        mst = nx.minimum_spanning_tree(tri_graph, weight="weight")
        return mst


class OpenStreetSecondaryStrategy(SecondaryNetworkStrategy):
    """Road-aware secondary network using local OpenStreetMap roads.

    Fetches the local road network for the group's bounding area and
    routes the secondary network along actual roads using a configurable
    routing strategy (defaults to weighted Steiner tree).

    Parameters
    ----------
    routing_strategy : RoutingStrategy, optional
        Strategy for routing within the fetched road network.
        Defaults to WeightedSteinerTreeStrategy (geodesic distance).
    buffer : Distance, optional
        Buffer around group bounding box for road fetching.
        Defaults to 50 meters.

    References
    ----------
    - Ali et al. 2023: "power lines follow road paths"
    - Caetano et al. 2026: "distribution networks are usually routed along the streets"
    """

    def __init__(
        self,
        routing_strategy: RoutingStrategy | None = None,
        buffer: Distance = Distance(50, "m"),
    ):
        self.routing_strategy = routing_strategy or WeightedSteinerTreeStrategy()
        self.buffer = buffer

    def build(self, group: GroupModel) -> nx.Graph:
        from shift.openstreet_roads import get_road_network
        from shift.utils.polygon_from_points import get_polygon_from_points
        from shift.utils.split_network_edges import split_network_edges

        if len(group.points) == 1:
            sec_graph = nx.Graph()
            node_name = str(uuid.uuid4())
            sec_graph.add_node(node_name, x=group.center[0], y=group.center[1])
            return sec_graph

        # Fetch local road network for this group's area
        all_points = [group.center] + list(group.points)
        polygon = get_polygon_from_points(all_points, self.buffer)
        road_network = get_road_network(polygon, reduce_to_mst=False)
        road_network = split_network_edges(road_network, split_length=Distance(50, "m"))

        # Find nearest road nodes to each load point and center
        nearest_nodes = _get_nearest_nodes_from_graph(road_network, all_points)

        # Preserve first-seen order for deterministic routing source/targets.
        unique_terminals = list(dict.fromkeys(nearest_nodes))
        if len(unique_terminals) <= 1:
            return nx.Graph(road_network.subgraph(unique_terminals))

        # Route using the configured strategy
        return self.routing_strategy.route(road_network, unique_terminals)


class HubLineStrategy(SecondaryNetworkStrategy):
    """k-nearest-neighbor consumer-to-transformer assignment.

    Based on the hub-line algorithm from Ali et al. 2023. Connects
    each consumer to the transformer (hub) via the shortest road-network
    path, or directly if no road network is provided.

    The hub-line algorithm computes spatial distance:
        d(p, e) = sqrt((px - eix)^2 + (py - eiy)^2)
    and connects the N_f nearest consumers to each hub/transformer.

    This produces a star topology per transformer where consumers are
    assigned based on proximity.

    References
    ----------
    - Ali et al. 2023: Hub-line algorithm for determining number of
      consumers connected to a single transformer (k-nearest neighbor)
    """

    def build(self, group: GroupModel) -> nx.Graph:
        sec_graph = nx.Graph()
        center_name = str(uuid.uuid4())
        sec_graph.add_node(center_name, x=group.center[0], y=group.center[1])

        if len(group.points) == 1:
            return sec_graph

        # Sort points by distance to center (hub-line k-NN concept)
        points_with_dist = []
        for point in group.points:
            dist = (
                get_distance_between_points(
                    GeoLocation(group.center[0], group.center[1]),
                    GeoLocation(point[0], point[1]),
                )
                .to("m")
                .magnitude
            )
            points_with_dist.append((point, dist))

        points_with_dist.sort(key=lambda x: x[1])

        # Connect all points to center (they're already assigned to this group)
        for point, _ in points_with_dist:
            node_name = str(uuid.uuid4())
            sec_graph.add_node(node_name, x=point[0], y=point[1])
            sec_graph.add_edge(center_name, node_name)

        return sec_graph


def _get_nearest_nodes_from_graph(graph: nx.Graph, points: list[GeoLocation]) -> list[str]:
    """Helper to find nearest nodes in a graph to a list of points."""
    if not graph.nodes:
        raise EmptyGraphError("Empty graph provided.")
    graph_nodes_mapper = {
        (data["x"], data["y"]): node for node, data in dict(graph.nodes(data=True)).items()
    }
    nearest = get_nearest_points(list(graph_nodes_mapper.keys()), points)
    return [graph_nodes_mapper[tuple(node)] for node in nearest]
