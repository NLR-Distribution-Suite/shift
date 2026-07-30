from functools import cached_property, reduce
from itertools import combinations, groupby
import operator
from typing import Literal

from gdm.distribution.components import DistributionTransformer
from gdm.distribution.enums import Phase
import numpy as np
import networkx as nx
from shift.exceptions import (
    AllocationMappingError,
    InvalidPhaseAllocationMethod,
    MissingTransformerMapping,
    UnsupportedTransformerType,
)
from sklearn.cluster import KMeans, AgglomerativeClustering
from networkx.algorithms.approximation import steiner_tree

from shift.graph.distribution_graph import DistributionGraph
from shift.data_model import VALID_NODE_TYPES
from shift.mapper.base_phase_mapper import BasePhaseMapper
from shift.data_model import TransformerTypes, TransformerPhaseMapperModel


def _get_allocations(names: list[str], labels: list[int], n_categories: int):
    """Internal function to get allocations."""
    allocations = [[] for _ in range(n_categories)]
    for name, index in zip(names, labels):
        allocations[index].append(name)
    return allocations


def agglomerative_allocations(
    distances: list[list[float]], names: list[str], num_categories: int
) -> list[list[str]]:
    """Kmeans weighted allocation."""
    # Cannot request more clusters than there are samples (e.g. fewer
    # single-phase transformers than phases); cap and leave extra bins empty.
    n_clusters = max(1, min(num_categories, len(names)))
    aggc = AgglomerativeClustering(n_clusters=n_clusters, linkage="ward")
    aggc.fit(distances)
    return _get_allocations(names, aggc.labels_, num_categories)


def kmeans_allocations(
    points: list[list[float]],
    names: list[str],
    num_categories: int,
    weights: list[float] | None = None,
) -> list[list[str]]:
    """Kmeans weighted allocation."""
    n_clusters = max(1, min(num_categories, len(names)))
    kmeans = KMeans(n_clusters=n_clusters)
    kmeans.fit(points, sample_weight=weights)
    return _get_allocations(names, kmeans.labels_, num_categories)


def greedy_allocations(weights: list[tuple[str, float]], num_categories: int) -> list[list[str]]:
    """Greedy allocation algorithm to assign weights to categories
    in balanced way as much as possible."""

    sorted_weights = sorted(weights, key=lambda x: x[1], reverse=True)
    allocations = [[] for _ in range(num_categories)]
    sums = [0 for _ in range(num_categories)]
    for weight in sorted_weights:
        min_sum_index = np.argmin(sums)
        sums[min_sum_index] += weight[1]
        allocations[min_sum_index].append(weight[0])

    return allocations


