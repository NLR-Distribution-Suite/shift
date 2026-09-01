# Mapping Voltages

Voltage mapping assigns primary and secondary voltage levels to nodes in the graph based on transformer topology. You can use the built-in `TransformerVoltageMapper` or extend `BaseVoltageMapper` for custom logic.

## Using TransformerVoltageMapper

`TransformerVoltageMapper` walks the graph from the voltage source and assigns voltages based on transformer connections. Provide a `TransformerVoltageModel` for each transformer edge, specifying the primary and secondary voltages.

```python
from shift import TransformerVoltageMapper, TransformerVoltageModel, add_voltage_mapper_to_plot
from gdm.quantities import Voltage
from gdm import DistributionTransformer

# `new_graph` is the DistributionGraph from the previous steps

voltage_mapper = TransformerVoltageMapper(
    new_graph,
    xfmr_voltage=[
        TransformerVoltageModel(
            name=edge.name,
            voltages=[Voltage(7.2, "kilovolt"), Voltage(120, "volt")],
        )
        for _, _, edge in new_graph.get_edges()
        if edge.edge_type is DistributionTransformer
    ],
)
```

## Visualizing Voltage Assignments

```python
from shift import PlotManager, GeoLocation
import osmnx as ox

center = GeoLocation(*reversed(ox.geocode("Fort Worth, TX")))
plot_manager = PlotManager(center=center)
add_voltage_mapper_to_plot(voltage_mapper, plot_manager)
plot_manager.show()
```

## Custom Voltage Mapper

For non-standard voltage assignment, subclass `BaseVoltageMapper`:

```python
from shift import BaseVoltageMapper

class MyVoltageMapper(BaseVoltageMapper):
    def __init__(self, dist_graph):
        super().__init__(dist_graph)
        # Implement custom voltage assignment logic
```

## Next Step

Proceed to [Mapping Equipment](mapping_equipment.md) to assign load and source equipment to graph nodes.

