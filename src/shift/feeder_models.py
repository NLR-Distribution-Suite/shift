"""Build all feeder distribution-system models for a service area in parallel.

The pipeline stitches together the existing building blocks:

1. :func:`shift.substation_boundaries.substation_boundaries` splits the
   service-area polygon into one cell per substation.
2. :func:`shift.feeder_boundaries.split_substation_into_feeders` tiles each
   substation cell into feeder cells (area- or parcel-count-based).
3. Each feeder's ``DistributionGraph`` is built with :class:`PRSG`, using the
   substation point as the power source.
4. Equipment is right-sized against a :class:`gdm.distribution.CatalogSystem`
   loaded through gdmloader (see :func:`load_catalog`), selecting conductors
   and transformers by served load via :class:`DefaultLoadEquipmentMapper`.
5. Feeder models are built concurrently (``ThreadPoolExecutor``) and exported
   with ``DistributionSystem.to_json`` to
   ``<export_folder>/<substation_<osm_id>>/<feeder_<index>>.json``.

All pipeline settings are configurable through a pydantic model
(:class:`FeederModelConfig`) that can be loaded from a TOML file via
:func:`FeederModelConfig.from_toml`. The config surface mirrors the SHIFT UI
request models (routing/secondary strategies, clustering, feeder estimation,
transformer/voltage ratings, catalog, parcel sources, and optional gdm-flow
post-processing).
"""

from __future__ import annotations

import math
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

import geopandas as gpd
import requests
from infrasys.quantities import Distance
from loguru import logger
from pydantic import BaseModel, Field, model_validator
from shapely import Polygon

try:  # Python 3.11+
    import tomllib
except ImportError:  # pragma: no cover
    import tomli as tomllib  # type: ignore

from gdm.distribution import CatalogSystem, DistributionSystem
from gdm.distribution.components import DistributionTransformer
from gdm.quantities import ApparentPower, Voltage

from shift.data_model import (
    GeoLocation,
    GroupModel,
    ParcelModel,
    TransformerPhaseMapperModel,
    TransformerTypes,
    TransformerVoltageModel,
)
from shift.exceptions import InvalidInputError
from shift.feeder_boundaries import _cell_area_km2, split_substation_into_feeders
from shift.graph.prsgb import PRSG
from shift.graph.strategy_resolver import (
    NETWORK_PRESETS,
    auto_select_secondary_strategy,
    get_routing_strategy,
    get_secondary_strategy,
)
from shift.mapper.balanced_phase_mapper import BalancedPhaseMapper
from shift.mapper.catalog_utils import snap_voltage_mapper_to_catalog, source_voltage_kv
from shift.mapper.default_load_equipment_mapper import DefaultLoadEquipmentMapper
from shift.mapper.transformer_voltage_mapper import TransformerVoltageMapper
from shift.parcel import parcels_from_geodataframe, parcels_from_location, parcels_from_pbf
from shift.parcel_sources import GISParcelFieldMapper, OSMParcelFieldMapper, ParcelFieldMapper
from shift.substation_boundaries import substation_boundaries
from shift.substation import substation_voltage_kv
from shift.system_builder import DistributionSystemBuilder
from shift.utils.get_cluster import (
    centroid_and_area_m2,
    estimate_feeder_count,
    estimate_load_kva,
    get_area_aware_clusters,
    get_balanced_kmeans_clusters,
    get_capacity_distance_clusters,
    get_kmeans_clusters,
)
from shift.utils.split_network_edges import get_distance_between_points

TransformerTypeChoice = Literal[
    "THREE_PHASE",
    "SINGLE_PHASE_PRIMARY_DELTA",
    "SINGLE_PHASE",
    "SPLIT_PHASE",
    "SPLIT_PHASE_PRIMARY_DELTA",
]
"""Allowed transformer phase types (matches ``shift.TransformerTypes`` values)."""

RoutingStrategyChoice = Literal[
    "SteinerTreeStrategy",
    "WeightedSteinerTreeStrategy",
    "ShortestPathTreeStrategy",
    "MinimumSpanningTreeStrategy",
    "FullRoadGraphStrategy",
]

SecondaryStrategyChoice = Literal[
    "AutoDensitySecondaryStrategy",
    "MeshSteinerStrategy",
    "RadialStrategy",
    "DelaunayStrategy",
    "OpenStreetSecondaryStrategy",
    "HubLineStrategy",
    "TrunkBranchStrategy",
]


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


class ExportConfig(BaseModel):
    """Export location and naming."""

    folder: Path = Field(..., description="Root folder where feeder models are exported.")


class FeederConfig(BaseModel):
    """Feeder splitting, parallelism, and naming settings."""

    split_method: Literal["area", "parcels"] = Field(
        "area",
        description="Feeder-count estimation: 'area' maps cell area to feeder count "
        "relative to all cells; 'parcels' uses parcel-count/density heuristics.",
    )
    min_feeders: int = Field(3, description="Feeder count for the smallest substation cell.")
    max_feeders: int = Field(8, description="Feeder count for the largest substation cell.")
    target_parcels_per_feeder: int = Field(
        80, description="Target parcels per feeder for split_method='parcels'."
    )
    high_density_threshold_per_km2: float = Field(
        300.0, description="Density above which an extra feeder is added."
    )
    large_region_threshold_km2: float = Field(
        1.5, description="Region size above which an extra feeder is added."
    )
    seed: int = Field(0, description="Base seed for deterministic feeder-center placement.")
    max_workers: int | None = Field(
        None, description="ThreadPoolExecutor workers; defaults to os.cpu_count()."
    )
    substation_merge_distance_km: float = Field(
        0.0,
        description="Merge substations closer than this distance (km) into the one with the "
        "largest footprint. Use to dedupe near-coincident OSM substation ways.",
    )
    substation_folder_prefix: str = Field(
        "substation", description="Prefix for substation folders."
    )
    feeder_file_prefix: str = Field("feeder", description="Prefix for feeder model files.")
    phase_method: Literal["kmean", "greedy", "agglomerative"] = Field(
        "agglomerative", description="Phase allocation method for the balanced phase mapper."
    )


