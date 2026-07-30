"""Documentation search tool."""

from __future__ import annotations

import json

from mcp.server import MCPServer
from mcp.server.mcpserver.context import Context

from shift.mcp_server.state import AppContext


def register(mcp: MCPServer) -> None:
    @mcp.tool()
    def search_docs(
        ctx: Context[AppContext],
        query: str,
        max_results: int = 5,
    ) -> str:
        """Search across all NREL-shift documentation for a keyword or phrase.

        Performs case-insensitive search across README, API reference, usage
        guides, and module reference docs. Returns matching sections with
        surrounding context lines.

        Args:
            query: Search term or phrase (case-insensitive).
            max_results: Maximum number of matching documents to return (default 5).

        Returns:
            JSON array of matches with doc_name, matching lines, and context.
        """
        try:
            app: AppContext = ctx.request_context.lifespan_context
            query_lower = query.lower()
            results = []

            for doc_key, content in app.docs_index.items():
                lines = content.split("\n")
                matches = []
                for i, line in enumerate(lines):
                    if query_lower in line.lower():
                        # Include 2 lines of context before and after
                        start = max(0, i - 2)
                        end = min(len(lines), i + 3)
                        context_lines = lines[start:end]
                        matches.append(
                            {
                                "line_number": i + 1,
                                "context": "\n".join(context_lines),
                            }
                        )

                if matches:
                    desc = app.docs_descriptions.get(doc_key, "")
                    results.append(
                        {
                            "doc_name": doc_key,
                            "description": desc,
                            "match_count": len(matches),
                            "matches": matches[:3],  # Limit context per doc
                        }
                    )

            # Sort by match count descending
            results.sort(key=lambda x: x["match_count"], reverse=True)
            results = results[:max_results]

            return json.dumps(
                {
                    "success": True,
                    "query": query,
                    "results": results,
                    "total_docs_matched": len(results),
                }
            )

        except Exception as exc:
            return json.dumps({"success": False, "error": str(exc)})
