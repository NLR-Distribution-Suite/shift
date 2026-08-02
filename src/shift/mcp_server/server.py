"""NREL-shift MCP Server — main application wiring."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from mcp.server import MCPServer

from shift.mcp_server.state import AppContext


# ---------------------------------------------------------------------------
# Documentation indexer
# ---------------------------------------------------------------------------

# Map of doc key → relative path from project root
_DOC_FILES: dict[str, str] = {
    "readme": "README.md",
    "quickstart": "QUICKSTART.md",
    "contributing": "CONTRIBUTING.md",
    "api_reference": "docs/API_REFERENCE.md",
    # Usage guides
    "usage/index": "docs/usage/index.md",
    "usage/building_graph": "docs/usage/building_graph.md",
    "usage/building_system": "docs/usage/building_system.md",
    "usage/complete_example": "docs/usage/complete_example.md",
    "usage/fetching_parcels": "docs/usage/fetching_parcels.md",
    "usage/mapping_equipment": "docs/usage/mapping_equipment.md",
    "usage/mapping_phases": "docs/usage/mapping_phases.md",
    "usage/mapping_voltages": "docs/usage/mapping_voltages.md",
    "usage/updating_branch_type": "docs/usage/updating_branch_type.md",
    # Module references
    "references/index": "docs/references/index.md",
    "references/clustering": "docs/references/clustering.md",
    "references/data_model": "docs/references/data_model.md",
    "references/dist_graph": "docs/references/dist_graph.md",
    "references/mesh_network": "docs/references/mesh_network.md",
    "references/nearest_points": "docs/references/nearest_points.md",
    "references/openstreet_graph": "docs/references/openstreet_graph.md",
    "references/openstreet_parcel": "docs/references/openstreet_parcel.md",
    "references/openstreet_roads": "docs/references/openstreet_roads.md",
    "references/plot_manager": "docs/references/plot_manager.md",
    "references/plots": "docs/references/plots.md",
    "references/polygon_from_points": "docs/references/polygon_from_points.md",
    "references/split_edges": "docs/references/split_edges.md",
    # RST reference files
    "references/equipment_mapper": "docs/references/equipment_mapper.rst",
    "references/phase_mapper": "docs/references/phase_mapper.rst",
    "references/system_builder": "docs/references/system_builder.rst",
    "references/voltage_mapper": "docs/references/voltage_mapper.rst",
}

_DOC_DESCRIPTIONS: dict[str, str] = {
    "readme": "Project overview, features, and installation instructions.",
    "quickstart": "Quick-start guide to get up and running.",
    "contributing": "Contribution guidelines.",
    "api_reference": "Full API reference documentation.",
    "usage/index": "Usage guides table of contents.",
    "usage/building_graph": "How to build a distribution graph.",
    "usage/building_system": "How to build a distribution system.",
    "usage/complete_example": "Complete end-to-end workflow example.",
    "usage/fetching_parcels": "How to fetch parcels from OpenStreetMap.",
    "usage/mapping_equipment": "How to map equipment to graph edges.",
    "usage/mapping_phases": "How to assign phases to transformers.",
    "usage/mapping_voltages": "How to assign voltages to transformers.",
    "usage/updating_branch_type": "How to update branch types.",
    "references/index": "Module reference table of contents.",
    "references/clustering": "get_kmeans_clusters utility reference.",
    "references/data_model": "Data model (GeoLocation, ParcelModel, etc.) reference.",
    "references/dist_graph": "DistributionGraph class reference.",
    "references/mesh_network": "Mesh network utility reference.",
    "references/nearest_points": "Nearest-point matching utility reference.",
    "references/openstreet_graph": "OpenStreetGraphBuilder reference.",
    "references/openstreet_parcel": "Parcel fetcher reference.",
    "references/openstreet_roads": "Road network fetcher reference.",
    "references/plot_manager": "Plot manager reference.",
    "references/plots": "Plotting utilities reference.",
    "references/polygon_from_points": "Polygon-from-points utility reference.",
    "references/split_edges": "Edge splitting utility reference.",
    "references/equipment_mapper": "Equipment mapper classes reference.",
    "references/phase_mapper": "Phase mapper classes reference.",
    "references/system_builder": "DistributionSystemBuilder reference.",
    "references/voltage_mapper": "Voltage mapper classes reference.",
}


def _index_docs(project_root: Path) -> tuple[dict[str, str], dict[str, str]]:
    """Read all documentation files into an in-memory index."""
    docs_index: dict[str, str] = {}
    docs_descriptions: dict[str, str] = {}

    for key, rel_path in _DOC_FILES.items():
        full_path = project_root / rel_path
        if full_path.exists():
            try:
                docs_index[key] = full_path.read_text(encoding="utf-8")
                docs_descriptions[key] = _DOC_DESCRIPTIONS.get(key, "")
            except OSError:
                continue  # Skip files that can't be read

    return docs_index, docs_descriptions


# ---------------------------------------------------------------------------
# Lifespan context — sets up AppContext for the session
# ---------------------------------------------------------------------------


@asynccontextmanager
async def app_lifespan(server: MCPServer) -> AsyncIterator[AppContext]:
    """Initialise session state: load config, index docs, yield context."""
    from shift.mcp_server.resources.docs import set_app_context

    project_root = Path(__file__).resolve().parent.parent
    docs_index, docs_descriptions = _index_docs(project_root)

    ctx = AppContext()
    ctx.docs_index = docs_index
    ctx.docs_descriptions = docs_descriptions

    set_app_context(ctx)
    yield ctx


# ---------------------------------------------------------------------------
# Build the MCPServer application
# ---------------------------------------------------------------------------


def create_server() -> MCPServer:
    """Create and configure the MCPServer server instance."""
    mcp = MCPServer(
        "nrel-shift",
        instructions=(
            "NREL-shift MCP server for building synthetic power distribution "
            "feeder models from OpenStreetMap geospatial data. Use the tools "
            "to fetch data, build graphs, configure mappers, build systems, "
            "and query project documentation."
        ),
        lifespan=app_lifespan,
    )

    # -- Register tool modules -------------------------------------------------
    from shift.mcp_server.tools.data_acquisition import parcels, roads, clustering
    from shift.mcp_server.tools.graph import (
        management,
        nodes,
        edges,
        query,
        builder,
        route_existing,
        layout_existing,
    )
    from shift.mcp_server.tools.mapper import phase, voltage, equipment
    from shift.mcp_server.tools.system import builder as sys_builder, export
    from shift.mcp_server.tools.utilities import geo, network, nearest
    from shift.mcp_server.tools.documentation import search, read

    parcels.register(mcp)
    roads.register(mcp)
    clustering.register(mcp)

    management.register(mcp)
    nodes.register(mcp)
    edges.register(mcp)
    query.register(mcp)
    builder.register(mcp)
    route_existing.register(mcp)
    layout_existing.register(mcp)

    phase.register(mcp)
    voltage.register(mcp)
    equipment.register(mcp)

    sys_builder.register(mcp)
    export.register(mcp)

    geo.register(mcp)
    network.register(mcp)
    nearest.register(mcp)

    search.register(mcp)
    read.register(mcp)

    # -- Register resources ----------------------------------------------------
    from shift.mcp_server.resources import docs as docs_resource

    docs_resource.register(mcp)

    # -- Register prompts ------------------------------------------------------
    from shift.mcp_server.prompts import workflows

    workflows.register(mcp)

    return mcp
