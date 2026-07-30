"""Nearest-points utility tools."""

from __future__ import annotations

import json

from mcp.server import MCPServer


def register(mcp: MCPServer) -> None:
    @mcp.tool()
    def find_nearest_points(
        source_points: list[list[float]],
        target_points: list[list[float]],
    ) -> str:
        """Find the nearest target point for each source point.

        For each source point, identifies the index of the closest target
        point. Useful for mapping parcels to nearest road nodes.

        Args:
            source_points: List of [x, y] coordinate pairs (source locations).
            target_points: List of [x, y] coordinate pairs (target locations).

        Returns:
            JSON array of indices — nearest_indices[i] is the index of
            the target point closest to source_points[i].
        """
        try:
            from shift.utils.nearest_points import get_nearest_points

            indices = get_nearest_points(source_points, target_points)

            return json.dumps(
                {
                    "success": True,
                    "nearest_indices": indices.tolist(),
                    "num_source": len(source_points),
                    "num_target": len(target_points),
                }
            )

        except Exception as exc:
            return json.dumps({"success": False, "error": str(exc)})
