"""Edge manipulation tools."""

from __future__ import annotations

import json

from mcp.server import MCPServer
from mcp.server.mcpserver.context import Context

from shift.mcp_server.state import AppContext
from shift.mcp_server.serializers import serialize_edge_tuple

# Lazy-loaded edge type map
_EDGE_TYPE_MAP: dict[str, type] | None = None


def _get_edge_type_map() -> dict[str, type]:
    global _EDGE_TYPE_MAP
    if _EDGE_TYPE_MAP is None:
        from gdm.distribution.components import (
            DistributionBranchBase,
            DistributionTransformer,
        )

        _EDGE_TYPE_MAP = {
            "DistributionBranchBase": DistributionBranchBase,
            "DistributionTransformer": DistributionTransformer,
        }
    return _EDGE_TYPE_MAP


def register(mcp: MCPServer) -> None:
    @mcp.tool()
    def add_edge(
        ctx: Context[AppContext],
        graph_id: str,
        from_node: str,
        to_node: str,
        edge_name: str,
        edge_type: str,
        length_meters: float | None = None,
    ) -> str:
        """Add an edge (line or transformer) to a distribution graph.

        Args:
            graph_id: Graph identifier.
            from_node: Source node name.
            to_node: Target node name.
            edge_name: Unique name for this edge.
            edge_type: Type of edge — "DistributionBranchBase" for lines/cables
                       or "DistributionTransformer" for transformers.
            length_meters: Edge length in meters. Required for branch edges,
                           must be omitted for transformer edges.

        Returns:
            JSON confirmation with edge details.
        """
        try:
            from shift.data_model import EdgeModel
            from gdm.quantities import Distance

            app: AppContext = ctx.request_context.lifespan_context
            graph = app.get_graph(graph_id)

            type_map = _get_edge_type_map()
            if edge_type not in type_map:
                return json.dumps(
                    {
                        "success": False,
                        "error": f"Unknown edge_type '{edge_type}'. Valid: {list(type_map.keys())}",
                    }
                )

            et = type_map[edge_type]
            length = Distance(length_meters, "m") if length_meters is not None else None

            edge = EdgeModel(name=edge_name, edge_type=et, length=length)
            graph.add_edge(from_node, to_node, edge)
            app.refresh_graph_meta(graph_id)

            return json.dumps(
                {
                    "success": True,
                    "edge": serialize_edge_tuple(from_node, to_node, edge),
                }
            )

        except Exception as exc:
            return json.dumps({"success": False, "error": str(exc)})

    @mcp.tool()
    def remove_edge(
        ctx: Context[AppContext],
        graph_id: str,
        from_node: str,
        to_node: str,
    ) -> str:
        """Remove an edge from a distribution graph.

        Args:
            graph_id: Graph identifier.
            from_node: Source node name.
            to_node: Target node name.

        Returns:
            JSON confirmation of removal.
        """
        try:
            app: AppContext = ctx.request_context.lifespan_context
            graph = app.get_graph(graph_id)
            graph.remove_edge(from_node, to_node)
            app.refresh_graph_meta(graph_id)
            return json.dumps({"success": True, "removed": f"{from_node} -> {to_node}"})
        except Exception as exc:
            return json.dumps({"success": False, "error": str(exc)})

    @mcp.tool()
    def get_edge(
        ctx: Context[AppContext],
        graph_id: str,
        from_node: str,
        to_node: str,
    ) -> str:
        """Get details of a specific edge in a distribution graph.

        Args:
            graph_id: Graph identifier.
            from_node: Source node name.
            to_node: Target node name.

        Returns:
            JSON with edge details: name, type, and length.
        """
        try:
            app: AppContext = ctx.request_context.lifespan_context
            graph = app.get_graph(graph_id)
            edge = graph.get_edge(from_node, to_node)
            return json.dumps(
                {
                    "success": True,
                    "edge": serialize_edge_tuple(from_node, to_node, edge),
                }
            )
        except Exception as exc:
            return json.dumps({"success": False, "error": str(exc)})
