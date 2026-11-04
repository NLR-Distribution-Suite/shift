"""Tests for serialization helpers."""

from gdm.systems.distribution.components import (
    DistributionBranchBase,
    DistributionLoad,
    DistributionTransformer,
    DistributionVoltageSource,
)
from gdm.quantities import Distance
from infrasys import Location

from shift.data_model import (
    EdgeModel,
    GeoLocation,
    GroupModel,
    NodeModel,
    ParcelModel,
)
from shift.mcp_server.serializers import (
    serialize_edge,
    serialize_edge_tuple,
    serialize_geo_location,
    serialize_graph_summary,
    serialize_group,
    serialize_node,
    serialize_nx_graph_summary,
    serialize_parcel,
)


class TestSerializeGeoLocation:
    def test_basic(self):
        result = serialize_geo_location(GeoLocation(-97.33, 32.75))
        assert result == {"longitude": -97.33, "latitude": 32.75}


class TestSerializeParcel:
    def test_point_geometry(self):
        parcel = ParcelModel(
            name="p1",
            geometry=GeoLocation(-97.33, 32.75),
            building_type="residential",
            city="Denver",
            state="CO",
            postal_address="80401",
        )
        result = serialize_parcel(parcel)
        assert result["name"] == "p1"
        assert result["building_type"] == "residential"
        assert result["geometry"]["longitude"] == -97.33

    def test_polygon_geometry(self):
        parcel = ParcelModel(
            name="p2",
            geometry=[GeoLocation(-97.33, 32.75), GeoLocation(-97.32, 32.76)],
            building_type="commercial",
            city="Denver",
            state="CO",
            postal_address="80401",
        )
        result = serialize_parcel(parcel)
        assert isinstance(result["geometry"], list)
        assert len(result["geometry"]) == 2


class TestSerializeGroup:
    def test_basic(self):
        group = GroupModel(
            center=GeoLocation(-97.33, 32.75),
            points=[GeoLocation(-97.32, 32.76), GeoLocation(-97.31, 32.77)],
        )
        result = serialize_group(group)
        assert result["num_points"] == 2
        assert result["center"]["longitude"] == -97.33


class TestSerializeNode:
    def test_node_without_assets(self):
        node = NodeModel(name="n1", location=Location(x=-97.33, y=32.75))
        result = serialize_node(node)
        assert result["name"] == "n1"
        assert result["longitude"] == -97.33
        assert result["latitude"] == 32.75
        assert result["assets"] == []

    def test_node_with_assets(self):
        node = NodeModel(
            name="n2",
            location=Location(x=-97.33, y=32.75),
            assets={DistributionLoad, DistributionVoltageSource},
        )
        result = serialize_node(node)
        assert len(result["assets"]) == 2
        assert set(result["assets"]) == {"DistributionLoad", "DistributionVoltageSource"}


class TestSerializeEdge:
    def test_branch_edge(self):
        edge = EdgeModel(name="line1", edge_type=DistributionBranchBase, length=Distance(150, "m"))
        result = serialize_edge(edge)
        assert result["name"] == "line1"
        assert result["edge_type"] == "DistributionBranchBase"
        assert abs(result["length_meters"] - 150.0) < 0.01

    def test_transformer_edge(self):
        edge = EdgeModel(name="xfmr1", edge_type=DistributionTransformer)
        result = serialize_edge(edge)
        assert result["name"] == "xfmr1"
        assert "length_meters" not in result

    def test_edge_tuple(self):
        edge = EdgeModel(name="line1", edge_type=DistributionBranchBase, length=Distance(50, "m"))
        result = serialize_edge_tuple("a", "b", edge)
        assert result["from_node"] == "a"
        assert result["to_node"] == "b"
        assert result["name"] == "line1"


class TestSerializeGraphSummary:
    def test_basic(self, sample_graph):
        result = serialize_graph_summary(sample_graph, "g1")
        assert result["graph_id"] == "g1"
        assert result["node_count"] == 3
        assert result["edge_count"] == 2
        assert result["vsource_node"] == "src"

    def test_with_meta(self, sample_graph):
        from shift.mcp_server.state import GraphMeta

        meta = GraphMeta(name="my-graph", created_at="2026-01-01T00:00:00")
        result = serialize_graph_summary(sample_graph, "g1", meta)
        assert result["name"] == "my-graph"
        assert result["created_at"] == "2026-01-01T00:00:00"


class TestSerializeNxGraphSummary:
    def test_basic(self):
        import networkx as nx

        g = nx.Graph()
        g.add_nodes_from(["a", "b", "c"])
        g.add_edge("a", "b")
        result = serialize_nx_graph_summary(g)
        assert result["node_count"] == 3
        assert result["edge_count"] == 1
