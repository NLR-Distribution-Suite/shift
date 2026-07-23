from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class RoutingStrategyName(str, Enum):
    STEINER = "SteinerTreeStrategy"
    WEIGHTED_STEINER = "WeightedSteinerTreeStrategy"
    SHORTEST_PATH_TREE = "ShortestPathTreeStrategy"
    MIN_SPANNING_TREE = "MinimumSpanningTreeStrategy"
    FULL_ROAD = "FullRoadGraphStrategy"


class SecondaryStrategyName(str, Enum):
    AUTO_DENSITY = "AutoDensitySecondaryStrategy"
    MESH_STEINER = "MeshSteinerStrategy"
    RADIAL = "RadialStrategy"
    DELAUNAY = "DelaunayStrategy"
    OPENSTREET = "OpenStreetSecondaryStrategy"
    HUB_LINE = "HubLineStrategy"
    TRUNK_BRANCH = "TrunkBranchStrategy"


class NetworkTypeName(str, Enum):
    BALANCED_DEFAULT = "balanced_default"
    ROAD_OPTIMIZED = "road_optimized"
    FULL_ROAD_EXPLORATION = "full_road_exploration"


class ClusterStrategyName(str, Enum):
    KMEANS_COUNT = "kmeans_count"
    AREA_AWARE = "area_aware"
    CAPACITY_DISTANCE = "capacity_distance"


class ClusterBalanceMode(str, Enum):
    BALANCED = "balanced"
    UNBALANCED = "unbalanced"


class GeoPoint(BaseModel):
    longitude: float = Field(ge=-180, le=180)
    latitude: float = Field(ge=-90, le=90)


class ParcelInput(BaseModel):
    name: str | None = None
    building_type: str | None = None
    geometry: list[GeoPoint] | GeoPoint


class FetchParcelsRequest(BaseModel):
    location: str | None = None
    distance_meters: float = Field(default=500.0, gt=0, le=5000.0)
    polygon: list[GeoPoint] | None = None


class ClusterRequest(BaseModel):
    points: list[GeoPoint] = Field(default_factory=list)
    parcels: list[ParcelInput] = Field(default_factory=list)
    strategy: ClusterStrategyName = ClusterStrategyName.KMEANS_COUNT
    balance_mode: ClusterBalanceMode = ClusterBalanceMode.BALANCED
    num_clusters: int = Field(default=5, gt=0)
    target_area_per_transformer_m2: float = Field(default=5000.0, gt=0)
    dedicated_transformer_area_m2: float = Field(default=2000.0, gt=0)
    target_kva_per_transformer: float = Field(default=75.0, gt=0)
    dedicated_transformer_load_kva: float = Field(default=150.0, gt=0)
    max_secondary_length_m: float = Field(default=120.0, gt=0)
    min_clusters: int = Field(default=1, gt=0)
    max_clusters: int | None = Field(default=None, gt=0)


class GroupInput(BaseModel):
    center: GeoPoint
    points: list[GeoPoint]


class GraphBuildRequest(BaseModel):
    groups: list[GroupInput]
    source_location: GeoPoint
    polygon: list[GeoPoint] | None = None
    network_type: NetworkTypeName = NetworkTypeName.BALANCED_DEFAULT
    routing_strategy: RoutingStrategyName | None = None
    secondary_strategy: SecondaryStrategyName | None = None
    auto_secondary_density_threshold_per_km2: float = Field(default=300.0, gt=0)
    buffer_meters: float = Field(default=20.0, gt=0, le=5000)
    secondary_buffer_meters: float = Field(default=50.0, gt=0, le=5000)
    secondary_mesh_spacing_meters: float = Field(default=50.0, gt=0, le=1000)
    offline: bool = Field(default=False, description="Skip road network; use geometric routing.")
    snap_to_roads: bool = Field(
        default=True, description="Snap transformer centers to nearest road node."
    )
    snap_threshold_m: float = Field(
        default=50.0, gt=0, description="Max distance to snap to road (meters)."
    )
    crossing_penalty: float = Field(
        default=1.0,
        ge=1.0,
        description="Penalty for edge crossings in weighted routing (1.0=none, 2-5=moderate).",
    )


class StrategyCompareRequest(BaseModel):
    builds: list[GraphBuildRequest]


class TransformerPhaseConfig(BaseModel):
    tr_name: str
    tr_type: str
    tr_capacity_kva: float = Field(gt=0)


class ConfigurePhaseMapperRequest(BaseModel):
    graph_id: str
    method: str = "agglomerative"
    transformer_configs: list[TransformerPhaseConfig]


class TransformerVoltageConfig(BaseModel):
    name: str
    voltages_kv: list[float] = Field(min_length=2)


class ConfigureVoltageMapperRequest(BaseModel):
    graph_id: str
    transformer_voltages: list[TransformerVoltageConfig]


class ConfigureEquipmentMapperRequest(BaseModel):
    graph_id: str
    catalog_path: str


class BuildSystemRequest(BaseModel):
    graph_id: str
    system_name: str


class ExportSystemRequest(BaseModel):
    system_name: str
    output_path: str | None = None


class MultiFeederBuildRequest(BaseModel):
    parcels: list[ParcelInput]
    polygon: list[GeoPoint] | None = None
    network_type: NetworkTypeName = NetworkTypeName.BALANCED_DEFAULT
    routing_strategy: RoutingStrategyName | None = None
    secondary_strategy: SecondaryStrategyName | None = None
    auto_secondary_density_threshold_per_km2: float = Field(default=300.0, gt=0)
    buffer_meters: float = Field(default=20.0, gt=0, le=5000)
    secondary_buffer_meters: float = Field(default=50.0, gt=0, le=5000)
    secondary_mesh_spacing_meters: float = Field(default=50.0, gt=0, le=1000)
    target_parcels_per_feeder: int = Field(default=80, gt=0)
    parcels_per_transformer: int = Field(default=10, gt=0)
    high_density_threshold_per_km2: float = Field(default=300.0, gt=0)
    large_region_threshold_km2: float = Field(default=1.5, gt=0)
    min_feeders: int = Field(default=1, gt=0)
    max_feeders: int = Field(default=8, gt=0)


class BuildSystemFullRequest(BaseModel):
    graph_id: str
    system_name: str = "my_feeder"
    transformer_type: str = "THREE_PHASE"
    transformer_capacity_kva: float = Field(default=500.0, gt=0)
    primary_voltage_kv: float = Field(default=12.47, gt=0)
    secondary_voltage_kv: float = Field(default=0.48, gt=0)
    phase_method: str = "greedy"
    catalog_path: str | None = None


class QuickBuildRequest(BaseModel):
    """One-shot: polygon + source → GDM system (no manual steps)."""

    polygon: list[GeoPoint]
    source_location: GeoPoint
    system_name: str = "my_feeder"
    transformer_type: str = "THREE_PHASE"
    transformer_capacity_kva: float = Field(default=500.0, gt=0)
    primary_voltage_kv: float = Field(default=12.47, gt=0)
    secondary_voltage_kv: float = Field(default=0.48, gt=0)
    target_area_per_transformer_m2: float = Field(default=5000.0, gt=0)
    dedicated_transformer_area_m2: float = Field(default=2000.0, gt=0)
    secondary_strategy: str = "DelaunayStrategy"
    catalog_path: str | None = None
    offline: bool = True
