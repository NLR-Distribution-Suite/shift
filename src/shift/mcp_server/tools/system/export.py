"""System export tools."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from mcp.server import MCPServer
from mcp.server.mcpserver.context import Context

from shift.mcp_server.state import AppContext


def register(mcp: MCPServer) -> None:
    @mcp.tool()
    def export_system_json(
        ctx: Context[AppContext],
        system_name: str,
        output_path: str = "",
    ) -> str:
        """Export a distribution system to JSON format.

        Serializes the GDM DistributionSystem to a JSON file that can be
        loaded back later or used with other GDM-compatible tools.

        Args:
            system_name: Name of the system to export.
            output_path: File path for the JSON output. If empty, returns
                         the path to a temporary file.

        Returns:
            JSON with the output file path and success status.
        """
        try:
            app: AppContext = ctx.request_context.lifespan_context
            if system_name not in app.systems:
                return json.dumps(
                    {
                        "success": False,
                        "error": f"No system found with name '{system_name}'. "
                        f"Available: {list(app.systems.keys())}",
                    }
                )

            system = app.systems[system_name]

            if not output_path:
                output_path = str(Path(tempfile.gettempdir()) / f"{system_name}.json")

            out = Path(output_path)
            out.parent.mkdir(parents=True, exist_ok=True)
            system.to_json(out)

            return json.dumps(
                {
                    "success": True,
                    "system_name": system_name,
                    "output_path": str(out),
                    "message": f"System exported to {out}",
                }
            )

        except Exception as exc:
            return json.dumps({"success": False, "error": str(exc)})
