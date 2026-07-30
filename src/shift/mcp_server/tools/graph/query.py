"""Graph query tools."""

from __future__ import annotations

import json

from mcp.server import MCPServer
from mcp.server.mcpserver.context import Context

from shift.mcp_server.state import AppContext
from shift.mcp_server.serializers import (
    serialize_graph_summary,
    serialize_node,
    serialize_edge_tuple,
)


def register(mcp: MCPServer) -> None:
    @mcp.tool()
    def query_graph(
        ctx: Context[AppContext],
        graph_id: str,
        query_type: str = "summary",
    ) -> str:
        """Query information about a distribution graph.

        Args:
            graph_id: Graph identifier.
            query_type: Type of query to run. Options:
                - "summary": Node/edge counts, vsource node
                - "nodes": List all nodes with coordinates and assets
                - "edges": List all edges with connections and types
                - "vsource": Get the voltage source node name
                - "dfs_tree": Get DFS traversal order from vsource

        Returns:
            JSON with the requested graph information.
        """
        try:
            app: AppContext = ctx.request_context.lifespan_context
            graph = app.get_graph(graph_id)
            meta = app.graph_meta.get(graph_id)

            if query_type == "summary":
                app.refresh_graph_meta(graph_id)
                return json.dumps(
                    {
                        "success": True,
                        **serialize_graph_summary(graph, graph_id, meta),
                    }
                )

            elif query_type == "nodes":
                nodes = [serialize_node(n) for n in graph.get_nodes()]
                return json.dumps({"success": True, "nodes": nodes, "count": len(nodes)})

            elif query_type == "edges":
                edges = [serialize_edge_tuple(f, t, e) for f, t, e in graph.get_edges()]
                return json.dumps({"success": True, "edges": edges, "count": len(edges)})

            elif query_type == "vsource":
                vsource = graph.vsource_node
                return json.dumps({"success": True, "vsource_node": vsource})

            elif query_type == "dfs_tree":
                dfs = graph.get_dfs_tree()
                node_order = list(dfs.nodes())
                edge_list = [(u, v) for u, v in dfs.edges()]
                return json.dumps(
                    {
                        "success": True,
                        "dfs_node_order": node_order,
                        "dfs_edges": edge_list,
                    }
                )

            else:
                return json.dumps(
                    {
                        "success": False,
                        "error": f"Unknown query_type '{query_type}'. "
                        "Valid: summary, nodes, edges, vsource, dfs_tree",
                    }
                )

        except Exception as exc:
            return json.dumps({"success": False, "error": str(exc)})
