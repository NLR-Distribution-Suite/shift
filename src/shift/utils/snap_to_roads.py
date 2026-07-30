"""Snap geographic cluster centers to the nearest road segment."""

from __future__ import annotations

from shift.data_model import GeoLocation
from shift.graph.prsgb import _project_point_to_segment
from shift.utils.split_network_edges import get_distance_between_points


def snap_cluster_to_road(
    center: GeoLocation,
    parcel_points: list[GeoLocation],
    edge_segments: list[tuple[float, float, float, float]],
    threshold_m: float,
) -> dict | None:
    """Find the best road-edge projection for a cluster center.

    Returns a dict with new center, snap_distance_m, or None if no
    candidate falls within threshold.
    """
    candidates = []
    for ax, ay, bx, by in edge_segments:
        px, py, _ = _project_point_to_segment(center.longitude, center.latitude, ax, ay, bx, by)
        proj_geo = GeoLocation(px, py)
        dist = get_distance_between_points(center, proj_geo).to("m").magnitude
        if dist <= threshold_m:
            if parcel_points:
                total_parcel = sum(
                    get_distance_between_points(proj_geo, pp).to("m").magnitude
                    for pp in parcel_points
                )
            else:
                total_parcel = dist
            candidates.append((px, py, dist, total_parcel))

    if not candidates:
        return None

    best = min(candidates, key=lambda c: c[3])
    return {
        "longitude": float(best[0]),
        "latitude": float(best[1]),
        "snap_distance_m": round(best[2], 1),
    }
