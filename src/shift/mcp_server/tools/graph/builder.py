"""High-level graph builder tools."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from loguru import logger
from mcp.server import MCPServer
from mcp.server.mcpserver.context import Context

from shift.mcp_server.state import AppContext, GraphMeta
from shift.mcp_server.serializers import serialize_graph_summary


def _create_run_best_effort(
    *,
    tool: str,
    run_type: str,
    run_id: str,
    session_id: str,
    payload: dict,
) -> None:
    """Best-effort runstore mirror — never raises.

    Records a ``create_run`` row when a runstore is configured
    (``DIST_STACK_RUNSTORE_DB`` set); otherwise logs a warning and returns so
    tool behavior is identical to a runstore-less deployment.
    """
    try:
        from dist_stack.runstore import RunstoreUnavailableError, create_run

        create_run(
            tool=tool,
            run_type=run_type,
            run_id=run_id,
            status="succeeded",
            session_id=session_id,
            payload=payload,
        )
    except RunstoreUnavailableError as exc:
        logger.warning(f"runstore unavailable — skipping run record: {exc}")


def register(mcp: MCPServer) -> None:
    @mcp.tool()
    def build_graph_from_groups(
        ctx: Context[AppContext],
        groups: list[dict],
        source_longitude: float,
        source_latitude: float,
        buffer_meters: float = 20.0,
        name: str = "",
    ) -> str:
        """Build a complete distribution graph from parcel groups using the PRSG algorithm.

        This is a high-level shortcut that runs the full Primary-Road /
        Secondary-Grid graph building pipeline. It:
        1. Fetches the road network from OpenStreetMap
        2. Builds a primary network connecting cluster centers via roads
        3. Builds secondary (grid) networks within each cluster
        4. Combines everything into a DistributionGraph

        Args:
            groups: List of cluster group dicts, each with:
                    - center: {longitude, latitude}
                    - points: [{longitude, latitude}, ...]
            source_longitude: Longitude of the voltage source (substation).
            source_latitude: Latitude of the voltage source (substation).
            buffer_meters: Buffer distance around points for road search (default 20).
            name: Optional name for the created graph.

        Returns:
            JSON with graph_id and summary of the created graph.
        """
        try:
            from shift.graph.prsgb import PRSG
            from shift.data_model import GeoLocation, GroupModel
            from gdm.quantities import Distance

            app: AppContext = ctx.request_context.lifespan_context

            group_models = []
            for g in groups:
                center = GeoLocation(g["center"]["longitude"], g["center"]["latitude"])
                points = [GeoLocation(p["longitude"], p["latitude"]) for p in g["points"]]
                group_models.append(GroupModel(center=center, points=points))

            source_loc = GeoLocation(source_longitude, source_latitude)
            builder = PRSG(
                groups=group_models,
                source_location=source_loc,
                buffer=Distance(buffer_meters, "m"),
            )
            dist_graph = builder.get_distribution_graph()

            graph_id = app.generate_id()
            app.graphs[graph_id] = dist_graph
            app.graph_meta[graph_id] = GraphMeta(
                name=name or f"prsg-{graph_id}",
                created_at=datetime.now(timezone.utc).isoformat(),
            )
            app.refresh_graph_meta(graph_id)

            _create_run_best_effort(
                tool="build_graph_from_groups",
                run_type="shift_graph",
                run_id=f"graph_{uuid.uuid4().hex[:12]}",
                session_id=app.session_id,
                payload={
                    "graph_id": graph_id,
                    "node_count": app.graph_meta[graph_id].node_count,
                    "edge_count": app.graph_meta[graph_id].edge_count,
                },
            )

            return json.dumps(
                {
                    "success": True,
                    **serialize_graph_summary(dist_graph, graph_id, app.graph_meta[graph_id]),
                }
            )

        except Exception as exc:
            return json.dumps({"success": False, "error": str(exc)})
