# Mapping Phases

Phase mapping assigns electrical phases (A, B, C, or split-phase) to transformer secondaries and downstream branches. You can use the built-in `BalancedPhaseMapper` or extend `BasePhaseMapper` for custom logic.

## Using BalancedPhaseMapper

`BalancedPhaseMapper` distributes load across phases as evenly as possible. You need to provide a `TransformerPhaseMapperModel` for each transformer in the graph, specifying its type and capacity. The actual transformer size used by the equipment mapper may differ — this model is used only for phase assignment.

```python
from shift import (
    TransformerPhaseMapperModel,
    TransformerTypes,
    BalancedPhaseMapper,
    add_phase_mapper_to_plot,
    PlotManager,
    GeoLocation,
)
from gdm import DistributionTransformer
from gdm.quantities import ApparentPower
import osmnx as ox

# `new_graph` is the DistributionGraph from the previous steps

# Build a phase mapper model for each transformer edge
mapper_models = [
    TransformerPhaseMapperModel(
        tr_name=edge.name,
        tr_type=TransformerTypes.SPLIT_PHASE,
        tr_capacity=ApparentPower(25, "kilovoltampere"),
        location=new_graph.get_node(from_node).location,
    )
    for from_node, _, edge in new_graph.get_edges()
    if edge.edge_type is DistributionTransformer
]

phase_mapper = BalancedPhaseMapper(new_graph, mapper=mapper_models, method="agglomerative")
```

## Visualizing Phase Assignments

```python
center = GeoLocation(*reversed(ox.geocode("Fort Worth, TX")))
plot_manager = PlotManager(center=center)
add_phase_mapper_to_plot(phase_mapper, plot_manager)
plot_manager.show()
```

## Custom Phase Mapper

For non-standard phase allocation, subclass `BasePhaseMapper`:

```python
from shift import BasePhaseMapper

class MyPhaseMapper(BasePhaseMapper):
    def __init__(self, dist_graph):
        super().__init__(dist_graph)
        # Implement custom phase assignment logic
```

## Next Step

Proceed to [Mapping Voltages](mapping_voltages.md) to assign primary and secondary voltage levels.