# API Quick Reference

Concise code snippets for every major class and function in NREL-shift. For full details, see the auto-generated [API Reference](references/index.md) or the [Usage Guides](usage/index.md).

---

## Data Models

### GeoLocation

```python
from shift import GeoLocation

location = GeoLocation(longitude=-97.33, latitude=32.75)
```

### ParcelModel

```python
from shift import ParcelModel, GeoLocation

parcel = ParcelModel(
    name="parcel-1",
    geometry=GeoLocation(-97.33, 32.75),
    building_type="residential",
    city="Fort Worth",
    state="TX",
    postal_address="76102",
)
```

### NodeModel

```python
from shift import NodeModel
from infrasys import Location
from gdm import DistributionLoad

node = NodeModel(
    name="node-1",
    location=Location(x=-97.33, y=32.75),
    assets={DistributionLoad},
)
```

### EdgeModel

```python
from shift import EdgeModel
from gdm import DistributionBranchBase
from infrasys.quantities import Distance

edge = EdgeModel(
    name="line-1",
    edge_type=DistributionBranchBase,
    length=Distance(100, "m"),
)
```

---

## Data Fetching

### Fetch Parcels

```python
from shift import parcels_from_location, GeoLocation
from infrasys.quantities import Distance

# By address
parcels = parcels_from_location("Fort Worth, TX", Distance(500, "m"))

# By coordinates
parcels = parcels_from_location(GeoLocation(-97.33, 32.75), Distance(500, "m"))

# By polygon (no distance needed)
polygon = [GeoLocation(-97.33, 32.75), GeoLocation(-97.32, 32.76), GeoLocation(-97.31, 32.75)]
parcels = parcels_from_location(polygon)
```

### Get Road Network

```python
from shift import get_road_network
from infrasys.quantities import Distance

network = get_road_network("Fort Worth, TX", Distance(500, "m"))
# Returns: networkx.Graph
```

---

## Graph Construction

### DistributionGraph

```python
from shift import DistributionGraph, NodeModel, EdgeModel
from gdm import DistributionBranchBase
from infrasys import Location

graph = DistributionGraph()

# Add nodes
graph.add_node(NodeModel(name="n1", location=Location(x=-97.33, y=32.75)))
graph.add_node(NodeModel(name="n2", location=Location(x=-97.32, y=32.76)))

# Add edge
graph.add_edge("n1", "n2", edge_data=EdgeModel(name="line-1", edge_type=DistributionBranchBase))

# Query
all_nodes = graph.get_nodes()                    # generator of NodeModel
node = graph.get_node("n1")                      # single NodeModel
filtered = graph.get_nodes(filter_func=lambda n: n.assets is not None)

all_edges = graph.get_edges()                    # generator of (from, to, EdgeModel)
edge = graph.get_edge("n1", "n2")                # single EdgeModel

# Check existence
graph.has_node("n1")                    # bool

# Mutate
graph.remove_edge("n1", "n2")
graph.remove_node("n1")

# Undirected copy (returns deep copy of internal nx.Graph)
undirected = graph.get_undirected_graph()
```

### PRSG (Road-Network Graph Builder)

```python
from shift import PRSG, GeoLocation, get_kmeans_clusters

clusters = get_kmeans_clusters(5, parcel_points)
builder = PRSG(groups=clusters, source_location=GeoLocation(-97.3, 32.75))
graph = builder.get_distribution_graph()
```

---

## Mappers

### BalancedPhaseMapper

```python
from shift import BalancedPhaseMapper, TransformerPhaseMapperModel, TransformerTypes
from gdm import DistributionTransformer
from infrasys.quantities import ApparentPower

models = [
    TransformerPhaseMapperModel(
        tr_name=edge.name,
        tr_type=TransformerTypes.SPLIT_PHASE,
        tr_capacity=ApparentPower(25, "kilovoltampere"),
        location=graph.get_node(from_node).location,
    )
    for from_node, _, edge in graph.get_edges()
    if edge.edge_type is DistributionTransformer
]

phase_mapper = BalancedPhaseMapper(graph, mapper=models, method="agglomerative")

# Outputs
phase_mapper.node_phase_mapping            # dict[str, set[Phase]]
phase_mapper.transformer_phase_mapping     # dict[str, set[Phase]]
phase_mapper.asset_phase_mapping           # dict[str, dict[type, set[Phase]]]
```

### TransformerVoltageMapper

```python
from shift import TransformerVoltageMapper, TransformerVoltageModel
from gdm import DistributionTransformer
from infrasys.quantities import Voltage

voltage_mapper = TransformerVoltageMapper(
    graph,
    xfmr_voltage=[
        TransformerVoltageModel(
            name=edge.name,
            voltages=[Voltage(7.2, "kilovolt"), Voltage(120, "volt")],
        )
        for _, _, edge in graph.get_edges()
        if edge.edge_type is DistributionTransformer
    ],
)

# Outputs
voltage_mapper.node_voltage_mapping  # dict[str, Voltage]
```

### EdgeEquipmentMapper