class CatalogConfig(BaseModel):
    """Settings for the equipment catalog used for rightsizing."""

    source: str = Field(
        "gdm_data", description="gdmloader source name (matches GCS_CASE_SOURCE.name)."
    )
    dataset: str = Field("gdm_catalog", description="Catalog dataset name under the source.")
    version: str | None = Field(None, description="Optional catalog version override.")
    cache_dir: Path | None = Field(
        None, description="Override the gdmloader local cache directory."
    )
    path: Path | None = Field(
        None,
        description="Optional path to a local catalog JSON (DatasetSystem). Takes precedence "
        "over gdmloader when set.",
    )


class ParcelSourceConfig(BaseModel):
    """Configures how parcels are obtained for each feeder cell."""

    source: Literal["location", "geodataframe", "pbf", "gis"] = Field(
        "location", description="Parcel source backend."
    )
    path: Path | None = Field(
        None,
        description="Path to a parcels file for source='geodataframe' (CSV/GeoJSON/GPKG/...).",
    )
    url: str | None = Field(
        None,
        description="ArcGIS FeatureServer layer URL for source='gis' "
        "(e.g. https://host/.../FeatureServer/0).",
    )
    layer: int | str | None = Field(
        None, description="Feature layer id/name when url points at the FeatureServer root."
    )
    where: str | None = Field(
        None, description="Optional SQL-style filter for source='gis' (default '1=1')."
    )
    id_field: str | None = Field(None, description="Source column used as the parcel name.")
    request_timeout: float = Field(60.0, description="Per-request timeout (s) for source='gis'.")
    name_column: str | None = Field(None, description="Column used as the parcel name.")
    field_mapper: Literal["osm", "gis"] = Field(
        "osm", description="Column mapper used by parcels_from_geodataframe."
    )
    column_map: dict[str, str] = Field(
        default_factory=dict, description="Override column names for the field mapper."
    )
    local_pbf_path: Path | None = Field(
        None, description="Optional local .pbf file used for source='pbf' and road extraction."
    )

    @model_validator(mode="after")
    def _validate_source(self):
        if self.source == "geodataframe" and self.path is None:
            msg = "parcels.path is required when parcels.source='geodataframe'."
            raise ValueError(msg)
        if self.source == "gis" and not self.url:
            msg = "parcels.url is required when parcels.source='gis'."
            raise ValueError(msg)
        return self


class ClusteringConfig(BaseModel):
    """Settings for grouping parcels into transformer service groups."""

    strategy: Literal["kmeans_count", "area_aware", "capacity_distance"] = Field(
        "capacity_distance", description="Clustering strategy used to form transformer groups."
    )
    balance_mode: Literal["balanced", "unbalanced"] = Field(
        "unbalanced",
        description="For strategy='kmeans_count': balanced assigns ~equal parcels per group.",
    )
    num_clusters: int | None = Field(
        None, description="Explicit cluster count for strategy='kmeans_count'."
    )
    parcels_per_cluster: int | None = Field(
        None, description="Alternative to num_clusters: derive cluster count from parcel count."
    )
    target_area_per_transformer_m2: float = Field(
        5000.0, description="Target parcel area per shared transformer for area-aware."
    )
    dedicated_transformer_area_m2: float = Field(
        2000.0, description="Parcel area at/above which it gets its own transformer."
    )
    target_kva_per_transformer: float = Field(
        75.0, description="Target connected load per shared transformer (kVA)."
    )
    dedicated_transformer_load_kva: float = Field(
        150.0, description="Parcel load at/above which it gets its own transformer."
    )
    max_secondary_length_m: float = Field(
        120.0, description="Maximum parcel-to-transformer distance for capacity-distance."
    )
    min_clusters: int = Field(1, description="Minimum number of transformer clusters.")
    max_clusters: int | None = Field(None, description="Maximum number of transformer clusters.")


class PRSGConfig(BaseModel):
    """Settings for the Primary Road / Secondary Grid graph builder."""

    network_type: Literal["balanced_default", "road_optimized", "full_road_exploration"] = Field(
        "balanced_default", description="Preset pairing of routing/secondary strategies."
    )
    routing_strategy: RoutingStrategyChoice | None = Field(
        None, description="Primary routing strategy; defaults to the network_type preset."
    )
    secondary_strategy: SecondaryStrategyChoice | None = Field(
        None, description="Secondary strategy; defaults to the network_type preset."
    )
    auto_secondary_density_threshold_per_km2: float = Field(
        300.0,
        description="Density threshold when secondary_strategy='AutoDensitySecondaryStrategy'.",
    )
    crossing_penalty: float = Field(
        1.0,
        ge=1.0,
        description="Penalty for edge crossings in weighted routing (1.0=none, 2-5=moderate).",
    )
    buffer_m: float = Field(20.0, description="Road-network search buffer in meters.")
    secondary_buffer_m: float = Field(
        50.0, description="Buffer (m) for OpenStreet/TrunkBranch secondary strategies."
    )
    secondary_mesh_spacing_m: float = Field(
        50.0, description="Grid spacing (m) for the MeshSteiner secondary strategy."
    )
    offline: bool = Field(False, description="Use geometric primary network (no OSM roads).")
    snap_to_roads: bool = Field(True, description="Snap transformer centers to road edges.")
    snap_threshold_m: float = Field(
        50.0, description="Maximum distance to snap a transformer center to a road (m)."
    )


