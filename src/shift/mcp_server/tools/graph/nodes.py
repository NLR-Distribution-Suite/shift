"""Node manipulation tools."""

from __future__ import annotations

import json

from mcp.server import MCPServer
from mcp.server.mcpserver.context import Context

from shift.mcp_server.state import AppContext
from shift.mcp_server.serializers import serialize_node

# Lookup table: string name ➜ GDM class
_ASSET_TYPE_MAP: dict[str, type] | None = None


def _get_asset_type_map() -> dict[str, type]:
    global _ASSET_TYPE_MAP
    if _ASSET_TYPE_MAP is None:
        from gdm.distribution.components import (
            DistributionLoad,
            DistributionSolar,
            DistributionCapacitor,
            DistributionVoltageSource,
        )

        _ASSET_TYPE_MAP = {
            "DistributionLoad": DistributionLoad,
            "DistributionSolar": DistributionSolar,
            "DistributionCapacitor": DistributionCapacitor,
            "DistributionVoltageSource": DistributionVoltageSource,
        }
    return _ASSET_TYPE_MAP


def register(mcp: MCPServer) -> None:
    @mcp.tool()
    def add_node(
        ctx: Context[AppContext],
        graph_id: str,
        node_name: str,
        longitude: float,
        latitude: float,
        assets: list[str] | None = None,
    ) -> str:
        """Add a node to a distribution graph.

        Args:
            graph_id: Graph identifier.
            node_name: Unique name for this node.
            longitude: Longitude coordinate.
            latitude: Latitude coordinate.
            assets: Optional list of asset type names attached to this node.
                    Valid values: "DistributionLoad", "DistributionSolar",
                    "DistributionCapacitor", "DistributionVoltageSource".

        Returns:
            JSON confirmation with the created node details.
        """
        try:
            from infrasys import Location
            from shift.data_model import NodeModel

            app: AppContext = ctx.request_context.lifespan_context
            graph = app.get_graph(graph_id)

            asset_types = set()
            if assets:
                type_map = _get_asset_type_map()
                for a in assets:
                    if a not in type_map:
                        return json.dumps(
                            {
                                "success": False,
                                "error": f"Unknown asset type '{a}'. Valid: {list(type_map.keys())}",
                            }
                        )
                    asset_types.add(type_map[a])

            node = NodeModel(
                name=node_name,
                location=Location(x=longitude, y=latitude),
                assets=asset_types or None,
            )
            graph.add_node(node)
            app.refresh_graph_meta(graph_id)

            return json.dumps({"success": True, "node": serialize_node(node)})

        except Exception as exc:
            return json.dumps({"success": False, "error": str(exc)})

    @mcp.tool()
    def remove_node(
        ctx: Context[AppContext],
        graph_id: str,
        node_name: str,
    ) -> str:
        """Remove a node from a distribution graph.

        Args:
            graph_id: Graph identifier.
            node_name: Name of the node to remove.

        Returns:
            JSON confirmation of removal.
        """
        try:
            app: AppContext = ctx.request_context.lifespan_context
            graph = app.get_graph(graph_id)
            graph.remove_node(node_name)
            app.refresh_graph_meta(graph_id)
            return json.dumps({"success": True, "removed": node_name})
        except Exception as exc:
            return json.dumps({"success": False, "error": str(exc)})

    @mcp.tool()
    def get_node(
        ctx: Context[AppContext],
        graph_id: str,
        node_name: str,
    ) -> str:
        """Get details of a specific node in a distribution graph.

        Args:
            graph_id: Graph identifier.
            node_name: Name of the node to retrieve.

        Returns:
            JSON with node details: name, coordinates, and asset types.
        """
        try:
            app: AppContext = ctx.request_context.lifespan_context
            graph = app.get_graph(graph_id)
            node = graph.get_node(node_name)
            return json.dumps({"success": True, "node": serialize_node(node)})
        except Exception as exc:
            return json.dumps({"success": False, "error": str(exc)})
