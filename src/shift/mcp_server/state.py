"""Shared session state for the MCP server."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from shift.graph.distribution_graph import DistributionGraph
from shift.mapper.base_phase_mapper import BasePhaseMapper
from shift.mapper.base_voltage_mapper import BaseVoltageMapper
from shift.mapper.base_equipment_mapper import BaseEquipmentMapper


@dataclass
class GraphMeta:
    """Metadata stored alongside each DistributionGraph."""

    name: str
    created_at: str  # ISO-8601
    node_count: int = 0
    edge_count: int = 0


@dataclass
class AppContext:
    """In-memory session state shared across all tool calls.

    Populated during the MCPServer lifespan hook and accessed via
    ``ctx.request_context.lifespan_context`` inside any tool function.
    """

    # -- session --------------------------------------------------------------
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    # -- graphs ---------------------------------------------------------------
    graphs: dict[str, DistributionGraph] = field(default_factory=dict)
    graph_meta: dict[str, GraphMeta] = field(default_factory=dict)

    # -- mappers (keyed by graph_id) ------------------------------------------
    phase_mappers: dict[str, BasePhaseMapper] = field(default_factory=dict)
    voltage_mappers: dict[str, BaseVoltageMapper] = field(default_factory=dict)
    equipment_mappers: dict[str, BaseEquipmentMapper] = field(default_factory=dict)

    # -- built systems (keyed by system name) ---------------------------------
    systems: dict[str, Any] = field(default_factory=dict)

    # -- documentation index (doc_key -> content) -----------------------------
    docs_index: dict[str, str] = field(default_factory=dict)
    docs_descriptions: dict[str, str] = field(default_factory=dict)

    # -- helpers --------------------------------------------------------------
    @staticmethod
    def generate_id() -> str:
        return uuid.uuid4().hex[:12]

    def get_graph(self, graph_id: str) -> DistributionGraph:
        if graph_id not in self.graphs:
            raise KeyError(
                f"No graph found with ID '{graph_id}'. Available: {list(self.graphs.keys())}"
            )
        return self.graphs[graph_id]

    def refresh_graph_meta(self, graph_id: str) -> None:
        g = self.graphs[graph_id]
        meta = self.graph_meta[graph_id]
        meta.node_count = len(list(g.get_nodes()))
        meta.edge_count = len(list(g.get_edges()))
