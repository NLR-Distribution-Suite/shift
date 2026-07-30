from functools import cached_property
from typing import Callable

from gdm.quantities import Voltage
from gdm.distribution.components import DistributionTransformer

import networkx as nx
from shift.graph.distribution_graph import DistributionGraph
from shift.mapper.base_voltage_mapper import BaseVoltageMapper
from shift.data_model import TransformerVoltageModel


class TransformerVoltageMapper(BaseVoltageMapper):
    """Class for mapping voltage to buses based on transformer voltage.


    Parameters
    ----------
    graph: DistributionGraph
        Instance of the DistributionGraph
    xfmr_voltage: list[TransformerVoltageModel]
        List of transformers voltage (assumed all line to ground voltages) models
    """

    def __init__(
        self,
        graph: DistributionGraph,
        xfmr_voltage: list[TransformerVoltageModel],
    ):
        xfmr_names_in_map = set([xfmr.name for xfmr in xfmr_voltage])
        xfmr_names_in_graph = set(
            [
                edge.name
                for _, _, edge in graph.get_edges(
                    filter_func=lambda x: x.edge_type is DistributionTransformer
                )
            ]
        )
        missing_xfmrs = xfmr_names_in_graph - xfmr_names_in_map

        if missing_xfmrs:
            msg = f"Voltages not available for {missing_xfmrs=}"
            raise ValueError(msg)

        self.xfmr_voltage = xfmr_voltage
        super().__init__(graph)

    def _update_mapper_by_func(
        self,
        nodes: list[str],
        xfmr: TransformerVoltageModel,
        mapper: dict[str, Voltage],
        compare_func: Callable,
    ):
        """Internal function to update voltage mapper."""
        for node in nodes:
            if node in mapper:
                mapper[node] = compare_func(mapper[node], compare_func(xfmr.voltages))
            else:
                mapper[node] = compare_func(xfmr.voltages)

    @cached_property
    def node_voltage_mapping(self) -> dict[str, Voltage]:
        node_voltages: dict[str, Voltage] = {}
        dfs_tree = self.graph.get_dfs_tree()
        xfmrs_in_mapper = [xfmr.name for xfmr in self.xfmr_voltage]
        edges = self.graph.get_edges(filter_func=lambda x: x.name in xfmrs_in_mapper)

        for xfmr, edge in zip(self.xfmr_voltage, edges):
            from_node, to_node, _ = edge

            ht_node, lt_node = (
                (from_node, to_node)
                if dfs_tree.has_edge(from_node, to_node)
                else (to_node, from_node)
            )

            self._update_mapper_by_func(
                dfs_tree.subgraph(nx.ancestors(dfs_tree, source=lt_node)), xfmr, node_voltages, max
            )
            self._update_mapper_by_func(
                dfs_tree.subgraph(nx.descendants(dfs_tree, source=ht_node)),
                xfmr,
                node_voltages,
                min,
            )

        self._fill_uncovered_nodes(node_voltages, dfs_tree)
        return node_voltages

    def _fill_uncovered_nodes(self, node_voltages: dict[str, Voltage], dfs_tree) -> None:
        """Assign voltages to nodes not reached by transformer propagation.

        Nodes that are neither upstream of a transformer's low side nor
        downstream of its high side (e.g. dead-end primary junctions with no
        transformer below them) receive no voltage from the propagation above.
        Such nodes inherit their DFS-tree parent's voltage, defaulting to the
        highest transformer primary voltage so buses can always be built.
        """
        all_voltages = [v for xfmr in self.xfmr_voltage for v in xfmr.voltages]
        default_voltage = max(all_voltages) if all_voltages else None

        source = getattr(self.graph, "vsource_node", None)
        if source is not None and source in dfs_tree:
            for node in nx.bfs_tree(dfs_tree, source=source):
                if node in node_voltages:
                    continue
                preds = list(dfs_tree.predecessors(node))
                if preds and preds[0] in node_voltages:
                    node_voltages[node] = node_voltages[preds[0]]
                elif default_voltage is not None:
                    node_voltages[node] = default_voltage

        if default_voltage is not None:
            for node in self.graph.get_nodes():
                node_voltages.setdefault(node.name, default_voltage)
