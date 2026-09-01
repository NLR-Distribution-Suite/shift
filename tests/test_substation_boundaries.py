"""Tests for substation_boundaries."""

from unittest import mock

import geopandas as gpd
import pytest
from shapely import Point, Polygon

from shift.substation_boundaries import substation_boundaries


def _substations(points):
    """Build a fake substations GeoDataFrame like get_substations returns."""
    return gpd.GeoDataFrame(
        {"osm_id": list(range(len(points))), "geometry": points},
        crs="EPSG:4326",
    )


@pytest.fixture
def square():
    """A 1x1 service-area polygon in WGS84."""
    return Polygon([[0, 0], [0, 1], [1, 1], [1, 0]])


def _mock_substations(square, points):
    """Patch get_substations to return the given substation points."""
    return mock.patch(
        "shift.substation_boundaries.get_substations",
        return_value=_substations([Point(p) for p in points]),
    )


def test_no_stations_returns_empty(square):
    """No substations -> empty GeoDataFrame, no error."""
    with _mock_substations(square, []):
        result = substation_boundaries(square)
    assert len(result) == 0
    assert result.geometry.is_empty.all()


def test_single_station_whole_polygon(square):
    """One substation -> the entire polygon is its cell."""
    with _mock_substations(square, [(0.5, 0.5)]):
        result = substation_boundaries(square)
    assert len(result) == 1
    assert result.geometry.iloc[0].area == pytest.approx(square.area)


def test_cells_tile_without_overlap_or_gaps(square):
    """Multiple substations -> cells partition the polygon exactly."""
    points = [(0.2, 0.2), (0.8, 0.2), (0.5, 0.75), (0.3, 0.6)]
    with _mock_substations(square, points):
        result = substation_boundaries(square)

    cells = list(result.geometry)
    n = len(points)

    # One cell per substation.
    assert len(cells) == n

    # Each cell contains exactly its own substation point and no other.
    for i, cell in enumerate(cells):
        assert cell.covers(Point(*points[i]))
        for j, p in enumerate(points):
            if i == j:
                continue
            assert not cell.covers(Point(*p))

    # No overlaps: every pairwise intersection has ~zero area.
    for a in range(n):
        for b in range(a + 1, n):
            assert cells[a].intersection(cells[b]).area == pytest.approx(0.0, abs=1e-12)

    # No gaps: the union covers the whole polygon.
    total = sum(c.area for c in cells)
    assert total == pytest.approx(square.area, rel=1e-9)
    gap = square.difference(gpd.GeoSeries(cells).union_all())
    assert gap.is_empty or gap.area == pytest.approx(0.0, abs=1e-12)


def test_concave_polygon_tiles(square):
    """A concave input still tiles with no overlaps."""
    concave = Polygon([(0, 0), [4, 0], [4, 4], [2, 2], [0, 4]])
    points = [(1, 1), (3, 3)]
    with mock.patch(
        "shift.substation_boundaries.get_substations",
        return_value=_substations([Point(p) for p in points]),
    ):
        result = substation_boundaries(concave)

    cells = list(result.geometry)
    assert len(cells) == 2
    for a in range(len(cells)):
        for b in range(a + 1, len(cells)):
            assert cells[a].intersection(cells[b]).area == pytest.approx(0.0, abs=1e-12)
    union = gpd.GeoSeries(cells).union_all()
    assert union.area == pytest.approx(concave.area, rel=1e-9)


def test_straddle_edge_station_clamped_inside(square):
    """A substation whose point lies on the edge is clamped inside its cell."""
    with mock.patch(
        "shift.substation_boundaries.get_substations",
        return_value=_substations([Point(0.5, 0.0), Point(0.5, 1.0)]),
    ):
        result = substation_boundaries(square)
    cells = list(result.geometry)
    assert len(cells) == 2
    # Neither cell should be empty even though both centers sit on the boundary.
    assert all(not c.is_empty for c in cells)
