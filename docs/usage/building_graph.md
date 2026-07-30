# Building a Distribution Graph

Once you have a list of `ParcelModel` objects (see [Fetching Parcels](fetching_parcels.md)), the next step is to construct a `DistributionGraph` — the connectivity model of nodes and edges that represents the distribution network.

## Cluster Parcels

First, cluster parcels into groups. Each cluster center becomes a candidate distribution transformer location. A common heuristic is roughly two customers per transformer, but you can adjust this to match your design criteria.

```python
from shift import ParcelModel, GeoLocation, get_kmeans_clusters

def _get_parcel_points(parcels: list[ParcelModel]) -> list[GeoLocation]:
    """Extract a single GeoLocation per parcel (centroid for polygons)."""
    return [
        el.geometry[0] if isinstance(el.geometry, list) else el.geometry
        for el in parcels
    ]

num_clusters = max(len(parcels) // 2, 1)
clusters = get_kmeans_clusters(num_clusters, _get_parcel_points(parcels))
```

## Build the Graph with PRSG

`PRSG` (Primary–Secondary Road-network Graph) builds the distribution graph in two steps:

1. **Primary network** — derived by routing through the road network in the area using a configurable {class}`~shift.RoutingStrategy`.
2. **Secondary network** — built using a configurable {class}`~shift.SecondaryNetworkStrategy` connecting transformer locations to nearby customer parcels.

The node closest to `source_location` is treated as the substation.

```python
from shift import PRSG, GeoLocation

builder = PRSG(
    groups=clusters,
    source_location=GeoLocation(-97.3, 32.75),  # substation coordinates
)
graph = builder.get_distribution_graph()
```

## Choosing a Routing Strategy

By default, PRSG uses a Steiner tree with uniform edge weights. For more realistic
routing that follows shorter physical paths, use {class}`~shift.WeightedSteinerTreeStrategy`:

```python
from shift import PRSG, WeightedSteinerTreeStrategy, GeoLocation

builder = PRSG(
    groups=clusters,
    source_location=GeoLocation(-97.3, 32.75),
    routing_strategy=WeightedSteinerTreeStrategy(),
)
graph = builder.get_distribution_graph()
```

Available routing strategies (see [Routing Strategies](../references/routing_strategies.md) for details):

- **`SteinerTreeStrategy`** — Steiner tree, uniform weights (default, backward-compatible)
- **`WeightedSteinerTreeStrategy`** — Steiner tree, geodesic distance weights {cite:p}`ali2023modeling`
- **`ShortestPathTreeStrategy`** — Dijkstra shortest-path tree from source {cite:p}`ali2023modeling`
- **`MinimumSpanningTreeStrategy`** — MST over terminals via shortest paths
- **`FullRoadGraphStrategy`** — Full road network as topology {cite:p}`ali2023modeling`

## Choosing a Secondary Network Strategy

By default, PRSG uses a rectangular mesh grid with Steiner tree reduction. For
simpler radial laterals or road-aware secondary routing:

```python
from shift import PRSG, RadialStrategy, GeoLocation

builder = PRSG(
    groups=clusters,
    source_location=GeoLocation(-97.3, 32.75),
    secondary_strategy=RadialStrategy(),
)
graph = builder.get_distribution_graph()
```

Available secondary strategies (see [Secondary Strategies](../references/secondary_strategies.md) for details):

- **`MeshSteinerStrategy`** — Rectangular mesh + Steiner tree (default)
- **`RadialStrategy`** — Direct star connection from transformer to loads
- **`DelaunayStrategy`** — Delaunay triangulation + MST pruning
- **`OpenStreetSecondaryStrategy`** — Routes secondary along actual roads {cite:p}`caetano2026bayesian`
- **`HubLineStrategy`** — k-NN consumer-to-transformer assignment {cite:p}`ali2023modeling`

## Visualize the Graph

You can overlay the distribution graph on the parcel plot from the previous step:

```python
from shift import add_distribution_graph_to_plot, PlotManager, GeoLocation
import osmnx as ox

center = GeoLocation(*reversed(ox.geocode("Fort Worth, TX")))
plot_manager = PlotManager(center=center)
add_distribution_graph_to_plot(graph, plot_manager)
plot_manager.show()
```

## Next Step

Proceed to [Updating Branch Types](updating_branch_type.md) to replace generic branch types with the specific equipment models your simulation requires.