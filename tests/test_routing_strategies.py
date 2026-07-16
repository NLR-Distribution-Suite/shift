"""Tests for routing strategies and secondary network strategies."""

import networkx as nx
import pytest

from shift.data_model import GeoLocation, GroupModel
from shift.exceptions import InvalidInputError
from shift.graph.routing import (
    CostOptimizedStrategy,
    FullRoadGraphStrategy,
    MinimumSpanningTreeStrategy,
    RoutingStrategy,
    ShortestPathTreeStrategy,
    SteinerTreeStrategy,
    WeightedSteinerTreeStrategy,
)
from shift.graph.secondary import (
    DelaunayStrategy,
    HubLineStrategy,
    MeshSteinerStrategy,
    OpenStreetSecondaryStrategy,
    RadialStrategy,
)


# ─── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture
def simple_graph():
    """A simple 7-node grid graph with geographic coordinates.

    Layout (approx):
        1 - 2 - 3
        |       |
        4 - 5 - 6
            |
            7
    """
    g = nx.Graph()
    # Row 1
    g.add_node("n1", x=-97.33, y=32.75)
    g.add_node("n2", x=-97.32, y=32.75)
    g.add_node("n3", x=-97.31, y=32.75)
    # Row 2
    g.add_node("n4", x=-97.33, y=32.74)
    g.add_node("n5", x=-97.32, y=32.74)
    g.add_node("n6", x=-97.31, y=32.74)
    # Extension
    g.add_node("n7", x=-97.32, y=32.73)

    g.add_edge("n1", "n2")
    g.add_edge("n2", "n3")
    g.add_edge("n1", "n4")
    g.add_edge("n3", "n6")
    g.add_edge("n4", "n5")
    g.add_edge("n5", "n6")
    g.add_edge("n5", "n7")
    return g


@pytest.fixture
def terminal_nodes():
    """Terminal nodes: n1 (source), n3 (transformer), n7 (load)."""
    return ["n1", "n3", "n7"]


@pytest.fixture
def simple_group():
    """A simple group with 4 load points around a center."""
    center = GeoLocation(-97.32, 32.74)
    points = [
        GeoLocation(-97.325, 32.745),
        GeoLocation(-97.315, 32.745),
        GeoLocation(-97.325, 32.735),
        GeoLocation(-97.315, 32.735),
    ]
    return GroupModel(center=center, points=points)


@pytest.fixture
def single_point_group():
    """A group with only one load point."""
    center = GeoLocation(-97.32, 32.74)
    points = [GeoLocation(-97.321, 32.741)]
    return GroupModel(center=center, points=points)


# ─── Routing Strategy Tests ──────────────────────────────────────────────────


class TestSteinerTreeStrategy:
    def test_connects_all_terminals(self, simple_graph, terminal_nodes):
        strategy = SteinerTreeStrategy()
        result = strategy.route(simple_graph, terminal_nodes)
        for node in terminal_nodes:
            assert node in result.nodes

    def test_result_is_connected(self, simple_graph, terminal_nodes):
        strategy = SteinerTreeStrategy()
        result = strategy.route(simple_graph, terminal_nodes)
        assert nx.is_connected(result)

    def test_result_is_tree(self, simple_graph, terminal_nodes):
        strategy = SteinerTreeStrategy()
        result = strategy.route(simple_graph, terminal_nodes)
        assert nx.is_tree(result)


class TestWeightedSteinerTreeStrategy:
    def test_connects_all_terminals(self, simple_graph, terminal_nodes):
        strategy = WeightedSteinerTreeStrategy()
        result = strategy.route(simple_graph, terminal_nodes)
        for node in terminal_nodes:
            assert node in result.nodes

    def test_result_is_connected(self, simple_graph, terminal_nodes):
        strategy = WeightedSteinerTreeStrategy()
        result = strategy.route(simple_graph, terminal_nodes)
        assert nx.is_connected(result)

    def test_result_is_tree(self, simple_graph, terminal_nodes):
        strategy = WeightedSteinerTreeStrategy()
        result = strategy.route(simple_graph, terminal_nodes)
        assert nx.is_tree(result)

    def test_custom_weight_fn(self, simple_graph, terminal_nodes):
        """Custom weight function should be used for routing."""
        call_count = {"n": 0}

        def counting_weight(graph, u, v):
            call_count["n"] += 1
            return 1.0

        strategy = WeightedSteinerTreeStrategy(weight_fn=counting_weight)
        result = strategy.route(simple_graph, terminal_nodes)
        assert call_count["n"] > 0
        assert nx.is_connected(result)


