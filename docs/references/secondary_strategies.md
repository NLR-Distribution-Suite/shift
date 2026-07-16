# Secondary Network Strategies

```{admonition} New in v0.7.0
:class: tip
Pluggable secondary network strategies allow you to control how loads are
connected to their serving transformer.
```

## Overview

The secondary (low-voltage) network connects individual customer loads to their
distribution transformer. Different topologies suit different deployment contexts
— dense urban areas may follow road paths, while rural residential areas typically
use simple radial connections.

Each strategy implements the {class}`~shift.SecondaryNetworkStrategy` interface and
can be passed to {class}`~shift.PRSG` via the `secondary_strategy` parameter.

---

## Available Strategies

### `MeshSteinerStrategy` (default)

**Rectangular mesh grid** + Steiner tree reduction. The original SHIFT algorithm.

- **Algorithm**: Build 2D grid in group bounding box, find Steiner tree to connect load points
- **Topology**: Grid-aligned tree (right-angle connections)
- **Parameters**: `spacing` (default 50m)
- **Trade-off**: Works well for uniform areas; produces right-angle artifacts

---

### `RadialStrategy`

**Direct star connection** from transformer to each load.

- **Algorithm**: Create center node at transformer location, connect each load directly
- **Topology**: Pure radial star (1 hop from transformer to each load)
- **Trade-off**: Simplest and most common real-world residential lateral topology; no intermediate nodes

**References**: {cite:t}`shahraeini2023algorithm`, {cite:t}`bidel2021synthetic`

---

### `DelaunayStrategy`

**Delaunay triangulation** of load points with MST pruning.

- **Algorithm**: (1) Triangulate all points (loads + center), (2) Weight edges by geodesic distance, (3) Extract MST
- **Topology**: Organic, non-grid tree following natural point clusters
- **Trade-off**: More natural-looking than mesh; requires ≥3 non-collinear points (falls back to radial otherwise)

---

### `OpenStreetSecondaryStrategy`

**Road-aware** secondary routing using local OpenStreetMap roads.

- **Algorithm**: Fetch local road network for group area, route using a configurable {class}`~shift.RoutingStrategy` (default: `WeightedSteinerTreeStrategy`)
- **Parameters**: `routing_strategy`, `buffer` (default 50m)
- **Topology**: Follows actual street layout
- **Trade-off**: Most realistic for urban areas; requires network fetch per group (slower)

**References**: {cite:t}`ali2023modeling`, {cite:t}`caetano2026bayesian`

---

### `HubLineStrategy`

**k-nearest-neighbor** consumer-to-transformer assignment.

- **Algorithm**: Sort loads by distance to transformer center (hub), connect each directly
- **Topology**: Star topology with loads ordered by proximity
- **Trade-off**: Similar output to `RadialStrategy` but preserves distance-ordering information; mirrors utility hub-line assignment practice

**Reference**: {cite:t}`ali2023modeling`

---

## Usage Examples

### Radial secondary (simplest)

```python
from shift import PRSG, RadialStrategy, GeoLocation

builder = PRSG(
    groups=clusters,
    source_location=GeoLocation(-97.3, 32.75),
    secondary_strategy=RadialStrategy(),
)
graph = builder.get_distribution_graph()
```

### Road-aware secondary

```python
from shift import PRSG, OpenStreetSecondaryStrategy, GeoLocation

builder = PRSG(
    groups=clusters,
    source_location=GeoLocation(-97.3, 32.75),
    secondary_strategy=OpenStreetSecondaryStrategy(),
)
graph = builder.get_distribution_graph()
```

### Combining strategies

```python
from shift import (
    PRSG,
    WeightedSteinerTreeStrategy,
    HubLineStrategy,
    GeoLocation,
)

builder = PRSG(
    groups=clusters,
    source_location=GeoLocation(-97.3, 32.75),
    routing_strategy=WeightedSteinerTreeStrategy(),  # primary
    secondary_strategy=HubLineStrategy(),            # secondary
)
graph = builder.get_distribution_graph()
```

---

## API Reference

```{eval-rst}
.. currentmodule:: shift

.. autoclass:: SecondaryNetworkStrategy
   :members:

.. autoclass:: MeshSteinerStrategy
   :members:
   :show-inheritance:

.. autoclass:: RadialStrategy
   :members:
   :show-inheritance:

.. autoclass:: DelaunayStrategy
   :members:
   :show-inheritance:

.. autoclass:: OpenStreetSecondaryStrategy
   :members:
   :show-inheritance:

.. autoclass:: HubLineStrategy
   :members:
   :show-inheritance:
```

---

## References

```{bibliography}
:filter: key % "ali2023" or key % "shahraeini2023" or key % "bidel2021" or key % "caetano2026"
```
