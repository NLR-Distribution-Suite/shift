from abc import abstractmethod
from collections import defaultdict
import uuid

import networkx as nx
from networkx.algorithms import approximation as ax
from loguru import logger
from gdm.distribution.components import (
    DistributionVoltageSource,
    DistributionTransformer,
    DistributionBranchBase,
    DistributionLoad,
)
from infrasys.quantities import Distance
from infrasys import Location


from shift.exceptions import EmptyGraphError
from shift.graph.base_graph_builder import BaseGraphBuilder
from shift.graph.distribution_graph import DistributionGraph
from shift.graph.routing import RoutingStrategy, SteinerTreeStrategy
from shift.data_model import GeoLocation, GroupModel, EdgeModel, NodeModel, VALID_NODE_TYPES
from shift.utils.nearest_points import get_nearest_points
from shift.utils.split_network_edges import get_distance_between_points


class OpenStreetGraphBuilder(BaseGraphBuilder):
    """Abstract class interface for building distribution graph using openstreet data.

    Parameters
    ----------

    groups: list[GroupModel]
        List of groups for building a openstreet network.
    source_location: GeoLocation
        Power source location.
    buffer: Distance, optional
        Buffer to be applied in a bounding polygon formed
        by `points` for searching road network. Defaults to 20m.

    Examples
    --------

    >>> from shift import get_parcels, get_kmeans_clusters
    >>> points = get_parcels("Fort Worth, Texas", Distance(100, "m"))
    >>> groups = get_kmeans_clusters(5, [el.geometry[0] if isinstance(el.geometry, list)
        else el.geometry for el in points])
    >>> builder = OpenStreetGraphBuilder(groups, GeoLocation(-97.3308, 32.7555))
    >>> graph = builder.get_distribution_graph()
    """

    def __init__(
        self,
        groups: list[GroupModel],
        source_location: GeoLocation,
        buffer: Distance = Distance(20, "m"),
        routing_strategy: RoutingStrategy | None = None,
    ):
        """Constructor for the class.

        Parameters
        ----------

        groups: list[GroupModel]
            List of groups for building a openstreet network.
        source_location: GeoLocation
            Power source location.
        buffer: Distance, optional
            Buffer to be applied in a bounding polygon formed
            by `points` for searching road network. Defaults to 20m.
        routing_strategy: RoutingStrategy, optional
            Strategy for routing the primary network. Defaults to
            SteinerTreeStrategy (uniform weights, backward-compatible).
        """
        self.groups = groups
        self.source_location = source_location
        self.buffer = buffer
        self.routing_strategy = routing_strategy or SteinerTreeStrategy()
        self.point_node_mapping = {}

    @staticmethod
    def _get_tuple_to_node_mapper(graph: nx.Graph) -> dict[tuple, str]:
        """Method to build tuple to node mapper.

        Assumes "x" and "y" coordinate values are available
        in the graph.

        Parameters
        ----------

        graph: nx.Graph
            Instance of networkx graph.

        Returns
        -------
            dict[tuple, str]
        """

        return {
            (data["x"], data["y"]): node for node, data in dict(graph.nodes(data=True)).items()
        }

    def _get_nearest_nodes(self, graph: nx.Graph, points: list[GeoLocation]) -> list[str]:
        """Method to compute nearest nodes in the graph.

        Parameters
        ----------

        graph: nx.Graph
            Instance of networkx graph.
        points: list[GeoLocation]
            List of geolocations

        Returns
        -------
            list[str]
        """
        if not graph.nodes:
            msg = f"Empty graph provided. {graph.nodes=}"
            raise EmptyGraphError(msg)
        graph_nodes_mapper = self._get_tuple_to_node_mapper(graph)
        nearest_nodes = get_nearest_points(list(graph_nodes_mapper.keys()), points)
        return [graph_nodes_mapper[tuple(node)] for node in nearest_nodes]

    @staticmethod
    def _get_steiner_tree(graph: nx.Graph, nearest_nodes: list[str]):
        """Returns steineer tree from a given graph and nearest nodes.

        .. deprecated::
            Use routing_strategy.route() instead. This static method is
            retained for backward compatibility.

        Parameters
        ----------

        graph: nx.Graph
            Instance of the graph.
        nearest_nodes: list[str]
            List of nodes to keep.

        Returns
        -------
        nx.Graph
        """
        nx.set_edge_attributes(graph, 1, "weight")
        return ax.steiner_tree(
            graph,
            nearest_nodes,
            method="mehlhorn",
        )

    def _route_network(self, graph: nx.Graph, terminal_nodes: list[str]) -> nx.Graph:
        """Route terminal nodes through the candidate graph using the configured strategy.

        Parameters
        ----------
        graph : nx.Graph
            Candidate network graph.
        terminal_nodes : list[str]
            Nodes to connect.

        Returns
        -------
        nx.Graph
        """
        return self.routing_strategy.route(graph, terminal_nodes)

    @abstractmethod
    def build_secondary_network(self, group: GroupModel) -> nx.Graph:
        """Abstract method to build secondary network.

        Parameters
        ----------
        group: GroupModel
            Group for which the secondary network is to be built.

        Returns
        -------
        nx.Graph

        """

    @abstractmethod
    def build_primary_network(self) -> nx.Graph:
        """Abstract method for building primary network.

        Returns
        -------
        nx.Graph
        """

    def get_point_node_mapping(self) -> dict[GeoLocation, str]:
        """Method to return parcel node mapping.

        Returns
        -------
        dict[GeoLocation, str]
        """
        return self.point_node_mapping

    def _get_node_assets_mapper(
        self, asset_nodes: dict[VALID_NODE_TYPES, list[str]]
    ) -> dict[str, set[VALID_NODE_TYPES]]:
        """Get set of asset types for nodes.


        Parameters
        ----------

        asset_nodes: dict[VALID_NODE_TYPES, list[str]]
            Dictionary mapping between node types and list of graph nodes.

        Returns
        -------

        dict[str, set[VALID_NODE_TYPES]]
            Dictionary mapping between node name and set of assets
            connected to that node.
        """

        nodes_asset_mapper: dict[str, set[VALID_NODE_TYPES]] = defaultdict(set)
        for asset_type, nodes in asset_nodes.items():
            for node in nodes:
                nodes_asset_mapper[node].add(asset_type)
        return dict(nodes_asset_mapper)

    @staticmethod
    def _explode_transformer_node(
        graph: DistributionGraph, transformer_nodes: list[str]
    ) -> DistributionGraph:
        """Internal method to explode transformer node to an edge.
        This updates graph in place.

        Parameters
        ----------
        graph: DistributionGraph
            Instance of the distribution graph.

        transformer_nodes: list[str]
            List of transformer node names.

        """

        dfs_tree = graph.get_dfs_tree()
        for node in set(transformer_nodes):
            node_obj = graph.get_node(node)
            new_node = NodeModel(name=f"{node_obj.name}_ht", location=node_obj.location)
            graph.add_node(new_node)
            predecessors = list(dfs_tree.predecessors(node))
            edges = [graph.get_edge(pred, node) for pred in predecessors]
            for pred, edge_data in zip(predecessors, edges):
                graph.add_edge(pred, new_node.name, edge_data=edge_data)
                graph.remove_edge(node, pred)
            graph.add_edge(
                node_obj.name,
                new_node.name,
                edge_data=EdgeModel(
                    name=str(uuid.uuid4()), length=None, edge_type=DistributionTransformer
                ),
            )

    def _get_distribution_graph_from_network(
        self,
        graph: nx.Graph,
        transformer_nodes: list[str],
        asset_nodes: dict[VALID_NODE_TYPES, list[str]],
    ) -> DistributionGraph:
        """Internal method to convert networkx graph to Distribution Graph.

        Parameters
        ----------

        graph: nx.Graph
            Instance of networkx graph.
        load_nodes: list[str]
            List of load nodes in the graph.
        asset_nodes: dict[VALID_NODE_TYPES, list[str]]

        Returns
        -------
        DistributionGraph

        """

        dist_graph = DistributionGraph()

        node_asset_mapper = self._get_node_assets_mapper(asset_nodes)
        for edge in graph.edges:
            locs: list[Location] = []
            for node in edge:
                location = Location(
                    x=graph.nodes[node]["x"], y=graph.nodes[node]["y"], crs="epsg:4326"
                )
                locs.append(location)
                if dist_graph.has_node(node):
                    continue
                assets = node_asset_mapper.get(node)
                dist_graph.add_node(
                    NodeModel(name=node, location=location, assets=assets)
                    if assets is not None
                    else NodeModel(name=node, location=location)
                )

            dist_graph.add_edge(
                *edge,
                edge_data=EdgeModel(
                    name=str(uuid.uuid4()),
                    edge_type=DistributionBranchBase,
                    length=get_distance_between_points(
                        *[GeoLocation(loc.x, loc.y) for loc in locs]
                    ),
                ),
            )
        self._explode_transformer_node(dist_graph, transformer_nodes)
        return dist_graph

    def get_distribution_graph(self) -> DistributionGraph:
        """Method to return distribution graph.

        Returns
        -------
        DistributionGraph
        """
        dist_network = nx.Graph(self.build_primary_network())
        if not dist_network.nodes:
            msg = "Empty primary graph created."
            raise EmptyGraphError(msg)
        dist_network = nx.relabel_nodes(
            dist_network, {node: str(node) for node in list(dist_network.nodes)}
        )
        substation_node = self._get_nearest_nodes(dist_network, [self.source_location])[0]
        transformer_nodes = self._get_nearest_nodes(dist_network, [c.center for c in self.groups])
        new_transformer_nodes = []
        for tr_node, group in zip(transformer_nodes, self.groups):
            logger.debug(f"Building secondary for {group.center}: {tr_node}")

            secondary_graph = self.build_secondary_network(group)
            # Relabel all secondary nodes to unique UUIDs to avoid
            # collisions with the primary network (OSMnx reuses node IDs).
            secondary_graph = nx.relabel_nodes(
                secondary_graph,
                {n: str(uuid.uuid4()) for n in secondary_graph.nodes},
            )
            sec_loads = self._get_nearest_nodes(secondary_graph, group.points)
            self.point_node_mapping.update(dict(zip(group.points, sec_loads)))
            tr_location = GeoLocation(
                dist_network.nodes[tr_node]["x"], dist_network.nodes[tr_node]["y"]
            )
            nearest_sec_node = self._get_nearest_nodes(secondary_graph, [tr_location])[0]
            dist_network = nx.union(dist_network, secondary_graph)
            new_tr_node_name = str(uuid.uuid4())
            dist_network.add_node(
                new_tr_node_name, x=tr_location.longitude + 1e-6, y=tr_location.latitude + 1e-6
            )
            dist_network.add_edge(tr_node, new_tr_node_name)
            dist_network.add_edge(new_tr_node_name, nearest_sec_node)
            new_transformer_nodes.append(new_tr_node_name)

        # Enforce radial topology: extract DFS tree from source node
        # This removes any cycles while keeping all nodes reachable from source.
        if nx.is_connected(dist_network):
            dfs_edges = list(nx.dfs_edges(dist_network, source=substation_node))
            radial = nx.Graph()
            for u, v in dfs_edges:
                radial.add_node(u, **dist_network.nodes[u])
                radial.add_node(v, **dist_network.nodes[v])
                radial.add_edge(u, v)
            # Add any isolated nodes (shouldn't happen but safety)
            for node in dist_network.nodes:
                if node not in radial:
                    radial.add_node(node, **dist_network.nodes[node])
            logger.debug(
                f"Radial enforcement: {dist_network.number_of_edges()} edges → "
                f"{radial.number_of_edges()} edges (removed {dist_network.number_of_edges() - radial.number_of_edges()} cycles)"
            )
            dist_network = radial

        return self._get_distribution_graph_from_network(
            dist_network,
            new_transformer_nodes,
            asset_nodes={
                DistributionVoltageSource: [substation_node],
                DistributionLoad: list(self.point_node_mapping.values()),
            },
        )
