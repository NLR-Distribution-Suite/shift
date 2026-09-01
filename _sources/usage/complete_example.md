# Complete Example: Building a Distribution System

This example demonstrates the full NREL-shift workflow — from fetching geospatial data to producing a simulator-ready distribution system model. Each step links to its detailed guide for further reading.

## Overview

| Step | Action | Guide |
|------|--------|-------|
| 1 | Fetch building parcels from OpenStreetMap | [Fetching Parcels](fetching_parcels.md) |
| 2 | Cluster parcels and build a distribution graph | [Building a Graph](building_graph.md) |
| 3 | Update branch types for your equipment catalog | [Updating Branch Types](updating_branch_type.md) |
| 4 | Assign phases to transformer secondaries | [Mapping Phases](mapping_phases.md) |
| 5 | Assign voltage levels | [Mapping Voltages](mapping_voltages.md) |
| 6 | Map equipment to nodes and edges | [Mapping Equipment](mapping_equipment.md) |
| 7 | Assemble and export the distribution system | [Building a System](building_system.md) |

## Step 1: Import Modules

```python
from pathlib import Path

from shift import (
    parcels_from_location,
    get_kmeans_clusters,
    PRSG,
    DistributionGraph,
    DistributionSystemBuilder,
    BalancedPhaseMapper,
    TransformerVoltageMapper,
    EdgeEquipmentMapper,
    TransformerPhaseMapperModel,
    TransformerVoltageModel,
    TransformerTypes,
    GeoLocation,
    PlotManager,
    add_parcels_to_plot,
    add_distribution_graph_to_plot,
)

from gdm import (
    DistributionSystem,
    DistributionTransformer,
    DistributionBranchBase,
    MatrixImpedanceBranch,
)
from gdm.quantities import Voltage, ApparentPower
from infrasys.quantities import Distance
import osmnx as ox
```

## Step 2: Fetch Parcels

```python
location = "Fort Worth, TX"
search_distance = Distance(500, "m")

parcels = parcels_from_location(location, search_distance)
print(f"Found {len(parcels)} parcels")
```

## Step 3: Build the Distribution Graph

```python
def _get_parcel_points(parcels):
    return [
        p.geometry[0] if isinstance(p.geometry, list) else p.geometry
        for p in parcels
    ]

num_clusters = max(len(parcels) // 2, 1)
clusters = get_kmeans_clusters(num_clusters, _get_parcel_points(parcels))

builder = PRSG(
    groups=clusters,
    source_location=GeoLocation(-97.3, 32.75),
)
graph = builder.get_distribution_graph()
print(f"Graph: {len(list(graph.get_nodes()))} nodes, {len(list(graph.get_edges()))} edges")
```

## Step 4: Update Branch Types

Replace generic `DistributionBranchBase` edges with the type expected by your equipment catalog:

```python
new_graph = DistributionGraph()

for node in graph.get_nodes():
    new_graph.add_node(node)

for from_node, to_node, edge in graph.get_edges():
    if edge.edge_type == DistributionBranchBase:
        edge.edge_type = MatrixImpedanceBranch
    new_graph.add_edge(from_node, to_node, edge_data=edge)
```

## Step 5: Map Phases

```python
transformer_phase_models = [
    TransformerPhaseMapperModel(
        tr_name=edge.name,
        tr_type=TransformerTypes.SPLIT_PHASE,
        tr_capacity=ApparentPower(25, "kilovoltampere"),
        location=new_graph.get_node(from_node).location,
    )
    for from_node, _, edge in new_graph.get_edges()
    if edge.edge_type is DistributionTransformer
]

phase_mapper = BalancedPhaseMapper(new_graph, mapper=transformer_phase_models, method="agglomerative")
```

## Step 6: Map Voltages

```python
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

## Step 7: Map Equipment

Load an equipment catalog and create the equipment mapper. For a custom node-level mapper (e.g., area-based loads), see [Mapping Equipment](mapping_equipment.md).

```python
import shift

MODELS_FOLDER = Path(shift.__file__).parent.parent.parent / "tests" / "models"
catalog_sys = DistributionSystem.from_json(MODELS_FOLDER / "p1rhs7_1247.json")

eq_mapper = EdgeEquipmentMapper(new_graph, catalog_sys, voltage_mapper, phase_mapper)
```

## Step 8: Build the System

```python
system_builder = DistributionSystemBuilder(
    name="fort_worth_feeder",
    dist_graph=new_graph,
    phase_mapper=phase_mapper,
    voltage_mapper=voltage_mapper,
    equipment_mapper=eq_mapper,
)

system = system_builder.get_system()
print(f"Built system: {system.name}")
```

## Step 9: Export

```python
output = Path("./models")
output.mkdir(exist_ok=True)
system.to_json(output / "fort_worth_feeder.json")
```

## Optional: Visualize

```python
center = GeoLocation(*reversed(ox.geocode("Fort Worth, TX")))
plot_manager = PlotManager(center=center)
add_parcels_to_plot(parcels, plot_manager)
add_distribution_graph_to_plot(new_graph, plot_manager)
plot_manager.show()
```

## Tips

- **Start small** — use a short search distance (200–500 m) when testing a new area.
- **Validate data** — not all locations have good OpenStreetMap building coverage.
- **Equipment sizing** — ensure transformer capacities in the catalog match your load assumptions.
- **Phase balance** — `BalancedPhaseMapper` with `method="greedy"` works well for residential feeders.
- **Error handling** — wrap `parcels_from_location` calls in `try/except` in case the geocoder or Overpass API is unavailable.

## Troubleshooting

| Problem | Solution |
|---------|----------|
| No parcels found | Increase `search_distance` or try a different location |
| Graph is disconnected | Ensure the `source_location` is inside the road network coverage area |
| Equipment mapping errors | Verify that branch types match the catalog; see [Updating Branch Types](updating_branch_type.md) |
