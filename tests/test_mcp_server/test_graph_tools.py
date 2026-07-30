"""Tests for graph management, node, edge, and query tools."""

from mcp.server import MCPServer

from shift.mcp_server.tools.graph import management, nodes, edges, query

from tests.test_mcp_server.conftest import MockContext, parse


# ---------------------------------------------------------------------------
# Register tools on a shared MCPServer instance
# ---------------------------------------------------------------------------

_mcp = MCPServer("test-graph")
management.register(_mcp)
nodes.register(_mcp)
edges.register(_mcp)
query.register(_mcp)


def _call(name: str, **kwargs) -> dict:
    """Call a registered tool by name and parse the JSON result."""

    async def _run():
        return await _mcp.call_tool(name, kwargs)

    # Tools here can't go through MCP call_tool easily because they
    # need a real Context — so we call the inner functions directly.
    # Instead, get the tool function from the manager.
    tool = _mcp._tool_manager._tools[name]
    # The function is stored on the tool object
    fn = tool.fn
    return parse(fn(**kwargs))


# ---------------------------------------------------------------------------
# Graph management
# ---------------------------------------------------------------------------


class TestCreateGraph:
    def test_create_unnamed(self, mock_ctx):
        fn = _mcp._tool_manager._tools["create_graph"].fn
        result = parse(fn(ctx=mock_ctx))
        assert result["success"] is True
        assert "graph_id" in result

    def test_create_named(self, mock_ctx):
        fn = _mcp._tool_manager._tools["create_graph"].fn
        result = parse(fn(ctx=mock_ctx, name="my-feeder"))
        assert result["success"] is True
        assert result["name"] == "my-feeder"

    def test_graph_stored_in_context(self, mock_ctx):
        fn = _mcp._tool_manager._tools["create_graph"].fn
        result = parse(fn(ctx=mock_ctx))
        gid = result["graph_id"]
        assert gid in mock_ctx.request_context.lifespan_context.graphs


class TestDeleteGraph:
    def test_delete_existing(self, populated_context):
        app, gid = populated_context
        ctx = MockContext(app)
        fn = _mcp._tool_manager._tools["delete_graph"].fn
        result = parse(fn(ctx=ctx, graph_id=gid))
        assert result["success"] is True
        assert gid not in app.graphs

    def test_delete_nonexistent(self, mock_ctx):
        fn = _mcp._tool_manager._tools["delete_graph"].fn
        result = parse(fn(ctx=mock_ctx, graph_id="nope"))
        assert result["success"] is False

    def test_delete_cleans_mappers(self, populated_context):
        app, gid = populated_context
        app.phase_mappers[gid] = "fake"
        app.voltage_mappers[gid] = "fake"
        app.equipment_mappers[gid] = "fake"
        ctx = MockContext(app)
        fn = _mcp._tool_manager._tools["delete_graph"].fn
        parse(fn(ctx=ctx, graph_id=gid))
        assert gid not in app.phase_mappers
        assert gid not in app.voltage_mappers
        assert gid not in app.equipment_mappers


class TestListGraphs:
    def test_empty(self, mock_ctx):
        fn = _mcp._tool_manager._tools["list_graphs"].fn
        result = parse(fn(ctx=mock_ctx))
        assert result["success"] is True
        assert result["count"] == 0

    def test_with_graphs(self, populated_context):
        app, gid = populated_context
        ctx = MockContext(app)
        fn = _mcp._tool_manager._tools["list_graphs"].fn
        result = parse(fn(ctx=ctx))
        assert result["count"] == 1
        assert result["graphs"][0]["graph_id"] == gid


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------


