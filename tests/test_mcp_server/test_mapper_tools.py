"""Tests for mapper tools (phase, voltage, equipment)."""

from mcp.server import MCPServer

from shift.mcp_server.tools.mapper import phase, voltage, equipment

from tests.test_mcp_server.conftest import MockContext, parse


_mcp = MCPServer("test-mapper")
phase.register(_mcp)
voltage.register(_mcp)
equipment.register(_mcp)


# ---------------------------------------------------------------------------
# Phase mapper
# ---------------------------------------------------------------------------


class TestConfigurePhaseMapper:
    def test_missing_graph(self, mock_ctx):
        fn = _mcp._tool_manager._tools["configure_phase_mapper"].fn
        result = parse(
            fn(
                ctx=mock_ctx,
                graph_id="no-such-graph",
                transformer_configs=[],
            )
        )
        assert result["success"] is False

    def test_configure_success(self, populated_context):
        app, gid = populated_context
        ctx = MockContext(app)
        fn = _mcp._tool_manager._tools["configure_phase_mapper"].fn
        result = parse(
            fn(
                ctx=ctx,
                graph_id=gid,
                transformer_configs=[
                    {
                        "tr_name": "xfmr1",
                        "tr_type": "SPLIT_PHASE",
                        "tr_capacity_kva": 25,
                    },
                ],
                method="greedy",
            )
        )
        assert result["success"] is True
        assert result["num_transformers"] == 1
        assert gid in app.phase_mappers

    def test_invalid_method_still_works(self, populated_context):
        """Invalid method should be caught by BalancedPhaseMapper."""
        app, gid = populated_context
        ctx = MockContext(app)
        fn = _mcp._tool_manager._tools["configure_phase_mapper"].fn
        result = parse(
            fn(
                ctx=ctx,
                graph_id=gid,
                transformer_configs=[
                    {
                        "tr_name": "xfmr1",
                        "tr_type": "SPLIT_PHASE",
                        "tr_capacity_kva": 25,
                    },
                ],
                method="invalid_method",
            )
        )
        # Should fail because the method is invalid
        assert result["success"] is False


class TestGetPhaseMapping:
    def test_no_mapper_configured(self, populated_context):
        app, gid = populated_context
        ctx = MockContext(app)
        fn = _mcp._tool_manager._tools["get_phase_mapping"].fn
        result = parse(fn(ctx=ctx, graph_id=gid))
        assert result["success"] is False
        assert "No phase mapper" in result["error"]

    def test_get_node_mapping(self, populated_context):
        app, gid = populated_context
        ctx = MockContext(app)

        # Configure first
        cfg_fn = _mcp._tool_manager._tools["configure_phase_mapper"].fn
        cfg_fn(
            ctx=ctx,
            graph_id=gid,
            transformer_configs=[
                {"tr_name": "xfmr1", "tr_type": "SPLIT_PHASE", "tr_capacity_kva": 25}
            ],
            method="greedy",
        )

        fn = _mcp._tool_manager._tools["get_phase_mapping"].fn
        result = parse(fn(ctx=ctx, graph_id=gid, mapping_type="nodes"))
        assert result["success"] is True
        assert result["count"] > 0

    def test_get_transformer_mapping(self, populated_context):
        app, gid = populated_context
        ctx = MockContext(app)
        cfg_fn = _mcp._tool_manager._tools["configure_phase_mapper"].fn
        cfg_fn(
            ctx=ctx,
            graph_id=gid,
            transformer_configs=[
                {"tr_name": "xfmr1", "tr_type": "SPLIT_PHASE", "tr_capacity_kva": 25}
            ],
            method="greedy",
        )
        fn = _mcp._tool_manager._tools["get_phase_mapping"].fn
        result = parse(fn(ctx=ctx, graph_id=gid, mapping_type="transformers"))
        assert result["success"] is True

    def test_invalid_mapping_type(self, populated_context):
        app, gid = populated_context
        ctx = MockContext(app)
        cfg_fn = _mcp._tool_manager._tools["configure_phase_mapper"].fn
        cfg_fn(
            ctx=ctx,
            graph_id=gid,
            transformer_configs=[
                {"tr_name": "xfmr1", "tr_type": "SPLIT_PHASE", "tr_capacity_kva": 25}
            ],
            method="greedy",
        )
        fn = _mcp._tool_manager._tools["get_phase_mapping"].fn
        result = parse(fn(ctx=ctx, graph_id=gid, mapping_type="invalid"))
        assert result["success"] is False


