from __future__ import annotations

import shutil
import traceback
from pathlib import Path
import tempfile

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from gdm.quantities import ApparentPower, Voltage
from infrasys import Location
from infrasys.quantities import Distance
import numpy as np
from sklearn.cluster import KMeans

from shift.data_model import GeoLocation, GroupModel, TransformerPhaseMapperModel, TransformerTypes
from shift.graph.graph_utils import compute_graph_metrics, extract_graph_geometry
from shift.graph.prsgb import PRSG
from shift.graph.routing import (
    FullRoadGraphStrategy,
    MinimumSpanningTreeStrategy,
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
    TrunkBranchStrategy,
)
from shift.graph.strategy_resolver import (
    auto_select_secondary_strategy,
)
from shift.mapper.balanced_phase_mapper import BalancedPhaseMapper
from shift.mapper.edge_equipment_mapper import EdgeEquipmentMapper
from shift.mapper.transformer_voltage_mapper import TransformerVoltageMapper
from shift.mcp_server.serializers import (
    serialize_graph_summary,
    serialize_group,
    serialize_parcel,
)
from gdm.distribution import DistributionSystem as DatasetSystem
from shift.parcel import parcels_from_location
from shift.system_builder import DistributionSystemBuilder
from shift.ui_api.models import (
    BuildSystemFullRequest,
    BuildSystemRequest,
    ClusterBalanceMode,
    ClusterStrategyName,
    ClusterRequest,
    ConfigureEquipmentMapperRequest,
    ConfigurePhaseMapperRequest,
    ConfigureVoltageMapperRequest,
    ExportSystemRequest,
    FetchParcelsRequest,
    GeoPoint,
    GraphBuildRequest,
    MultiFeederBuildRequest,
    NetworkTypeName,
    QuickBuildRequest,
    RoutingStrategyName,
    SecondaryStrategyName,
    StrategyCompareRequest,
)
from shift.ui_api.state import UiSessionState
from shift.utils.get_cluster import (
    centroid_and_area_m2,
    estimate_feeder_count,
    get_area_aware_clusters,
    get_balanced_kmeans_clusters,
    get_capacity_distance_clusters,
    get_kmeans_clusters,
)
from shift.utils.geo import region_area_km2_from_points, region_area_km2_from_polygon
from gdm.distribution.upgrade_handler.upgrade_handler import UpgradeHandler

_GDM_UPGRADE_HANDLER = UpgradeHandler().upgrade


def _load_dataset_system_compat(path: Path) -> DatasetSystem:
    """Load DatasetSystem JSON using GDM's official upgrade handler chain."""
    return DatasetSystem.from_json(path, upgrade_handler=_GDM_UPGRADE_HANDLER)


def _catalog_transformer_type(equipment) -> str:
    primary_winding = equipment.windings[0]
    primary_voltage_type = getattr(primary_winding, "voltage_type", None)
    is_delta_primary = str(primary_voltage_type).endswith("LINE_TO_LINE")

    if getattr(equipment, "is_center_tapped", False):
        return (
            TransformerTypes.SPLIT_PHASE_PRIMARY_DELTA.value
            if is_delta_primary
            else TransformerTypes.SPLIT_PHASE.value
        )

    if getattr(primary_winding, "num_phases", None) == 3:
        return TransformerTypes.THREE_PHASE.value

    return (
        TransformerTypes.SINGLE_PHASE_PRIMARY_DELTA.value
        if is_delta_primary
        else TransformerTypes.SINGLE_PHASE.value
    )


def _catalog_transformer_options(catalog: DatasetSystem) -> list[dict]:
    from gdm.distribution.equipment import DistributionTransformerEquipment

    options: dict[tuple, dict] = {}
    for equipment in catalog.get_components(DistributionTransformerEquipment):
        voltages = [w.rated_voltage.to("kV").magnitude for w in equipment.windings]
        capacities = [w.rated_power.to("kVA").magnitude for w in equipment.windings]
        primary_kv = round(max(voltages), 6)
        secondary_kv = round(min(voltages), 6)
        capacity_kva = round(min(capacities), 6)
        transformer_type = _catalog_transformer_type(equipment)
        num_phases = max(getattr(w, "num_phases", 0) for w in equipment.windings)
        key = (transformer_type, capacity_kva, primary_kv, secondary_kv)
        if key not in options:
            label = f"{transformer_type} | {capacity_kva:g} kVA | {primary_kv:g} -> {secondary_kv:g} kV"
            options[key] = {
                "label": label,
                "transformer_type": transformer_type,
                "transformer_capacity_kva": capacity_kva,
                "primary_voltage_kv": primary_kv,
                "secondary_voltage_kv": secondary_kv,
                "is_center_tapped": bool(getattr(equipment, "is_center_tapped", False)),
                "num_phases": num_phases,
                "count": 0,
            }
        options[key]["count"] += 1

    return sorted(
        options.values(),
        key=lambda item: (
            item["transformer_type"],
            item["primary_voltage_kv"],
            item["secondary_voltage_kv"],
            item["transformer_capacity_kva"],
        ),
    )


def _select_catalog_transformer_option(
    catalog: DatasetSystem,
    transformer_type: str,
    transformer_capacity_kva: float,
    primary_voltage_kv: float,
    secondary_voltage_kv: float,
) -> dict | None:
    options = _catalog_transformer_options(catalog)
    matching_type = [opt for opt in options if opt["transformer_type"] == transformer_type]
    if not matching_type:
        return None

    def score(option: dict) -> tuple[float, float, float]:
        return (
            abs(option["primary_voltage_kv"] - primary_voltage_kv)
            + abs(option["secondary_voltage_kv"] - secondary_voltage_kv),
            abs(option["transformer_capacity_kva"] - transformer_capacity_kva),
            option["transformer_capacity_kva"],
        )

    return min(matching_type, key=score)


def _graph_metrics(graph) -> dict[str, float | int | bool]:
    return compute_graph_metrics(graph)


def _graph_geometry(graph) -> dict[str, list]:
    return extract_graph_geometry(graph)


