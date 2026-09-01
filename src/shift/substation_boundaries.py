"""Substation boundary generation.

Splits a service-area polygon into non-overlapping cells, one per substation
found inside it. Each cell is the set of locations closer to its substation
than to any other (a single KMeans assignment pass with frozen centroids),
computed exactly via Voronoi half-plane clipping so the cells tile the input
polygon with no gaps and no overlaps.
"""

from __future__ import annotations

import math
import numpy as np
import geopandas as gpd
from loguru import logger
from shapely import Point, Polygon, box

from shift.exceptions import InvalidInputError
from shift.substation import get_substations

# ~1 cm in degrees; separates coincident substation points so their cells stay distinct.
_JITTER_DEG = 1e-7


def _representative_point(geometry) -> Point:
    """Return a single point representing a substation geometry."""
    if geometry.geom_type == "Point":
        return geometry
    # Guaranteed to lie inside the (possibly concave) polygon.
    return geometry.representative_point()


def _clamp_to_polygon(point: Point, polygon: Polygon) -> Point:
    """Return ``point`` if inside ``polygon``, else a point just inside the nearest boundary.

    Substation ways can straddle the service-area edge; clamping keeps every
    Voronoi center strictly inside the polygon so each cell stays non-empty.
    The inward nudge targets ``representative_point()`` (guaranteed interior)
    to avoid floating-point slivers on the boundary itself.
    """
    if polygon.covers(point):
        return point
    exterior = polygon.exterior
    on_boundary = exterior.interpolate(exterior.project(point))
    interior = polygon.representative_point()
    dx, dy = interior.x - on_boundary.x, interior.y - on_boundary.y
    dist = math.hypot(dx, dy)
    if dist == 0.0:
        return on_boundary
    step = min(_JITTER_DEG * 10.0 / dist, 0.5)
    return Point(on_boundary.x + dx * step, on_boundary.y + dy * step)


def _jitter_duplicates(points: list[Point]) -> list[Point]:
    """Deterministically offset coincident points so Voronoi cells stay distinct."""
    counts: dict[tuple[float, float], int] = {}
    out: list[Point] = []
    for point in points:
        key = (point.x, point.y)
        k = counts.get(key, 0)
        counts[key] = k + 1
        if k == 0:
            out.append(point)
        else:
            out.append(Point(point.x + k * _JITTER_DEG, point.y))
    return out


def _clip_halfplane(subject: np.ndarray, midpoint: np.ndarray, normal: np.ndarray) -> np.ndarray:
    """Clip convex polygon ``subject`` to the half-plane {x : dot(x - midpoint, normal) <= 0}.

    Sutherland-Hodgman clipping; returns an (n, 2) array of vertices.
    """
    s = subject
    f = (s - midpoint) @ normal
    out: list[np.ndarray] = []
    n = len(s)
    for i in range(n):
        j = (i - 1) % n
        fj, fi = f[j], f[i]
        if fi <= 0.0:
            if fj > 0.0:
                t = fj / (fj - fi)
                out.append(s[j] + t * (s[i] - s[j]))
            out.append(s[i])
        elif fj <= 0.0:
            t = fj / (fj - fi)
            out.append(s[j] + t * (s[i] - s[j]))
    return np.asarray(out, dtype=float).reshape(-1, 2)


def _voronoi_cell(points: list[Point], index: int, start_box: Polygon) -> Polygon | None:
    """Voronoi cell of ``points[index]``, clipped to ``start_box``.

    The cell is the intersection of all half-planes closer to ``points[index]``
    than to any other point, computed by sequential convex clipping starting
    from ``start_box`` (which must contain the desired region).
    """
    target = np.asarray([points[index].x, points[index].y], dtype=float)
    # Drop the ring's closing vertex; clipping walks edges with wraparound.
    subject = np.asarray(start_box.exterior.coords, dtype=float)[:-1]

    for j, point in enumerate(points):
        if j == index:
            continue
        other = np.asarray([point.x, point.y], dtype=float)
        midpoint = (target + other) / 2.0
        normal = other - target
        subject = _clip_halfplane(subject, midpoint, normal)
        if len(subject) < 3:
            return None

    cell = Polygon(subject)
    if not cell.is_valid or cell.is_empty:
        return None
    return cell