class TransformerConfig(BaseModel):
    """Assumed transformer type/rating used by the phase mapper."""

    type: TransformerTypeChoice = Field(
        "SPLIT_PHASE", description="Transformer type assumed for all transformer edges."
    )
    capacity_kva: float = Field(
        25.0,
        description="Default transformer rating used when load-based estimation is unavailable.",
    )


class VoltageConfig(BaseModel):
    """Nominal transformer voltages used before snapping to the catalog."""

    primary_voltage_kv: float = Field(12.47, description="Primary-side line-to-line voltage (kV).")
    secondary_voltage_kv: float = Field(0.48, description="Secondary-side voltage (kV).")
    use_substation_voltage: bool = Field(
        True,
        description="Override primary_voltage_kv with the substation's OSM `voltage` tag "
        "when available (distribution-side level, in kV).",
    )


class FlowConfig(BaseModel):
    """Optional gdm-flow violation-fix pass run after each system is built."""

    enabled: bool = Field(False, description="Run gdm-flow fix_violations after building.")
    solver: Literal["ldf", "ac"] = Field("ldf", description="gdm-flow power-flow solver.")
    vm_min_pu: float = Field(0.95, description="Minimum voltage limit (pu).")
    vm_max_pu: float = Field(1.05, description="Maximum voltage limit (pu).")
    max_iterations: int = Field(10, description="Maximum fix iterations.")
    impedance_reduction_factor: float = Field(
        0.90, description="Conductor resize factor; must be > 0 and < 1."
    )


class FeederModelConfig(BaseModel):
    """Top-level configuration for the parallel feeder-model pipeline.

    Load from TOML with :meth:`FeederModelConfig.from_toml`:

    .. code-block:: toml

        [export]
        folder = "./models"

        [feeders]
        min_feeders = 3
        max_feeders = 8
        max_workers = 4

        [catalog]
        dataset = "gdm_catalog"

        [parcels]
        source = "geodataframe"
        path = "./data/parcels.geojson"

        [clustering]
        strategy = "capacity_distance"

        [prsg]
        network_type = "balanced_default"
    """

    export: ExportConfig
    feeders: FeederConfig = Field(default_factory=FeederConfig)
    catalog: CatalogConfig = Field(default_factory=CatalogConfig)
    parcels: ParcelSourceConfig = Field(default_factory=ParcelSourceConfig)
    clustering: ClusteringConfig = Field(default_factory=ClusteringConfig)
    prsg: PRSGConfig = Field(default_factory=PRSGConfig)
    transformers: TransformerConfig = Field(default_factory=TransformerConfig)
    voltages: VoltageConfig = Field(default_factory=VoltageConfig)
    flow: FlowConfig = Field(default_factory=FlowConfig)

    @property
    def export_folder(self) -> Path:
        """Root folder where feeder models are exported."""
        return self.export.folder

    @classmethod
    def from_toml(cls, path: str | Path) -> "FeederModelConfig":
        """Load the configuration from a TOML file."""
        with Path(path).open("rb") as fpointer:
            data = tomllib.load(fpointer)
        return cls(**data)


# ---------------------------------------------------------------------------
# Parcel sources
# ---------------------------------------------------------------------------


class ParcelSource(Protocol):
    """Interface for a source of parcels inside a polygon."""

    def get_parcels(self, polygon: Polygon) -> list[ParcelModel]: ...


def _polygon_parts(polygon: Polygon):
    """Yield each constituent polygon of ``polygon`` (handles MultiPolygons)."""
    geoms = polygon.geoms if hasattr(polygon, "geoms") else [polygon]
    for poly in geoms:
        yield poly


class LocationParcelSource:
    """Fetch parcels from OpenStreetMap via :func:`shift.parcel.parcels_from_location`."""

    def get_parcels(self, polygon: Polygon) -> list[ParcelModel]:
        parcels: list[ParcelModel] = []
        for poly in _polygon_parts(polygon):
            coords = [GeoLocation(x, y) for x, y in poly.exterior.coords]
            if len(coords) < 3:
                continue
            parcels.extend(parcels_from_location(coords) or [])
        return parcels


class PbfParcelSource:
    """Extract parcels from the configured local PBF file."""

    def get_parcels(self, polygon: Polygon) -> list[ParcelModel]:
        parcels: list[ParcelModel] = []
        for poly in _polygon_parts(polygon):
            parcels.extend(parcels_from_pbf(poly) or [])
        return parcels


class GeoDataFrameParcelSource:
    """Clip a user-supplied GeoDataFrame to each feeder cell.

    The frame is loaded once at construction (main thread) and only read from
    worker threads, so it is safe to share across the parallel build.
    """

    def __init__(self, config: ParcelSourceConfig):
        if config.path is None:
            msg = "parcels.path is required for source='geodataframe'."
            raise InvalidInputError(msg)
        self._gdf = _load_geodataframe(config.path)
        self._mapper: ParcelFieldMapper = _make_field_mapper(config)
        self._name_column = config.name_column

    def get_parcels(self, polygon: Polygon) -> list[ParcelModel]:
        clipped = self._gdf.clip(polygon)
        if len(clipped) == 0:
            return []
        return parcels_from_geodataframe(
            clipped,
            mapper=self._mapper,
            name_column=self._name_column,
        )


