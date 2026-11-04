from typing import Callable, Iterable
import copy

import networkx as nx
from gdm.systems.distribution.components import DistributionVoltageSource


from shift.exceptions import (
    EdgeAlreadyExists,
    EdgeDoesNotExist,
    InvalidEdgeDataError,
    InvalidNodeDataError,
    NodeAlreadyExists,
    NodeDoesNotExist,
    VsourceNodeAlreadyExists,
    VsourceNodeDoesNotExist,
)
from shift.data_model import NodeModel, EdgeModel


class DistributionGraph:
    """A class representing distribution system as a graph.

    Internally, graph data is stored using networkx Graph instance.

    Examples
    --------
    >>> dgraph = DistributionGraph()

    Adding a node the system.

    >>> from shift import NodeModel
    >>> dgraph.add_node(NodeModel(name="node_1"))

    Adding multiple nodes to the system.

    >>> from gdm.systems.distribution.components import DistributionLoad
    >>> dgraph.add_nodes([NodeModel(name="node_2", assets={DistributionLoad}),
        NodeModel(name="node_3")])

    Adding an edge to the system.

    >>> from shift import EdgeModel
    >>> dgraph.add_edge("node_1", "node_2", edge_data=EdgeModel(name="node1_node2",
        edge_type=DistributionBranchBase))

    Getting node data.

    >>> dgraph.get_node("node_1")

    Getting all nodes.

    >>> dgraph.get_nodes()

    Getting filtered nodes.

    >>> dgraph.get_nodes(filter_func=lambda x: len(x.assets) == 0)

    Remove a node.

    >>> dgraph.remove_node("node_2")
    """

    node_data_ppty = "node_data"
    edge_data_ppty = "edge_data"

    def __init__(self):
        self._graph = nx.Graph()
        self.vsource_node = None

    def add_node(self, node: NodeModel):
        """Adds node to the graph.

        Parameters
        ----------
        node : NodeModel
            Instance of `NodeModel` to add to the graph.

        Raises
        ------
        NodeAlreadyExists
            Raises this exception if node already exists.
        VsourceNodeAlreadyExists:
            Raises this exception if an attempt is made to add
            node with substation in assets more than once.

        Examples
        --------

        >>> dgraph.add_node(sf.NodeModel(name="node_1"))
        """

        if self._graph.has_node(node.name):
            msg = f"{node=} already exists in the graph."
            raise NodeAlreadyExists(msg)
        if (
            self.vsource_node is not None
            and node.assets
            and DistributionVoltageSource in node.assets
        ):
            msg = f"{self.vsource_node=} already exists. Cannot add {node=}"
            raise VsourceNodeAlreadyExists(msg)
        self._graph.add_node(node.name, **{self.node_data_ppty: node})
        if node.assets and DistributionVoltageSource in node.assets:
            self.vsource_node = node.name

    def add_nodes(self, nodes: list[NodeModel]):
        """Adds multiple nodes to the graph.

        Parameters
        ----------
        nodes : NodeModel
            Instance of `NodeModel` to add to the graph.

        Examples
        --------

        >>> dgraph.add_nodes([sf.NodeModel(name="node_1"),
            sf.NodeModel(name="node_2")])
        """
        for node in nodes:
            self.add_node(node)

    def add_edge(self, from_node: str | NodeModel, to_node: str | NodeModel, edge_data: EdgeModel):
        """Adds edge to the graph.

        If from_node or to_node are of type `NodeModel` and they
        do not exist in the graph they will be automatically added.

        Parameters
        ----------
        from_node : str | NodeModel
            Name of the from node.
        to_node : str | NodeModel
            Name of the to node.
        edge_data : EdgeModel
            Instance of the `EdgeModel`.

        Raises
        ------
            EdgeAlreadyExists
                Raises an exception if edge already exists.

        Examples
        --------

        >>> dgraph.add_edge("node_1", "node_2", edge_data=edge_data)
        """

        for node in [from_node, to_node]:
            if isinstance(node, NodeModel) and not self._graph.has_node(node.name):
                self.add_node(node)

        from_node_name = from_node if isinstance(from_node, str) else from_node.name
        to_node_name = to_node if isinstance(to_node, str) else to_node.name

        if self._graph.has_edge(from_node_name, to_node_name):
            msg = f"Edge already exists between {from_node=} and {to_node=}"
            raise EdgeAlreadyExists(msg)

        if not (self._graph.has_node(from_node_name) and self._graph.has_node(to_node_name)):
            msg = (
                f"Either {from_node=} or {to_node=} does not exist. Make sure"
                f"they are added to the graph before creating an edge."
            )
            raise NodeDoesNotExist(msg)
        self._graph.add_edge(from_node_name, to_node_name, **{self.edge_data_ppty: edge_data})

    def get_node(self, node_name: str) -> NodeModel:
        """Get node data by node name.

        Parameters
        ----------
        node_name : str
            Name of the node.

        Returns
        -------
        NodeModel

        Examples
        --------

        >>> dgraph.get_node("node_1")
        """
        if node_name not in list(self._graph.nodes):
            msg = f"{node_name=} does not exist in the graph."
            raise NodeDoesNotExist(msg)

        node_data = self._graph.nodes[node_name]
        if self.node_data_ppty not in node_data:
            msg = f"{self.node_data_ppty} does not exist in {node_data=} for {node_name=}"
            raise InvalidNodeDataError(msg)

        node_obj = node_data.get(self.node_data_ppty)
        if not isinstance(node_obj, NodeModel):
            msg = f"{node_obj=} is not of type NodeModel"
            raise InvalidNodeDataError(msg)
        return node_obj

    def get_nodes(
        self, filter_func: Callable[[NodeModel], bool] | None = None
    ) -> Iterable[NodeModel]:
        """Returns list of nodes.

        Parameters
        ----------
        filter_func : Callable[[NodeModel], bool] | None, optional
            Filter function for getting nodes., by default None

        Returns
        -------
        Iterable[NodeModel]
            Iterable for getting node.

        Examples
        --------

        >>> dgraph.get_nodes(filter_func=lambda x: "tr" in x)
        """
        for node in self._graph.nodes:
            node_obj = self.get_node(node)
            if (filter_func and filter_func(node_obj)) or filter_func is None:
                yield node_obj

    def remove_node(self, node_name: str):
        """Removes a node from the system.

        Parameters
        ----------
        node_name: str
            Name of the node to remove.

        Examples
        --------

        >>> dgraph.remove_node("node_1")
        """
        self._graph.remove_node(node_name)

    def has_node(self, node_name: str) -> bool:
        """Function to check whether node already exists or not.

        Parameters
        ----------

        node_name: str
            Name of the node to check.

        Returns
        -------
        bool

        Examples
        --------

        >>> dgraph.has_node("node_1")
        """
        return self._graph.has_node(node_name)

    def remove_edge(self, from_node: str, to_node: str):
        """Removes an edge from the system.

        Parameters
        ----------
        from_node: str
            From node name.

        to_node: str
            To node name

        Examples
        --------

        >>> dgraph.remove_edge("node_1", "node_2")
        """
        self._graph.remove_edge(from_node, to_node)

    def get_edge(self, from_node: str, to_node: str) -> EdgeModel:
        """Get edge data.


        Parameters
        ----------

        from_node: str
            Name of the from node.
        to_node: str
            Name of yje to node.

        Returns
        -------
        EdgeModel


        Examples
        --------

        >>> dgraph.get_edge("node_1", "node_2")
        """
        if not self._graph.has_edge(from_node, to_node):
            msg = f"Edge between {from_node=} and {to_node=} does not exist."
            raise EdgeDoesNotExist(msg)

        edge_data = self._graph.get_edge_data(from_node, to_node)
        if self.edge_data_ppty not in edge_data:
            msg = f"{self.edge_data_ppty} does not exist in {edge_data=} for {from_node, to_node}"
            raise InvalidEdgeDataError(msg)

        edg_obj = edge_data.get(self.edge_data_ppty)

        if not isinstance(edg_obj, EdgeModel):
            msg = f"{edge_data=} is not of type {EdgeModel}"
            raise InvalidEdgeDataError(msg)
        return edg_obj

    def get_edges(
        self, filter_func: Callable[[EdgeModel], bool] = None
    ) -> Iterable[tuple[str, str, EdgeModel]]:
        """Returns interator for all edges in the graph.

        Parameters
        ----------
        filter_func: Callable[[EdgeModel], bool]
            Optional filter function.

        Returns
        -------
        Iterable[tuple[str, str, EdgeModel]]
        """
        for edge in self._graph.edges:
            edge_data = self.get_edge(*edge)
            if filter_func and not filter_func(edge_data):
                continue
            yield tuple([edge[0], edge[1], edge_data])

    def get_undirected_graph(self) -> nx.Graph:
        """Method to return undirected graph."""
        return copy.deepcopy(self._graph)

    def get_dfs_tree(self) -> nx.DiGraph:
        """Internal method to directed dfs tree from vsource."""
        if self.vsource_node is None:
            raise VsourceNodeDoesNotExist("Vsource node does not exist on this graph.")
        return nx.dfs_tree(self._graph, source=self.vsource_node)
