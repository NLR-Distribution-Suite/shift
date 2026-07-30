"""Geographic layout strategies for embedding an abstract graph in a region.

A :class:`LayoutStrategy` turns a geometry-free topology (e.g. a PG-DiGress
sample) into geographic node positions confined to a user-drawn polygon, with
the source node pinned at a chosen substation location. The interface is kept
deliberately small so alternative layouts (relaxation, circular, geographic
anchoring, ...) can be added and selected by name via :func:`get_layout_strategy`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import networkx as nx
from shapely.geometry import Point, Polygon
from shapely.ops import nearest_points

from shift.data_model import GeoLocation


class LayoutStrategy(ABC):
    """Compute geographic positions for an abstract graph within a region."""

    @abstractmethod
    def compute(
        self,
        graph: nx.Graph,
        *,
        source_node: int,
        source_location: GeoLocation,
        polygon: list[GeoLocation],
    ) -> dict[int, list[float]]:
        """Return ``{node: [longitude, latitude]}`` for every node in ``graph``.

        Implementations must position ``source_node`` at ``source_location`` and
        keep every other node inside ``polygon``.
        """


class SpringLayoutStrategy(LayoutStrategy):
    """Force-directed (spring) layout scaled into and confined to the polygon.

    The abstract graph's edge structure is preserved exactly; only node
    coordinates are assigned. Nodes are fit into the polygon's bounding box
    (inset by ``margin``) and any node landing outside the polygon outline is
    pulled to the nearest interior point, so the whole feeder stays inside the
    region of interest.
    """

    def __init__(self, *, seed: int | None = None, margin: float = 0.08, iterations: int = 200):
        self.seed = seed
        self.margin = max(0.0, min(0.45, float(margin)))
        self.iterations = max(1, int(iterations))

    def compute(
        self,
        graph: nx.Graph,
        *,
        source_node: int,
        source_location: GeoLocation,
        polygon: list[GeoLocation],
    ) -> dict[int, list[float]]:
        poly = Polygon([(p.longitude, p.latitude) for p in polygon])
        if poly.is_empty or not poly.is_valid:
            poly = poly.buffer(0)  # repair self-intersections from freehand draws
        if poly.is_empty:
            raise ValueError("Layout polygon is empty or invalid.")

        minx, miny, maxx, maxy = poly.bounds
        mx = (maxx - minx) * self.margin
        my = (maxy - miny) * self.margin
        bx0, by0, bx1, by1 = minx + mx, miny + my, maxx - mx, maxy - my

        raw = nx.spring_layout(graph, seed=self.seed, iterations=self.iterations)
        xs = [p[0] for p in raw.values()] or [0.0]
        ys = [p[1] for p in raw.values()] or [0.0]
        x0, x1 = min(xs), max(xs)
        y0, y1 = min(ys), max(ys)

        def _norm(v: float, lo: float, hi: float) -> float:
            return 0.5 if hi <= lo else (v - lo) / (hi - lo)

        positions: dict[int, list[float]] = {}
        for node, (x, y) in raw.items():
            lon = bx0 + _norm(x, x0, x1) * (bx1 - bx0)
            lat = by0 + _norm(y, y0, y1) * (by1 - by0)
            if not poly.contains(Point(lon, lat)):
                lon, lat = self._pull_inside(poly, lon, lat)
            positions[node] = [lon, lat]

        # Pin the source at the substation (validated to be inside the polygon).
        positions[source_node] = [source_location.longitude, source_location.latitude]
        return positions

    @staticmethod
    def _pull_inside(poly: Polygon, lon: float, lat: float) -> tuple[float, float]:
        """Move an outside point to the nearest interior point of the polygon."""
        inside = nearest_points(poly, Point(lon, lat))[0]
        centroid = poly.centroid
        # Nudge slightly toward the centroid so the node is not exactly on the edge.
        return (
            inside.x + (centroid.x - inside.x) * 0.02,
            inside.y + (centroid.y - inside.y) * 0.02,
        )


# Registry so callers select a layout by name and new strategies plug in here.
_LAYOUT_REGISTRY: dict[str, type[LayoutStrategy]] = {
    "spring": SpringLayoutStrategy,
}


def get_layout_strategy(name: str, **kwargs) -> LayoutStrategy:
    """Instantiate a registered :class:`LayoutStrategy` by name."""
    cls = _LAYOUT_REGISTRY.get((name or "spring").lower())
    if cls is None:
        valid = ", ".join(sorted(_LAYOUT_REGISTRY))
        raise ValueError(f"Unknown layout '{name}'. Valid layouts: {valid}.")
    return cls(**kwargs)
