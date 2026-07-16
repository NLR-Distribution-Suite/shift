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
    MESH_STEINER = "MeshSteinerStrategy"
    RADIAL = "RadialStrategy"
    DELAUNAY = "DelaunayStrategy"
    OPENSTREET = "OpenStreetSecondaryStrategy"
    HUB_LINE = "HubLineStrategy"


class NetworkTypeName(str, Enum):
    BALANCED_DEFAULT = "balanced_default"
    ROAD_OPTIMIZED = "road_optimized"
    FULL_ROAD_EXPLORATION = "full_road_exploration"


class GeoPoint(BaseModel):
    longitude: float = Field(ge=-180, le=180)
    latitude: float = Field(ge=-90, le=90)


class FetchParcelsRequest(BaseModel):
    location: str | None = None
    distance_meters: float = Field(default=500.0, gt=0, le=5000.0)
    polygon: list[GeoPoint] | None = None


class ClusterRequest(BaseModel):
    points: list[GeoPoint]
    num_clusters: int = Field(default=5, gt=0)


class GroupInput(BaseModel):
    center: GeoPoint
    points: list[GeoPoint]


class GraphBuildRequest(BaseModel):
    groups: list[GroupInput]
    source_location: GeoPoint
    network_type: NetworkTypeName = NetworkTypeName.BALANCED_DEFAULT
    routing_strategy: RoutingStrategyName | None = None
    secondary_strategy: SecondaryStrategyName | None = None
    buffer_meters: float = Field(default=20.0, gt=0, le=5000)
    secondary_buffer_meters: float = Field(default=50.0, gt=0, le=5000)
    secondary_mesh_spacing_meters: float = Field(default=50.0, gt=0, le=1000)


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