class BalancedPhaseMapper(BasePhaseMapper):
    """Class interface for balanced phase mapper.

    Parameters
    ----------

    graph: DistributionGraph
        Instance of the distribution graph.
    mapper: list[TransformerPhaseMapperModel]
        List of phase mapper models.
    method: Literal["kmean", "greedy"]
        Method used for allocation, optional, defaults to "kmeans".
    """

    def __init__(
        self,
        graph: DistributionGraph,
        mapper: list[TransformerPhaseMapperModel],
        method: Literal["kmean", "greedy", "agglomerative"] = "agglomerative",
    ):
        self.mapper = mapper

        missing_transformers = set([item.tr_name for item in self.mapper]) - set(
            edge.name
            for _, _, edge in graph.get_edges()
            if edge.edge_type == DistributionTransformer
        )
        if missing_transformers:
            msg = f"Missing transformers from mapping {missing_transformers=}"
            raise MissingTransformerMapping(msg)
        self._transformer_phase_mapping: dict[str, set[Phase]] = {}
        self.method = method
        super().__init__(graph)

    def _get_distance_matrix(self, tr_names: list[str]):
        """Function to return distance matrix for list of transformers."""

        selected_nodes = [
            from_node
            for from_node, _, _ in self.graph.get_edges(filter_func=lambda x: x.name in tr_names)
        ]
        G = self.graph.get_undirected_graph()
        subgraph = steiner_tree(G, selected_nodes)
        return nx.floyd_warshall_numpy(subgraph)

    def _get_nodes_by_edge_names(self, edge_names: list[str]) -> set[str]:
        """Internal method to get three phase nodes."""
        nodes = set()
        for from_node, to_node, _ in self.graph.get_edges(
            filter_func=lambda x: x.name in edge_names
        ):
            edge_node_set = set([from_node, to_node])
            nodes = reduce(operator.or_, [nodes, edge_node_set])
        return nodes

    def _update_three_phase_nodes(
        self, trs: list[TransformerPhaseMapperModel], container: dict, transformer_mapper: dict
    ):
        """Internal method to update three phase nodes."""
        tr_names = [item.tr_name for item in trs]
        three_phase = set([Phase.A, Phase.B, Phase.C])
        for tr in tr_names:
            transformer_mapper[tr] = three_phase
        for node in self._get_nodes_by_edge_names(tr_names):
            container[node] = three_phase

    def _get_head_node(self, edge_name: str) -> str:
        """Internal method to return head node."""
        nodes = list(self._get_nodes_by_edge_names([edge_name]))
        successors = nx.dfs_successors(self.graph.get_dfs_tree(), source=nodes[0], depth_limit=1)
        return nodes[0] if nodes[1] in successors.get(nodes[0], []) else nodes[1]

    def _update_single_phase_tr_nodes(
        self,
        trs: list[TransformerPhaseMapperModel],
        ht_phases: list[list[Phase]],
        is_split_phase: bool,
        container: dict,
        transformer_mapper: dict,
    ):
        """Internal method to update three phase nodes."""
        trs = [el for el in trs]
        tr_names = [tr.tr_name for tr in trs]
        match self.method:
            case "greedy":
                allocations = greedy_allocations(
                    [(tr.tr_name, tr.tr_capacity.to("va").magnitude) for tr in trs], len(ht_phases)
                )
            case "kmeans":
                allocations = kmeans_allocations(
                    points=[[tr.location.x, tr.location.y] for tr in trs],
                    weights=[tr.tr_capacity.to("va").magnitude for tr in trs],
                    names=tr_names,
                    num_categories=len(ht_phases),
                )
            case "agglomerative":
                allocations = agglomerative_allocations(
                    distances=self._get_distance_matrix(tr_names),
                    names=tr_names,
                    num_categories=len(ht_phases),
                )
            case _:
                msg = f"Invalid method supplied {self.method=}"
                raise InvalidPhaseAllocationMethod(msg)

        allocated_trs = set([el for item in allocations for el in item])
        if set(tr_names) != allocated_trs:
            msg = f"Missing mapping for transformers: {tr_names - allocated_trs}"
            raise AllocationMappingError(msg)

        for allocation, phases in zip(allocations, ht_phases):
            for tr in allocation:
                nodes = self._get_nodes_by_edge_names([tr])
                head_node = self._get_head_node(tr)
                tail_node = list(set(nodes) - set([head_node]))[0]
                container[head_node] = set(phases)
                container[tail_node] = (
                    set([Phase.S1, Phase.N, Phase.S2]) if is_split_phase else set(phases)
                )
                transformer_mapper[tr] = set(phases)

    def _update_transformer_node_phases(
        self, mapper: list[TransformerPhaseMapperModel], container: dict, transformer_mapper: dict
    ):
        """Internal method to update transformer nodes phases."""
        delta_phase_combinations = [[Phase.A, Phase.B], [Phase.B, Phase.C], [Phase.C, Phase.A]]
        single_phase_combinations = [[Phase.A], [Phase.B], [Phase.C]]

        type_to_input_mapper = {
            TransformerTypes.SPLIT_PHASE: [single_phase_combinations, True],
            TransformerTypes.SINGLE_PHASE: [single_phase_combinations, False],
            TransformerTypes.SPLIT_PHASE_PRIMARY_DELTA: [delta_phase_combinations, True],
            TransformerTypes.SINGLE_PHASE_PRIMARY_DELTA: [delta_phase_combinations, False],
        }

        def key_func(tr_: TransformerPhaseMapperModel):
            return tr_.tr_type

        for tr_type, group in groupby(sorted(mapper, key=key_func), key_func):
            if tr_type == TransformerTypes.THREE_PHASE:
                self._update_three_phase_nodes(group, container, transformer_mapper)
            elif tr_type in type_to_input_mapper:
                self._update_single_phase_tr_nodes(
                    group, *type_to_input_mapper[tr_type], container, transformer_mapper
                )
            else:
                msg = f"{tr_type=} not supported yet."
                raise UnsupportedTransformerType(msg)

    def _update_node_phases_upward_from_transformer(
        self,
        mapper: list[TransformerPhaseMapperModel],
        container: dict,
    ):
        """Internal method to update transformer nodes phases."""

        for tr in mapper:
            head_node = self._get_head_node(tr.tr_name)
            tr_head_node_phase = container[head_node]
            shortest_path = reversed(
                nx.shortest_path(
                    self.graph.get_dfs_tree(),
                    source=self.graph.vsource_node,
                    target=head_node,
                )
            )
            for node in shortest_path:
                container[node] = reduce(
                    operator.or_,
                    [
                        set() if container.get(node) is None else container.get(node),
                        tr_head_node_phase,
                    ],
                )
                if len(container[node]) > 3:
                    # An over-merged bus (more than three assigned phases) is
                    # normalized to full three-phase primary — consistent with
                    # the two-phase promotion below and safe for GDM.
                    container[node] = {Phase.A, Phase.B, Phase.C}
                three_phase = {Phase.A, Phase.B, Phase.C}
                two_phase_sets = list([set(el) for el in combinations(three_phase, 2)])
                if container[node] in two_phase_sets:
                    container[node] = three_phase

    def _update_node_phases_downward_from_transformer(
        self,
        mapper: list[TransformerPhaseMapperModel],
        container: dict,
    ):
        """Internal method to update nodes downward of the transformer."""
        for tr in mapper:
            tr_nodes = list(self._get_nodes_by_edge_names([tr.tr_name]))
            head_node = self._get_head_node(tr.tr_name)
            lt_node = list(set(tr_nodes) - set([head_node]))[0]
            lt_phase = container[lt_node]
            is_split_phase = set([Phase.S1, Phase.N, Phase.S2]) == lt_phase
            for descendant in nx.descendants(self.graph.get_dfs_tree(), source=head_node):
                if descendant not in container:
                    container[descendant] = (
                        set([Phase.S1, Phase.S2]) if is_split_phase else lt_phase
                    )

    @cached_property
    def node_phase_mapping(self) -> dict[str, set[Phase]]:
        node_phase_mapping: dict[str, set[Phase]] = {}
        self._update_transformer_node_phases(
            self.mapper, node_phase_mapping, self._transformer_phase_mapping
        )
        self._update_node_phases_upward_from_transformer(self.mapper, node_phase_mapping)
        self._update_node_phases_downward_from_transformer(self.mapper, node_phase_mapping)
        self._fill_uncovered_nodes(node_phase_mapping)
        return node_phase_mapping

    def _fill_uncovered_nodes(self, container: dict) -> None:
        """Assign phases to nodes not reached by transformer propagation.

        Some topologies contain nodes that are neither on a transformer's
        upstream path nor a descendant of a transformer head (e.g. primary
        nodes without a downstream transformer). Such nodes inherit their
        DFS-tree parent's phases so every node ends up with a valid mapping;
        anything still unresolved defaults to three-phase.
        """
        three_phase = {Phase.A, Phase.B, Phase.C}
        tree = self.graph.get_dfs_tree()
        for node in nx.bfs_tree(tree, source=self.graph.vsource_node):
            if node in container:
                continue
            preds = list(tree.predecessors(node))
            if preds and container.get(preds[0]):
                container[node] = set(container[preds[0]])
            else:
                container[node] = set(three_phase)
        for node in self.graph.get_nodes():
            container.setdefault(node.name, set(three_phase))

    @cached_property
    def asset_phase_mapping(self) -> dict[str, dict[VALID_NODE_TYPES, set[Phase]]]:
        asset_mapping: dict[str, dict[VALID_NODE_TYPES, set[Phase]]] = {}
        for node in self.graph.get_nodes():
            asset_mapping[node.name] = {
                asset: self.node_phase_mapping[node.name] for asset in (node.assets or set())
            }
        return asset_mapping

    @cached_property
    def transformer_phase_mapping(self) -> dict[str, set[Phase]]:
        _ = self.node_phase_mapping
        return self._transformer_phase_mapping
