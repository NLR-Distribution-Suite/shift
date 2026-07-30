"""Tests for system builder/export tools and utility tools."""

import pytest
from mcp.server import MCPServer

from shift.mcp_server.tools.system import builder as sys_builder, export
from shift.mcp_server.tools.utilities import geo, network, nearest
from shift.mcp_server.tools.data_acquisition import clustering

from tests.test_mcp_server.conftest import MockContext, parse


_mcp = MCPServer("test-sys-util")
sys_builder.register(_mcp)
export.register(_mcp)
geo.register(_mcp)
network.register(_mcp)
nearest.register(_mcp)
clustering.register(_mcp)


# ---------------------------------------------------------------------------
# System builder
# ---------------------------------------------------------------------------


class TestBuildSystem:
    def test_missing_graph(self, mock_ctx):
        fn = _mcp._tool_manager._tools["build_system"].fn
        result = parse(fn(ctx=mock_ctx, system_name="s1", graph_id="nope"))
        assert result["success"] is False

    def test_missing_mappers(self, populated_context):
        app, gid = populated_context
        ctx = MockContext(app)
        fn = _mcp._tool_manager._tools["build_system"].fn
        result = parse(fn(ctx=ctx, system_name="s1", graph_id=gid))
        assert result["success"] is False
        assert "Missing mappers" in result["error"]


class TestListSystems:
    def test_empty(self, mock_ctx):
        fn = _mcp._tool_manager._tools["list_systems"].fn
        result = parse(fn(ctx=mock_ctx))
        assert result["success"] is True
        assert result["count"] == 0

    def test_with_systems(self, mock_ctx):
        mock_ctx.request_context.lifespan_context.systems["feeder1"] = "placeholder"
        fn = _mcp._tool_manager._tools["list_systems"].fn
        result = parse(fn(ctx=mock_ctx))
        assert result["count"] == 1
        assert "feeder1" in result["systems"]


class TestGetSystemSummary:
    def test_missing_system(self, mock_ctx):
        fn = _mcp._tool_manager._tools["get_system_summary"].fn
        result = parse(fn(ctx=mock_ctx, system_name="nope"))
        assert result["success"] is False


class TestExportSystemJson:
    def test_missing_system(self, mock_ctx):
        fn = _mcp._tool_manager._tools["export_system_json"].fn
        result = parse(fn(ctx=mock_ctx, system_name="nope"))
        assert result["success"] is False


# ---------------------------------------------------------------------------
# Utilities — geo
# ---------------------------------------------------------------------------


class TestDistanceBetweenPoints:
    def test_same_point(self):
        fn = _mcp._tool_manager._tools["distance_between_points"].fn
        result = parse(fn(lon1=-105.2, lat1=39.75, lon2=-105.2, lat2=39.75))
        assert result["success"] is True
        assert result["distance_meters"] == pytest.approx(0.0, abs=1.0)

    def test_different_points(self):
        fn = _mcp._tool_manager._tools["distance_between_points"].fn
        result = parse(fn(lon1=-105.2, lat1=39.75, lon2=-105.21, lat2=39.76))
        assert result["success"] is True
        assert result["distance_meters"] > 0


class TestPolygonFromPoints:
    def test_too_few_points(self):
        fn = _mcp._tool_manager._tools["polygon_from_points"].fn
        result = parse(
            fn(
                points=[{"longitude": -105.2, "latitude": 39.75}],
                buffer_meters=50.0,
            )
        )
        assert result["success"] is False
        assert "At least 3" in result["error"]

    def test_valid_polygon(self):
        fn = _mcp._tool_manager._tools["polygon_from_points"].fn
        result = parse(
            fn(
                points=[
                    {"longitude": -105.20, "latitude": 39.75},
                    {"longitude": -105.21, "latitude": 39.76},
                    {"longitude": -105.22, "latitude": 39.75},
                ],
                buffer_meters=50.0,
            )
        )
        assert result["success"] is True
        assert result["num_vertices"] >= 3


# ---------------------------------------------------------------------------
# Utilities — nearest points
# ---------------------------------------------------------------------------


class TestFindNearestPoints:
    def test_basic(self):
        fn = _mcp._tool_manager._tools["find_nearest_points"].fn
        result = parse(
            fn(
                source_points=[[0, 0], [5, 5]],
                target_points=[[1, 1], [6, 6]],
            )
        )
        assert result["success"] is True
        # Returns nearest source points (coords), not indices
        assert result["nearest_indices"] == [[0, 0], [5, 5]]


# ---------------------------------------------------------------------------
# Utilities — clustering
# ---------------------------------------------------------------------------


class TestClusterParcels:
    def test_basic(self):
        fn = _mcp._tool_manager._tools["cluster_parcels"].fn
        points = [
            {"longitude": -105.20 + i * 0.01, "latitude": 39.75 + i * 0.01} for i in range(10)
        ]
        result = parse(fn(points=points, num_clusters=2))
        assert result["success"] is True
        assert result["num_clusters"] == 2

    def test_too_many_clusters(self):
        fn = _mcp._tool_manager._tools["cluster_parcels"].fn
        result = parse(
            fn(
                points=[{"longitude": -105.2, "latitude": 39.75}],
                num_clusters=5,
            )
        )
        assert result["success"] is False
        assert "must be <=" in result["error"]
