"""Feeder-area generation for a substation service polygon.

Two related pieces live here:

* :func:`estimate_feeder_count_by_area` maps a substation service polygon's
  area to a feeder count in ``[min_feeders, max_feeders]`` (smallest area ->
  min feeders, largest area -> max feeders, linear in between).
* :func:`split_substation_into_feeders` tiles the polygon into that many
  non-overlapping feeder cells. Each cell is a single Voronoi region of a
  sampled feeder center clipped to the polygon, so the cells exactly tile the
  input with no gaps and no overlaps (shared edges only).

The tiling reuses the convex half-plane clipping strategy from
:mod:`shift.substation_boundaries`; the helpers are reproduced here so this
module stays self-contained.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import geopandas as gpd
from loguru import logger
from shapely import Point, Polygon, box

from shift.data_model import GeoLocation
from shift.exceptions import InvalidInputError
from shift.utils.geo import region_area_km2_from_polygon

# Default service-area bounds (km^2) used to map area -> feeder count. Calibrate
# to the smallest and largest substation service areas in a utility's footprint.
_DEFAULT_MIN_AREA_KM2 = 1.0
_DEFAULT_MAX_AREA_KM2 = 20.0


def _cell_area_km2(geometry) -> float:
    """Sum the geodesic area (km^2) of every polygon in ``geometry``."""
    total = 0.0
    geoms = geometry.geoms if hasattr(geometry, "geoms") else [geometry]
    for poly in geoms:
        coords = list(poly.exterior.coords)
        locs = [GeoLocation(longitude=x, latitude=y) for x, y in coords]
        total += region_area_km2_from_polygon(locs)
    return float(total)


def estimate_feeder_count_by_area(
    polygon: Polygon,
    *,
    min_feeders: int = 3,
    max_feeders: int = 8,
    min_area_km2: float = _DEFAULT_MIN_AREA_KM2,
    max_area_km2: float = _DEFAULT_MAX_AREA_KM2,
) -> int:
    """Map a substation service polygon's area to a feeder count.

    Areas at or below ``min_area_km2`` yield ``min_feeders``; areas at or above
    ``max_area_km2`` yield ``max_feeders``; everything in between scales linearly
    and is rounded to the nearest integer, then clamped to ``[min_feeders,
    max_feeders]``.

    Parameters
    ----------
    polygon : shapely Polygon
        Substation service-area polygon in WGS84 (EPSG:4326).
    min_feeders : int
        Feeder count for the smallest service areas.
    max_feeders : int
        Feeder count for the largest service areas.
    min_area_km2 : float
        Area (km^2) that maps to ``min_feeders``.
    max_area_km2 : float
        Area (km^2) that maps to ``max_feeders``.

    Returns
    -------
    int
        Number of feeders in ``[min_feeders, max_feeders]``.
    """
    if min_feeders < 1:
        raise InvalidInputError("min_feeders must be >= 1.")
    if max_feeders < min_feeders:
        raise InvalidInputError("max_feeders must be >= min_feeders.")

    area_km2 = region_area_km2_from_polygon(
        [GeoLocation(longitude=x, latitude=y) for x, y in polygon.exterior.coords]
    )

    if area_km2 <= min_area_km2:
        return min_feeders
    if area_km2 >= max_area_km2:
        return max_feeders

    frac = (area_km2 - min_area_km2) / (max_area_km2 - min_area_km2)
    count = min_feeders + frac * (max_feeders - min_feeders)
    return int(round(count))


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
    than to any other point, computed by sequential convex clipping starting from
    ``start_box`` (which must contain the desired region).
    """
    target = np.asarray([points[index].x, points[index].y], dtype=float)
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


def _sample_feeder_centers(polygon: Polygon, n: int, rng: np.random.Generator) -> list[Point]:
    """Pick ``n`` well-separated points strictly inside ``polygon``.

    Uses stratified random sampling over the bounding box (one point per grid
    cell, keeping those inside the polygon) followed by greedy farthest-point
    sampling so the feeder centers spread across the service area.
    """
    minx, miny, maxx, maxy = polygon.bounds
    strata = 40
    candidates: list[Point] = []
    for i in range(strata):
        for j in range(strata):
            x = minx + (maxx - minx) * ((i + rng.random()) / strata)
            y = miny + (maxy - miny) * ((j + rng.random()) / strata)
            p = Point(x, y)
            if polygon.contains(p):
                candidates.append(p)

    if len(candidates) < n:
        raise InvalidInputError(
            f"Could not find {n} interior points for {n} feeders; the polygon is too "
            f"concave or thin (found {len(candidates)})."
        )

    coords = np.array([[p.x, p.y] for p in candidates], dtype=float)
    centers_idx = [int(rng.integers(len(coords)))]
    nearest = np.linalg.norm(coords - coords[centers_idx[0]], axis=1)
    while len(centers_idx) < n:
        nxt = int(np.argmax(nearest))
        centers_idx.append(nxt)
        nearest = np.minimum(nearest, np.linalg.norm(coords - coords[nxt], axis=1))

    return [Point(*coords[k]) for k in centers_idx]


