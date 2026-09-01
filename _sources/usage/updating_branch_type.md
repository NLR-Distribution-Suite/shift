# Updating Branch Types

By default, edges in the `DistributionGraph` use the generic `DistributionBranchBase` type. If your equipment catalog requires a more specific type — such as `MatrixImpedanceBranch` — you need to update the edges before mapping equipment.

The simplest approach is to create a new graph with the updated edge types:

```python
from shift import DistributionGraph
from gdm import DistributionBranchBase, MatrixImpedanceBranch

# `graph` is the DistributionGraph from the previous step (see Building a Graph)

new_graph = DistributionGraph()

# Copy all nodes
for node in graph.get_nodes():
    new_graph.add_node(node)

# Copy edges, replacing branch types as needed
for from_node, to_node, edge in graph.get_edges():
    if edge.edge_type == DistributionBranchBase:
        edge.edge_type = MatrixImpedanceBranch
    new_graph.add_edge(from_node, to_node, edge_data=edge)
```

You can verify the result by plotting the updated graph:

```python
from shift import add_distribution_graph_to_plot, PlotManager, GeoLocation
import osmnx as ox

center = GeoLocation(*reversed(ox.geocode("Fort Worth, TX")))
plot_manager = PlotManager(center=center)
add_distribution_graph_to_plot(new_graph, plot_manager)
plot_manager.show()
```

Use `new_graph` (with updated branch types) in all subsequent mapper steps.

## Next Step

Proceed to [Mapping Phases](mapping_phases.md) to assign electrical phases to transformer secondaries.