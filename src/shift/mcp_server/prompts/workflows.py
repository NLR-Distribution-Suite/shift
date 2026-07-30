"""Pre-built prompt templates for common NREL-shift workflows."""

from __future__ import annotations

from mcp.server import MCPServer


def register(mcp: MCPServer) -> None:
    """Register workflow prompt templates."""

    @mcp.prompt()
    def build_feeder_from_location(
        location: str = "Golden, CO",
        distance_meters: float = 300.0,
    ) -> str:
        """End-to-end prompt: build a synthetic distribution feeder from a location.

        Guides the LLM through the full pipeline:
        1. Fetch parcels → 2. Cluster → 3. Build graph → 4. Map phases →
        5. Map voltages → 6. Map equipment → 7. Build system → 8. Export
        """
        return f"""Build a complete synthetic distribution feeder model for the location
"{location}" with a search radius of {distance_meters} meters.

Follow these steps in order:

1. **Fetch parcels**: Use `fetch_parcels` with the location and distance.
2. **Cluster parcels**: Use `cluster_parcels` on the parcel centroids to form
   groups of about 5-10 parcels each.
3. **Build graph**: Use `build_graph_from_groups` with the cluster groups and
   choose an appropriate source (voltage source) location near the center.
4. **Configure phase mapper**: Use `configure_phase_mapper` with the graph.
   Use 3 single-phase transformers per group as a starting configuration.
5. **Configure voltage mapper**: Use `configure_voltage_mapper` with primary
   voltage 12.47 kV and secondary voltage 0.24 kV.
6. **Configure equipment mapper**: Use `configure_equipment_mapper` with the
   default NREL equipment catalog.
7. **Build system**: Use `build_system` to create the final distribution system.
8. **Export**: Use `export_system_json` to save the model.

After each step, report what was created and any relevant statistics.
"""

    @mcp.prompt()
    def inspect_network(graph_id: str = "") -> str:
        """Prompt template for inspecting an existing distribution graph."""
        graph_clause = (
            f'Use graph_id="{graph_id}".'
            if graph_id
            else "First call `list_graphs` to pick a graph."
        )
        return f"""Inspect the distribution graph and provide a detailed summary.

{graph_clause}

1. Query the graph summary (query_type="summary").
2. List all nodes with their asset types.
3. List all edges with their types and lengths.
4. Check if a voltage source exists.
5. Summarise the network topology (tree structure, number of laterals,
   total line length, transformer count).
"""

    @mcp.prompt()
    def explore_api(topic: str = "getting started") -> str:
        """Prompt template for exploring the NREL-shift API documentation."""
        return f"""Help me understand the NREL-shift library, specifically about: {topic}

1. Use `list_docs` to see all available documentation.
2. Use `search_docs` with relevant keywords from my topic.
3. Use `read_doc` to read the most relevant documents.
4. Summarise the key concepts, classes, and functions related to my topic.
5. Provide a short code example if applicable.
"""