```python
from shift import EdgeEquipmentMapper

eq_mapper = EdgeEquipmentMapper(graph, catalog_sys, voltage_mapper, phase_mapper)

# Outputs
eq_mapper.node_asset_equipment_mapping  # dict[str, dict[type, Equipment]]
eq_mapper.edge_equipment_mapping        # dict[str, Equipment]
```

---

## System Builder

```python
from shift import DistributionSystemBuilder

builder = DistributionSystemBuilder(
    name="my_feeder",
    dist_graph=graph,
    phase_mapper=phase_mapper,
    voltage_mapper=voltage_mapper,
    equipment_mapper=eq_mapper,
)

system = builder.get_system()        # returns a DistributionSystem (GDM)
system.to_json("model.json")
```

---

## Utility Functions

### K-Means Clustering

```python
from shift import get_kmeans_clusters, GeoLocation

points = [GeoLocation(-97.33, 32.75), GeoLocation(-97.32, 32.76), GeoLocation(-97.31, 32.77)]
clusters = get_kmeans_clusters(num_cluster=2, points=points)

for cluster in clusters:
    print(f"Center: {cluster.center}, Members: {len(cluster.points)}")
```

### Nearest Points

```python
from shift import get_nearest_points

nearest = get_nearest_points(
    source=[[1, 2], [2, 3], [3, 4]],
    target=[[4, 5], [0.5, 1.5]],
)
# Returns: numpy array of nearest source points for each target
```

### Mesh Network

```python
from shift import get_mesh_network, GeoLocation
from infrasys.quantities import Distance

mesh = get_mesh_network(GeoLocation(-97.33, 32.75), GeoLocation(-97.32, 32.76), Distance(100, "m"))
# Returns: networkx.Graph
```

### Split Network Edges

```python
from shift import split_network_edges
from infrasys.quantities import Distance
import networkx as nx

g = nx.Graph()
g.add_node("a", x=-97.33, y=32.75)
g.add_node("b", x=-97.32, y=32.76)
g.add_edge("a", "b")

split_network_edges(g, split_length=Distance(50, "m"))
```

### Polygon from Points

```python
from shift import get_polygon_from_points
from infrasys.quantities import Distance

polygon = get_polygon_from_points([[-97.33, 32.75], [-97.32, 32.76]], Distance(20, "m"))
# Returns: shapely.Polygon
```

---

## Visualization

```python
from shift import (
    PlotManager,
    GeoLocation,
    add_parcels_to_plot,
    add_distribution_graph_to_plot,
    add_phase_mapper_to_plot,
    add_voltage_mapper_to_plot,
)

plot_manager = PlotManager(center=GeoLocation(-97.33, 32.75))

add_parcels_to_plot(parcels, plot_manager)
add_distribution_graph_to_plot(graph, plot_manager)
add_phase_mapper_to_plot(phase_mapper, plot_manager)
add_voltage_mapper_to_plot(voltage_mapper, plot_manager)

plot_manager.show()
```

---

## Constants

```python
from shift import TransformerTypes

TransformerTypes.THREE_PHASE
TransformerTypes.SINGLE_PHASE
TransformerTypes.SPLIT_PHASE
TransformerTypes.SINGLE_PHASE_PRIMARY_DELTA
TransformerTypes.SPLIT_PHASE_PRIMARY_DELTA
```

```python
from shift import VALID_NODE_TYPES, VALID_EDGE_TYPES

# VALID_NODE_TYPES: DistributionLoad, DistributionSolar,
#                   DistributionCapacitor, DistributionVoltageSource
# VALID_EDGE_TYPES: DistributionBranchBase, DistributionTransformer
```

---

## Exceptions

All exceptions inherit from `ShiftException`.

```python
from shift.exceptions import (
    # Base
    ShiftException,

    # Graph errors
    GraphError,
    NodeAlreadyExists,
    NodeDoesNotExist,
    EdgeAlreadyExists,
    EdgeDoesNotExist,
    VsourceNodeAlreadyExists,
    VsourceNodeDoesNotExist,
    EmptyGraphError,
    InvalidNodeDataError,
    InvalidEdgeDataError,

    # Input errors
    InvalidInputError,
    InvalidAssetPhase,

    # Mapper errors
    MapperError,
    AllocationMappingError,
    InvalidPhaseAllocationMethod,
    MissingTransformerMapping,
    UnsupportedTransformerType,
    MissingVoltageMappingError,
    UnsupportedBranchEquipmentType,

    # Equipment errors
    EquipmentError,
    EquipmentNotFoundError,
    WrongEquipmentAssigned,

    # System builder errors
    SystemBuildError,
    UnsupportedEdgeTypeError,
    WindingMismatchError,
    InvalidSplitPhaseWindingError,
)

try:
    graph.add_node(existing_node)
except NodeAlreadyExists as e:
    print(e)
```

---

## See Also

- [Complete Example](usage/complete_example.md) — End-to-end workflow
- [Usage Guides](usage/index.md) — Step-by-step guides for each stage
- [Auto-generated API Docs](references/index.md) — Full docstring reference