def _resolve_strategies(payload: GraphBuildRequest):
    network_presets = {
        NetworkTypeName.BALANCED_DEFAULT: (
            RoutingStrategyName.STEINER,
            SecondaryStrategyName.OPENSTREET,
        ),
        NetworkTypeName.ROAD_OPTIMIZED: (
            RoutingStrategyName.WEIGHTED_STEINER,
            SecondaryStrategyName.OPENSTREET,
        ),
        NetworkTypeName.FULL_ROAD_EXPLORATION: (
            RoutingStrategyName.FULL_ROAD,
            SecondaryStrategyName.OPENSTREET,
        ),
    }

    default_routing, default_secondary = network_presets[payload.network_type]
    routing_name = payload.routing_strategy or default_routing
    secondary_name = payload.secondary_strategy or default_secondary

    auto_secondary_context: dict[str, float | str] = {}
    if secondary_name == SecondaryStrategyName.AUTO_DENSITY:
        candidate_points: list[GeoLocation] = []
        groups = getattr(payload, "groups", None)
        if groups:
            candidate_points = [
                GeoLocation(point.longitude, point.latitude)
                for group in groups
                for point in group.points
            ]
        else:
            parcels = getattr(payload, "parcels", None) or []
            for parcel in parcels:
                center, _ = _centroid_and_area_m2(parcel.geometry)
                candidate_points.append(center)

        polygon_points = [
            GeoLocation(p.longitude, p.latitude) for p in (getattr(payload, "polygon", None) or [])
        ]
        secondary_name, auto_secondary_context = _auto_select_secondary_strategy(
            candidate_points=candidate_points,
            polygon_points=polygon_points,
            density_threshold_per_km2=payload.auto_secondary_density_threshold_per_km2,
        )

    routing = {
        RoutingStrategyName.STEINER: SteinerTreeStrategy(),
        RoutingStrategyName.WEIGHTED_STEINER: WeightedSteinerTreeStrategy(
            crossing_penalty=getattr(payload, "crossing_penalty", 1.0),
        ),
        RoutingStrategyName.SHORTEST_PATH_TREE: ShortestPathTreeStrategy(),
        RoutingStrategyName.MIN_SPANNING_TREE: MinimumSpanningTreeStrategy(),
        RoutingStrategyName.FULL_ROAD: FullRoadGraphStrategy(),
    }[routing_name]

    secondary = {
        SecondaryStrategyName.AUTO_DENSITY: DelaunayStrategy(),
        SecondaryStrategyName.MESH_STEINER: MeshSteinerStrategy(
            spacing=Distance(payload.secondary_mesh_spacing_meters, "m")
        ),
        SecondaryStrategyName.RADIAL: RadialStrategy(),
        SecondaryStrategyName.DELAUNAY: DelaunayStrategy(),
        SecondaryStrategyName.OPENSTREET: OpenStreetSecondaryStrategy(
            buffer=Distance(payload.secondary_buffer_meters, "m")
        ),
        SecondaryStrategyName.HUB_LINE: HubLineStrategy(),
        SecondaryStrategyName.TRUNK_BRANCH: TrunkBranchStrategy(
            buffer=Distance(payload.secondary_buffer_meters, "m")
        ),
    }[secondary_name]

    return routing_name.value, secondary_name.value, routing, secondary, auto_secondary_context


def _centroid_and_area_m2(parcel_geometry) -> tuple[GeoLocation, float]:
    """Thin wrapper around centroid_and_area_m2 for backward compat."""
    return centroid_and_area_m2(parcel_geometry)


def _estimate_feeder_count(**kwargs) -> int:
    return estimate_feeder_count(**kwargs)


def _region_area_km2_from_polygon(points: list[GeoLocation] | None) -> float:
    return region_area_km2_from_polygon(points)


def _region_area_km2_from_points(points: list[GeoLocation]) -> float:
    return region_area_km2_from_points(points)


def _auto_select_secondary_strategy(
    *,
    candidate_points: list[GeoLocation],
    polygon_points: list[GeoLocation] | None,
    density_threshold_per_km2: float,
) -> tuple[SecondaryStrategyName, dict[str, float | str]]:
    name, context = auto_select_secondary_strategy(
        candidate_points=candidate_points,
        polygon_points=polygon_points,
        density_threshold_per_km2=density_threshold_per_km2,
    )
    name_map = {v.value: v for v in SecondaryStrategyName}
    return name_map[name], context


def _build_area_aware_clusters(payload: ClusterRequest) -> list[GroupModel]:
    if not payload.parcels:
        raise ValueError("Area-aware clustering requires parcels payload.")
    return get_area_aware_clusters(
        payload.parcels,
        target_area_per_transformer_m2=payload.target_area_per_transformer_m2,
        dedicated_transformer_area_m2=payload.dedicated_transformer_area_m2,
        min_clusters=payload.min_clusters,
        max_clusters=payload.max_clusters,
    )


def _build_capacity_distance_clusters(payload: ClusterRequest) -> list[GroupModel]:
    if not payload.parcels:
        raise ValueError("Capacity-distance clustering requires parcels payload.")
    return get_capacity_distance_clusters(
        payload.parcels,
        target_kva_per_transformer=payload.target_kva_per_transformer,
        dedicated_transformer_area_m2=payload.dedicated_transformer_area_m2,
        dedicated_transformer_load_kva=payload.dedicated_transformer_load_kva,
        max_secondary_length_m=payload.max_secondary_length_m,
        min_clusters=payload.min_clusters,
        max_clusters=payload.max_clusters,
    )


def _build_balanced_kmeans_clusters(
    points: list[GeoLocation], num_clusters: int
) -> list[GroupModel]:
    return get_balanced_kmeans_clusters(points, num_clusters)


def _load_road_graph_for_snap(clusters: list[dict], polygon: list[dict]):
    """Load a road network graph for snapping, trying local PBF then Overpass."""
    from shift.openstreet_roads import extract_from_pbf, get_local_pbf, get_road_network
    from fastapi import HTTPException

    road_graph = None
    if get_local_pbf() and polygon and len(polygon) >= 3:
        lons = [p["longitude"] for p in polygon]
        lats = [p["latitude"] for p in polygon]
        bbox = (min(lons), min(lats), max(lons), max(lats))
        xml_path = extract_from_pbf(bbox)
        try:
            import osmnx as ox

            road_graph = ox.graph_from_xml(xml_path).to_undirected()
        except Exception:  # noqa: BLE001
            road_graph = None
        Path(xml_path).unlink(missing_ok=True)

    if road_graph is None:
        try:
            all_pts = [
                GeoLocation(c["center"]["longitude"], c["center"]["latitude"]) for c in clusters
            ]
            from shift.utils.polygon_from_points import get_polygon_from_points

            poly = get_polygon_from_points(all_pts, Distance(50, "m"))
            road_graph = get_road_network(poly, reduce_to_mst=False)
        except Exception as exc:
            raise HTTPException(
                status_code=400,
                detail="No road data available (local PBF or Overpass required).",
            ) from exc

    if not road_graph or not road_graph.nodes:
        raise HTTPException(status_code=400, detail="Empty road network for this area.")
    return road_graph