def _load_geodataframe(path: Path) -> gpd.GeoDataFrame:
    """Load a GeoDataFrame from CSV (WKT geometry) or a geospatial file."""
    if path.suffix.lower() == ".csv":
        import pandas as pd
        from shapely import wkt

        df = pd.read_csv(path)
        if "geometry" not in df.columns:
            msg = f"geometry column missing in {path}."
            raise InvalidInputError(msg)
        df["geometry"] = df["geometry"].apply(wkt.loads)
        return gpd.GeoDataFrame(df, crs="EPSG:4326")
    return gpd.read_file(path).to_crs("EPSG:4326")


def _make_field_mapper(config: ParcelSourceConfig) -> ParcelFieldMapper:
    mapper: type[ParcelFieldMapper] = (
        OSMParcelFieldMapper if config.field_mapper == "osm" else GISParcelFieldMapper
    )
    return mapper(config.column_map)


class GisParcelSource:
    """Fetch parcels/addresses from an ArcGIS FeatureServer layer.

    Features intersecting a feeder cell's bounding envelope are fetched with
    pagination (``maxRecordCount``-sized pages via ``resultOffset``) and then
    clipped to the cell. The frame is fetched per cell from worker threads;
    requests are independent so this is safe to share.
    """

    def __init__(self, config: ParcelSourceConfig):
        if not config.url:
            msg = "parcels.url is required for source='gis'."
            raise InvalidInputError(msg)
        base = config.url.rstrip("/")
        if "/FeatureServer/" not in base:
            layer = config.layer if config.layer is not None else 0
            base = f"{base}/FeatureServer/{layer}"
        self._query_url = f"{base}/query"
        self._where = config.where or "1=1"
        self._timeout = config.request_timeout
        self._mapper = _make_field_mapper(config)
        self._name_column = config.id_field or config.name_column

    def get_parcels(self, polygon: Polygon) -> list[ParcelModel]:
        features = self._fetch_intersecting(polygon)
        if not features:
            return []
        from shift.parcel_sources import _features_to_geodataframe

        gdf = _features_to_geodataframe(features, "EPSG:4326")
        if gdf.crs is None:
            gdf = gdf.set_crs("EPSG:4326")
        clipped = gdf.clip(polygon)
        if len(clipped) == 0:
            return []
        return parcels_from_geodataframe(
            clipped, mapper=self._mapper, name_column=self._name_column
        )

    def _fetch_intersecting(self, polygon: Polygon) -> list[dict]:
        minx, miny, maxx, maxy = polygon.bounds
        pad = max((maxx - minx), (maxy - miny)) * 0.02 or 0.001
        features: list[dict] = []
        offset = 0
        while True:
            params = {
                "where": self._where,
                "geometry": f"{minx - pad},{miny - pad},{maxx + pad},{maxy + pad}",
                "geometryType": "esriGeometryEnvelope",
                "spatialRel": "esriSpatialRelIntersects",
                "inSR": "4326",
                "outSR": "4326",
                "outFields": "*",
                "returnGeometry": "true",
                "resultOffset": offset,
                "resultRecordCount": 2000,
                "f": "json",
            }
            response = requests.get(self._query_url, params=params, timeout=self._timeout)
            response.raise_for_status()
            data = response.json()
            if isinstance(data, dict) and data.get("error"):
                msg = f"FeatureServer error: {data['error']}"
                raise InvalidInputError(msg)
            page = data.get("features", [])
            features.extend(page)
            if not data.get("exceededTransferLimit") or not page:
                break
            offset += len(page)
        return features


def _make_parcel_source(config: ParcelSourceConfig) -> ParcelSource:
    if config.local_pbf_path is not None:
        from shift.openstreet_roads import set_local_pbf

        set_local_pbf(str(config.local_pbf_path))
    if config.source == "location":
        return LocationParcelSource()
    if config.source == "pbf":
        return PbfParcelSource()
    if config.source == "gis":
        return GisParcelSource(config)
    return GeoDataFrameParcelSource(config)


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------


def load_catalog(config: CatalogConfig | None = None) -> CatalogSystem:
    """Load a :class:`gdm.distribution.CatalogSystem` through gdmloader.

    Uses gdmloader's ``SystemLoader`` with the public Google Cloud Storage case
    source (``GCS_CASE_SOURCE``) and the ``gdm_catalog`` dataset by default.
    """
    from gdm.distribution import CatalogSystem as _CatalogSystem
    from gdmloader.constants import GCS_CASE_SOURCE
    from gdmloader.source import SystemLoader

    cfg = config or CatalogConfig()
    cache_dir = cfg.cache_dir or (Path.home() / "gdmloader-cache")
    loader = SystemLoader(cached_dir=cache_dir)
    loader.add_source(GCS_CASE_SOURCE)

    logger.info(
        "Loading catalog dataset '{}' from source '{}' into {}.",
        cfg.dataset,
        cfg.source,
        cache_dir,
    )
    catalog = loader.load_dataset(
        system_type=_CatalogSystem,
        source_name=cfg.source,
        dataset_name=cfg.dataset,
        version=cfg.version,
    )
    augment_catalog_with_matrix_branches(catalog)
    _prewarm_catalog(catalog)
    return catalog


