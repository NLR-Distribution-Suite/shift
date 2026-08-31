"""Tests for feeder_boundaries."""

import geopandas as gpd
import pytest
from shapely import Point, Polygon

from shift.data_model import GeoLocation

from shift.exceptions import InvalidInputError
from shift.feeder_boundaries import (
    estimate_feeder_count_by_area,
    feeder_counts_for_cells,
    split_substation_into_feeders,
    split_substations_into_feeders,
)
from shift.utils.geo import region_area_km2_from_polygon


def _square(side_deg: float, lon: float = -122.3, lat: float = 37.8) -> Polygon:
    """A square service-area polygon of the given side length in degrees."""
    return Polygon(
        [
            (lon, lat),
            (lon + side_deg, lat),
            (lon + side_deg, lat + side_deg),
            (lon, lat + side_deg),
        ]
    )


def _expected_count(area_km2: float, min_area: float, max_area: float, mn: int, mx: int) -> int:
    """Independent reference implementation of the area->feeder mapping."""
    if area_km2 <= min_area:
        return mn
    if area_km2 >= max_area:
        return mx
    frac = (area_km2 - min_area) / (max_area - min_area)
    return int(round(mn + frac * (mx - mn)))


@pytest.mark.parametrize(
    "side_deg,expected",
    [
        (0.005, 3),  # ~0.24 km^2 -> below min area -> min feeders
        (0.02, None),  # ~3.9 km^2
        (0.03, None),  # ~8.8 km^2
        (0.04, None),  # ~15.6 km^2
        (0.06, 8),  # ~35 km^2 -> above max area -> max feeders
    ],
)
def test_estimate_scales_linearly_with_area(side_deg, expected):
    """Feeder count rises linearly from min to max as area grows."""
    polygon = _square(side_deg)
    area = region_area_km2_from_polygon(
        [GeoLocation(longitude=x, latitude=y) for x, y in polygon.exterior.coords]
    )
    got = estimate_feeder_count_by_area(
        polygon, min_feeders=3, max_feeders=8, min_area_km2=1.0, max_area_km2=20.0
    )
    if expected is not None:
        assert got == expected
    else:
        assert got == _expected_count(area, 1.0, 20.0, 3, 8)


def test_estimate_is_monotonic_across_sizes():
    """Larger polygons never yield fewer feeders than smaller ones."""
    sides = [0.006, 0.012, 0.018, 0.024, 0.030, 0.036, 0.045]
    counts = [
        estimate_feeder_count_by_area(_square(s), min_feeders=3, max_feeders=8) for s in sides
    ]
    assert counts == sorted(counts)
    assert counts[0] == 3
    assert counts[-1] >= counts[0]


def test_estimate_rejects_bad_bounds():
    """Invalid min/max feeder bounds are rejected."""
    with pytest.raises(InvalidInputError):
        estimate_feeder_count_by_area(_square(0.02), min_feeders=8, max_feeders=3)
    with pytest.raises(InvalidInputError):
        estimate_feeder_count_by_area(_square(0.02), min_feeders=0)


def test_split_returns_one_cell_per_feeder():
    """Splitting yields exactly ``n`` non-overlapping cells that tile the polygon."""
    polygon = _square(0.05)
    result = split_substation_into_feeders(polygon, feeder_count=5, seed=1)

    cells = list(result.geometry)
    assert len(cells) == 5
    assert list(result["feeder_index"]) == [1, 2, 3, 4, 5]

    # Each cell contains its own feeder center and no other.
    centers = list(result["center"])
    for i, (cell, center) in enumerate(zip(cells, centers)):
        assert cell.covers(center)
        for j, other in enumerate(centers):
            if i != j:
                assert not cell.covers(other)

    # No overlaps between any pair of cells (shared edges are measure zero).
    for a in range(len(cells)):
        for b in range(a + 1, len(cells)):
            overlap = cells[a].intersection(cells[b]).area
            assert overlap <= 1e-9 * polygon.area

    # No gaps: the union covers the whole polygon (within geodesic rounding).
    total = float(result["area_km2"].sum())
    polygon_area = region_area_km2_from_polygon(
        [GeoLocation(longitude=x, latitude=y) for x, y in polygon.exterior.coords]
    )
    assert total == pytest.approx(polygon_area, rel=1e-4)
    gap = polygon.difference(gpd.GeoSeries(cells).union_all())
    assert gap.is_empty or gap.area / polygon.area < 1e-6