def create_app() -> FastAPI:  # noqa: C901
    app = FastAPI(title="SHIFT UI API", version="0.1.0")
    state = UiSessionState()

    def _write_complete_model_bundle(system_name: str, system) -> tuple[Path, Path, Path]:
        """Write full system bundle (JSON + time_series) and zip archive.

        Returns: (json_path, bundle_dir, bundle_zip_path)
        """
        temp_dir = Path(tempfile.gettempdir())
        json_path = temp_dir / f"{system_name}.json"
        bundle_dir = temp_dir / f"{system_name}_bundle"
        bundle_zip = temp_dir / f"{system_name}_bundle.zip"

        system.to_json(str(json_path), overwrite=True)

        if bundle_dir.exists():
            shutil.rmtree(bundle_dir)
        system.save(bundle_dir, filename=f"{system_name}.json", overwrite=True)

        if bundle_zip.exists():
            bundle_zip.unlink()
        shutil.make_archive(str(bundle_dir), "zip", bundle_dir)

        return json_path, bundle_dir, bundle_zip

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/options")
    def options() -> dict:
        return {
            "network_types": [x.value for x in NetworkTypeName],
            "cluster_strategies": [x.value for x in ClusterStrategyName],
            "cluster_balance_modes": [x.value for x in ClusterBalanceMode],
            "routing_strategies": [x.value for x in RoutingStrategyName],
            "secondary_strategies": [x.value for x in SecondaryStrategyName],
            "phase_methods": ["agglomerative", "kmean", "greedy"],
            "transformer_types": [x.value for x in TransformerTypes],
            "flow_solvers": ["ldf", "ac"],
        }

    @app.post("/api/catalog/transformers")
    def catalog_transformers(payload: dict) -> dict:
        catalog_path = payload.get("catalog_path")
        if not catalog_path:
            raise HTTPException(status_code=400, detail="catalog_path is required")

        path = Path(catalog_path)
        if not path.exists():
            raise HTTPException(status_code=404, detail=f"Catalog file not found: {catalog_path}")

        try:
            catalog = _load_dataset_system_compat(path)
            return {
                "success": True,
                "catalog_path": str(path),
                "transformers": _catalog_transformer_options(catalog),
            }
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/parcels/fetch")
    def fetch_parcels(payload: FetchParcelsRequest) -> dict:
        try:
            if payload.polygon:
                loc = [GeoLocation(p.longitude, p.latitude) for p in payload.polygon]
            elif payload.location:
                if "," in payload.location:
                    parts = payload.location.split(",")
                    if len(parts) == 2:
                        loc = GeoLocation(float(parts[0].strip()), float(parts[1].strip()))
                    else:
                        loc = payload.location
                else:
                    loc = payload.location
            else:
                raise ValueError("Provide either location or polygon.")

            parcels = parcels_from_location(loc, Distance(payload.distance_meters, "m"))
            parcels = parcels or []
            return {
                "success": True,
                "count": len(parcels),
                "parcels": [serialize_parcel(p) for p in parcels],
            }
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/clusters/build")
    def build_clusters(payload: ClusterRequest) -> dict:
        try:
            uses_num_clusters = payload.strategy == ClusterStrategyName.KMEANS_COUNT
            strategy_details: dict[str, float | int | str | bool] = {}
            if payload.strategy == ClusterStrategyName.AREA_AWARE:
                clusters = _build_area_aware_clusters(payload)
                parcel_areas: list[float] = []
                dedicated_count = 0
                shared_area_total = 0.0
                for parcel in payload.parcels:
                    _, area_m2 = _centroid_and_area_m2(parcel.geometry)
                    parcel_areas.append(area_m2)
                    if area_m2 >= payload.dedicated_transformer_area_m2:
                        dedicated_count += 1
                    else:
                        shared_area_total += max(area_m2, 1.0)

                strategy_details = {
                    "area_aware_input_target_area_m2": payload.target_area_per_transformer_m2,
                    "area_aware_input_dedicated_threshold_m2": payload.dedicated_transformer_area_m2,
                    "area_aware_total_parcels": len(payload.parcels),
                    "area_aware_dedicated_parcels": dedicated_count,
                    "area_aware_shared_parcels": len(payload.parcels) - dedicated_count,
                    "area_aware_shared_area_total_m2": round(shared_area_total, 2),
                    "area_aware_estimated_shared_clusters_raw": int(
                        np.ceil(
                            shared_area_total / max(payload.target_area_per_transformer_m2, 1.0)
                        )
                    )
                    if (len(payload.parcels) - dedicated_count) > 0
                    else 0,
                    "area_aware_num_clusters_input_used": False,
                    "area_aware_estimation_method": "ceil(total_shared_area/target_area)",
                    "area_aware_min_parcel_area_m2": round(min(parcel_areas), 2)
                    if parcel_areas
                    else 0.0,
                    "area_aware_max_parcel_area_m2": round(max(parcel_areas), 2)
                    if parcel_areas
                    else 0.0,
                }
            elif payload.strategy == ClusterStrategyName.CAPACITY_DISTANCE:
                clusters = _build_capacity_distance_clusters(payload)
                strategy_details = {
                    "capacity_distance_num_clusters_input_used": False,
                    "capacity_distance_estimation_method": "derived_from_load_and_distance_constraints",
                }
            else:
                if len(payload.points) < payload.num_clusters:
                    raise ValueError("num_clusters must be <= number of points")
                points = [GeoLocation(p.longitude, p.latitude) for p in payload.points]
                if payload.balance_mode == ClusterBalanceMode.BALANCED:
                    clusters = _build_balanced_kmeans_clusters(points, payload.num_clusters)
                else:
                    clusters = get_kmeans_clusters(payload.num_clusters, points)

            return {
                "success": True,
                "count": len(clusters),
                "strategy": payload.strategy.value,
                "balance_mode": payload.balance_mode.value,
                "input_num_clusters": payload.num_clusters,
                "uses_num_clusters": uses_num_clusters,
                "strategy_details": strategy_details,
                "clusters": [serialize_group(c) for c in clusters],
            }
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/graph/build")
    def build_graph(payload: GraphBuildRequest) -> dict:
        try:
            groups = [
                GroupModel(
                    center=GeoLocation(g.center.longitude, g.center.latitude),
                    points=[GeoLocation(p.longitude, p.latitude) for p in g.points],
                )
                for g in payload.groups
            ]
            source_location = GeoLocation(
                payload.source_location.longitude,
                payload.source_location.latitude,
            )

            routing_name, secondary_name, routing, secondary, auto_secondary_context = (
                _resolve_strategies(payload)
            )

            builder = PRSG(
                groups=groups,
                source_location=source_location,
                buffer=Distance(payload.buffer_meters, "m"),
                routing_strategy=routing,
                secondary_strategy=secondary,
                offline=getattr(payload, "offline", False),
                snap_to_roads=getattr(payload, "snap_to_roads", True),
                snap_threshold_m=getattr(payload, "snap_threshold_m", 50.0),
            )
            graph = builder.get_distribution_graph()
            graph_id = state.new_id("graph")
            state.graphs[graph_id] = graph

            summary = serialize_graph_summary(graph, graph_id)
            summary.update(_graph_metrics(graph))
            summary.update(
                {
                    "network_type": payload.network_type.value,
                    "routing_strategy": routing_name,
                    "secondary_strategy": secondary_name,
                }
            )
            if auto_secondary_context:
                summary.update(auto_secondary_context)
            geometry = _graph_geometry(graph)
            return {"success": True, "summary": summary, "geometry": geometry}
        except Exception as exc:
            traceback.print_exc()
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/roads/network")
    def get_road_network_geometry(payload: GraphBuildRequest) -> dict:
        """Return raw road network geometry for map visualization."""
        try:
            from shift.openstreet_roads import get_road_network
            from shift.utils.polygon_from_points import get_polygon_from_points

            points = []
            for g in payload.groups:
                for p in g.points:
                    points.append(GeoLocation(p.longitude, p.latitude))
            if not points and payload.polygon:
                points = [GeoLocation(p.longitude, p.latitude) for p in payload.polygon]

            if not points:
                raise HTTPException(status_code=400, detail="No points to define road area")

            polygon = get_polygon_from_points(points, Distance(payload.buffer_meters, "m"))
            road_graph = get_road_network(polygon, reduce_to_mst=False)

            # Extract edges as line segments
            edges = []
            for u, v in road_graph.edges():
                ud = road_graph.nodes[u]
                vd = road_graph.nodes[v]
                if "x" in ud and "y" in ud and "x" in vd and "y" in vd:
                    edges.append(
                        {
                            "from": {"latitude": ud["y"], "longitude": ud["x"]},
                            "to": {"latitude": vd["y"], "longitude": vd["x"]},
                        }
                    )
            return {"success": True, "edge_count": len(edges), "edges": edges}
        except Exception as exc:
            traceback.print_exc()
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/graph/compare")
    def compare_graph_builds(payload: StrategyCompareRequest) -> dict:
        runs = []
        for idx, build in enumerate(payload.builds, start=1):
            result = build_graph(build)
            runs.append({"run": idx, **result["summary"]})
        return {"success": True, "runs": runs}

    @app.post("/api/feeders/auto-build")
    def auto_build_feeders(payload: MultiFeederBuildRequest) -> dict:
        if not payload.parcels:
            raise HTTPException(status_code=400, detail="Parcels are required.")

        try:
            parcel_entries = []
            for p in payload.parcels:
                center, _ = _centroid_and_area_m2(p.geometry)
                parcel_entries.append({"parcel": p, "center": center})

            region_points = [
                GeoLocation(pt.longitude, pt.latitude) for pt in payload.polygon or []
            ]
            region_area_km2 = _region_area_km2_from_polygon(region_points)

            feeder_count = _estimate_feeder_count(
                parcel_count=len(parcel_entries),
                region_area_km2=region_area_km2,
                target_parcels_per_feeder=payload.target_parcels_per_feeder,
                high_density_threshold_per_km2=payload.high_density_threshold_per_km2,
                large_region_threshold_km2=payload.large_region_threshold_km2,
                min_feeders=payload.min_feeders,
                max_feeders=payload.max_feeders,
            )

            feeder_count = min(feeder_count, len(parcel_entries))
            coords = np.array(
                [(e["center"].longitude, e["center"].latitude) for e in parcel_entries]
            )
            model = KMeans(n_clusters=feeder_count, random_state=0)
            model.fit(coords)

            routing_name, secondary_name, routing, secondary, auto_secondary_context = (
                _resolve_strategies(payload)
            )

            feeder_summaries = []
            for idx in range(feeder_count):
                feeder_points = [
                    parcel_entries[i]["center"]
                    for i, lbl in enumerate(model.labels_)
                    if int(lbl) == idx
                ]
                if not feeder_points:
                    continue

                tx_clusters = max(
                    1, int(np.ceil(len(feeder_points) / payload.parcels_per_transformer))
                )
                groups = get_kmeans_clusters(tx_clusters, feeder_points)

                source = GeoLocation(
                    float(np.mean([p.longitude for p in feeder_points])),
                    float(np.mean([p.latitude for p in feeder_points])),
                )

                builder = PRSG(
                    groups=groups,
                    source_location=source,
                    buffer=Distance(payload.buffer_meters, "m"),
                    routing_strategy=routing,
                    secondary_strategy=secondary,
                )
                graph = builder.get_distribution_graph()
                graph_id = state.new_id("graph")
                state.graphs[graph_id] = graph

                summary = serialize_graph_summary(graph, graph_id)
                summary.update(_graph_metrics(graph))
                summary.update(
                    {
                        "feeder_index": idx + 1,
                        "parcel_count": len(feeder_points),
                        "transformer_group_count": len(groups),
                        "source_location": {
                            "longitude": source.longitude,
                            "latitude": source.latitude,
                        },
                    }
                )
                feeder_summaries.append(summary)

            density = len(parcel_entries) / max(region_area_km2, 0.01)
            return {
                "success": True,
                "requested_parcels": len(parcel_entries),
                "region_area_km2": round(region_area_km2, 4),
                "parcel_density_per_km2": round(density, 2),
                "estimated_feeder_count": feeder_count,
                "routing_strategy": routing_name,
                "secondary_strategy": secondary_name,
                "auto_secondary": auto_secondary_context,
                "feeders": feeder_summaries,
            }
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/graph/{graph_id}/transformers")
    def list_transformers(graph_id: str) -> dict:
        graph = state.graphs.get(graph_id)
        if graph is None:
            raise HTTPException(status_code=404, detail=f"Unknown graph_id {graph_id}")
        transformers = []
        for _, _, edge in graph.get_edges():
            edge_type = getattr(edge.edge_type, "__name__", str(edge.edge_type))
            if edge_type == "DistributionTransformer":
                transformers.append(edge.name)
        return {"success": True, "graph_id": graph_id, "transformers": transformers}

    @app.post("/api/mapper/phase")
    def configure_phase_mapper(payload: ConfigurePhaseMapperRequest) -> dict:
        graph = state.graphs.get(payload.graph_id)
        if graph is None:
            raise HTTPException(status_code=404, detail=f"Unknown graph_id {payload.graph_id}")

        try:
            models = []
            for cfg in payload.transformer_configs:
                tr_loc = None
                for _, to_n, edge in graph.get_edges():
                    if edge.name == cfg.tr_name:
                        tr_loc = graph.get_node(to_n).location
                        break
                if tr_loc is None:
                    tr_loc = Location(x=0, y=0)

                models.append(
                    TransformerPhaseMapperModel(
                        tr_name=cfg.tr_name,
                        tr_type=TransformerTypes(cfg.tr_type),
                        tr_capacity=ApparentPower(cfg.tr_capacity_kva, "kVA"),
                        location=tr_loc,
                    )
                )

            mapper = BalancedPhaseMapper(graph, models, method=payload.method)
            state.phase_mappers[payload.graph_id] = mapper
            return {
                "success": True,
                "graph_id": payload.graph_id,
                "count": len(models),
            }
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/mapper/voltage")
    def configure_voltage_mapper(payload: ConfigureVoltageMapperRequest) -> dict:
        graph = state.graphs.get(payload.graph_id)
        if graph is None:
            raise HTTPException(status_code=404, detail=f"Unknown graph_id {payload.graph_id}")

        try:
            from shift.data_model import TransformerVoltageModel

            models = []
            for cfg in payload.transformer_voltages:
                models.append(
                    TransformerVoltageModel(
                        name=cfg.name,
                        voltages=[Voltage(v, "kV") for v in cfg.voltages_kv],
                    )
                )
            mapper = TransformerVoltageMapper(graph, models)
            state.voltage_mappers[payload.graph_id] = mapper
            return {
                "success": True,
                "graph_id": payload.graph_id,
                "count": len(models),
            }
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/mapper/equipment")
    def configure_equipment_mapper(payload: ConfigureEquipmentMapperRequest) -> dict:
        graph = state.graphs.get(payload.graph_id)
        if graph is None:
            raise HTTPException(status_code=404, detail=f"Unknown graph_id {payload.graph_id}")
        if (
            payload.graph_id not in state.phase_mappers
            or payload.graph_id not in state.voltage_mappers
        ):
            raise HTTPException(
                status_code=400,
                detail="Phase and voltage mappers must be configured first.",
            )

        try:
            catalog = _load_dataset_system_compat(Path(payload.catalog_path))
            mapper = EdgeEquipmentMapper(
                graph,
                catalog,
                state.voltage_mappers[payload.graph_id],
                state.phase_mappers[payload.graph_id],
            )
            state.equipment_mappers[payload.graph_id] = mapper
            return {"success": True, "graph_id": payload.graph_id}
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/system/build")
    def build_system(payload: BuildSystemRequest) -> dict:
        graph = state.graphs.get(payload.graph_id)
        if graph is None:
            raise HTTPException(status_code=404, detail=f"Unknown graph_id {payload.graph_id}")

        for name, mapper_store in {
            "phase_mapper": state.phase_mappers,
            "voltage_mapper": state.voltage_mappers,
            "equipment_mapper": state.equipment_mappers,
        }.items():
            if payload.graph_id not in mapper_store:
                raise HTTPException(
                    status_code=400, detail=f"Missing {name} for graph {payload.graph_id}"
                )

        try:
            builder = DistributionSystemBuilder(
                name=payload.system_name,
                dist_graph=graph,
                phase_mapper=state.phase_mappers[payload.graph_id],
                voltage_mapper=state.voltage_mappers[payload.graph_id],
                equipment_mapper=state.equipment_mappers[payload.graph_id],
            )
            system = builder.get_system()
            state.systems[payload.system_name] = system
            return {"success": True, "system_name": payload.system_name}
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/system/export")
    def export_system(payload: ExportSystemRequest) -> dict:
        system = state.systems.get(payload.system_name)
        if system is None:
            raise HTTPException(status_code=404, detail=f"Unknown system {payload.system_name}")

        output_path = payload.output_path or str(
            Path(tempfile.gettempdir()) / f"{payload.system_name}.json"
        )
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        system.to_json(out)
        _, bundle_dir, bundle_zip = _write_complete_model_bundle(payload.system_name, system)
        return {
            "success": True,
            "system_name": payload.system_name,
            "output_path": str(out),
            "bundle_dir": str(bundle_dir),
            "bundle_zip_path": str(bundle_zip),
            "download_url": f"/api/system/{payload.system_name}/download",
            "download_bundle_url": f"/api/system/{payload.system_name}/download-bundle",
        }

    @app.get("/api/system/{system_name}/download")
    def download_system(system_name: str):
        system = state.systems.get(system_name)
        if system is None:
            raise HTTPException(status_code=404, detail=f"Unknown system {system_name}")

        out, _, _ = _write_complete_model_bundle(system_name, system)
        return FileResponse(
            path=out,
            filename=f"{system_name}.json",
            media_type="application/json",
        )

    @app.get("/api/system/{system_name}/download-bundle")
    def download_system_bundle(system_name: str):
        system = state.systems.get(system_name)
        if system is None:
            raise HTTPException(status_code=404, detail=f"Unknown system {system_name}")

        _, _, bundle_zip = _write_complete_model_bundle(system_name, system)
        return FileResponse(
            path=bundle_zip,
            filename=f"{system_name}_bundle.zip",
            media_type="application/zip",
        )

    @app.post("/api/system/fix-violations")
    def fix_system_violations(payload: dict) -> dict:
        """Run gdm-flow violation fix loop on a built system.

        Requires the optional 'flow' extra: pip install nrel-shift[flow]
        """
        try:
            from gdm_flow.fix import (
                AddCapacitorStrategy,
                AdjustRegulatorTapStrategy,
                ResizeConductorStrategy,
                ResizeTransformerStrategy,
                fix_violations,
            )
        except ImportError:
            raise HTTPException(
                status_code=501,
                detail="gdm-flow not installed. Install with: pip install nrel-shift[flow]",
            )

        system_name = payload.get("system_name")
        if not system_name or system_name not in state.systems:
            raise HTTPException(
                status_code=404,
                detail=f"Unknown system '{system_name}'. Build a system first.",
            )

        system = state.systems[system_name]
        output_system_name = payload.get("output_system_name") or system_name
        max_iterations = int(payload.get("max_iterations", 10))
        solver = str(payload.get("solver", "ldf")).strip().lower()
        if solver not in {"ldf", "ac"}:
            raise HTTPException(
                status_code=400, detail=f"Unsupported solver '{solver}'. Use 'ldf' or 'ac'."
            )
        vm_min_pu = float(payload.get("vm_min_pu", 0.95))
        vm_max_pu = float(payload.get("vm_max_pu", 1.05))
        impedance_reduction_factor = float(payload.get("impedance_reduction_factor", 0.90))
        if not (0.0 < impedance_reduction_factor < 1.0):
            raise HTTPException(
                status_code=400,
                detail="impedance_reduction_factor must be > 0 and < 1",
            )

        try:
            conductor_strategy = ResizeConductorStrategy(
                impedance_reduction_factor=impedance_reduction_factor
            )
        except TypeError:
            conductor_strategy = ResizeConductorStrategy()

        strategies = [
            AdjustRegulatorTapStrategy(),
            AddCapacitorStrategy(),
            conductor_strategy,
            ResizeTransformerStrategy(),
        ]

        try:
            result = fix_violations(
                system,
                strategies=strategies,
                max_iterations=max_iterations,
                solver=solver,
                vm_min_pu=vm_min_pu,
                vm_max_pu=vm_max_pu,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        # Keep the latest fixed system snapshot under requested output name.
        state.systems[output_system_name] = system
        _, _, bundle_zip = _write_complete_model_bundle(output_system_name, system)
        download_url = f"/api/system/{output_system_name}/download"
        download_bundle_url = f"/api/system/{output_system_name}/download-bundle"

        return {
            "success": result.success,
            "message": result.message,
            "initial_voltage_violations": result.initial_voltage_violations,
            "initial_loading_violations": result.initial_loading_violations,
            "final_voltage_violations": result.final_voltage_violations,
            "final_loading_violations": result.final_loading_violations,
            "total_actions": result.total_actions,
            "violations_fixed": result.violations_fixed,
            "iterations": len(result.iterations),
            "solver": solver,
            "max_iterations": max_iterations,
            "impedance_reduction_factor": impedance_reduction_factor,
            "iteration_details": [
                {
                    "iteration": it.iteration,
                    "voltage_violations": it.voltage_violations,
                    "loading_violations": it.loading_violations,
                    "actions": [a.description for a in it.actions],
                }
                for it in result.iterations
            ],
            "download_url": download_url,
            "download_bundle_url": download_bundle_url,
            "bundle_zip_path": str(bundle_zip),
            "output_system_name": output_system_name,
        }

    @app.post("/api/config/local-pbf")
    def configure_local_pbf(payload: dict) -> dict:
        """Set the local PBF file path for offline building/road extraction."""
        from shift.openstreet_roads import set_local_pbf

        path = payload.get("pbf_path", "")
        if not path or not Path(path).exists():
            raise HTTPException(status_code=400, detail=f"PBF file not found: {path}")
        set_local_pbf(path)
        return {"success": True, "pbf_path": path}

    @app.post("/api/clusters/snap-to-roads")
    def snap_clusters_to_roads(payload: dict) -> dict:
        """Snap cluster centers to nearest road nodes using local PBF."""
        from shift.utils.snap_to_roads import snap_cluster_to_road

        clusters = payload.get("clusters", [])
        threshold_m = payload.get("threshold_m", 50.0)
        polygon = payload.get("polygon", [])

        if not clusters:
            raise HTTPException(status_code=400, detail="No clusters provided.")

        try:
            road_graph = _load_road_graph_for_snap(clusters, polygon)

            edge_segments = [
                (
                    road_graph.nodes[u]["x"],
                    road_graph.nodes[u]["y"],
                    road_graph.nodes[v]["x"],
                    road_graph.nodes[v]["y"],
                )
                for u, v in road_graph.edges()
            ]

            snapped = []
            snap_count = 0
            for cluster in clusters:
                center = cluster["center"]
                center_geo = GeoLocation(center["longitude"], center["latitude"])
                parcel_points = [
                    GeoLocation(p["longitude"], p["latitude"]) for p in cluster.get("points", [])
                ]

                result = snap_cluster_to_road(
                    center_geo, parcel_points, edge_segments, threshold_m
                )
                if result is None:
                    snapped.append({**cluster, "snapped": False, "snap_distance_m": 999.0})
                else:
                    new_center = {
                        "longitude": result["longitude"],
                        "latitude": result["latitude"],
                    }
                    snapped.append(
                        {
                            **cluster,
                            "center": new_center,
                            "snapped": True,
                            "snap_distance_m": result["snap_distance_m"],
                        }
                    )
                    snap_count += 1

            return {
                "success": True,
                "clusters": snapped,
                "snapped_count": snap_count,
                "total": len(clusters),
                "threshold_m": threshold_m,
            }
        except HTTPException:
            raise
        except Exception as exc:
            traceback.print_exc()
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/parcels/fetch-local")
    def fetch_parcels_local(payload: dict) -> dict:
        """Fetch parcels from local PBF via osmium extract + OSMnx XML parsing."""
        from shift.openstreet_roads import extract_from_pbf, get_local_pbf

        if not get_local_pbf():
            raise HTTPException(
                status_code=400,
                detail="No local PBF configured. POST /api/config/local-pbf first.",
            )

        polygon = payload.get("polygon", [])
        if len(polygon) < 3:
            raise HTTPException(status_code=400, detail="Polygon needs at least 3 points.")

        try:
            lons = [p["longitude"] for p in polygon]
            lats = [p["latitude"] for p in polygon]
            bbox = (min(lons), min(lats), max(lons), max(lats))

            # Extract from PBF
            xml_path = extract_from_pbf(bbox)

            # Parse buildings from XML (handle broken relations gracefully)
            import defusedxml.ElementTree as ET

            tree = ET.parse(xml_path)
            root = tree.getroot()

            # Build node lookup
            nodes_map = {}
            for node_el in root.findall("node"):
                nid = node_el.get("id")
                nodes_map[nid] = {
                    "longitude": float(node_el.get("lon")),
                    "latitude": float(node_el.get("lat")),
                }

            # Extract building ways and filter by actual polygon
            from shapely.geometry import Point as _ShapelyPoint, Polygon as _ShapelyPolygon

            user_polygon = _ShapelyPolygon([(p["longitude"], p["latitude"]) for p in polygon])

            parcels = []
            for way_el in root.findall("way"):
                tags = {t.get("k"): t.get("v") for t in way_el.findall("tag")}
                if "building" not in tags:
                    continue
                nd_refs = [nd.get("ref") for nd in way_el.findall("nd")]
                coords = [nodes_map[ref] for ref in nd_refs if ref in nodes_map]
                if len(coords) < 3:
                    continue

                # Check if centroid falls within the user's polygon
                avg_lon = sum(c["longitude"] for c in coords) / len(coords)
                avg_lat = sum(c["latitude"] for c in coords) / len(coords)
                if not user_polygon.contains(_ShapelyPoint(avg_lon, avg_lat)):
                    continue

                parcels.append(
                    {
                        "name": f"parcel_{len(parcels)}",
                        "building_type": tags.get("building", "yes"),
                        "city": tags.get("addr:city", ""),
                        "state": tags.get("addr:state", ""),
                        "postal_address": tags.get("addr:street", ""),
                        "geometry": coords,
                    }
                )

            # Clean up temp file
            Path(xml_path).unlink(missing_ok=True)

            return {
                "success": True,
                "count": len(parcels),
                "parcels": parcels,
                "source": "local_pbf",
            }
        except Exception as exc:
            traceback.print_exc()
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/system/quick-build")
    def quick_build_system(payload: QuickBuildRequest) -> dict:  # noqa: C901
        """Polygon + source → parcels → clusters → graph → GDM system in one call."""
        try:
            # 1. Fetch parcels
            loc = [GeoLocation(p.longitude, p.latitude) for p in payload.polygon]
            try:
                raw_parcels = parcels_from_location(loc, Distance(500, "m"))
                raw_parcels = raw_parcels or []
            except Exception:
                raw_parcels = []
            if not raw_parcels:
                raise ValueError("No parcels found in polygon.")

            # 2. Cluster (area-aware)
            parcel_data = [serialize_parcel(p) for p in raw_parcels]
            from shift.ui_api.models import ParcelInput, ClusterRequest, ClusterStrategyName

            parcel_inputs = []
            for pd_item in parcel_data:
                geom = pd_item["geometry"]
                if isinstance(geom, list):
                    geo_pts = [
                        GeoPoint(longitude=g["longitude"], latitude=g["latitude"]) for g in geom
                    ]
                else:
                    geo_pts = [GeoPoint(longitude=geom["longitude"], latitude=geom["latitude"])]
                parcel_inputs.append(
                    ParcelInput(
                        name=pd_item.get("name"),
                        building_type=pd_item.get("building_type"),
                        geometry=geo_pts,
                    )
                )

            cluster_req = ClusterRequest(
                strategy=ClusterStrategyName.AREA_AWARE,
                parcels=parcel_inputs,
                points=[],
                target_area_per_transformer_m2=payload.target_area_per_transformer_m2,
                dedicated_transformer_area_m2=payload.dedicated_transformer_area_m2,
            )
            clusters = _build_area_aware_clusters(cluster_req)

            # 3. Build graph
            source_loc = GeoLocation(
                payload.source_location.longitude, payload.source_location.latitude
            )
            from shift.graph.secondary import DelaunayStrategy as _DS, RadialStrategy as _RS

            sec_strategy = {"DelaunayStrategy": _DS(), "RadialStrategy": _RS()}.get(
                payload.secondary_strategy, _DS()
            )
            prsg = PRSG(
                groups=clusters,
                source_location=source_loc,
                buffer=Distance(20, "m"),
                secondary_strategy=sec_strategy,
                offline=payload.offline,
            )
            graph = prsg.get_distribution_graph()
            graph_id = state.new_id("graph")
            state.graphs[graph_id] = graph

            # 4. Build GDM system
            build_req = BuildSystemFullRequest(
                graph_id=graph_id,
                system_name=payload.system_name,
                transformer_type=payload.transformer_type,
                transformer_capacity_kva=payload.transformer_capacity_kva,
                primary_voltage_kv=payload.primary_voltage_kv,
                secondary_voltage_kv=payload.secondary_voltage_kv,
                catalog_path=payload.catalog_path,
            )
            sys_result = build_system_full(build_req)

            geometry = _graph_geometry(graph)
            graph_summary = serialize_graph_summary(graph, graph_id)
            graph_summary.update(_graph_metrics(graph))

            return {
                "success": True,
                "parcels_count": len(parcel_data),
                "clusters_count": len(clusters),
                "graph_summary": graph_summary,
                "geometry": geometry,
                "system_name": sys_result.get("system_name"),
                "output_path": sys_result.get("output_path"),
                "bundle_dir": sys_result.get("bundle_dir"),
                "bundle_zip_path": sys_result.get("bundle_zip_path"),
                "download_url": sys_result.get("download_url"),
                "download_bundle_url": sys_result.get("download_bundle_url"),
            }
        except Exception as exc:
            traceback.print_exc()
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/system/build-full")
    def build_system_full(payload: BuildSystemFullRequest) -> dict:  # noqa: C901
        """One-shot: configure mappers + build + export a GDM system."""
        graph = state.graphs.get(payload.graph_id)
        if graph is None:
            raise HTTPException(status_code=404, detail=f"Unknown graph_id {payload.graph_id}")

        try:
            from functools import cached_property as _cached_property
            from gdm.distribution.equipment import (
                LoadEquipment,
                PhaseLoadEquipment,
                VoltageSourceEquipment,
                PhaseVoltageSourceEquipment,
            )
            from gdm.distribution.components import DistributionVoltageSource, DistributionLoad
            from gdm.distribution.components import DistributionTransformer as _DT
            from gdm.distribution.enums import VoltageTypes, Phase as _Phase
            from gdm.quantities import Reactance, ActivePower as _AP, ReactivePower as _RP
            from infrasys.component import Component as _Component
            from infrasys.quantities import Resistance, Angle
            from shift.data_model import TransformerVoltageModel as _TVM

            # Phase mapper
            tr_models = []
            for from_node, _, edge in graph.get_edges():
                if edge.edge_type is not _DT:
                    continue
                tr_models.append(
                    TransformerPhaseMapperModel(
                        tr_name=edge.name,
                        tr_type=TransformerTypes(payload.transformer_type),
                        tr_capacity=ApparentPower(payload.transformer_capacity_kva, "kVA"),
                        location=graph.get_node(from_node).location,
                    )
                )
            phase_mapper = BalancedPhaseMapper(graph, tr_models, method=payload.phase_method)

            # Voltage mapper
            v_models = [
                _TVM(
                    name=edge.name,
                    voltages=[
                        Voltage(payload.primary_voltage_kv, "kV"),
                        Voltage(payload.secondary_voltage_kv, "kV"),
                    ],
                )
                for _, _, edge in graph.get_edges()
                if edge.edge_type is _DT
            ]
            voltage_mapper = TransformerVoltageMapper(graph, v_models)

            # Load catalog if provided, else try auto-detect voltages
            catalog = None
            if payload.catalog_path:
                catalog = _load_dataset_system_compat(Path(payload.catalog_path))
                selected_option = _select_catalog_transformer_option(
                    catalog,
                    payload.transformer_type,
                    payload.transformer_capacity_kva,
                    payload.primary_voltage_kv,
                    payload.secondary_voltage_kv,
                )
                if selected_option is not None:
                    pri = selected_option["primary_voltage_kv"]
                    sec = selected_option["secondary_voltage_kv"]
                    v_models = [
                        _TVM(
                            name=edge.name,
                            voltages=[Voltage(pri, "kV"), Voltage(sec, "kV")],
                        )
                        for _, _, edge in graph.get_edges()
                        if edge.edge_type is _DT
                    ]
                    voltage_mapper = TransformerVoltageMapper(graph, v_models)
                    payload.primary_voltage_kv = pri
                    payload.secondary_voltage_kv = sec

            # Equipment mapper with default loads
            class _FullMapper(EdgeEquipmentMapper):
                @_cached_property
                def node_asset_equipment_mapping(self):
                    mapping = {}

                    def _build_phase_matched_load(
                        template: LoadEquipment,
                        node_name: str,
                        phase_count: int,
                    ) -> LoadEquipment:
                        """Create load equipment whose phase_loads length matches node phase count."""
                        count = max(1, phase_count)
                        src_phase_loads = (
                            list(template.phase_loads) if template.phase_loads else []
                        )
                        if not src_phase_loads:
                            src_phase_loads = [
                                PhaseLoadEquipment(
                                    name=f"{node_name}_phase_load_template",
                                    real_power=_AP(10, "kilowatt"),
                                    reactive_power=_RP(3, "kilovar"),
                                    z_real=0,
                                    z_imag=0,
                                    i_real=0,
                                    i_imag=0,
                                    p_real=1,
                                    p_imag=1,
                                )
                            ]

                        total_p_kw = sum(
                            pl.real_power.to("kilowatt").magnitude for pl in src_phase_loads
                        )
                        total_q_kvar = sum(
                            pl.reactive_power.to("kilovar").magnitude for pl in src_phase_loads
                        )

                        base = src_phase_loads[0]
                        per_phase_p_kw = total_p_kw / count if count else total_p_kw
                        per_phase_q_kvar = total_q_kvar / count if count else total_q_kvar

                        phase_loads = [
                            PhaseLoadEquipment(
                                name=f"{node_name}_phase_load_{idx + 1}",
                                real_power=_AP(per_phase_p_kw, "kilowatt"),
                                reactive_power=_RP(per_phase_q_kvar, "kilovar"),
                                z_real=base.z_real,
                                z_imag=base.z_imag,
                                i_real=base.i_real,
                                i_imag=base.i_imag,
                                p_real=base.p_real,
                                p_imag=base.p_imag,
                            )
                            for idx in range(count)
                        ]

                        return LoadEquipment(
                            name=f"{node_name}_load_equipment", phase_loads=phase_loads
                        )

                    load_equips = (
                        list(self.catalog_sys.get_components(LoadEquipment))
                        if self.catalog_sys
                        else []
                    )
                    if load_equips:
                        default_load = load_equips[0]
                    else:
                        default_load = LoadEquipment(
                            name="default_load",
                            phase_loads=[
                                PhaseLoadEquipment(
                                    name="default_phase_load",
                                    real_power=_AP(10, "kilowatt"),
                                    reactive_power=_RP(3, "kilovar"),
                                    z_real=0,
                                    z_imag=0,
                                    i_real=0,
                                    i_imag=0,
                                    p_real=1,
                                    p_imag=1,
                                )
                            ],
                        )
                    vsrc = VoltageSourceEquipment(
                        name="default_vsource",
                        sources=[
                            PhaseVoltageSourceEquipment(
                                name=f"vsrc_{i}",
                                r0=Resistance(0.001, "ohm"),
                                r1=Resistance(0.001, "ohm"),
                                x0=Reactance(0.001, "ohm"),
                                x1=Reactance(0.001, "ohm"),
                                voltage=Voltage(payload.primary_voltage_kv, "kV"),
                                voltage_type=VoltageTypes.LINE_TO_LINE,
                                angle=Angle(i * 120, "degree"),
                            )
                            for i in range(3)
                        ],
                    )
                    for node in self.graph.get_nodes():
                        if not node.assets:
                            continue
                        nm = {}
                        if DistributionLoad in node.assets:
                            phases = self.phase_mapper.asset_phase_mapping[node.name][
                                DistributionLoad
                            ]
                            load_phase_count = len([ph for ph in phases if ph != _Phase.N])
                            nm[DistributionLoad] = _build_phase_matched_load(
                                default_load,
                                node.name,
                                load_phase_count,
                            )
                        if DistributionVoltageSource in node.assets:
                            nm[DistributionVoltageSource] = vsrc
                        if nm:
                            mapping[node.name] = nm
                    return mapping

            if catalog is None:
                # Create a minimal catalog with generic equipment
                catalog = DatasetSystem(name="default_catalog", auto_add_composed_components=True)

            eq_mapper = _FullMapper(
                graph=graph,
                catalog_sys=catalog,
                voltage_mapper=voltage_mapper,
                phase_mapper=phase_mapper,
            )

            builder = DistributionSystemBuilder(
                name=payload.system_name,
                dist_graph=graph,
                phase_mapper=phase_mapper,
                voltage_mapper=voltage_mapper,
                equipment_mapper=eq_mapper,
            )
            system = builder.get_system()
            state.systems[payload.system_name] = system

            # Export
            out, bundle_dir, bundle_zip = _write_complete_model_bundle(
                payload.system_name,
                system,
            )

            component_count = len(list(system.get_components(_Component)))

            return {
                "success": True,
                "system_name": payload.system_name,
                "components": component_count,
                "output_path": str(out),
                "bundle_dir": str(bundle_dir),
                "bundle_zip_path": str(bundle_zip),
                "download_url": f"/api/system/{payload.system_name}/download",
                "download_bundle_url": f"/api/system/{payload.system_name}/download-bundle",
            }
        except Exception as exc:
            traceback.print_exc()
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    # --- Server-Sent Events log stream ---
    import asyncio
    import queue
    from loguru import logger as _loguru
    from starlette.responses import StreamingResponse

    _log_queue: queue.Queue = queue.Queue(maxsize=200)

    class _QueueSink:
        def write(self, message):
            record = message.record
            line = f"[{record['level'].name}] {record['name']}:{record['function']}:{record['line']} — {record['message']}"
            try:
                _log_queue.put_nowait(line)
            except queue.Full:
                try:
                    _log_queue.get_nowait()
                    _log_queue.put_nowait(line)
                except queue.Empty:
                    pass

    _loguru.add(_QueueSink(), format="{message}", level="DEBUG")

    @app.get("/api/logs/stream")
    async def stream_logs():
        async def _generate():
            while True:
                try:
                    line = _log_queue.get_nowait()
                    yield f"data: {line}\n\n"
                except queue.Empty:
                    yield ": keepalive\n\n"
                await asyncio.sleep(0.3)

        return StreamingResponse(_generate(), media_type="text/event-stream")

    @app.get("/api/session/summary")
    def session_summary() -> dict:
        return {
            "success": True,
            "graphs": list(state.graphs.keys()),
            "systems": list(state.systems.keys()),
            "mapper_counts": {
                "phase": len(state.phase_mappers),
                "voltage": len(state.voltage_mappers),
                "equipment": len(state.equipment_mappers),
            },
        }

    static_dir = Path(__file__).parent / "static"
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="ui")
    return app


app = create_app()
