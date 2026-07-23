# Usage Guides

Step-by-step guides for building distribution system models with NREL-shift. Each guide covers one stage of the workflow.

**New to NREL-shift?** Start with the [Complete Example](complete_example.md) to see the full pipeline from data fetching to system export.

## Workflow Order

The guides are listed in the order you would typically follow:

1. [Fetching Parcels](fetching_parcels.md) — Load building locations from OpenStreetMap, CSV, or GeoDataFrames
2. [Building a Graph](building_graph.md) — Cluster parcels and construct a distribution graph
3. [Updating Branch Types](updating_branch_type.md) — Replace generic branch types with specific equipment models
4. [Mapping Phases](mapping_phases.md) — Assign phases to transformer secondaries
5. [Mapping Voltages](mapping_voltages.md) — Assign primary and secondary voltage levels
6. [Mapping Equipment](mapping_equipment.md) — Map loads, sources, and catalog equipment to nodes
7. [Building a System](building_system.md) — Assemble everything into a Grid Data Models system
8. [UI Studio](ui_studio.md) — Run the browser UI and iterate on routing/secondary strategies interactively