def split_substation_into_feeders(
    polygon: Polygon,
    *,
    min_feeders: int = 3,
    max_feeders: int = 8,
    min_area_km2: float = _DEFAULT_MIN_AREA_KM2,
    max_area_km2: float = _DEFAULT_MAX_AREA_KM2,
    feeder_count: int | None = None,
    seed: int = 0,
) -> gpd.GeoDataFrame:
    """Tile a substation service polygon into non-overlapping feeder cells.

    The number of feeders is taken from ``feeder_count`` when given, otherwise it
    is estimated by :func:`estimate_feeder_count_by_area`. Each cell is the set of
    locations closer to its feeder center than to any other, clipped to the
    polygon, so the cells tile ``polygon`` exactly: no gaps, no overlaps (shared
    edges only).

    Parameters
    ----------
    polygon : shapely Polygon
        Substation service-area polygon in WGS84 (EPSG:4326). Must be a valid,
        simple Polygon (not MultiPolygon).
    min_feeders : int
        Minimum feeder count (also the floor for area-based estimation).
    max_feeders : int
        Maximum feeder count (also the ceiling for area-based estimation).
    min_area_km2 : float
        Area (km^2) mapping to ``min_feeders`` in area-based estimation.
    max_area_km2 : float
        Area (km^2) mapping to ``max_feeders`` in area-based estimation.
    feeder_count : int | None
        Explicit feeder count; overrides the area estimate. Must lie within
        ``[min_feeders, max_feeders]``.
    seed : int
        Seed for deterministic feeder-center placement.

    Returns
    -------
    GeoDataFrame
        One row per feeder with columns ``feeder_index``, ``center`` (a shapely
        Point), and ``area_km2``; the active geometry column is the feeder cell.
        Cells may be MultiPolygons for concave inputs.
    """
    if not isinstance(polygon, Polygon):
        raise InvalidInputError("polygon must be a shapely Polygon (WGS84).")
    if not polygon.is_valid:
        raise InvalidInputError("polygon is not valid; fix its geometry first.")
    if min_feeders < 1:
        raise InvalidInputError("min_feeders must be >= 1.")
    if max_feeders < min_feeders:
        raise InvalidInputError("max_feeders must be >= min_feeders.")

    if feeder_count is not None:
        n = feeder_count
        if not (min_feeders <= n <= max_feeders):
            raise InvalidInputError(
                f"feeder_count={n} is outside the allowed range [{min_feeders}, {max_feeders}]."
            )
    else:
        n = estimate_feeder_count_by_area(
            polygon,
            min_feeders=min_feeders,
            max_feeders=max_feeders,
            min_area_km2=min_area_km2,
            max_area_km2=max_area_km2,
        )

    logger.info(f"Splitting substation area into {n} feeder(s).")

    rng = np.random.default_rng(seed)
    centers = _sample_feeder_centers(polygon, n, rng)

    start_box = box(*polygon.bounds)
    cells = [_voronoi_cell(centers, i, start_box) for i in range(n)]
    for i, cell in enumerate(cells):
        if cell is None:
            raise InvalidInputError(f"Could not compute a feeder boundary for feeder {i}.")

    clipped = [cell.intersection(polygon) for cell in cells]

    area_km2 = [_cell_area_km2(c) for c in clipped]
    gdf = gpd.GeoDataFrame(
        {"feeder_index": list(range(1, n + 1)), "center": centers, "area_km2": area_km2},
        geometry=clipped,
        crs="EPSG:4326",
    )

    total_area = sum(area_km2)
    polygon_area = region_area_km2_from_polygon(
        [GeoLocation(longitude=x, latitude=y) for x, y in polygon.exterior.coords]
    )
    if abs(total_area - polygon_area) > 1e-9 * max(1.0, polygon_area):
        logger.warning(
            f"Feeder cells cover {total_area:.6f} km^2 of polygon area {polygon_area:.6f} km^2."
        )

    return gdf