class TestShortestPathTreeStrategy:
    def test_connects_all_terminals(self, simple_graph, terminal_nodes):
        strategy = ShortestPathTreeStrategy()
        result = strategy.route(simple_graph, terminal_nodes)
        for node in terminal_nodes:
            assert node in result.nodes

    def test_result_is_connected(self, simple_graph, terminal_nodes):
        strategy = ShortestPathTreeStrategy()
        result = strategy.route(simple_graph, terminal_nodes)
        assert nx.is_connected(result)

    def test_single_terminal(self, simple_graph):
        strategy = ShortestPathTreeStrategy()
        result = strategy.route(simple_graph, ["n1"])
        assert "n1" in result.nodes


class TestMinimumSpanningTreeStrategy:
    def test_connects_all_terminals(self, simple_graph, terminal_nodes):
        strategy = MinimumSpanningTreeStrategy()
        result = strategy.route(simple_graph, terminal_nodes)
        for node in terminal_nodes:
            assert node in result.nodes

    def test_result_is_connected(self, simple_graph, terminal_nodes):
        strategy = MinimumSpanningTreeStrategy()
        result = strategy.route(simple_graph, terminal_nodes)
        assert nx.is_connected(result)

    def test_result_is_tree(self, simple_graph, terminal_nodes):
        strategy = MinimumSpanningTreeStrategy()
        result = strategy.route(simple_graph, terminal_nodes)
        # MST-based strategy should produce a tree (edges = nodes - 1)
        assert nx.is_tree(result)


class TestFullRoadGraphStrategy:
    def test_contains_all_terminals(self, simple_graph, terminal_nodes):
        strategy = FullRoadGraphStrategy()
        result = strategy.route(simple_graph, terminal_nodes)
        for node in terminal_nodes:
            assert node in result.nodes

    def test_result_is_connected(self, simple_graph, terminal_nodes):
        strategy = FullRoadGraphStrategy()
        result = strategy.route(simple_graph, terminal_nodes)
        assert nx.is_connected(result)

    def test_returns_full_component(self, simple_graph, terminal_nodes):
        """Should return the full connected component, not just a tree."""
        strategy = FullRoadGraphStrategy()
        result = strategy.route(simple_graph, terminal_nodes)
        # The full graph has 7 edges, not just a tree
        assert len(result.edges) >= len(result.nodes) - 1

    def test_raises_for_disconnected_terminals(self, simple_graph):
        """Should fail fast if terminals are not in the same component."""
        simple_graph.add_node("n8", x=-97.30, y=32.70)
        simple_graph.add_node("n9", x=-97.29, y=32.70)
        simple_graph.add_edge("n8", "n9")

        strategy = FullRoadGraphStrategy()
        with pytest.raises(InvalidInputError):
            strategy.route(simple_graph, ["n1", "n9"])

    def test_raises_for_missing_terminal(self, simple_graph):
        strategy = FullRoadGraphStrategy()
        with pytest.raises(InvalidInputError):
            strategy.route(simple_graph, ["n1", "missing_node"])


class TestCostOptimizedStrategy:
    def test_raises_not_implemented(self, simple_graph, terminal_nodes):
        strategy = CostOptimizedStrategy()
        with pytest.raises(NotImplementedError):
            strategy.route(simple_graph, terminal_nodes)


# ─── Secondary Network Strategy Tests ────────────────────────────────────────


