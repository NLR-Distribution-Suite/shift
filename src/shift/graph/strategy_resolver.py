"""Strategy resolution for primary routing and secondary network algorithms.

Provides factory functions to instantiate routing and secondary network
strategies by name, and logic for automatic density-based strategy selection.
"""

from __future__ import annotations

from infrasys.quantities import Distance

from shift.data_model import GeoLocation
from shift.graph.routing import (
    FullRoadGraphStrategy,
    MinimumSpanningTreeStrategy,
    RoutingStrategy,
    ShortestPathTreeStrategy,
    SteinerTreeStrategy,
    WeightedSteinerTreeStrategy,
)
from shift.graph.secondary import (
    DelaunayStrategy,
    HubLineStrategy,
    MeshSteinerStrategy,
    OpenStreetSecondaryStrategy,
    RadialStrategy,
    SecondaryNetworkStrategy,
    TrunkBranchStrategy,
)
from shift.utils.geo import region_area_km2_from_points, region_area_km2_from_polygon

ROUTING_STRATEGIES: dict[str, type[RoutingStrategy]] = {
    "SteinerTreeStrategy": SteinerTreeStrategy,
    "WeightedSteinerTreeStrategy": WeightedSteinerTreeStrategy,
    "ShortestPathTreeStrategy": ShortestPathTreeStrategy,
    "MinimumSpanningTreeStrategy": MinimumSpanningTreeStrategy,
    "FullRoadGraphStrategy": FullRoadGraphStrategy,
}

SECONDARY_STRATEGIES: dict[str, type[SecondaryNetworkStrategy]] = {
    "MeshSteinerStrategy": MeshSteinerStrategy,
    "RadialStrategy": RadialStrategy,
    "DelaunayStrategy": DelaunayStrategy,
    "OpenStreetSecondaryStrategy": OpenStreetSecondaryStrategy,
    "HubLineStrategy": HubLineStrategy,
    "TrunkBranchStrategy": TrunkBranchStrategy,
}

NETWORK_PRESETS: dict[str, tuple[str, str]] = {
    "balanced_default": ("SteinerTreeStrategy", "OpenStreetSecondaryStrategy"),
    "road_optimized": ("WeightedSteinerTreeStrategy", "OpenStreetSecondaryStrategy"),
    "full_road_exploration": ("FullRoadGraphStrategy", "OpenStreetSecondaryStrategy"),
}


def auto_select_secondary_strategy(
    *,
    candidate_points: list[GeoLocation],
    polygon_points: list[GeoLocation] | None = None,
    density_threshold_per_km2: float = 500.0,
) -> tuple[str, dict[str, float | str]]:
    """Select a secondary network strategy based on parcel density.

    For low-density areas, Delaunay triangulation is preferred. For denser
    areas, road-aware (OpenStreet) routing produces more realistic layouts.

    Parameters
    ----------
    candidate_points : list[GeoLocation]
        Load/parcel locations used to estimate density.
    polygon_points : list[GeoLocation] | None
        Boundary polygon for area computation. Falls back to bounding box
        of candidate_points if not provided.
    density_threshold_per_km2 : float
        Points per km² above which OpenStreet is chosen over Delaunay.

    Returns
    -------
    tuple[str, dict]
        (strategy_name, context_dict) where strategy_name is one of the
        SECONDARY_STRATEGIES keys and context_dict has area/density metadata.
    """
    if len(candidate_points) < 4:
        return "RadialStrategy", {
            "auto_secondary_area_km2": 0.0,
            "auto_secondary_density_per_km2": 0.0,
            "auto_secondary_reason": "too_few_points",
        }

    area_km2 = region_area_km2_from_polygon(polygon_points)
    if area_km2 <= 0:
        area_km2 = region_area_km2_from_points(candidate_points)

    density = len(candidate_points) / max(area_km2, 0.01)
    strategy_name = (
        "OpenStreetSecondaryStrategy"
        if density >= density_threshold_per_km2
        else "DelaunayStrategy"
    )
    return strategy_name, {
        "auto_secondary_area_km2": round(area_km2, 4),
        "auto_secondary_density_per_km2": round(density, 2),
        "auto_secondary_reason": "density_threshold",
    }


def get_routing_strategy(
    name: str,
    *,
    crossing_penalty: float = 1.0,
) -> RoutingStrategy:
    """Instantiate a routing strategy by name.

    Parameters
    ----------
    name : str
        One of the keys in ``ROUTING_STRATEGIES``.
    crossing_penalty : float
        Penalty factor for WeightedSteinerTreeStrategy.

    Returns
    -------
    RoutingStrategy

    Raises
    ------
    ValueError
        If name is not a recognized strategy.
    """
    if name not in ROUTING_STRATEGIES:
        raise ValueError(
            f"Unknown routing strategy '{name}'. Available: {list(ROUTING_STRATEGIES.keys())}"
        )
    cls = ROUTING_STRATEGIES[name]
    if cls is WeightedSteinerTreeStrategy:
        return cls(crossing_penalty=crossing_penalty)
    return cls()


def get_secondary_strategy(
    name: str,
    *,
    buffer_meters: float = 20.0,
    mesh_spacing_meters: float = 30.0,
) -> SecondaryNetworkStrategy:
    """Instantiate a secondary network strategy by name.

    Parameters
    ----------
    name : str
        One of the keys in ``SECONDARY_STRATEGIES``.
    buffer_meters : float
        Buffer distance for OpenStreet and TrunkBranch strategies.
    mesh_spacing_meters : float
        Grid spacing for MeshSteiner strategy.

    Returns
    -------
    SecondaryNetworkStrategy

    Raises
    ------
    ValueError
        If name is not a recognized strategy.
    """
    if name not in SECONDARY_STRATEGIES:
        raise ValueError(
            f"Unknown secondary strategy '{name}'. Available: {list(SECONDARY_STRATEGIES.keys())}"
        )
    cls = SECONDARY_STRATEGIES[name]
    if cls is MeshSteinerStrategy:
        return cls(spacing=Distance(mesh_spacing_meters, "m"))
    if cls in (OpenStreetSecondaryStrategy, TrunkBranchStrategy):
        return cls(buffer=Distance(buffer_meters, "m"))
    return cls()
