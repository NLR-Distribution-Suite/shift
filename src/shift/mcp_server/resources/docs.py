"""Documentation resources — expose docs via MCP resource URIs."""

from __future__ import annotations

import json

from mcp.server import MCPServer
from mcp.server.mcpserver.context import Context

from shift.mcp_server.state import AppContext

# Module-level reference set during lifespan; resources need it but
# MCP 2.0 disallows Context on static resources.
_app_ctx: AppContext | None = None


def set_app_context(ctx: AppContext) -> None:
    global _app_ctx
    _app_ctx = ctx


def register(mcp: MCPServer) -> None:
    """Register documentation resources."""

    @mcp.resource("shift://docs")
    def list_all_docs() -> str:
        """List all available documentation files."""
        app = _app_ctx
        if app is None:
            return json.dumps({"docs": [], "count": 0})
        docs = []
        for key in sorted(app.docs_index.keys()):
            desc = app.docs_descriptions.get(key, "")
            docs.append({"name": key, "description": desc, "uri": f"shift://docs/{key}"})
        return json.dumps({"docs": docs, "count": len(docs)})

    @mcp.resource("shift://docs/{doc_name}")
    def read_doc_resource(doc_name: str, ctx: Context[AppContext]) -> str:
        """Read a specific documentation file by name.

        URI pattern: shift://docs/{doc_name}
        Example: shift://docs/readme, shift://docs/usage/complete_example
        """
        app: AppContext = ctx.request_context.lifespan_context
        if doc_name not in app.docs_index:
            return json.dumps(
                {
                    "error": f"Document '{doc_name}' not found",
                    "available": sorted(app.docs_index.keys()),
                }
            )
        return app.docs_index[doc_name]

    @mcp.resource("shift://graphs")
    def list_graphs_resource() -> str:
        """List all in-memory distribution graphs."""
        app = _app_ctx
        if app is None:
            return json.dumps({"graphs": [], "count": 0})
        graphs = []
        for gid, meta in app.graph_meta.items():
            graphs.append(
                {
                    "id": gid,
                    "name": meta.name,
                    "node_count": meta.node_count,
                    "edge_count": meta.edge_count,
                    "created_at": meta.created_at,
                }
            )
        return json.dumps({"graphs": graphs, "count": len(graphs)})