def test_split_auto_counts_within_range():
    """Area-based auto count always lands within [min_feeders, max_feeders]."""
    for side in (0.006, 0.02, 0.04, 0.06):
        result = split_substation_into_feeders(_square(side), seed=0)
        n = len(result)
        assert 3 <= n <= 8


def test_split_rejects_bad_bounds():
    """Invalid bounds and out-of-range explicit counts are rejected."""
    with pytest.raises(InvalidInputError):
        split_substation_into_feeders(_square(0.05), min_feeders=8, max_feeders=3)
    with pytest.raises(InvalidInputError):
        split_substation_into_feeders(_square(0.05), feeder_count=9)


def test_split_rejects_non_polygon():
    """Non-Polygon input is rejected."""
    with pytest.raises(InvalidInputError):
        split_substation_into_feeders([(0, 0), (1, 0), (1, 1)])


def test_feeder_counts_for_cells_relative_scaling():
    """Smallest area -> min, largest -> max, others scale linearly."""
    counts = feeder_counts_for_cells([4.0, 2.0, 1.0], min_feeders=3, max_feeders=8)
    # Order preserved: [4.0->8, 2.0->mid, 1.0->3]
    assert counts == [8, 5, 3]
    # Monotonic with area.
    areas = [1.0, 2.0, 3.0, 4.0, 5.0]
    ordered = feeder_counts_for_cells(areas, min_feeders=3, max_feeders=8)
    assert ordered == sorted(ordered)


def test_feeder_counts_for_cells_equal_areas():
    """Equal (or single) areas all map to the minimum count."""
    assert feeder_counts_for_cells([2.0, 2.0, 2.0]) == [3, 3, 3]
    assert feeder_counts_for_cells([5.0]) == [3]


def test_feeder_counts_for_cells_invalid():
    """Invalid bounds are rejected."""
    with pytest.raises(InvalidInputError):
        feeder_counts_for_cells([1.0], min_feeders=8, max_feeders=3)
    with pytest.raises(InvalidInputError):
        feeder_counts_for_cells([1.0], min_feeders=0)


def _mock_substations(points):
    """Patch get_substations to return the given substation points."""
    from unittest.mock import patch

    substations = gpd.GeoDataFrame(
        {"osm_id": list(range(len(points))), "geometry": [Point(p) for p in points]},
        crs="EPSG:4326",
    )
    return patch("shift.substation_boundaries.get_substations", return_value=substations)


def test_split_substations_pipeline_counts_scale_with_cell_size():
    """Largest substation cell gets more feeders than the smallest."""
    # Wide rectangle so off-center substations yield unequal cells.
    polygon = Polygon([(-122.30, 37.82), (-122.24, 37.82), (-122.24, 37.84), (-122.30, 37.84)])
    points = [(-122.295, 37.825), (-122.275, 37.83), (-122.255, 37.835)]

    with _mock_substations(points):
        result = split_substations_into_feeders(polygon, seed=0)

    # One feeder group per substation; indices are 1..n.
    assert sorted(result["substation_index"].unique()) == [1, 2, 3]
    counts_per_sub = result.groupby("substation_index").size().to_dict()

    # Feeder count is non-decreasing with each substation cell's area.
    areas_per_sub = result.groupby("substation_index")["area_km2"].sum().sort_values()
    smallest_sub = areas_per_sub.idxmin()
    largest_sub = areas_per_sub.idxmax()
    assert counts_per_sub[largest_sub] >= counts_per_sub[smallest_sub]
    assert all(3 <= c <= 8 for c in counts_per_sub.values())

    # Every feeder region is disjoint and together they cover the whole polygon.
    cells = list(result.geometry)
    for a in range(len(cells)):
        for b in range(a + 1, len(cells)):
            assert cells[a].intersection(cells[b]).area <= 1e-9 * polygon.area
    total = float(result["area_km2"].sum())
    polygon_area_km2 = region_area_km2_from_polygon(
        [GeoLocation(longitude=x, latitude=y) for x, y in polygon.exterior.coords]
    )
    assert total == pytest.approx(polygon_area_km2, rel=1e-4)


def test_split_substations_empty():
    """No substations -> empty result with the expected columns."""
    with _mock_substations([]):
        result = split_substations_into_feeders(_square(0.05))
    assert len(result) == 0
    assert list(result.columns) == [
        "substation_index",
        "substation_point",
        "feeder_index",
        "center",
        "area_km2",
        "geometry",
    ]
