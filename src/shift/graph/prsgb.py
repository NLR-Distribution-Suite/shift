import uuid
import copy

import networkx as nx
from infrasys.quantities import Distance

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
    ):
        super().__init__(groups, source_location, buffer, routing_strategy)
        self.secondary_strategy = secondary_strategy or MeshSteinerStrategy()

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

    def build_primary_network(self) -> nx.Graph:
        """Internal method for building primary network.

        Returns
        -------
        nx.Graph
        """
        points = [point for group in self.groups for point in group.points]
        use_full_road_graph = isinstance(self.routing_strategy, FullRoadGraphStrategy)
        road_network_ = get_road_network(
            get_polygon_from_points(points, self.buffer),
            reduce_to_mst=not use_full_road_graph,
        )
        road_network_ = self._extend_road_network(road_network_, self.groups)
        road_network = split_network_edges(road_network_, split_length=Distance(150, "m"))
        nearest_nodes = self._get_nearest_nodes(
            road_network,
            [c.center for c in self.groups] + [self.source_location],
        )
        primary_network = self._route_network(
            road_network,
            nearest_nodes,
        )
        return primary_network
