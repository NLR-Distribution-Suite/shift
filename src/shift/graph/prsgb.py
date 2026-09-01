import uuid
import copy

import networkx as nx
from infrasys.quantities import Distance
from loguru import logger

from shift.data_model import GroupModel, GeoLocation
from shift.graph.openstreet_graph_builder import OpenStreetGraphBuilder
from shift.graph.routing import RoutingStrategy, FullRoadGraphStrategy
from shift.graph.secondary import SecondaryNetworkStrategy, MeshSteinerStrategy
from shift.openstreet_roads import get_road_network
from shift.utils.polygon_from_points import get_polygon_from_points
from shift.utils.split_network_edges import (
    get_distance_between_points,
    split_network_edges,
)


def _project_point_to_segment(px, py, ax, ay, bx, by):
    """Project point (px,py) onto line segment (ax,ay)-(bx,by).

    Returns (proj_x, proj_y, parametric_t) where t is clamped to [0,1].
    """
    dx, dy = bx - ax, by - ay
    len_sq = dx * dx + dy * dy
    if len_sq < 1e-20:
        return ax, ay, 0.0
    t = ((px - ax) * dx + (py - ay) * dy) / len_sq
    t = max(0.0, min(1.0, t))
    return ax + t * dx, ay + t * dy, t