def _merge_close_substations(
    substations: gpd.GeoDataFrame,
    repr_points: list[Point],
    merge_distance_deg: float,
) -> tuple[gpd.GeoDataFrame, list[Point]]:
    """Merge substations closer than ``merge_distance_deg`` into their most informative member.

    OSM often maps the same physical substation as several near-coincident ways.
    Each cluster keeps the substation with the largest geometry (most detailed
    footprint); its representative point is used for the Voronoi split.

    Returns the filtered substations GeoDataFrame and matching representative
    points (``jitter_duplicates`` is not applied to the merged result).
    """
    if merge_distance_deg <= 0.0:
        return substations, repr_points

    keep_indices: list[int] = []
    cluster_centers: list[Point] = []
    for index, (point, geometry) in enumerate(zip(repr_points, substations.geometry)):
        merged = False
        for center in cluster_centers:
            if point.distance(center) <= merge_distance_deg:
                merged = True
                break
        if not merged:
            keep_indices.append(index)
            cluster_centers.append(point)

    # Keep, per cluster, the member with the largest geometry area.
    final_indices: list[int] = []
    for keep in keep_indices:
        members = [
            i
            for i, point in enumerate(repr_points)
            if point.distance(repr_points[keep]) <= merge_distance_deg
        ]
        best = max(members, key=lambda i: float(substations.geometry.iloc[i].area))
        final_indices.append(best)

    final_indices = sorted(set(final_indices))
    merged_gdf = substations.iloc[final_indices].reset_index(drop=True)
    merged_points = [repr_points[i] for i in final_indices]
    logger.info(
        "Merged {} substation(s) to {} within {:.4f} deg.",
        len(substations),
        len(final_indices),
        merge_distance_deg,
    )
    return merged_gdf, merged_points


def substation_boundaries(
    polygon: Polygon, *, merge_distance_deg: float = 0.0
) -> gpd.GeoDataFrame:
    """Split ``polygon`` into non-overlapping cells, one per substation inside it.

    Substations are fetched from OpenStreetMap via :func:`shift.substation.get_substations`.
    Each returned row carries the substation's OSM tags plus its representative
    point (``substation_point``, clamped onto ``polygon`` if a substation way
    straddles the edge); the active geometry column is the boundary cell.
    Cells tile ``polygon`` exactly: no gaps, no overlaps (shared edges only).

    Parameters
    ----------
    polygon : shapely Polygon
        Service-area polygon in WGS84 (EPSG:4326). Must be a valid, simple
        Polygon (not MultiPolygon).
    merge_distance_deg : float
        When > 0, substations closer than this distance (degrees, WGS84) are
        merged into the member with the largest footprint. Use this to dedupe
        near-coincident OSM substation ways. Defaults to 0 (no merging).

    Returns
    -------
    GeoDataFrame
        One row per substation found inside ``polygon``. For concave inputs a
        cell may be a MultiPolygon. Empty when no substations are found.
    """
    if not isinstance(polygon, Polygon):
        raise InvalidInputError("polygon must be a shapely Polygon (WGS84).")
    if not polygon.is_valid:
        raise InvalidInputError("polygon is not valid; fix its geometry first.")

    substations = get_substations(polygon)
    n = len(substations)
    logger.info(f"Found {n} substation(s) in polygon; generating boundaries.")

    if n == 0:
        return gpd.GeoDataFrame(
            {"osm_type": [], "osm_id": [], "substation_point": [], "geometry": []},
            crs="EPSG:4326",
        )

    repr_points = [
        _clamp_to_polygon(_representative_point(g), polygon) for g in substations.geometry
    ]
    substations, repr_points = _merge_close_substations(
        substations, repr_points, merge_distance_deg
    )
    n = len(substations)
    points = _jitter_duplicates(repr_points)

    if n == 1:
        cells: list[Polygon | None] = [polygon]
    else:
        # The input polygon's bounding box always contains every cell ∩ polygon.
        start_box = box(*polygon.bounds)
        cells = [_voronoi_cell(points, i, start_box) for i in range(n)]

    for i, cell in enumerate(cells):
        if cell is None:
            osm_id = substations["osm_id"].iloc[i] if "osm_id" in substations else i
            raise InvalidInputError(
                f"Could not compute a boundary for substation {i} (osm_id={osm_id})."
            )

    clipped = [cell.intersection(polygon) for cell in cells]

    gdf = substations.drop(columns=["geometry"]).copy()
    gdf["substation_point"] = repr_points
    gdf["geometry"] = clipped
    result = gpd.GeoDataFrame(gdf, crs="EPSG:4326")

    total_area = sum(float(c.area) for c in clipped)
    if abs(total_area - float(polygon.area)) > 1e-9 * max(1.0, float(polygon.area)):
        logger.warning(
            f"Boundary cells cover {total_area:.6f} of polygon area {float(polygon.area):.6f}."
        )

    return result