class TestAddNode:
    def test_add_basic_node(self, populated_context):
        app, gid = populated_context
        ctx = MockContext(app)
        fn = _mcp._tool_manager._tools["add_node"].fn
        result = parse(
            fn(ctx=ctx, graph_id=gid, node_name="new1", longitude=-105.0, latitude=39.0)
        )
        assert result["success"] is True
        assert result["node"]["name"] == "new1"

    def test_add_node_with_assets(self, populated_context):
        app, gid = populated_context
        ctx = MockContext(app)
        fn = _mcp._tool_manager._tools["add_node"].fn
        result = parse(
            fn(
                ctx=ctx,
                graph_id=gid,
                node_name="solar1",
                longitude=-105.0,
                latitude=39.0,
                assets=["DistributionLoad"],
            )
        )
        assert result["success"] is True
        assert "DistributionLoad" in result["node"]["assets"]

    def test_add_node_invalid_asset(self, populated_context):
        app, gid = populated_context
        ctx = MockContext(app)
        fn = _mcp._tool_manager._tools["add_node"].fn
        result = parse(
            fn(
                ctx=ctx,
                graph_id=gid,
                node_name="bad",
                longitude=-105.0,
                latitude=39.0,
                assets=["FakeAsset"],
            )
        )
        assert result["success"] is False
        assert "Unknown asset type" in result["error"]

    def test_add_node_bad_graph(self, mock_ctx):
        fn = _mcp._tool_manager._tools["add_node"].fn
        result = parse(fn(ctx=mock_ctx, graph_id="nope", node_name="x", longitude=0, latitude=0))
        assert result["success"] is False


class TestRemoveNode:
    def test_remove_existing(self, populated_context):
        app, gid = populated_context
        ctx = MockContext(app)
        fn = _mcp._tool_manager._tools["remove_node"].fn
        result = parse(fn(ctx=ctx, graph_id=gid, node_name="load1"))
        assert result["success"] is True

    def test_remove_nonexistent(self, populated_context):
        app, gid = populated_context
        ctx = MockContext(app)
        fn = _mcp._tool_manager._tools["remove_node"].fn
        result = parse(fn(ctx=ctx, graph_id=gid, node_name="ghost"))
        assert result["success"] is False


class TestGetNode:
    def test_get_existing(self, populated_context):
        app, gid = populated_context
        ctx = MockContext(app)
        fn = _mcp._tool_manager._tools["get_node"].fn
        result = parse(fn(ctx=ctx, graph_id=gid, node_name="src"))
        assert result["success"] is True
        assert result["node"]["name"] == "src"
        assert "DistributionVoltageSource" in result["node"]["assets"]

    def test_get_nonexistent(self, populated_context):
        app, gid = populated_context
        ctx = MockContext(app)
        fn = _mcp._tool_manager._tools["get_node"].fn
        result = parse(fn(ctx=ctx, graph_id=gid, node_name="nope"))
        assert result["success"] is False


# ---------------------------------------------------------------------------
# Edges
# ---------------------------------------------------------------------------


class TestAddEdge:
    def test_add_branch_edge(self, populated_context):
        app, gid = populated_context
        ctx = MockContext(app)
        fn = _mcp._tool_manager._tools["add_edge"].fn
        # Add a new node first
        add_node_fn = _mcp._tool_manager._tools["add_node"].fn
        add_node_fn(ctx=ctx, graph_id=gid, node_name="bus2", longitude=-105.23, latitude=39.78)

        result = parse(
            fn(
                ctx=ctx,
                graph_id=gid,
                from_node="bus1",
                to_node="bus2",
                edge_name="line2",
                edge_type="DistributionBranchBase",
                length_meters=200.0,
            )
        )
        assert result["success"] is True
        assert result["edge"]["name"] == "line2"

    def test_add_transformer_edge(self, populated_context):
        app, gid = populated_context
        ctx = MockContext(app)
        add_node_fn = _mcp._tool_manager._tools["add_node"].fn
        add_node_fn(ctx=ctx, graph_id=gid, node_name="sec1", longitude=-105.23, latitude=39.78)

        fn = _mcp._tool_manager._tools["add_edge"].fn
        result = parse(
            fn(
                ctx=ctx,
                graph_id=gid,
                from_node="bus1",
                to_node="sec1",
                edge_name="xfmr2",
                edge_type="DistributionTransformer",
            )
        )
        assert result["success"] is True

    def test_add_edge_invalid_type(self, populated_context):
        app, gid = populated_context
        ctx = MockContext(app)
        fn = _mcp._tool_manager._tools["add_edge"].fn
        result = parse(
            fn(
                ctx=ctx,
                graph_id=gid,
                from_node="src",
                to_node="bus1",
                edge_name="bad",
                edge_type="FakeType",
            )
        )
        assert result["success"] is False
        assert "Unknown edge_type" in result["error"]


