# Routing Strategies

```{admonition} New in v0.7.0
:class: tip
Pluggable routing strategies allow you to control how the primary distribution
network topology is constructed from road network data.
```

## Overview

Distribution networks are typically routed along public roads. The choice of
*how* to select which road segments become power line paths is a key design
decision. SHIFT provides multiple routing formulations drawn from the synthetic
distribution grid generation literature.

Each strategy implements the {class}`~shift.RoutingStrategy` interface and can be
passed to {class}`~shift.PRSG` via the `routing_strategy` parameter.

---

## Available Strategies

### `SteinerTreeStrategy` (default)

Steiner tree approximation with **uniform edge weights**. This is the original
SHIFT algorithm — preserved as the default for backward compatibility.

- **Algorithm**: Mehlhorn approximation of the Steiner tree
- **Edge weights**: All edges weighted equally (weight = 1)
- **Topology**: Minimum-node tree connecting all terminals
- **Trade-off**: Fast, but ignores physical distance → can produce jagged paths

---

### `WeightedSteinerTreeStrategy`

Steiner tree with **geodesic distance** as edge weight. Produces more realistic
routing by preferring physically shorter paths.

- **Algorithm**: Mehlhorn Steiner tree with distance-weighted edges
- **Edge weights**: Geodesic distance (meters) or user-supplied `weight_fn`
- **Topology**: Distance-minimizing tree
- **Trade-off**: Slightly slower, but significantly more realistic paths

```{admonition} Custom weight functions
:class: note
Pass a callable `weight_fn(graph, u, v) -> float` to implement custom weighting
policies such as penalizing road crossings or applying distance-zone penalties
{cite:p}`caetano2026bayesian`.
```

**References**: {cite:t}`ali2023modeling`, {cite:t}`caetano2026bayesian`

---

### `ShortestPathTreeStrategy`

Dijkstra **shortest-path tree** from the source node to all other terminals.

- **Algorithm**: Dijkstra's algorithm from source to each terminal
- **Edge weights**: Geodesic distance or user-supplied `weight_fn`
- **Topology**: Star-like trunk from substation, with shared path segments
- **Trade-off**: Always follows the true shortest road path; may produce longer total wire length than Steiner tree

**Reference**: {cite:t}`ali2023modeling`

---

### `MinimumSpanningTreeStrategy`

**MST over terminals** using pairwise shortest-path distances in the road graph.

- **Algorithm**: (1) Compute all-pairs shortest paths between terminals, (2) Build complete distance graph, (3) Find MST, (4) Map back to road paths
- **Edge weights**: Geodesic distance or user-supplied `weight_fn`
- **Topology**: Trunk-branch (feeder backbone with laterals)
- **Trade-off**: Optimal total wire length; more computation for many terminals

---

### `FullRoadGraphStrategy`

Returns the **full road network** without reduction — power lines follow all available road paths.

- **Algorithm**: Connected-component extraction (no tree reduction)
- **Topology**: Meshed (may contain cycles)
- **Trade-off**: Most realistic for urban networks with redundant paths; not radial

**Reference**: {cite:t}`ali2023modeling`

---

### `CostOptimizedStrategy` *(placeholder)*

**MILP cost-minimization** with binary decision variables per candidate edge.

- **Formulation**: Minimize investment cost + operational losses subject to radiality and AC power flow constraints
- **Status**: Interface defined; implementation requires external solver (PuLP/Pyomo)
- **Use case**: Planning-grade synthetic grids matching utility practice

**Reference**: {cite:t}`trpovski2018synthetic`

---

## Usage Examples

### Basic usage (weighted Steiner tree)

```python
from shift import PRSG, WeightedSteinerTreeStrategy, GeoLocation

builder = PRSG(
    groups=clusters,
    source_location=GeoLocation(-97.3, 32.75),
    routing_strategy=WeightedSteinerTreeStrategy(),
)
graph = builder.get_distribution_graph()
```

### Custom weight function

```python
from shift import WeightedSteinerTreeStrategy
from shift.utils.split_network_edges import get_distance_between_points
from shift.data_model import GeoLocation

def penalized_weight(graph, u, v):
    """Super-linear distance penalty — discourages long edges."""
    dist = get_distance_between_points(
        GeoLocation(graph.nodes[u]["x"], graph.nodes[u]["y"]),
        GeoLocation(graph.nodes[v]["x"], graph.nodes[v]["y"]),
    ).to("m").magnitude
    return dist ** 1.5

strategy = WeightedSteinerTreeStrategy(weight_fn=penalized_weight)
```

### Full road graph (no reduction)

```python
from shift import PRSG, FullRoadGraphStrategy, GeoLocation

builder = PRSG(
    groups=clusters,
    source_location=GeoLocation(-97.3, 32.75),
    routing_strategy=FullRoadGraphStrategy(),
)
```

---

## API Reference

```{eval-rst}
.. currentmodule:: shift

.. autoclass:: RoutingStrategy
   :members:

.. autoclass:: SteinerTreeStrategy
   :members:
   :show-inheritance:

.. autoclass:: WeightedSteinerTreeStrategy
   :members:
   :show-inheritance:

.. autoclass:: ShortestPathTreeStrategy
   :members:
   :show-inheritance:

.. autoclass:: MinimumSpanningTreeStrategy
   :members:
   :show-inheritance:

.. autoclass:: FullRoadGraphStrategy
   :members:
   :show-inheritance:

.. autoclass:: CostOptimizedStrategy
   :members:
   :show-inheritance:
```

---

## References

```{bibliography}
:filter: key % "ali2023" or key % "trpovski2018" or key % "caetano2026"
```
