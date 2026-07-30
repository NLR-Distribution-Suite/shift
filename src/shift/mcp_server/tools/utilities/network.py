"""Network utility tools."""

from __future__ import annotations

import json

from mcp.server import MCPServer

from shift.mcp_server.serializers import serialize_nx_graph_summary


def register(mcp: MCPServer) -> None:
    @mcp.tool()
    def create_mesh_network(
        lower_left_lon: float,
        lower_left_lat: float,
        upper_right_lon: float,
        upper_right_lat: float,
        spacing_meters: float = 50.0,
    ) -> str:
        """Create a regular 2D mesh/grid network between two corner points.

        Generates a networkx graph with nodes arranged in a grid pattern,
        useful as a base network for secondary distribution systems.

        Args:
            lower_left_lon: Longitude of the lower-left corner.
            lower_left_lat: Latitude of the lower-left corner.
            upper_right_lon: Longitude of the upper-right corner.
            upper_right_lat: Latitude of the upper-right corner.
            spacing_meters: Distance between grid nodes in meters (default 50).

        Returns:
            JSON summary of the generated mesh network.
        """
        try:
            from shift.utils.mesh_network import get_mesh_network
            from shift.data_model import GeoLocation
            from gdm.quantities import Distance

            mesh = get_mesh_network(
                lower_left=GeoLocation(lower_left_lon, lower_left_lat),
                upper_right=GeoLocation(upper_right_lon, upper_right_lat),
                spacing=Distance(spacing_meters, "m"),
            )

            summary = serialize_nx_graph_summary(mesh)
            summary["success"] = True
            summary["spacing_meters"] = spacing_meters

            return json.dumps(summary)

        except Exception as exc:
            return json.dumps({"success": False, "error": str(exc)})

    @mcp.tool()
    def split_edges(
        split_length_meters: float,
        nodes: list[dict],
        edges: list[dict],
    ) -> str:
        """Split long edges in a network into shorter segments.

        Subdivides edges that are longer than the specified split length,
        inserting intermediate nodes. Useful for creating finer-grained
        network models.

        Args:
            split_length_meters: Maximum edge length in meters.
            nodes: List of node dicts with {id, x, y}.
            edges: List of edge dicts with {source, target}.

        Returns:
            JSON summary of the modified network.
        """
        try:
            import networkx as nx
            from shift.utils.split_network_edges import split_network_edges
            from gdm.quantities import Distance

            graph = nx.Graph()
            for n in nodes:
                graph.add_node(n["id"], x=n["x"], y=n["y"])
            for e in edges:
                graph.add_edge(e["source"], e["target"])

            result_graph = split_network_edges(graph, Distance(split_length_meters, "m"))
            summary = serialize_nx_graph_summary(result_graph)
            summary["success"] = True
            summary["split_length_meters"] = split_length_meters

            return json.dumps(summary)

        except Exception as exc:
            return json.dumps({"success": False, "error": str(exc)})