# ---------------------------------------------------------------------------
# Voltage mapper
# ---------------------------------------------------------------------------


class TestConfigureVoltageMapper:
    def test_missing_graph(self, mock_ctx):
        fn = _mcp._tool_manager._tools["configure_voltage_mapper"].fn
        result = parse(fn(ctx=mock_ctx, graph_id="nope", transformer_voltages=[]))
        assert result["success"] is False

    def test_configure_success(self, populated_context):
        app, gid = populated_context
        ctx = MockContext(app)
        fn = _mcp._tool_manager._tools["configure_voltage_mapper"].fn
        result = parse(
            fn(
                ctx=ctx,
                graph_id=gid,
                transformer_voltages=[
                    {"name": "xfmr1", "voltages_kv": [7.2, 0.12]},
                ],
            )
        )
        assert result["success"] is True
        assert result["num_transformers"] == 1
        assert gid in app.voltage_mappers


class TestGetVoltageMapping:
    def test_no_mapper(self, populated_context):
        app, gid = populated_context
        ctx = MockContext(app)
        fn = _mcp._tool_manager._tools["get_voltage_mapping"].fn
        result = parse(fn(ctx=ctx, graph_id=gid))
        assert result["success"] is False

    def test_get_mapping(self, populated_context):
        app, gid = populated_context
        ctx = MockContext(app)
        cfg_fn = _mcp._tool_manager._tools["configure_voltage_mapper"].fn
        cfg_fn(
            ctx=ctx,
            graph_id=gid,
            transformer_voltages=[
                {"name": "xfmr1", "voltages_kv": [7.2, 0.12]},
            ],
        )
        fn = _mcp._tool_manager._tools["get_voltage_mapping"].fn
        result = parse(fn(ctx=ctx, graph_id=gid))
        assert result["success"] is True
        assert result["count"] > 0


# ---------------------------------------------------------------------------
# Equipment mapper
# ---------------------------------------------------------------------------


class TestConfigureEquipmentMapper:
    def test_missing_graph(self, mock_ctx):
        fn = _mcp._tool_manager._tools["configure_equipment_mapper"].fn
        result = parse(fn(ctx=mock_ctx, graph_id="nope", catalog_path="/fake.json"))
        assert result["success"] is False

    def test_missing_voltage_mapper(self, populated_context):
        app, gid = populated_context
        ctx = MockContext(app)
        fn = _mcp._tool_manager._tools["configure_equipment_mapper"].fn
        result = parse(fn(ctx=ctx, graph_id=gid, catalog_path="/fake.json"))
        assert result["success"] is False
        assert "Voltage mapper" in result["error"]

    def test_missing_phase_mapper(self, populated_context):
        app, gid = populated_context
        # Add voltage mapper but not phase mapper
        app.voltage_mappers[gid] = "fake"
        ctx = MockContext(app)
        fn = _mcp._tool_manager._tools["configure_equipment_mapper"].fn
        result = parse(fn(ctx=ctx, graph_id=gid, catalog_path="/fake.json"))
        assert result["success"] is False
        assert "Phase mapper" in result["error"]

    def test_missing_catalog_file(self, populated_context):
        app, gid = populated_context
        app.voltage_mappers[gid] = "fake"
        app.phase_mappers[gid] = "fake"
        ctx = MockContext(app)
        fn = _mcp._tool_manager._tools["configure_equipment_mapper"].fn
        result = parse(fn(ctx=ctx, graph_id=gid, catalog_path="/nonexistent/catalog.json"))
        assert result["success"] is False
        assert "not found" in result["error"]


class TestGetEquipmentMapping:
    def test_no_mapper(self, populated_context):
        app, gid = populated_context
        ctx = MockContext(app)
        fn = _mcp._tool_manager._tools["get_equipment_mapping"].fn
        result = parse(fn(ctx=ctx, graph_id=gid))
        assert result["success"] is False
        assert "No equipment mapper" in result["error"]
