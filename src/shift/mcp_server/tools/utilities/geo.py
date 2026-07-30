"""Geospatial utility tools."""

from __future__ import annotations

import json

from mcp.server import MCPServer

from shift.mcp_server.serializers import serialize_geo_location


def register(mcp: MCPServer) -> None:
    @mcp.tool()
    def distance_between_points(
        lon1: float,
        lat1: float,
        lon2: float,
        lat2: float,
    ) -> str:
        """Calculate the geodesic distance between two geographic points.

        Uses the Haversine formula to compute the real-world distance
        between two longitude/latitude coordinate pairs.

        Args:
            lon1: Longitude of the first point.
            lat1: Latitude of the first point.
            lon2: Longitude of the second point.
            lat2: Latitude of the second point.

        Returns:
            JSON with distance in meters.
        """
        try:
            from shift.utils.split_network_edges import get_distance_between_points
            from shift.data_model import GeoLocation

            p1 = GeoLocation(lon1, lat1)
            p2 = GeoLocation(lon2, lat2)
            dist = get_distance_between_points(p1, p2)

            return json.dumps(
                {
                    "success": True,
                    "distance_meters": float(dist.to("m").magnitude),
                    "from": serialize_geo_location(p1),
                    "to": serialize_geo_location(p2),
                }
            )

        except Exception as exc:
            return json.dumps({"success": False, "error": str(exc)})

    @mcp.tool()
    def polygon_from_points(
        points: list[dict[str, float]],
        buffer_meters: float = 50.0,
    ) -> str:
        """Create a polygon boundary from a set of geographic points.

        Computes the convex hull of the given points and expands it by
        the specified buffer distance.

        Args:
            points: List of {longitude, latitude} dicts (at least 3).
            buffer_meters: Buffer distance in meters to expand the polygon.

        Returns:
            JSON with polygon vertex coordinates (WKT-style exterior ring).
        """
        try:
            from shift.utils.polygon_from_points import get_polygon_from_points
            from shift.data_model import GeoLocation
            from gdm.quantities import Distance

            if len(points) < 3:
                return json.dumps(
                    {
                        "success": False,
                        "error": "At least 3 points required to form a polygon.",
                    }
                )

            geo_points = [GeoLocation(p["longitude"], p["latitude"]) for p in points]
            polygon = get_polygon_from_points(geo_points, Distance(buffer_meters, "m"))

            coords = [{"longitude": x, "latitude": y} for x, y in polygon.exterior.coords]

            return json.dumps(
                {
                    "success": True,
                    "vertices": coords,
                    "num_vertices": len(coords),
                }
            )

        except Exception as exc:
            return json.dumps({"success": False, "error": str(exc)})
