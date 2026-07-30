from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from shift.graph.distribution_graph import DistributionGraph


@dataclass
class UiSessionState:
    """In-memory session state for the UI API.

    This intentionally mirrors the MCP server approach to keep behavior
    familiar and make it easy to persist snapshots later.
    """

    graphs: dict[str, DistributionGraph] = field(default_factory=dict)
    phase_mappers: dict[str, Any] = field(default_factory=dict)
    voltage_mappers: dict[str, Any] = field(default_factory=dict)
    equipment_mappers: dict[str, Any] = field(default_factory=dict)
    systems: dict[str, Any] = field(default_factory=dict)

    _counter: int = 0

    def new_id(self, prefix: str) -> str:
        self._counter += 1
        return f"{prefix}-{self._counter:04d}"