class TestMeshSteinerStrategy:
    def test_produces_connected_graph(self, simple_group):
        strategy = MeshSteinerStrategy()
        result = strategy.build(simple_group)
        assert len(result.nodes) > 0
        assert nx.is_connected(result)

    def test_single_point_group(self, single_point_group):
        strategy = MeshSteinerStrategy()
        result = strategy.build(single_point_group)
        assert len(result.nodes) == 1

    def test_nodes_have_coordinates(self, simple_group):
        strategy = MeshSteinerStrategy()
        result = strategy.build(simple_group)
        for node, data in result.nodes(data=True):
            assert "x" in data
            assert "y" in data


class TestRadialStrategy:
    def test_produces_star_topology(self, simple_group):
        strategy = RadialStrategy()
        result = strategy.build(simple_group)
        # Star: center connects to all 4 load points = 5 nodes, 4 edges
        assert len(result.nodes) == 5
        assert len(result.edges) == 4

    def test_result_is_connected(self, simple_group):
        strategy = RadialStrategy()
        result = strategy.build(simple_group)
        assert nx.is_connected(result)

    def test_result_is_tree(self, simple_group):
        strategy = RadialStrategy()
        result = strategy.build(simple_group)
        assert nx.is_tree(result)

    def test_single_point_group(self, single_point_group):
        strategy = RadialStrategy()
        result = strategy.build(single_point_group)
        assert len(result.nodes) == 1

    def test_center_has_highest_degree(self, simple_group):
        strategy = RadialStrategy()
        result = strategy.build(simple_group)
        degrees = dict(result.degree())
        max_degree_node = max(degrees, key=degrees.get)
        assert degrees[max_degree_node] == len(simple_group.points)


class TestDelaunayStrategy:
    def test_produces_connected_graph(self, simple_group):
        strategy = DelaunayStrategy()
        result = strategy.build(simple_group)
        assert len(result.nodes) > 0
        assert nx.is_connected(result)

    def test_result_is_tree(self, simple_group):
        """MST pruning should produce a tree."""
        strategy = DelaunayStrategy()
        result = strategy.build(simple_group)
        assert nx.is_tree(result)

    def test_single_point_group(self, single_point_group):
        strategy = DelaunayStrategy()
        result = strategy.build(single_point_group)
        assert len(result.nodes) == 1

    def test_two_point_group(self):
        """Two points should fall back to radial."""
        center = GeoLocation(-97.32, 32.74)
        points = [GeoLocation(-97.321, 32.741), GeoLocation(-97.319, 32.739)]
        group = GroupModel(center=center, points=points)
        strategy = DelaunayStrategy()
        result = strategy.build(group)
        assert len(result.nodes) > 0
        assert nx.is_connected(result)


class TestHubLineStrategy:
    def test_produces_star_topology(self, simple_group):
        strategy = HubLineStrategy()
        result = strategy.build(simple_group)
        # Hub (center) + 4 load points
        assert len(result.nodes) == 5
        assert len(result.edges) == 4

    def test_result_is_connected(self, simple_group):
        strategy = HubLineStrategy()
        result = strategy.build(simple_group)
        assert nx.is_connected(result)

    def test_single_point_group(self, single_point_group):
        strategy = HubLineStrategy()
        result = strategy.build(single_point_group)
        assert len(result.nodes) == 1

    def test_nodes_have_coordinates(self, simple_group):
        strategy = HubLineStrategy()
        result = strategy.build(simple_group)
        for node, data in result.nodes(data=True):
            assert "x" in data
            assert "y" in data


