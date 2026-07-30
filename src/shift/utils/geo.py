"""Geodesic utility functions for area and distance calculations."""

from __future__ import annotations

from pyproj import Geod

from shift.data_model import GeoLocation

_GEOD = Geod(ellps="WGS84")


def region_area_km2_from_polygon(points: list[GeoLocation] | None) -> float:
    """Compute the geodesic area of a polygon in square kilometres.

    Parameters
    ----------
    points : list[GeoLocation] | None
        Vertices of the polygon (longitude, latitude). Must have at least 3
        points to compute an area.

    Returns
    -------
    float
        Area in km². Returns 0.0 if fewer than 3 points are provided.
    """
    if not points or len(points) < 3:
        return 0.0

    lons = [p.longitude for p in points]
    lats = [p.latitude for p in points]
    if lons[0] != lons[-1] or lats[0] != lats[-1]:
        lons = [*lons, lons[0]]
        lats = [*lats, lats[0]]

    area_m2, _ = _GEOD.polygon_area_perimeter(lons, lats)
    return abs(float(area_m2)) / 1_000_000.0


def region_area_km2_from_points(points: list[GeoLocation]) -> float:
    """Compute the bounding-box area of a set of points in square kilometres.

    Parameters
    ----------
    points : list[GeoLocation]
        Geographic points whose bounding box defines the area.

    Returns
    -------
    float
        Area of the bounding rectangle in km². Returns 0.0 if fewer than 2
        points are provided.
    """
    if not points or len(points) < 2:
        return 0.0

    min_lon = min(p.longitude for p in points)
    max_lon = max(p.longitude for p in points)
    min_lat = min(p.latitude for p in points)
    max_lat = max(p.latitude for p in points)

    lons = [min_lon, max_lon, max_lon, min_lon, min_lon]
    lats = [min_lat, min_lat, max_lat, max_lat, min_lat]
    area_m2, _ = _GEOD.polygon_area_perimeter(lons, lats)
    return abs(float(area_m2)) / 1_000_000.0
