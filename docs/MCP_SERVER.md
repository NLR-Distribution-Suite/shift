# MCP Server

NREL-shift includes a [Model Context Protocol](https://modelcontextprotocol.io/) (MCP) server that exposes the full framework to LLM-based agents. The server provides 36 tools, 3 resource templates, and 3 prompt templates that enable AI assistants to build synthetic distribution feeder models interactively.

## Installation

Install the MCP optional dependencies:

```bash
pip install -e ".[mcp]"
```

## Running the Server

```bash
# Via console script
shift-mcp-server

# Via Python module
python -m shift.mcp_server
```

The server uses **stdio** transport by default.

### Claude Desktop Configuration

Add the following to your Claude Desktop config (`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS):

```json
{
  "mcpServers": {
    "nrel-shift": {
      "command": "shift-mcp-server"
    }
  }
}
```

## Architecture

```
src/shift/mcp_server/
├── __init__.py
├── __main__.py          # Entry point
├── server.py            # FastMCP instance, lifespan, registration
├── config.py            # ServerConfig (Pydantic model)
├── state.py             # AppContext — in-memory session state
├── serializers.py       # JSON serialization helpers
├── tools/
│   ├── data_acquisition/
│   │   ├── parcels.py       # fetch_parcels, fetch_parcels_in_polygon
│   │   ├── roads.py         # fetch_road_network
│   │   └── clustering.py    # cluster_parcels
│   ├── graph/
│   │   ├── management.py    # create_graph, delete_graph, list_graphs
│   │   ├── nodes.py         # add_node, remove_node, get_node
│   │   ├── edges.py         # add_edge, remove_edge, get_edge
│   │   ├── query.py         # query_graph
│   │   └── builder.py       # build_graph_from_groups
│   ├── mapper/
│   │   ├── phase.py         # configure_phase_mapper, get_phase_mapping
│   │   ├── voltage.py       # configure_voltage_mapper, get_voltage_mapping
│   │   └── equipment.py     # configure_equipment_mapper, get_equipment_mapping
│   ├── system/
│   │   ├── builder.py       # build_system, get_system_summary, list_systems
│   │   └── export.py        # export_system_json
│   ├── utilities/
│   │   ├── geo.py           # distance_between_points, polygon_from_points
│   │   ├── network.py       # create_mesh_network, split_edges
│   │   └── nearest.py       # find_nearest_points
│   └── documentation/
│       ├── search.py        # search_docs
│       └── read.py          # list_docs, read_doc
├── resources/
│   └── docs.py              # shift://docs, shift://docs/{name}, shift://graphs
└── prompts/
    └── workflows.py         # build_feeder_from_location, inspect_network, explore_api
```

## Session State

The server is **stateful** — graphs, mappers, and systems are held in memory for the duration of a session via the `AppContext` dataclass. Each tool receives the context through FastMCP's lifespan mechanism.

Key state containers:

| Container | Type | Contents |
|-----------|------|----------|
| `graphs` | `dict[str, DistributionGraph]` | In-memory distribution graphs |
| `phase_mappers` | `dict[str, BalancedPhaseMapper]` | Phase mapper instances |
| `voltage_mappers` | `dict[str, TransformerVoltageMapper]` | Voltage mapper instances |
| `equipment_mappers` | `dict[str, EdgeEquipmentMapper]` | Equipment mapper instances |
| `systems` | `dict[str, DistributionSystem]` | Built distribution systems |
| `docs_index` | `dict[str, str]` | Indexed documentation content |

## Tools Reference

### Data Acquisition (5 tools)

| Tool | Description |
|------|-------------|
| `fetch_parcels` | Fetch building parcels from OpenStreetMap for a given location |
| `fetch_parcels_in_polygon` | Fetch building parcels within a polygon boundary |
| `set_local_pbf` | Configure a local OpenStreetMap PBF for offline parcel extraction |
| `fetch_road_network` | Fetch the road network from OpenStreetMap around a location |
| `cluster_parcels` | Cluster geographic points into groups |

### Graph Management (13 tools)

| Tool | Description |
|------|-------------|
| `create_graph` | Create a new empty distribution graph |
| `delete_graph` | Delete a distribution graph and its associated mappers |
| `list_graphs` | List all distribution graphs in the current session |
| `add_node` | Add a node to a distribution graph |
| `remove_node` | Remove a node from a distribution graph |
| `get_node` | Get details of a specific node |
| `add_edge` | Add an edge (line or transformer) to a distribution graph |
| `remove_edge` | Remove an edge from a distribution graph |
| `get_edge` | Get details of a specific edge |
| `query_graph` | Query information about a distribution graph (summary, nodes, edges, vsource, dfs_tree) |
| `build_graph_from_groups` | Build a complete distribution graph from parcel groups using the PRSG algorithm |
| `route_existing_graph` | Route an existing graph using a selected routing strategy |
| `layout_existing_graph` | Layout an existing graph using a selected secondary-network strategy |

### Mappers (6 tools)

| Tool | Description |
|------|-------------|
| `configure_phase_mapper` | Configure balanced phase mapping for a distribution graph |
| `get_phase_mapping` | Get phase assignments (nodes, assets, or transformers) |
| `configure_voltage_mapper` | Configure voltage mapping for a distribution graph |
| `get_voltage_mapping` | Get voltage assignments for all nodes |
| `configure_equipment_mapper` | Configure equipment mapping using an equipment catalog |
| `get_equipment_mapping` | Get equipment assignments for all edges |

### System (4 tools)

| Tool | Description |
|------|-------------|
| `build_system` | Build a complete distribution system from a configured graph |
| `get_system_summary` | Get a summary of a built distribution system |
| `list_systems` | List all built distribution systems in the current session |
| `export_system_json` | Export a distribution system to JSON format |

### Utilities (5 tools)

| Tool | Description |
|------|-------------|
| `distance_between_points` | Calculate geodesic distance between two points |
| `polygon_from_points` | Create a polygon boundary from a set of points |
| `create_mesh_network` | Create a regular 2D mesh/grid network |
| `split_edges` | Split long edges into shorter segments |
| `find_nearest_points` | Find the nearest target point for each source point |

### Documentation (3 tools)

| Tool | Description |
|------|-------------|
| `list_docs` | List all available documentation files |
| `search_docs` | Search across all documentation for a keyword or phrase |
| `read_doc` | Read a specific documentation file, optionally by section |

## Resource Templates

| URI | Description |
|-----|-------------|
| `shift://docs` | List all indexed documentation files |
| `shift://docs/{doc_name}` | Read a specific documentation file by name |
| `shift://graphs` | List all in-memory distribution graphs |

## Prompt Templates

| Prompt | Description |
|--------|-------------|
| `build_feeder_from_location` | Guides through the full pipeline: fetch → cluster → build graph → map phases → map voltages → map equipment → build system → export |
| `inspect_network` | Inspect an existing distribution graph and summarize its topology |
| `explore_api` | Explore the NREL-shift API documentation on a given topic |

## Configuration

The server loads configuration from a `ServerConfig` Pydantic model. Defaults can be overridden by placing a `shift_mcp_config.yaml` file in the working directory.

| Setting | Default | Description |
|---------|---------|-------------|
| `server_name` | `"nrel-shift"` | Server display name |
| `server_version` | `"0.1.0"` | Server version |
| `default_search_distance_m` | `500.0` | Default parcel/road search radius (meters) |
| `max_search_distance_m` | `5000.0` | Maximum allowed search radius (meters) |
| `default_cluster_count` | `5` | Default number of K-means clusters |
| `docs_path` | `""` | Override path to documentation directory |
| `log_level` | `"INFO"` | Logging level |

## Example Workflow

A typical agent-driven workflow:

```
User: Build a small distribution feeder for Golden, CO

Agent:
1. fetch_parcels(location="Golden, CO", distance_meters=300)
   → 24 parcels found

2. cluster_parcels(points=[...], num_clusters=6)
   → 6 groups created

3. build_graph_from_groups(groups=[...], source_longitude=-105.22, source_latitude=39.75)
   → graph "graph-a1b2" created with 31 nodes, 30 edges

4. configure_phase_mapper(graph_id="graph-a1b2", transformer_configs=[...])
   → phase mapper configured

5. configure_voltage_mapper(graph_id="graph-a1b2", transformer_voltages=[...])
   → voltage mapper configured

6. configure_equipment_mapper(graph_id="graph-a1b2", catalog_path="...")
   → equipment mapper configured

7. build_system(system_name="golden_feeder", graph_id="graph-a1b2")
   → system built

8. export_system_json(system_name="golden_feeder", output_path="./golden_feeder.json")
   → exported to ./golden_feeder.json
```

## Known Limitations

- Install the MCP extra in the same environment as SHIFT with `pip install -e ".[mcp]"`; the current project pins `grid-data-models==2.3.7` and declares `mcp>=2.0` as an optional dependency.
- **Network-dependent tools**: `fetch_parcels`, `fetch_parcels_in_polygon`, and `fetch_road_network` require internet access to query OpenStreetMap.
- **Single session**: The stdio transport serves one client at a time. For multi-client scenarios, wrap with a proxy or use the SSE transport.
