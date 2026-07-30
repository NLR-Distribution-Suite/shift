"""Graph lifecycle management tools."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from mcp.server import MCPServer
from mcp.server.mcpserver.context import Context

from shift.mcp_server.state import AppContext, GraphMeta
from shift.mcp_server.serializers import serialize_graph_summary


def register(mcp: MCPServer) -> None:
    @mcp.tool()
    def create_graph(
        ctx: Context[AppContext],
        name: str = "",
    ) -> str:
        """Create a new empty distribution graph.

        Creates a graph that can hold nodes (buses, loads, sources) and edges
        (lines, transformers). Returns a graph_id for use in all subsequent
        graph operations.

        Args:
            name: Optional human-readable name for the graph.

        Returns:
            JSON with graph_id to use in later calls.
        """
        try:
            from shift.graph.distribution_graph import DistributionGraph

            app: AppContext = ctx.request_context.lifespan_context
            graph_id = app.generate_id()
            app.graphs[graph_id] = DistributionGraph()
            app.graph_meta[graph_id] = GraphMeta(
                name=name or f"graph-{graph_id}",
                created_at=datetime.now(timezone.utc).isoformat(),
            )
            return json.dumps(
                {
                    "success": True,
                    "graph_id": graph_id,
                    "name": app.graph_meta[graph_id].name,
                }
            )
        except Exception as exc:
            return json.dumps({"success": False, "error": str(exc)})

    @mcp.tool()
    def delete_graph(
        ctx: Context[AppContext],
        graph_id: str,
    ) -> str:
        """Delete a distribution graph and its associated mappers.

        Args:
            graph_id: Graph identifier returned by create_graph.

        Returns:
            JSON confirmation of deletion.
        """
        try:
            app: AppContext = ctx.request_context.lifespan_context
            if graph_id not in app.graphs:
                return json.dumps(
                    {
                        "success": False,
                        "error": f"No graph found with ID '{graph_id}'.",
                    }
                )
            del app.graphs[graph_id]
            del app.graph_meta[graph_id]
            app.phase_mappers.pop(graph_id, None)
            app.voltage_mappers.pop(graph_id, None)
            app.equipment_mappers.pop(graph_id, None)
            return json.dumps({"success": True, "deleted": graph_id})
        except Exception as exc:
            return json.dumps({"success": False, "error": str(exc)})

    @mcp.tool()
    def list_graphs(
        ctx: Context[AppContext],
    ) -> str:
        """List all distribution graphs in the current session.

        Returns:
            JSON array of graph summaries with graph_id, name, node_count,
            edge_count, and vsource status.
        """
        try:
            app: AppContext = ctx.request_context.lifespan_context
            results = []
            for gid, graph in app.graphs.items():
                app.refresh_graph_meta(gid)
                results.append(serialize_graph_summary(graph, gid, app.graph_meta.get(gid)))
            return json.dumps({"success": True, "graphs": results, "count": len(results)})
        except Exception as exc:
            return json.dumps({"success": False, "error": str(exc)})