def _load_local_catalog(path: Path) -> "DistributionSystem":
    """Load a catalog from a local DatasetSystem JSON file."""
    from gdm.distribution.upgrade_handler.upgrade_handler import UpgradeHandler

    return DistributionSystem.from_json(path, upgrade_handler=UpgradeHandler().upgrade)


def _prewarm_catalog(catalog) -> None:
    """Force-cache the component type indexes on the shared catalog.

    ``infrasys.System`` lazily builds per-type caches on the first
    ``get_components`` call. Warming them in the main thread avoids concurrent
    first-access races from the worker threads.
    """
    from gdm.distribution.components import (
        DistributionBranchBase,
        DistributionLoad,
        DistributionTransformer as _DistributionTransformer,
    )
    from gdm.distribution.equipment import (
        DistributionTransformerEquipment,
        GeometryBranchEquipment,
        LoadEquipment,
        MatrixImpedanceBranchEquipment,
        SequenceImpedanceBranchEquipment,
    )

    for component_type in (
        DistributionTransformerEquipment,
        MatrixImpedanceBranchEquipment,
        SequenceImpedanceBranchEquipment,
        GeometryBranchEquipment,
        LoadEquipment,
        _DistributionTransformer,
        DistributionBranchBase,
        DistributionLoad,
    ):
        try:
            list(catalog.get_components(component_type))
        except Exception:
            logger.debug("No {} components in catalog.", component_type.__name__)


# Standard conductor phase spacings used when converting conductors to matrix
# branch equipment (meters). Matches common overhead primary construction.
_OVERHEAD_SPACING_M = 0.4
_OVERHEAD_HEIGHT_M = 5.6
_UNDERGROUND_DEPTH_M = -1.0


def _phase_positions(num_phases: int) -> list[float]:
    """Evenly spaced horizontal positions (meters) centered on zero."""
    return [round((i - (num_phases - 1) / 2) * _OVERHEAD_SPACING_M, 6) for i in range(num_phases)]


def augment_catalog_with_matrix_branches(catalog, *, phase_counts=(1, 2, 3)) -> None:
    """Add ``MatrixImpedanceBranchEquipment`` to ``catalog`` from its conductors.

    gdmloader's ``gdm_catalog`` stores conductors as ``BareConductorEquipment`` /
    ``ConcentricCableEquipment`` rather than impedance branch equipment. For each
    conductor, this builds ``GeometryBranchEquipment`` assemblies (one per phase
    count) using standard construction spacing and converts them with
    ``GeometryBranchEquipment.to_matrix_representation()`` so the rightsizing
    mapper can select matrix branch equipment. Idempotent: assemblies already in
    the catalog are skipped.
    """
    from gdm.distribution.equipment import (
        BareConductorEquipment,
        ConcentricCableEquipment,
        GeometryBranchEquipment,
        MatrixImpedanceBranchEquipment,
    )
    from gdm.quantities import Distance

    conductors = [
        *catalog.get_components(BareConductorEquipment),
        *catalog.get_components(ConcentricCableEquipment),
    ]
    if not conductors:
        return

    existing = {e.name for e in catalog.get_components(MatrixImpedanceBranchEquipment)}
    added = 0
    for conductor in conductors:
        is_cable = isinstance(conductor, ConcentricCableEquipment)
        vertical = _UNDERGROUND_DEPTH_M if is_cable else _OVERHEAD_HEIGHT_M
        for num_phases in phase_counts:
            name = f"{conductor.name}_{num_phases}ph"
            if name in existing:
                continue
            try:
                geometry = GeometryBranchEquipment(
                    name=name,
                    conductors=[conductor] * num_phases,
                    horizontal_positions=Distance(_phase_positions(num_phases), "m"),
                    vertical_positions=Distance([vertical] * num_phases, "m"),
                )
                matrix = geometry.to_matrix_representation()
                catalog.add_component(matrix)
                existing.add(name)
                added += 1
            except Exception:
                logger.debug(
                    "Could not convert conductor {} to {}-phase matrix branch.",
                    conductor.name,
                    num_phases,
                )

    if added:
        logger.info("Added {} MatrixImpedanceBranchEquipment from catalog conductors.", added)


# ---------------------------------------------------------------------------
# Single feeder model
# ---------------------------------------------------------------------------


def _kmeans_count_groups(
    centroids: list[GeoLocation], config: ClusteringConfig
) -> list[GroupModel]:
    """Cluster centroids into a fixed number of groups (balanced or plain KMeans)."""
    n_parcels = len(centroids)
    if config.num_clusters is not None:
        num_clusters = config.num_clusters
    elif config.parcels_per_cluster:
        num_clusters = max(1, int(math.ceil(n_parcels / config.parcels_per_cluster)))
    else:
        num_clusters = max(1, int(math.ceil(n_parcels / 3)))
    if config.max_clusters is not None:
        num_clusters = min(num_clusters, config.max_clusters)
    num_clusters = max(config.min_clusters, min(num_clusters, n_parcels))
    if config.balance_mode == "balanced":
        return get_balanced_kmeans_clusters(centroids, num_clusters)
    return get_kmeans_clusters(num_clusters, centroids)


