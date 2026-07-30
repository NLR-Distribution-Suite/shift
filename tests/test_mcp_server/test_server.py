"""Tests for server creation, prompts, and doc indexing."""

from shift.mcp_server.server import create_server, _index_docs
from shift.mcp_server.prompts import workflows
from mcp.server import MCPServer


# ---------------------------------------------------------------------------
# Server creation
# ---------------------------------------------------------------------------


class TestCreateServer:
    def test_server_creates_successfully(self):
        server = create_server()
        assert server is not None
        assert server.name == "nrel-shift"

    def test_has_tools(self):
        server = create_server()
        tools = server._tool_manager._tools
        assert len(tools) == 36

    def test_has_prompts(self):
        server = create_server()
        prompts = server._prompt_manager._prompts
        assert len(prompts) == 3

    def test_has_resource_templates(self):
        server = create_server()
        templates = server._resource_manager._templates
        assert len(templates) == 1

    def test_expected_tool_names(self):
        server = create_server()
        tool_names = set(server._tool_manager._tools.keys())
        expected = {
            "fetch_parcels",
            "fetch_parcels_in_polygon",
            "fetch_road_network",
            "cluster_parcels",
            "create_graph",
            "delete_graph",
            "list_graphs",
            "add_node",
            "remove_node",
            "get_node",
            "add_edge",
            "remove_edge",
            "get_edge",
            "query_graph",
            "build_graph_from_groups",
            "configure_phase_mapper",
            "get_phase_mapping",
            "configure_voltage_mapper",
            "get_voltage_mapping",
            "configure_equipment_mapper",
            "get_equipment_mapping",
            "build_system",
            "get_system_summary",
            "list_systems",
            "export_system_json",
            "distance_between_points",
            "polygon_from_points",
            "create_mesh_network",
            "split_edges",
            "find_nearest_points",
            "list_docs",
            "read_doc",
            "search_docs",
            "set_local_pbf",
            "route_existing_graph",
            "layout_existing_graph",
        }
        assert tool_names == expected

    def test_expected_prompt_names(self):
        server = create_server()
        prompt_names = set(server._prompt_manager._prompts.keys())
        assert prompt_names == {"build_feeder_from_location", "inspect_network", "explore_api"}

    def test_expected_resource_uris(self):
        server = create_server()
        uris = set(server._resource_manager._templates.keys())
        assert uris == {"shift://docs/{doc_name}"}


# ---------------------------------------------------------------------------
# Doc indexing
# ---------------------------------------------------------------------------


class TestIndexDocs:
    def test_indexes_real_docs(self, tmp_path):
        """Verify _index_docs reads markdown files from a project root."""

        # Create a minimal project structure
        (tmp_path / "README.md").write_text("# Test README")
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        (docs_dir / "API_REFERENCE.md").write_text("# API Ref")
        usage_dir = docs_dir / "usage"
        usage_dir.mkdir()
        (usage_dir / "index.md").write_text("# Usage Index")

        docs_index, docs_desc = _index_docs(tmp_path)

        assert "readme" in docs_index
        assert docs_index["readme"] == "# Test README"
        assert "api_reference" in docs_index
        assert "usage/index" in docs_index

    def test_missing_files_skipped(self, tmp_path):
        """Files that don't exist should be skipped without error."""
        docs_index, _ = _index_docs(tmp_path)
        # Most files won't exist in tmp_path, so index should be empty or very small
        assert isinstance(docs_index, dict)


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------


class TestPrompts:
    def test_build_feeder_prompt_registered(self):
        mcp = MCPServer("test-prompts")
        workflows.register(mcp)
        prompts = mcp._prompt_manager._prompts
        assert "build_feeder_from_location" in prompts

    def test_inspect_network_prompt_registered(self):
        mcp = MCPServer("test-prompts")
        workflows.register(mcp)
        assert "inspect_network" in mcp._prompt_manager._prompts

    def test_explore_api_prompt_registered(self):
        mcp = MCPServer("test-prompts")
        workflows.register(mcp)
        assert "explore_api" in mcp._prompt_manager._prompts