class TestRemoveEdge:
    def test_remove_existing(self, populated_context):
        app, gid = populated_context
        ctx = MockContext(app)
        fn = _mcp._tool_manager._tools["remove_edge"].fn
        result = parse(fn(ctx=ctx, graph_id=gid, from_node="bus1", to_node="load1"))
        assert result["success"] is True

    def test_remove_nonexistent(self, populated_context):
        app, gid = populated_context
        ctx = MockContext(app)
        fn = _mcp._tool_manager._tools["remove_edge"].fn
        result = parse(fn(ctx=ctx, graph_id=gid, from_node="bus1", to_node="ghost"))
        assert result["success"] is False


class TestGetEdge:
    def test_get_existing(self, populated_context):
        app, gid = populated_context
        ctx = MockContext(app)
        fn = _mcp._tool_manager._tools["get_edge"].fn
        result = parse(fn(ctx=ctx, graph_id=gid, from_node="src", to_node="bus1"))
        assert result["success"] is True
        assert result["edge"]["name"] == "xfmr1"


# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------


class TestQueryGraph:
    def test_summary(self, populated_context):
        app, gid = populated_context
        ctx = MockContext(app)
        fn = _mcp._tool_manager._tools["query_graph"].fn
        result = parse(fn(ctx=ctx, graph_id=gid, query_type="summary"))
        assert result["success"] is True
        assert result["node_count"] == 3
        assert result["edge_count"] == 2

    def test_nodes(self, populated_context):
        app, gid = populated_context
        ctx = MockContext(app)
        fn = _mcp._tool_manager._tools["query_graph"].fn
        result = parse(fn(ctx=ctx, graph_id=gid, query_type="nodes"))
        assert result["success"] is True
        assert result["count"] == 3

    def test_edges(self, populated_context):
        app, gid = populated_context
        ctx = MockContext(app)
        fn = _mcp._tool_manager._tools["query_graph"].fn
        result = parse(fn(ctx=ctx, graph_id=gid, query_type="edges"))
        assert result["success"] is True
        assert result["count"] == 2

    def test_vsource(self, populated_context):
        app, gid = populated_context
        ctx = MockContext(app)
        fn = _mcp._tool_manager._tools["query_graph"].fn
        result = parse(fn(ctx=ctx, graph_id=gid, query_type="vsource"))
        assert result["success"] is True
        assert result["vsource_node"] == "src"

    def test_dfs_tree(self, populated_context):
        app, gid = populated_context
        ctx = MockContext(app)
        fn = _mcp._tool_manager._tools["query_graph"].fn
        result = parse(fn(ctx=ctx, graph_id=gid, query_type="dfs_tree"))
        assert result["success"] is True
        assert len(result["dfs_node_order"]) == 3

    def test_invalid_query_type(self, populated_context):
        app, gid = populated_context
        ctx = MockContext(app)
        fn = _mcp._tool_manager._tools["query_graph"].fn
        result = parse(fn(ctx=ctx, graph_id=gid, query_type="invalid"))
        assert result["success"] is False
        assert "Unknown query_type" in result["error"]

    def test_bad_graph_id(self, mock_ctx):
        fn = _mcp._tool_manager._tools["query_graph"].fn
        result = parse(fn(ctx=mock_ctx, graph_id="nope"))
        assert result["success"] is False
