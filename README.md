[![Tests](https://github.com/NLR-Distribution-Suite/shift/actions/workflows/tests.yml/badge.svg)](https://github.com/NLR-Distribution-Suite/shift/actions/workflows/tests.yml) • [![Pytest](https://github.com/NLR-Distribution-Suite/shift/actions/workflows/pull_request_tests.yml/badge.svg)](https://github.com/NLR-Distribution-Suite/shift/actions/workflows/pull_request_tests.yml) • [![Documentation](https://github.com/NLR-Distribution-Suite/shift/actions/workflows/gh-pages.yml/badge.svg)](https://github.com/NLR-Distribution-Suite/shift/actions/workflows/gh-pages.yml) • [![Upload to PyPi](https://github.com/NLR-Distribution-Suite/shift/actions/workflows/publish_to_pypi.yaml/badge.svg)](https://github.com/NLR-Distribution-Suite/shift/actions/workflows/publish_to_pypi.yaml) • ![PyPI Downloads](https://img.shields.io/pypi/dm/nrel-shift) • ![License](https://img.shields.io/github/license/NLR-Distribution-Suite/shift) • ![Issues](https://img.shields.io/github/issues/NLR-Distribution-Suite/shift) • ![CodeFactor](https://www.codefactor.io/repository/github/NLR-Distribution-Suite/shift/badge) • ![Codecov](https://img.shields.io/codecov/c/github/NLR-Distribution-Suite/shift) • ![MCP Server](https://img.shields.io/badge/MCP_Server-enabled-brightgreen) • ![MCP Tools](https://img.shields.io/badge/MCP_Tools-33-blue) • [![PyPI Downloads](https://static.pepy.tech/personalized-badge/nrel-shift?period=total&units=INTERNATIONAL_SYSTEM&left_color=BLACK&right_color=GREEN&left_text=downloads)](https://pepy.tech/projects/nrel-shift)

# NREL-shift

A Python framework for building synthetic power distribution feeder models from open-source geospatial data. NREL-shift fetches building parcels and road networks from OpenStreetMap, constructs graph-based network topologies, and exports simulator-ready models through [Grid Data Models](https://github.com/NLR-Distribution-Suite/grid-data-models) and [Ditto](https://github.com/NLR-Distribution-Suite/ditto).

## Features

- **Automated Feeder Generation** — Build distribution feeder models directly from OpenStreetMap data
- **Graph-Based Network Modeling** — Represent distribution networks as NetworkX graphs with typed nodes and edges
- **Equipment Mapping** — Assign transformers, loads, and other equipment to network components
- **Phase Balancing** — Automatically balance phases across distribution transformers
- **Voltage Mapping** — Assign voltage levels throughout the distribution network based on transformer topology
- **Visualization** — Built-in Plotly-based plotting for parcels, networks, and phase/voltage overlays
- **Interactive UI Studio** — Browser-based workflow for parcel fetch, clustering, strategy selection, graph build, and side-by-side comparisons
- **Simulator Export** — Write models to OpenDSS, CYME, Synergi, and other simulators via Grid Data Models

## Installation

### From PyPI

```bash
pip install nrel-shift
```

### From Source

```bash
git clone https://github.com/NLR-Distribution-Suite/shift.git
cd shift
pip install -e .
```

### Optional Extras

```bash
# Development (testing + linting)
pip install -e ".[dev]"

# Documentation
pip install -e ".[doc]"

# MCP server (AI agent integration)
pip install -e ".[mcp]"

# UI API + browser studio
pip install -e ".[ui]"

# Everything
pip install -e ".[dev,doc,mcp,ui]"
```

## UI Studio

NREL-shift includes a FastAPI-backed UI that exposes core modeling workflows through a browser interface.

```bash
pip install -e ".[ui]"
shift-ui-server
```

Open `http://127.0.0.1:8000` to access the UI. The first vertical slice includes:

- map-assisted source selection,
- parcel fetch and clustering,
- routing/secondary strategy selection,
- graph build and strategy comparison,
- mapper/system build endpoints ready for UI wiring.

## Quick Start

The typical workflow has four stages: **fetch data → build graph → configure mappers → build system**.

### 1. Fetch Parcels and Road Network

```python
from shift import parcels_from_location, get_road_network, GeoLocation
from gdm.quantities import Distance

# Fetch building parcels from OpenStreetMap
parcels = parcels_from_location("Fort Worth, TX", Distance(500, "m"))

# Fetch the road network for the same area
road_network = get_road_network("Fort Worth, TX", Distance(500, "m"))
```

You can also pass coordinates instead of an address:

```python
location = GeoLocation(longitude=-97.3, latitude=32.75)
parcels = parcels_from_location(location, Distance(500, "m"))
```

### 2. Build a Distribution Graph

```python
from shift import get_kmeans_clusters, PRSG, GeoLocation

# Cluster parcels for transformer placement (~2 customers per transformer)
parcel_points = [
    p.geometry[0] if isinstance(p.geometry, list) else p.geometry
    for p in parcels
]
clusters = get_kmeans_clusters(max(len(parcels) // 2, 1), parcel_points)

# Build the distribution graph from clusters and road network
builder = PRSG(
    groups=clusters,
    source_location=GeoLocation(-97.3, 32.75),
)
graph = builder.get_distribution_graph()
```

### 3. Configure Mappers and Build the System

```python
from shift import (
    BalancedPhaseMapper,
    TransformerVoltageMapper,
    EdgeEquipmentMapper,
    DistributionSystemBuilder,
    TransformerPhaseMapperModel,
    TransformerVoltageModel,
    TransformerTypes,
)
from gdm import DistributionTransformer
from gdm.quantities import ApparentPower, Voltage

# Phase mapper — assign phases to transformer secondaries
transformer_phase_models = [
    TransformerPhaseMapperModel(
        tr_name=edge.name,
        tr_type=TransformerTypes.SPLIT_PHASE,
        tr_capacity=ApparentPower(25, "kilovoltampere"),
        location=graph.get_node(from_node).location,
    )
    for from_node, _, edge in graph.get_edges()
    if edge.edge_type is DistributionTransformer
]
phase_mapper = BalancedPhaseMapper(graph, mapper=transformer_phase_models, method="agglomerative")

# Voltage mapper — assign primary/secondary voltages
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

# Build the system
from pathlib import Path
from gdm import DistributionSystem
import shift

MODELS_FOLDER = Path(shift.__file__).parent.parent.parent / "tests" / "models"
catalog_sys = DistributionSystem.from_json(MODELS_FOLDER / "p1rhs7_1247.json")

system = DistributionSystemBuilder(
    name="fort_worth_feeder",
    dist_graph=graph,
    phase_mapper=phase_mapper,
    voltage_mapper=voltage_mapper,
    equipment_mapper=EdgeEquipmentMapper(graph, catalog_sys, voltage_mapper, phase_mapper),
)
distribution_system = system.get_system()
```

See the [Complete Example](./docs/usage/complete_example.md) for a full end-to-end walkthrough.

## Documentation

### User Guides

These guides walk through individual stages of the workflow:

| Guide | Description |
|-------|-------------|
| [Complete Example](./docs/usage/complete_example.md) | End-to-end workflow from data fetching to system export |
| [Fetching Parcels](./docs/usage/fetching_parcels.md) | Loading building parcels from CSV, addresses, or GeoDataFrames |
| [Building a Graph](./docs/usage/building_graph.md) | Constructing distribution graphs from clustered parcels |
| [Updating Branch Types](./docs/usage/updating_branch_type.md) | Changing edge types for specific equipment models |
| [Mapping Phases](./docs/usage/mapping_phases.md) | Assigning phases with balanced or custom mappers |
| [Mapping Voltages](./docs/usage/mapping_voltages.md) | Assigning voltage levels via transformer topology |
| [Mapping Equipment](./docs/usage/mapping_equipment.md) | Mapping loads, sources, and catalog equipment |
| [Building a System](./docs/usage/building_system.md) | Assembling the final distribution system model |
| [UI Studio](./docs/usage/ui_studio.md) | Running and using the browser-based UI/API workflow |

### MCP Server (AI Agent Integration)

NREL-shift includes an MCP server for use with LLM-based agents. See the [MCP Server Guide](./docs/MCP_SERVER.md) for setup and usage.

### Developer Resources

- [API Reference](./docs/API_REFERENCE.md) — Quick lookup for all classes and functions
- [Contributing](./CONTRIBUTING.md) — Development workflow and code style guidelines
- [Quick Start for Contributors](./QUICKSTART.md) — Fast-track development setup

## Running Tests

```bash
pip install -e ".[dev]"

pytest                              # Run all tests
pytest --cov=shift --cov-report=html  # With coverage report
pytest tests/test_graph.py          # Single test file
pytest -m "not slow"                # Skip slow tests
```

## Requirements

- Python >= 3.10
- [OSMnx](https://osmnx.readthedocs.io/) — OpenStreetMap data access
- [NetworkX](https://networkx.org/) — Graph operations
- [Grid Data Models](https://github.com/NLR-Distribution-Suite/grid-data-models) — Power system component models
- See [pyproject.toml](./pyproject.toml) for the complete dependency list

## License

BSD-3-Clause — see [LICENSE.txt](./LICENSE.txt).

## Authors

- Kapil Duwadi (Kapil.Duwadi@nlr.gov)
- Aadil Latif (Aadil.Latif@nlr.gov)
- Erik Pohl (Erik.Pohl@nlr.gov)

## Citation

```bibtex
@software{nrel_shift,
  title = {NREL-shift: Framework for Developing Synthetic Distribution Feeder Models},
  author = {Duwadi, Kapil and Latif, Aadil and Pohl, Erik},
  year = {2026},
  url = {https://github.com/NLR-Distribution-Suite/shift}
}
```

## Support

- [Open an issue](https://github.com/NLR-Distribution-Suite/shift/issues) for bugs and feature requests
- [Discussions](https://github.com/NLR-Distribution-Suite/shift/discussions) for questions