class PRSG(OpenStreetGraphBuilder):
    """Class interface for Primary Road and Secondary Grid distribution graph builder.

    It searches for available openstreet road network within an area defined by
    `points` + `buffer`. Primary network is built by applying a routing strategy
    (default: Steiner tree) on the road network connecting all nodes closest to the
    group centers, which will be treated as distribution transformer locations.
    Secondary network is built using a configurable secondary strategy (default:
    rectangular mesh + Steiner tree).

    Parameters
    ----------
    groups : list[GroupModel]
        List of groups for building a openstreet network.
    source_location : GeoLocation
        Power source location.
    buffer : Distance, optional
        Buffer for road network search. Defaults to 20m.
    routing_strategy : RoutingStrategy, optional
        Strategy for primary network routing. Defaults to SteinerTreeStrategy.
    secondary_strategy : SecondaryNetworkStrategy, optional
        Strategy for secondary network construction. Defaults to MeshSteinerStrategy.
    """

    def __init__(
        self,
        groups: list[GroupModel],
        source_location: GeoLocation,
        buffer: Distance = Distance(20, "m"),
        routing_strategy: RoutingStrategy | None = None,
        secondary_strategy: SecondaryNetworkStrategy | None = None,
        offline: bool = False,
        snap_to_roads: bool = True,
        snap_threshold_m: float = 50.0,
    ):
        super().__init__(groups, source_location, buffer, routing_strategy)
        self.secondary_strategy = secondary_strategy or MeshSteinerStrategy()
        self.offline = offline
        self.snap_to_roads = snap_to_roads
        self.snap_threshold_m = snap_threshold_m

    def build_secondary_network(self, group: GroupModel) -> nx.Graph:
        """Build secondary network using the configured strategy.

        Parameters
        ----------
        group: GroupModel
            Group for which the secondary network is to be built.

        Returns
        -------
        nx.Graph

        """
        return self.secondary_strategy.build(group)

    def _extend_road_network(self, graph: nx.Graph, groups: list[GroupModel]) -> nx.Graph:
        """Internal method to extend primary network if necessary."""

        copied_graph = copy.deepcopy(graph)
        for group in groups:
            node = self._get_nearest_nodes(copied_graph, [group.center])[0]
            distance_to_road = get_distance_between_points(
                group.center,
                GeoLocation(copied_graph.nodes[node]["x"], copied_graph.nodes[node]["y"]),
            )
            if distance_to_road.to("m").magnitude > 20:
                node_name = str(uuid.uuid4())
                copied_graph.add_node(node_name, x=group.center.longitude, y=group.center.latitude)
                copied_graph.add_edge(node_name, node)
        return copied_graph

    def _build_geometric_primary(self) -> nx.Graph:
        """Fallback primary network using direct geometry when roads are unavailable."""
        graph = nx.Graph()
        # Add source node
        src_name = str(uuid.uuid4())
        graph.add_node(src_name, x=self.source_location.longitude, y=self.source_location.latitude)
        # Add cluster center nodes and connect to source via MST
        center_names = []
        for group in self.groups:
            name = str(uuid.uuid4())
            graph.add_node(name, x=group.center.longitude, y=group.center.latitude)
            center_names.append(name)
        # Connect all nodes with edges weighted by distance
        all_names = [src_name] + center_names
        for i, a in enumerate(all_names):
            for b in all_names[i + 1 :]:
                dist = (
                    get_distance_between_points(
                        GeoLocation(graph.nodes[a]["x"], graph.nodes[a]["y"]),
                        GeoLocation(graph.nodes[b]["x"], graph.nodes[b]["y"]),
                    )
                    .to("m")
                    .magnitude
                )
                graph.add_edge(a, b, weight=dist)
        return nx.minimum_spanning_tree(graph, weight="weight")

    def _snap_groups_to_road(self, road_network) -> list[GroupModel]:  # noqa: C901
        """Snap group centers to the closest point on a road edge.

        Projects each center onto every road edge (line segment) and picks
        the projection that minimizes total distance to the group's parcels.
        The snapped point is inserted as a new node on the road network.
        """
        snapped_groups = []
        snap_count = 0

        # Pre-build edge segment list
        edge_segments = []
        for u, v in list(road_network.edges()):
            ux, uy = road_network.nodes[u]["x"], road_network.nodes[u]["y"]
            vx, vy = road_network.nodes[v]["x"], road_network.nodes[v]["y"]
            edge_segments.append((u, v, ux, uy, vx, vy))

        for group in self.groups:
            cx, cy = group.center.longitude, group.center.latitude

            # Find closest point on any edge
            best_proj = None
            best_dist = float("inf")
            best_edge = None

            for u, v, ux, uy, vx, vy in edge_segments:
                px, py, dist = _project_point_to_segment(cx, cy, ux, uy, vx, vy)
                actual_dist = (
                    get_distance_between_points(group.center, GeoLocation(px, py))
                    .to("m")
                    .magnitude
                )
                if actual_dist < best_dist:
                    best_dist = actual_dist
                    best_proj = GeoLocation(px, py)
                    best_edge = (u, v)

            if best_dist > self.snap_threshold_m or best_proj is None:
                snapped_groups.append(group)
                continue

            # If multiple edges within threshold, pick the one minimizing parcel distance
            if group.points:
                candidates = []
                for u, v, ux, uy, vx, vy in edge_segments:
                    px, py, _ = _project_point_to_segment(cx, cy, ux, uy, vx, vy)
                    proj_geo = GeoLocation(px, py)
                    d = get_distance_between_points(group.center, proj_geo).to("m").magnitude
                    if d <= self.snap_threshold_m:
                        total_parcel_dist = sum(
                            get_distance_between_points(proj_geo, pt).to("m").magnitude
                            for pt in group.points
                        )
                        candidates.append((proj_geo, total_parcel_dist, u, v))

                if candidates:
                    best = min(candidates, key=lambda c: c[1])
                    best_proj = best[0]
                    best_edge = (best[2], best[3])

            # Insert the snapped point as a new node on the road network
            new_node = str(uuid.uuid4())
            road_network.add_node(new_node, x=best_proj.longitude, y=best_proj.latitude)
            road_network.add_edge(best_edge[0], new_node)
            road_network.add_edge(new_node, best_edge[1])

            snapped_groups.append(GroupModel(center=best_proj, points=group.points))
            snap_count += 1

        if snap_count:
            logger.info(
                f"Snapped {snap_count}/{len(self.groups)} transformers to road edges (threshold={self.snap_threshold_m}m)"
            )
        return snapped_groups

    def build_primary_network(self) -> nx.Graph:
        """Internal method for building primary network.

        Returns
        -------
        nx.Graph
        """
        points = [point for group in self.groups for point in group.points]
        use_full_road_graph = isinstance(self.routing_strategy, FullRoadGraphStrategy)
        if self.offline:
            logger.info("Offline mode — using geometric primary network")
            return self._build_geometric_primary()
        try:
            road_network_ = get_road_network(
                get_polygon_from_points(points, self.buffer),
                reduce_to_mst=not use_full_road_graph,
            )
        except Exception:
            logger.warning("Road network unavailable — using geometric primary fallback")
            return self._build_geometric_primary()

        if not road_network_.nodes:
            logger.warning("Road network empty — using geometric primary fallback")
            return self._build_geometric_primary()

        # Snap transformer centers to road if enabled
        try:
            if self.snap_to_roads:
                self.groups = self._snap_groups_to_road(road_network_)
        except Exception:
            logger.warning("Road snapping failed; continuing with unsnapped groups.")

        road_network_ = self._extend_road_network(road_network_, self.groups)
        road_network = split_network_edges(road_network_, split_length=Distance(150, "m"))
        nearest_nodes = self._get_nearest_nodes(
            road_network,
            [c.center for c in self.groups] + [self.source_location],
        )
        try:
            primary_network = self._route_network(
                road_network,
                nearest_nodes,
            )
        except Exception:
            logger.warning("Road-based primary routing failed; using geometric primary fallback.")
            return self._build_geometric_primary()
        return primary_network
