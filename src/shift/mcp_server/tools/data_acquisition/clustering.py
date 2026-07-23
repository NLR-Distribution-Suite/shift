"""Parcel clustering tools."""

from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

from shift.mcp_server.serializers import serialize_group


def register(mcp: FastMCP) -> None:
    """Register clustering tools on the FastMCP instance."""

    @mcp.tool()
    def cluster_parcels(
        points: list[dict[str, float]] | None = None,
        num_clusters: int = 5,
        strategy: str = "kmeans",
        parcels: list[dict] | None = None,
        target_kva_per_transformer: float = 75.0,
        dedicated_transformer_area_m2: float = 2000.0,
        dedicated_transformer_load_kva: float = 150.0,
        max_secondary_length_m: float = 120.0,
        min_clusters: int = 1,
        max_clusters: int | None = None,
    ) -> str:
        """Cluster parcels into transformer service groups.

        Two strategies are supported:

        - ``"kmeans"`` (default): geographic K-means over ``points``. Produces
          exactly ``num_clusters`` groups balancing proximity only.
        - ``"capacity_distance"``: sizes transformer groups from each parcel's
          estimated electrical load and a maximum secondary-line reach. The
          number of transformers is derived automatically (not supplied); large
          parcels get dedicated transformers and every load stays within
          ``max_secondary_length_m`` of its transformer. Requires ``parcels``
          (with ``geometry`` and ``building_type``), not just ``points``.

        Each returned cluster has a center coordinate (a candidate transformer
        site) and the member points served by that transformer.

        Args:
            points: List of {longitude, latitude} dicts (used by ``kmeans``).
            num_clusters: Number of clusters for ``kmeans`` (default 5).
            strategy: ``"kmeans"`` or ``"capacity_distance"``.
            parcels: List of parcel dicts with ``geometry`` (polygon vertices or
                     a point) and ``building_type`` (used by ``capacity_distance``).
            target_kva_per_transformer: Target load per shared transformer, kVA.
            dedicated_transformer_area_m2: Footprint area at/above which a parcel
                     gets its own transformer.
            dedicated_transformer_load_kva: Estimated load at/above which a parcel
                     gets its own transformer.
            max_secondary_length_m: Max distance from a parcel to its transformer.
            min_clusters: Lower bound on the number of shared transformers.
            max_clusters: Optional upper bound on the number of shared transformers.

        Returns:
            JSON array of cluster objects with center coordinates and member
            points for each cluster.
        """
        try:
            from shift.utils.get_cluster import (
                get_kmeans_clusters,
                get_capacity_distance_clusters,
            )
            from shift.data_model import GeoLocation

            if strategy == "capacity_distance":
                if not parcels:
                    return json.dumps(
                        {
                            "success": False,
                            "error": "capacity_distance strategy requires 'parcels' "
                            "(with geometry and building_type).",
                        }
                    )
                clusters = get_capacity_distance_clusters(
                    parcels,
                    target_kva_per_transformer=target_kva_per_transformer,
                    dedicated_transformer_area_m2=dedicated_transformer_area_m2,
                    dedicated_transformer_load_kva=dedicated_transformer_load_kva,
                    max_secondary_length_m=max_secondary_length_m,
                    min_clusters=min_clusters,
                    max_clusters=max_clusters,
                )
                result = [serialize_group(c) for c in clusters]
                return json.dumps(
                    {
                        "success": True,
                        "clusters": result,
                        "num_clusters": len(result),
                        "strategy": strategy,
                    }
                )

            if not points:
                return json.dumps(
                    {
                        "success": False,
                        "error": "kmeans strategy requires 'points'.",
                    }
                )
            if len(points) < num_clusters:
                return json.dumps(
                    {
                        "success": False,
                        "error": f"num_clusters ({num_clusters}) must be <= number of points ({len(points)}).",
                    }
                )

            geo_points = [GeoLocation(p["longitude"], p["latitude"]) for p in points]
            clusters = get_kmeans_clusters(num_clusters, geo_points)
            result = [serialize_group(c) for c in clusters]

            return json.dumps(
                {
                    "success": True,
                    "clusters": result,
                    "num_clusters": len(result),
                    "strategy": strategy,
                }
            )

        except Exception as exc:
            return json.dumps({"success": False, "error": str(exc)})