def _cluster_parcels(
    parcels: list[ParcelModel], config: ClusteringConfig, default_kva: float
) -> tuple[list[GroupModel], list[ApparentPower]]:
    """Cluster parcels into transformer groups and estimate per-group load (kVA)."""
    if not parcels:
        raise InvalidInputError("No parcels found in the feeder area.")

    centroids: list[GeoLocation] = []
    load_by_centroid: dict[tuple[float, float], float] = {}
    for parcel in parcels:
        center, area_m2 = centroid_and_area_m2(_parcel_geometry(parcel))
        centroids.append(center)
        load_by_centroid[(center.longitude, center.latitude)] = estimate_load_kva(
            area_m2, _parcel_building_type(parcel)
        )

    if config.strategy == "kmeans_count":
        groups = _kmeans_count_groups(centroids, config)
    elif config.strategy == "capacity_distance":
        groups = get_capacity_distance_clusters(
            parcels,
            target_kva_per_transformer=config.target_kva_per_transformer,
            dedicated_transformer_area_m2=config.dedicated_transformer_area_m2,
            dedicated_transformer_load_kva=config.dedicated_transformer_load_kva,
            max_secondary_length_m=config.max_secondary_length_m,
            min_clusters=config.min_clusters,
            max_clusters=config.max_clusters,
        )
    else:
        groups = get_area_aware_clusters(
            parcels,
            target_area_per_transformer_m2=config.target_area_per_transformer_m2,
            dedicated_transformer_area_m2=config.dedicated_transformer_area_m2,
            min_clusters=config.min_clusters,
            max_clusters=config.max_clusters,
        )

    capacities: list[ApparentPower] = []
    for group in groups:
        kva = sum(load_by_centroid.get((p.longitude, p.latitude), 0.0) for p in group.points)
        if kva <= 0:
            kva = default_kva
        capacities.append(ApparentPower(kva, "kilovolt_ampere"))
    return groups, capacities


def _parcel_geometry(parcel):
    """Read a parcel's geometry attribute (dict or object)."""
    return parcel["geometry"] if isinstance(parcel, dict) else parcel.geometry


def _parcel_building_type(parcel):
    """Read a parcel's building_type attribute (dict or object)."""
    return parcel.get("building_type") if isinstance(parcel, dict) else parcel.building_type


def _nearest_group_capacity(
    location,
    groups: list[GroupModel],
    capacities: list[ApparentPower],
    default_kva: float,
) -> ApparentPower:
    """Return the capacity of the group whose center is closest to ``location``."""
    location_geo = GeoLocation(location.x, location.y)
    best_index, best_distance = 0, float("inf")
    for i, group in enumerate(groups):
        distance = get_distance_between_points(location_geo, group.center).to("m").magnitude
        if distance < best_distance:
            best_index, best_distance = i, distance
    return capacities[best_index] if capacities else ApparentPower(default_kva, "kilovolt_ampere")


def _resolve_prsg_strategies(
    config: PRSGConfig,
    *,
    candidate_points: list[GeoLocation] | None = None,
    polygon_points: list[GeoLocation] | None = None,
):
    """Resolve routing/secondary strategies from the config, mirroring the UI."""
    default_routing, default_secondary = NETWORK_PRESETS[config.network_type]
    routing_name = config.routing_strategy or default_routing
    secondary_name = config.secondary_strategy or default_secondary
    if secondary_name == "AutoDensitySecondaryStrategy":
        secondary_name, _ = auto_select_secondary_strategy(
            candidate_points=candidate_points or [],
            polygon_points=polygon_points,
            density_threshold_per_km2=config.auto_secondary_density_threshold_per_km2,
        )
    routing = get_routing_strategy(routing_name, crossing_penalty=config.crossing_penalty)
    secondary = get_secondary_strategy(
        secondary_name,
        buffer_meters=config.secondary_buffer_m,
        mesh_spacing_meters=config.secondary_mesh_spacing_m,
    )
    return routing, secondary


def _fix_violations(system, flow: FlowConfig) -> None:
    """Run the optional gdm-flow violation-fix pass on a built system (in place)."""
    if not flow.enabled:
        return
    try:
        from gdm_flow.fix import (
            AddCapacitorStrategy,
            AdjustRegulatorTapStrategy,
            ResizeConductorStrategy,
            ResizeTransformerStrategy,
            fix_violations,
        )
    except ImportError:
        logger.warning("flow.enabled is true but gdm-flow is not installed; skipping.")
        return

    try:
        conductor_strategy = ResizeConductorStrategy(
            impedance_reduction_factor=flow.impedance_reduction_factor
        )
    except TypeError:
        conductor_strategy = ResizeConductorStrategy()

    fix_violations(
        system,
        strategies=[
            AdjustRegulatorTapStrategy(),
            AddCapacitorStrategy(),
            conductor_strategy,
            ResizeTransformerStrategy(),
        ],
        max_iterations=flow.max_iterations,
        solver=flow.solver,
        vm_min_pu=flow.vm_min_pu,
        vm_max_pu=flow.vm_max_pu,
    )


