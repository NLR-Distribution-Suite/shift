"""Road network fetching tools."""

from __future__ import annotations

import json

from mcp.server import MCPServer

from shift.mcp_server.serializers import serialize_nx_graph_summary


def register(mcp: MCPServer) -> None:
    """Register road network tools on the MCPServer instance."""

    @mcp.tool()
    def fetch_road_network(
        location: str,
        distance_meters: float = 500.0,
    ) -> str:
        """Fetch the road network from OpenStreetMap around a location.

        Retrieves a networkx graph of the road network which can be used
        as the basis for building a distribution system graph.

        Args:
            location: Address string (e.g. "Fort Worth, TX") or coordinates
                      as "longitude,latitude".
            distance_meters: Search radius in meters (default 500, max 5000).

        Returns:
            JSON summary with node_count and edge_count of the road network,
            plus sample node coordinates.
        """
        try:
            from shift.openstreet_roads import get_road_network
            from shift.data_model import GeoLocation
            from gdm.quantities import Distance

            distance_meters = min(distance_meters, 5000.0)

            if "," in location:
                parts = location.split(",")
                if len(parts) == 2:
                    try:
                        lon, lat = float(parts[0].strip()), float(parts[1].strip())
                        loc = GeoLocation(lon, lat)
                    except ValueError:
                        loc = location
                else:
                    loc = location
            else:
                loc = location

            graph = get_road_network(loc, Distance(distance_meters, "m"))

            summary = serialize_nx_graph_summary(graph)

            # Include sample node coordinates (up to 10)
            sample_nodes = []
            for i, (node_id, data) in enumerate(graph.nodes(data=True)):
                if i >= 10:
                    break
                sample_nodes.append(
                    {
                        "id": str(node_id),
                        "x": data.get("x"),
                        "y": data.get("y"),
                    }
                )
            summary["sample_nodes"] = sample_nodes
            summary["success"] = True

            return json.dumps(summary)

        except Exception as exc:
            return json.dumps({"success": False, "error": str(exc)})
