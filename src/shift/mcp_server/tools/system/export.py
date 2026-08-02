"""System export tools."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from dist_stack.manifest import write_manifest
from loguru import logger
from mcp.server import MCPServer
from mcp.server.mcpserver.context import Context

from shift.mcp_server.state import AppContext
from shift.version import VERSION as __version__


def _attach_export_artifact_best_effort(
    *,
    session_id: str,
    system_name: str,
    export_path,
) -> None:
    """Best-effort runstore mirror — never raises.

    Attaches the exported artifact (and its manifest sidecar) to the most
    recent ``shift_feeder`` run of this session — preferring the run whose
    payload built ``system_name``. No-ops with a warning when no runstore is
    configured or no matching run exists.
    """
    try:
        from dist_stack.runstore import RunstoreUnavailableError, attach_artifact, list_runs

        runs = list_runs(run_type="shift_feeder", session_id=session_id, limit=10)
        if not runs:
            logger.warning(
                "runstore: no shift_feeder run found for session — skipping artifact attach"
            )
            return
        run = next(
            (r for r in runs if (r.payload or {}).get("system_name") == system_name),
            runs[0],
        )
        attach_artifact(run.run_id, str(export_path))
    except RunstoreUnavailableError as exc:
        logger.warning(f"runstore unavailable — skipping artifact attach: {exc}")


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

            # Standalone provenance sidecar, always written regardless of any
            # model-registry env var. If a registry record were available from
            # registration, model_id/model_version would be included here.
            write_manifest(
                out,
                artifact_type="shift_feeder",
                tool="export_system_json",
                tool_version=__version__,
                package="shift",
                package_version=__version__,
                config={"system_name": system_name},
            )

            _attach_export_artifact_best_effort(
                session_id=app.session_id,
                system_name=system_name,
                export_path=out,
            )

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