def feeder_counts_for_cells(
    areas: list[float], min_feeders: int = 3, max_feeders: int = 8
) -> list[int]:
    """Map a set of cell areas to feeder counts relative to that set.

    The smallest area maps to ``min_feeders`` and the largest to ``max_feeders``;
    everything in between scales linearly and is rounded. If all areas are equal
    (or there is only one) every cell gets ``min_feeders``.

    Parameters
    ----------
    areas : list[float]
        Areas (km^2) of the cells being split, in order.
    min_feeders : int
        Feeder count for the smallest cell.
    max_feeders : int
        Feeder count for the largest cell.

    Returns
    -------
    list[int]
        One feeder count per input area, aligned by position.
    """
    if min_feeders < 1:
        raise InvalidInputError("min_feeders must be >= 1.")
    if max_feeders < min_feeders:
        raise InvalidInputError("max_feeders must be >= min_feeders.")

    lo, hi = min(areas), max(areas)
    counts: list[int] = []
    for area in areas:
        if hi <= lo:
            counts.append(min_feeders)
            continue
        frac = (area - lo) / (hi - lo)
        counts.append(int(round(min_feeders + frac * (max_feeders - min_feeders))))
    return counts


def split_substations_into_feeders(
    polygon: Polygon,
    *,
    min_feeders: int = 3,
    max_feeders: int = 8,
    seed: int = 0,
) -> gpd.GeoDataFrame:
    """Full pipeline: service-area polygon -> substation cells -> feeder regions.

    First splits ``polygon`` into one cell per substation via
    :func:`shift.substation_boundaries.substation_boundaries`. Then, relative to
    the smallest and largest of those cells, assigns each a feeder count in
    ``[min_feeders, max_feeders]`` (largest cell -> max, smallest -> min) using
    :func:`feeder_counts_for_cells`, and finally tiles each substation cell into
    its feeders.

    Parameters
    ----------
    polygon : shapely Polygon
        Service-area polygon in WGS84 (EPSG:4326). Must be a valid, simple
        Polygon (not MultiPolygon).
    min_feeders : int
        Feeder count for the smallest substation cell.
    max_feeders : int
        Feeder count for the largest substation cell.
    seed : int
        Base seed for deterministic feeder-center placement.

    Returns
    -------
    GeoDataFrame
        One row per feeder region across all substations, with columns
        ``substation_index`` (1..n), ``substation_point`` (the substation's
        representative Point), ``feeder_index`` (local 1..N within each
        substation), ``center`` (a shapely Point), and ``area_km2``; the active
        geometry column is the feeder cell. Empty when no substations are found.
    """
    if not isinstance(polygon, Polygon):
        raise InvalidInputError("polygon must be a shapely Polygon (WGS84).")
    if not polygon.is_valid:
        raise InvalidInputError("polygon is not valid; fix its geometry first.")

    from shift.substation_boundaries import substation_boundaries  # local import avoids cycle

    cells_gdf = substation_boundaries(polygon)
    n_subs = len(cells_gdf)
    if n_subs == 0:
        return gpd.GeoDataFrame(
            {
                "substation_index": [],
                "substation_point": [],
                "feeder_index": [],
                "center": [],
                "area_km2": [],
                "geometry": [],
            },
            crs="EPSG:4326",
        )

    areas = [_cell_area_km2(c) for c in cells_gdf.geometry]
    counts = feeder_counts_for_cells(areas, min_feeders=min_feeders, max_feeders=max_feeders)
    logger.info(f"Feeder counts for {n_subs} substation cell(s): {counts}")

    sub_points = list(cells_gdf["substation_point"])
    frames: list[gpd.GeoDataFrame] = []
    for sub_idx, (cell, n) in enumerate(zip(cells_gdf.geometry, counts)):
        feeder_gdf = split_substation_into_feeders(cell, feeder_count=n, seed=seed + sub_idx)
        feeder_gdf["substation_index"] = sub_idx + 1
        feeder_gdf["substation_point"] = sub_points[sub_idx]
        frames.append(feeder_gdf)

    result = pd.concat(frames, ignore_index=True)
    return result[
        ["substation_index", "substation_point", "feeder_index", "center", "area_km2", "geometry"]
    ]
