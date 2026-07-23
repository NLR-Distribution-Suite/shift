"""Tests for the ExistingGraphRouter (routing an externally-provided graph)."""

import json

import pytest
from gdm.distribution.components import DistributionLoad, DistributionVoltageSource

from shift.data_model import GeoLocation
from shift.exceptions import InvalidInputError
from shift.graph.existing_graph_router import (
    AbstractGraph,
    ExistingGraphRouter,
    resolve_node_roles,
)


# ─── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def star_export():
    """A DiGress-style JSON export: a 5-node star (node 0 = hub, 1-4 = leaves)."""
    return {
        "metadata": {
            "node_labels": ["substation", "bus"],
            "edge_labels": ["none", "line"],
            "num_graphs": 1,
        },
        "graphs": [
            {
                "graph_index": 0,
                "num_nodes": 5,
                # node 0 is class 0 ("substation"), the rest are class 1 ("bus")
                "node_classes": [0, 1, 1, 1, 1],
                "edges": [[0, 1, 1], [0, 2, 1], [0, 3, 1], [0, 4, 1]],
            }
        ],
    }


@pytest.fixture
def parcels():
    return [
        GeoLocation(-97.330, 32.750),
        GeoLocation(-97.320, 32.750),
        GeoLocation(-97.330, 32.740),
        GeoLocation(-97.320, 32.740),
        GeoLocation(-97.325, 32.745),
        GeoLocation(-97.322, 32.748),
    ]


# ─── AbstractGraph parsing ───────────────────────────────────────────────────


def test_abstract_graph_from_export(star_export):
    abstract = AbstractGraph.from_export(star_export, graph_index=0)
    assert abstract.num_nodes == 5
    assert len(abstract.edges) == 4
    assert abstract.node_labels == ["substation", "bus"]
    assert abstract.edge_labels == ["none", "line"]


def test_abstract_graph_bad_index(star_export):
    with pytest.raises(InvalidInputError):
        AbstractGraph.from_export(star_export, graph_index=5)


def test_abstract_graph_from_json_file(tmp_path, star_export):
    path = tmp_path / "candidate_graphs.json"
    path.write_text(json.dumps(star_export), encoding="utf-8")
    abstract = AbstractGraph.from_json_file(path, graph_index=0)
    assert abstract.num_nodes == 5


# ─── Role resolution ─────────────────────────────────────────────────────────


def test_resolve_roles_prefers_labelled_source(star_export):
    import networkx as nx

    abstract = AbstractGraph.from_export(star_export)
    g = nx.Graph()
    g.add_nodes_from(range(abstract.num_nodes))
    g.add_edges_from(abstract.edges)
    roles = resolve_node_roles(abstract, g)
    # node 0 has the "substation" label -> source
    assert roles.source == 0
    assert set(roles.loads) == {1, 2, 3, 4}


def test_resolve_roles_explicit_index(star_export):
    import networkx as nx

    abstract = AbstractGraph.from_export(star_export)
    g = nx.Graph()
    g.add_nodes_from(range(abstract.num_nodes))
    g.add_edges_from(abstract.edges)
    roles = resolve_node_roles(abstract, g, source_node_index=2)
    assert roles.source == 2


# ─── Full routing ────────────────────────────────────────────────────────────


def test_route_existing_graph_produces_valid_distribution_graph(star_export, parcels):
    abstract = AbstractGraph.from_export(star_export)
    router = ExistingGraphRouter(
        abstract_graph=abstract,
        parcels=parcels,
        source_location=GeoLocation(-97.315, 32.755),
    )
    dist_graph = router.get_distribution_graph()

    # A voltage source must be designated.
    assert dist_graph.vsource_node is not None

    # Every node carries a geographic location.
    nodes = list(dist_graph.get_nodes())
    assert all(node.location is not None for node in nodes)

    # Loads are present (one per leaf node).
    load_nodes = [n for n in nodes if n.assets and DistributionLoad in n.assets]
    assert len(load_nodes) == 4

    # Exactly one voltage source asset.
    vsource_nodes = [n for n in nodes if n.assets and DistributionVoltageSource in n.assets]
    assert len(vsource_nodes) == 1

    # Transformer explosion adds the "_ht" high-tension nodes -> more nodes than
    # the original abstract topology.
    assert len(nodes) > abstract.num_nodes


def test_route_requires_parcels(star_export):
    abstract = AbstractGraph.from_export(star_export)
    with pytest.raises(InvalidInputError):
        ExistingGraphRouter(
            abstract_graph=abstract,
            parcels=[],
            source_location=GeoLocation(-97.315, 32.755),
        )


def test_route_disconnected_topology_is_connected(parcels):
    """Two disconnected edges should be joined into one connected graph."""
    export = {
        "metadata": {"node_labels": [], "edge_labels": []},
        "graphs": [
            {
                "graph_index": 0,
                "num_nodes": 4,
                "node_classes": [0, 0, 0, 0],
                "edges": [[0, 1, 1], [2, 3, 1]],
            }
        ],
    }
    abstract = AbstractGraph.from_export(export)
    router = ExistingGraphRouter(
        abstract_graph=abstract,
        parcels=parcels,
        source_location=GeoLocation(-97.315, 32.755),
    )
    dist_graph = router.get_distribution_graph()
    # DFS tree from the source should reach a transformer/load subtree.
    assert dist_graph.vsource_node is not None
    assert len(list(dist_graph.get_nodes())) >= 4