def build_feeder_model(
    feeder_polygon: Polygon,
    substation_point: GeoLocation,
    catalog,
    config: FeederModelConfig,
    *,
    parcel_source: ParcelSource | None = None,
    primary_voltage_kv: float | None = None,
    name: str = "feeder",
) -> DistributionSystem:
    """Build a single feeder ``DistributionSystem`` sourced from a substation.

    Parameters
    ----------
    feeder_polygon : Polygon
        Feeder service-area cell in WGS84 (EPSG:4326).
    substation_point : GeoLocation
        Substation location; used as the graph's voltage-source location.
    catalog : CatalogSystem
        Equipment catalog used for rightsizing.
    config : FeederModelConfig
        Pipeline configuration.
    parcel_source : ParcelSource | None
        Source of parcels inside ``feeder_polygon``. Defaults to one built from
        ``config.parcels``.
    primary_voltage_kv : float | None
        Distribution-side primary voltage (kV) for this substation, e.g. derived
        from the OSM ``voltage`` tag. Defaults to ``config.voltages.primary_voltage_kv``.
    name : str
        Name of the built system.

    Returns
    -------
    DistributionSystem
    """
    if parcel_source is None:
        parcel_source = _make_parcel_source(config.parcels)

    parcels = parcel_source.get_parcels(feeder_polygon)
    if not parcels:
        msg = f"No parcels found in feeder area for {name}."
        raise InvalidInputError(msg)

    groups, capacities = _cluster_parcels(
        parcels, config.clustering, config.transformers.capacity_kva
    )

    candidate_points = [point for group in groups for point in group.points]
    routing, secondary = _resolve_prsg_strategies(config.prsg, candidate_points=candidate_points)

    prsg = PRSG(
        groups=groups,
        source_location=substation_point,
        buffer=Distance(config.prsg.buffer_m, "m"),
        routing_strategy=routing,
        secondary_strategy=secondary,
        offline=config.prsg.offline,
        snap_to_roads=config.prsg.snap_to_roads,
        snap_threshold_m=config.prsg.snap_threshold_m,
    )
    graph = prsg.get_distribution_graph()

    transformer_edges = [
        (from_node, to_node, edge_data)
        for from_node, to_node, edge_data in graph.get_edges()
        if issubclass(edge_data.edge_type, DistributionTransformer)
    ]
    if not transformer_edges:
        msg = f"No transformers created in the graph for {name}."
        raise InvalidInputError(msg)

    transformer_type = TransformerTypes(config.transformers.type)
    primary_kv = (
        primary_voltage_kv
        if primary_voltage_kv is not None
        else config.voltages.primary_voltage_kv
    )
    phase_models: list[TransformerPhaseMapperModel] = []
    voltage_models: list[TransformerVoltageModel] = []
    for from_node, to_node, edge_data in transformer_edges:
        center_node = to_node if from_node.endswith("_ht") else from_node
        location = graph.get_node(center_node).location
        phase_models.append(
            TransformerPhaseMapperModel(
                tr_name=edge_data.name,
                tr_type=transformer_type,
                tr_capacity=_nearest_group_capacity(
                    location,
                    groups,
                    capacities,
                    config.transformers.capacity_kva,
                ),
                location=location,
            )
        )
        voltage_models.append(
            TransformerVoltageModel(
                name=edge_data.name,
                voltages=[
                    Voltage(primary_kv, "kilovolt"),
                    Voltage(config.voltages.secondary_voltage_kv, "kilovolt"),
                ],
            )
        )

    phase_mapper = BalancedPhaseMapper(
        graph,
        mapper=phase_models,
        method=config.feeders.phase_method,
    )
    voltage_mapper = TransformerVoltageMapper(graph, xfmr_voltage=voltage_models)
    voltage_mapper = snap_voltage_mapper_to_catalog(graph, catalog, voltage_mapper, phase_mapper)

    equipment_mapper = DefaultLoadEquipmentMapper(
        graph,
        catalog,
        voltage_mapper,
        phase_mapper,
        source_voltage_kv=source_voltage_kv(voltage_mapper),
    )

    builder = DistributionSystemBuilder(
        name=name,
        dist_graph=graph,
        phase_mapper=phase_mapper,
        voltage_mapper=voltage_mapper,
        equipment_mapper=equipment_mapper,
    )
    return builder.get_system()


# ---------------------------------------------------------------------------
# Parallel pipeline + export
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _FeederTask:
    substation_index: int
    osm_id: object
    substation_point: GeoLocation
    primary_voltage_kv: float
    feeder_index: int
    feeder_polygon: Polygon
    output_path: Path
    system_name: str


def _substation_primary_voltage_kv(cells_gdf, sub_idx: int, config: FeederModelConfig) -> float:
    """Distribution-side primary voltage (kV) for a substation from its OSM tag.

    Uses the substation's ``voltage`` tag when ``voltages.use_substation_voltage``
    is on and the tag parses; otherwise falls back to ``primary_voltage_kv``.
    """
    if config.voltages.use_substation_voltage and "voltage" in cells_gdf.columns:
        parsed = substation_voltage_kv(cells_gdf["voltage"].iloc[sub_idx])
        if parsed is not None:
            logger.info(
                "Substation {} reports voltage tag '{}' -> primary {:.3g} kV.",
                cells_gdf["osm_id"].iloc[sub_idx],
                cells_gdf["voltage"].iloc[sub_idx],
                parsed,
            )
            return parsed
    return float(config.voltages.primary_voltage_kv)


def _feeder_counts(
    cells_gdf, config: FeederConfig, parcel_source: ParcelSource | None
) -> list[int]:
    """Return one feeder count per substation cell, ordered as ``cells_gdf``."""
    areas = [_cell_area_km2(c) for c in cells_gdf.geometry]
    if config.split_method == "parcels":
        if parcel_source is None:
            msg = "parcels.source must be configured when feeders.split_method='parcels'."
            raise InvalidInputError(msg)
        return [
            estimate_feeder_count(
                parcel_count=len(parcel_source.get_parcels(cell)),
                region_area_km2=area_km2,
                target_parcels_per_feeder=config.target_parcels_per_feeder,
                high_density_threshold_per_km2=config.high_density_threshold_per_km2,
                large_region_threshold_km2=config.large_region_threshold_km2,
                min_feeders=config.min_feeders,
                max_feeders=config.max_feeders,
            )
            for cell, area_km2 in zip(cells_gdf.geometry, areas)
        ]
    from shift.feeder_boundaries import feeder_counts_for_cells

    return feeder_counts_for_cells(
        areas, min_feeders=config.min_feeders, max_feeders=config.max_feeders
    )


