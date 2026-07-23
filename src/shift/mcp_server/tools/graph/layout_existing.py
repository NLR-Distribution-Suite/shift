"""MCP tool for laying out an abstract graph inside a polygon (no parcels)."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession

from shift.mcp_server.state import AppContext, GraphMeta
from shift.mcp_server.serializers import serialize_graph_summary


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    def layout_existing_graph(
        ctx: Context[ServerSession, AppContext],
        candidate_graphs_path: str,
        source_longitude: float,
        source_latitude: float,
        polygon: list[dict],
        graph_index: int = 0,
        source_node_index: int | None = None,
        layout: str = "spring",
        seed: int | None = None,
        name: str = "",
    ) -> str:
        """Embed an abstract graph inside a polygon with a force-directed layout.

        Unlike ``route_existing_graph`` (which anchors nodes onto fetched parcel
        locations and can collapse detail), this preserves the generated
        topology exactly and assigns geographic coordinates confined to
        ``polygon``, with the source pinned at the substation. It produces a
        DistributionGraph that the SHIFT mappers and system builder consume
        unchanged.

        Args:
            candidate_graphs_path: Path to a PG-DiGress JSON export.
            source_longitude: Longitude of the voltage source (substation).
            source_latitude: Latitude of the voltage source (substation). The
                substation must lie inside ``polygon``.
            polygon: Region of interest as ``[{longitude, latitude}, ...]`` with
                at least 3 vertices; all non-source nodes are confined to it.
            graph_index: Which graph within the export to lay out (default 0).
            source_node_index: Force a specific abstract node to be the source.
                Auto-detected from labels/degree when omitted.
            layout: Layout strategy name (default ``"spring"``).
            seed: Optional RNG seed for a reproducible layout.
            name: Optional name for the created graph.

        Returns:
            JSON with graph_id and a summary of the created graph.
        """
        try:
            from shapely.geometry import Point, Polygon as ShapelyPolygon

            from shift.data_model import GeoLocation
            from shift.graph.existing_graph_router import AbstractGraph, ExistingGraphRouter
            from shift.graph.layout import get_layout_strategy

            if not polygon or len(polygon) < 3:
                return json.dumps(
                    {"success": False, "error": "polygon needs at least 3 vertices."}
                )

            poly_points = [GeoLocation(p["longitude"], p["latitude"]) for p in polygon]
            shp = ShapelyPolygon([(p.longitude, p.latitude) for p in poly_points])
            if not shp.is_valid:
                shp = shp.buffer(0)
            if not shp.contains(Point(source_longitude, source_latitude)):
                return json.dumps(
                    {"success": False, "error": "Substation must be inside the polygon."}
                )

            app: AppContext = ctx.request_context.lifespan_context

            abstract = AbstractGraph.from_json_file(candidate_graphs_path, graph_index=graph_index)
            strategy = get_layout_strategy(layout, seed=seed)
            router = ExistingGraphRouter(
                abstract_graph=abstract,
                parcels=[],
                source_location=GeoLocation(source_longitude, source_latitude),
                source_node_index=source_node_index,
                polygon=poly_points,
                layout_strategy=strategy,
            )
            dist_graph = router.get_distribution_graph()

            graph_id = app.generate_id()
            app.graphs[graph_id] = dist_graph
            app.graph_meta[graph_id] = GraphMeta(
                name=name or f"layout-{graph_id}",
                created_at=datetime.now(timezone.utc).isoformat(),
            )
            app.refresh_graph_meta(graph_id)

            return json.dumps(
                {
                    "success": True,
                    "graph_index": graph_index,
                    "num_abstract_nodes": abstract.num_nodes,
                    "layout": layout,
                    **serialize_graph_summary(dist_graph, graph_id, app.graph_meta[graph_id]),
                }
            )

        except Exception as exc:
            return json.dumps({"success": False, "error": str(exc)})
