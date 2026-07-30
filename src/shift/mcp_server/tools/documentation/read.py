"""Documentation reading tools."""

from __future__ import annotations

import json
import re

from mcp.server import MCPServer
from mcp.server.mcpserver.context import Context

from shift.mcp_server.state import AppContext


def _extract_section(content: str, section: str) -> str | None:
    """Extract content under a specific markdown heading. Returns None if not found."""
    section_lower = section.lower()
    lines = content.split("\n")
    in_section = False
    section_lines = []
    section_level = 0

    for line in lines:
        heading_match = re.match(r"^(#{1,6})\s+(.*)", line)
        if heading_match:
            level = len(heading_match.group(1))
            title = heading_match.group(2).strip()

            if title.lower() == section_lower:
                in_section = True
                section_level = level
                section_lines.append(line)
                continue

            if in_section and level <= section_level:
                break

        if in_section:
            section_lines.append(line)

    return "\n".join(section_lines) if section_lines else None


def register(mcp: MCPServer) -> None:
    @mcp.tool()
    def list_docs(
        ctx: Context[AppContext],
    ) -> str:
        """List all available NREL-shift documentation files.

        Returns:
            JSON array of doc names with brief descriptions.
        """
        try:
            app: AppContext = ctx.request_context.lifespan_context
            docs = []
            for doc_key in sorted(app.docs_index.keys()):
                desc = app.docs_descriptions.get(doc_key, "")
                docs.append({"name": doc_key, "description": desc})

            return json.dumps({"success": True, "docs": docs, "count": len(docs)})

        except Exception as exc:
            return json.dumps({"success": False, "error": str(exc)})

    @mcp.tool()
    def read_doc(
        ctx: Context[AppContext],
        doc_name: str,
        section: str = "",
    ) -> str:
        """Read a specific NREL-shift documentation file.

        Use list_docs to see available doc names.

        Args:
            doc_name: Document identifier (e.g. "readme", "api_reference",
                      "usage/complete_example", "references/data_model").
            section: Optional section heading to extract. If provided, returns
                     only the content under that heading. Case-insensitive.

        Returns:
            The documentation content as text (Markdown or RST format).
        """
        try:
            app: AppContext = ctx.request_context.lifespan_context
            if doc_name not in app.docs_index:
                return json.dumps(
                    {
                        "success": False,
                        "error": f"Document '{doc_name}' not found. "
                        f"Available: {sorted(app.docs_index.keys())}",
                    }
                )

            content = app.docs_index[doc_name]

            if section:
                extracted = _extract_section(content, section)
                if extracted is None:
                    return json.dumps(
                        {
                            "success": False,
                            "error": f"Section '{section}' not found in '{doc_name}'.",
                        }
                    )
                content = extracted

            return json.dumps(
                {
                    "success": True,
                    "doc_name": doc_name,
                    "content": content,
                }
            )

        except Exception as exc:
            return json.dumps({"success": False, "error": str(exc)})