def _iter_feeder_tasks(
    polygon: Polygon,
    config: FeederModelConfig,
    parcel_source: ParcelSource | None,
) -> list[_FeederTask]:
    """Split ``polygon`` into per-substation feeder cells and build export tasks."""
    merge_deg = config.feeders.substation_merge_distance_km / 111.0
    cells_gdf = substation_boundaries(polygon, merge_distance_deg=merge_deg)
    n_subs = len(cells_gdf)
    if n_subs == 0:
        logger.warning("No substations found in the service area.")
        return []

    counts = _feeder_counts(cells_gdf, config.feeders, parcel_source)

    export_root = Path(config.export_folder)
    tasks: list[_FeederTask] = []
    for sub_idx, (cell, count) in enumerate(zip(cells_gdf.geometry, counts)):
        osm_id = cells_gdf["osm_id"].iloc[sub_idx] if "osm_id" in cells_gdf else sub_idx + 1
        substation_point = cells_gdf["substation_point"].iloc[sub_idx]
        substation_geo = GeoLocation(substation_point.x, substation_point.y)
        primary_voltage_kv = _substation_primary_voltage_kv(cells_gdf, sub_idx, config)
        substation_folder = export_root / f"{config.feeders.substation_folder_prefix}_{osm_id}"

        feeder_gdf = split_substation_into_feeders(
            cell,
            feeder_count=count,
            seed=config.feeders.seed + sub_idx,
        )
        for feeder_index, feeder_polygon in enumerate(feeder_gdf.geometry, start=1):
            tasks.append(
                _FeederTask(
                    substation_index=sub_idx + 1,
                    osm_id=osm_id,
                    substation_point=substation_geo,
                    primary_voltage_kv=primary_voltage_kv,
                    feeder_index=feeder_index,
                    feeder_polygon=feeder_polygon,
                    output_path=substation_folder
                    / f"{config.feeders.feeder_file_prefix}_{feeder_index}.json",
                    system_name=f"substation_{osm_id}_feeder_{feeder_index}",
                )
            )
    return tasks


def _build_and_export_feeder(task: _FeederTask, config, parcel_source, catalog) -> dict:
    """Build one feeder model and export it with ``DistributionSystem.to_json``."""
    system = build_feeder_model(
        task.feeder_polygon,
        task.substation_point,
        catalog,
        config,
        parcel_source=parcel_source,
        primary_voltage_kv=task.primary_voltage_kv,
        name=task.system_name,
    )
    _fix_violations(system, config.flow)
    task.output_path.parent.mkdir(parents=True, exist_ok=True)
    system.to_json(task.output_path, overwrite=True)
    logger.info("Exported {} -> {}", task.system_name, task.output_path)
    return {
        "substation_index": task.substation_index,
        "osm_id": task.osm_id,
        "feeder_index": task.feeder_index,
        "system_name": task.system_name,
        "output_path": str(task.output_path),
    }


def build_feeder_models(
    polygon: Polygon,
    config: FeederModelConfig,
    *,
    catalog=None,
) -> list[dict]:
    """Build and export every feeder model in a service area, in parallel.

    Each feeder's ``DistributionSystem`` is built concurrently on a
    ``ThreadPoolExecutor`` (the graph construction is dominated by network I/O)
    with the substation point as the voltage source, right-sized against
    ``catalog`` (loaded via gdmloader when not supplied), and exported to
    ``<export_folder>/<substation_<osm_id>>/<feeder_<index>>.json``.

    Parameters
    ----------
    polygon : Polygon
        Service-area polygon in WGS84 (EPSG:4326).
    config : FeederModelConfig
        Pipeline configuration.
    catalog : CatalogSystem | None
        Equipment catalog. Loaded via :func:`load_catalog` when omitted.

    Returns
    -------
    list[dict]
        Manifest of exported models, one entry per successfully built feeder.
    """
    parcel_source = _make_parcel_source(config.parcels)
    from shift.substation import set_substations_cache_dir

    default_cache = Path(".") / ".dump"
    set_substations_cache_dir(default_cache if default_cache.is_dir() else None)
    tasks = _iter_feeder_tasks(polygon, config, parcel_source)
    if not tasks:
        return []

    if catalog is None:
        if config.catalog.path is not None:
            catalog = _load_local_catalog(config.catalog.path)
        else:
            catalog = load_catalog(config.catalog)
    else:
        augment_catalog_with_matrix_branches(catalog)
        _prewarm_catalog(catalog)

    max_workers = config.feeders.max_workers or min(32, (os.cpu_count() or 1))
    logger.info(
        "Building {} feeder model(s) with {} worker(s) into {}.",
        len(tasks),
        max_workers,
        config.export_folder,
    )

    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_build_and_export_feeder, task, config, parcel_source, catalog): task
            for task in tasks
        }
        for future in as_completed(futures):
            task = futures[future]
            try:
                results.append(future.result())
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "Failed to build feeder {} (substation {}) for {}: {}",
                    task.feeder_index,
                    task.osm_id,
                    task.output_path,
                    exc,
                )

    results.sort(
        key=lambda r: (
            r["substation_index"],
            r["feeder_index"],
        )
    )
    logger.info("Built and exported {}/{} feeder model(s).", len(results), len(tasks))
    return results
