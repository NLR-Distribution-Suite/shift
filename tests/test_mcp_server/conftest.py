"""Shared fixtures for MCP server tests.

Provides a mock MCP Context that injects an AppContext, plus helper
factories for building graphs with nodes/edges already populated.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import pytest
from gdm.systems.distribution.components import (
    DistributionBranchBase,
    DistributionLoad,
    DistributionTransformer,
    DistributionVoltageSource,
)
from gdm.quantities import Distance
from infrasys import Location

from shift.data_model import EdgeModel, NodeModel
from shift.graph.distribution_graph import DistributionGraph
from shift.mcp_server.state import AppContext, GraphMeta


# ---------------------------------------------------------------------------
# Mock MCP Context
# ---------------------------------------------------------------------------


@dataclass
class _MockRequestContext:
    lifespan_context: AppContext


class MockContext:
    """Mimics ``mcp.server.fastmcp.Context`` for tool testing.

    Usage::

        ctx = MockContext(app_context)
        result = some_tool(ctx, ...)
    """

    def __init__(self, app: AppContext) -> None:
        self.request_context = _MockRequestContext(lifespan_context=app)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def app_context() -> AppContext:
    """Return a fresh AppContext with sample docs loaded."""
    ctx = AppContext()
    ctx.docs_index = {
        "readme": "# NREL-shift\n\nA Python framework for distribution feeders.\n\n## Features\n\n- Graph modeling\n- Phase mapping",
        "quickstart": "# Quick Start\n\nInstall with pip.\n\n## Setup\n\nRun the tests.",
        "usage/complete_example": "# Complete Example\n\n## Step 1\n\nFetch parcels.\n\n## Step 2\n\nBuild graph.",
    }
    ctx.docs_descriptions = {
        "readme": "Project overview.",
        "quickstart": "Quick-start guide.",
        "usage/complete_example": "End-to-end workflow.",
    }
    return ctx


@pytest.fixture
def mock_ctx(app_context: AppContext) -> MockContext:
    """Return a MockContext wrapping a fresh AppContext."""
    return MockContext(app_context)


@pytest.fixture
def sample_graph() -> DistributionGraph:
    """Create a small distribution graph with 3 nodes and 2 edges."""
    graph = DistributionGraph()
    n1 = NodeModel(
        name="src", location=Location(x=-105.2, y=39.75), assets={DistributionVoltageSource}
    )
    n2 = NodeModel(name="bus1", location=Location(x=-105.21, y=39.76))
    n3 = NodeModel(name="load1", location=Location(x=-105.22, y=39.77), assets={DistributionLoad})
    graph.add_edge(n1, n2, edge_data=EdgeModel(name="xfmr1", edge_type=DistributionTransformer))
    graph.add_edge(
        n2,
        n3,
        edge_data=EdgeModel(
            name="line1", edge_type=DistributionBranchBase, length=Distance(100, "m")
        ),
    )
    return graph


@pytest.fixture
def populated_context(
    app_context: AppContext, sample_graph: DistributionGraph
) -> tuple[AppContext, str]:
    """Return an AppContext with a graph already registered, plus its graph_id."""
    gid = "test123"
    app_context.graphs[gid] = sample_graph
    app_context.graph_meta[gid] = GraphMeta(
        name="test-graph",
        created_at="2026-01-01T00:00:00+00:00",
        node_count=3,
        edge_count=2,
    )
    return app_context, gid


def parse(result: str) -> dict[str, Any]:
    """Parse a JSON tool result string."""
    return json.loads(result)