class TestOpenStreetSecondaryStrategy:
    def test_uses_full_road_graph_and_deterministic_terminals(self, monkeypatch, simple_group):
        """OpenStreet secondary should disable MST and preserve first-seen terminal order."""
        calls = {"reduce_to_mst": None, "terminals": None}

        # Small deterministic candidate graph
        road_graph = nx.Graph()
        road_graph.add_node("a", x=-97.320, y=32.740)
        road_graph.add_node("b", x=-97.321, y=32.741)
        road_graph.add_node("c", x=-97.319, y=32.739)
        road_graph.add_edge("a", "b")
        road_graph.add_edge("b", "c")

        def fake_get_road_network(_polygon, max_distance=None, reduce_to_mst=True):
            calls["reduce_to_mst"] = reduce_to_mst
            return road_graph

        class CaptureRouting(RoutingStrategy):
            def route(self, graph, terminal_nodes):
                calls["terminals"] = terminal_nodes
                # Return a minimal valid graph
                return graph.subgraph(terminal_nodes).copy()

        monkeypatch.setattr("shift.openstreet_roads.get_road_network", fake_get_road_network)
        monkeypatch.setattr(
            "shift.utils.split_network_edges.split_network_edges", lambda g, split_length: g
        )
        monkeypatch.setattr(
            "shift.graph.secondary._get_nearest_nodes_from_graph",
            lambda graph, points: ["a", "b", "a", "c", "b"],
        )

        strategy = OpenStreetSecondaryStrategy(routing_strategy=CaptureRouting())
        strategy.build(simple_group)

        assert calls["reduce_to_mst"] is False
        # First-seen unique order from [a,b,a,c,b] should be [a,b,c]
        assert calls["terminals"] == ["a", "b", "c"]


# ─── Integration: PRSG with strategies ────────────────────────────────────────


class TestPRSGWithStrategies:
    """Test that PRSG accepts strategy parameters without error."""

    def test_prsg_accepts_routing_strategy(self):
        """PRSG should accept routing_strategy parameter."""
        from shift import PRSG

        groups = [
            GroupModel(
                center=GeoLocation(-97.32, 32.74),
                points=[GeoLocation(-97.321, 32.741)],
            )
        ]
        builder = PRSG(
            groups=groups,
            source_location=GeoLocation(-97.33, 32.75),
            routing_strategy=WeightedSteinerTreeStrategy(),
        )
        assert isinstance(builder.routing_strategy, WeightedSteinerTreeStrategy)

    def test_prsg_accepts_secondary_strategy(self):
        """PRSG should accept secondary_strategy parameter."""
        from shift import PRSG

        groups = [
            GroupModel(
                center=GeoLocation(-97.32, 32.74),
                points=[GeoLocation(-97.321, 32.741)],
            )
        ]
        builder = PRSG(
            groups=groups,
            source_location=GeoLocation(-97.33, 32.75),
            secondary_strategy=RadialStrategy(),
        )
        assert isinstance(builder.secondary_strategy, RadialStrategy)

    def test_prsg_default_strategies(self):
        """PRSG should default to SteinerTree + MeshSteiner."""
        from shift import PRSG

        groups = [
            GroupModel(
                center=GeoLocation(-97.32, 32.74),
                points=[GeoLocation(-97.321, 32.741)],
            )
        ]
        builder = PRSG(
            groups=groups,
            source_location=GeoLocation(-97.33, 32.75),
        )
        assert isinstance(builder.routing_strategy, SteinerTreeStrategy)
        assert isinstance(builder.secondary_strategy, MeshSteinerStrategy)

    def test_prsg_uses_full_road_graph_for_full_road_strategy(self, monkeypatch):
        """PRSG should disable MST reduction when FullRoadGraphStrategy is selected."""
        from shift import PRSG

        calls = {"reduce_to_mst": None}

        road_graph = nx.Graph()
        road_graph.add_node("r1", x=-97.320, y=32.740)
        road_graph.add_node("r2", x=-97.321, y=32.741)
        road_graph.add_edge("r1", "r2")

        def fake_get_road_network(_location, max_distance=None, reduce_to_mst=True):
            calls["reduce_to_mst"] = reduce_to_mst
            return road_graph

        monkeypatch.setattr("shift.graph.prsgb.get_road_network", fake_get_road_network)
        monkeypatch.setattr("shift.graph.prsgb.split_network_edges", lambda g, split_length: g)

        groups = [
            GroupModel(
                center=GeoLocation(-97.32, 32.74),
                points=[GeoLocation(-97.321, 32.741)],
            )
        ]
        builder = PRSG(
            groups=groups,
            source_location=GeoLocation(-97.33, 32.75),
            routing_strategy=FullRoadGraphStrategy(),
        )

        _ = builder.build_primary_network()
        assert calls["reduce_to_mst"] is False
