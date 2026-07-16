from __future__ import annotations

from pathlib import Path
import tempfile

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from gdm.quantities import ApparentPower, Voltage
from infrasys import Location
from infrasys.quantities import Distance

from shift.data_model import GeoLocation, GroupModel, TransformerPhaseMapperModel, TransformerTypes
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
    BuildSystemRequest,
    ClusterRequest,
    ConfigureEquipmentMapperRequest,
    ConfigurePhaseMapperRequest,
    ConfigureVoltageMapperRequest,
    ExportSystemRequest,
    FetchParcelsRequest,
    GraphBuildRequest,
    NetworkTypeName,
    RoutingStrategyName,
    SecondaryStrategyName,
    StrategyCompareRequest,
)
from shift.ui_api.state import UiSessionState
from shift.utils.get_cluster import get_kmeans_clusters


def _graph_metrics(graph) -> dict[str, float | int]:
    total_length_m = 0.0
    for _, _, edge in graph.get_edges():
        if edge.length is not None:
            total_length_m += float(edge.length.to("m").magnitude)

    transformers = 0
    loads = 0
    for node in graph.get_nodes():
        assets = node.assets or set()
        for asset in assets:
            name = getattr(asset, "__name__", str(asset))
            if name == "DistributionLoad":
                loads += 1
        if node.name.endswith("_ht"):
            transformers += 1

    return {
        "node_count": len(list(graph.get_nodes())),
        "edge_count": len(list(graph.get_edges())),
        "total_length_m": round(total_length_m, 2),
        "transformer_hint_count": transformers,
        "load_node_count": loads,
    }


def _resolve_strategies(payload: GraphBuildRequest):
    network_presets = {
        NetworkTypeName.BALANCED_DEFAULT: (
            RoutingStrategyName.STEINER,
            SecondaryStrategyName.MESH_STEINER,
        ),
        NetworkTypeName.ROAD_OPTIMIZED: (
            RoutingStrategyName.WEIGHTED_STEINER,
            SecondaryStrategyName.OPENSTREET,
        ),
        NetworkTypeName.FULL_ROAD_EXPLORATION: (
            RoutingStrategyName.FULL_ROAD,
            SecondaryStrategyName.HUB_LINE,
        ),
    }

    default_routing, default_secondary = network_presets[payload.network_type]
    routing_name = payload.routing_strategy or default_routing
    secondary_name = payload.secondary_strategy or default_secondary

    routing = {
        RoutingStrategyName.STEINER: SteinerTreeStrategy(),
        RoutingStrategyName.WEIGHTED_STEINER: WeightedSteinerTreeStrategy(),
        RoutingStrategyName.SHORTEST_PATH_TREE: ShortestPathTreeStrategy(),
        RoutingStrategyName.MIN_SPANNING_TREE: MinimumSpanningTreeStrategy(),
        RoutingStrategyName.FULL_ROAD: FullRoadGraphStrategy(),
    }[routing_name]

    secondary = {
        SecondaryStrategyName.MESH_STEINER: MeshSteinerStrategy(
            spacing=Distance(payload.secondary_mesh_spacing_meters, "m")
        ),
        SecondaryStrategyName.RADIAL: RadialStrategy(),
        SecondaryStrategyName.DELAUNAY: DelaunayStrategy(),
        SecondaryStrategyName.OPENSTREET: OpenStreetSecondaryStrategy(
            buffer=Distance(payload.secondary_buffer_meters, "m")
        ),
        SecondaryStrategyName.HUB_LINE: HubLineStrategy(),
    }[secondary_name]

    return routing_name.value, secondary_name.value, routing, secondary


def create_app() -> FastAPI:  # noqa: C901
    app = FastAPI(title="SHIFT UI API", version="0.1.0")
    state = UiSessionState()

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
            "routing_strategies": [x.value for x in RoutingStrategyName],
            "secondary_strategies": [x.value for x in SecondaryStrategyName],
            "phase_methods": ["agglomerative", "kmean", "greedy"],
            "transformer_types": [x.value for x in TransformerTypes],
        }

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
            if len(payload.points) < payload.num_clusters:
                raise ValueError("num_clusters must be <= number of points")
            points = [GeoLocation(p.longitude, p.latitude) for p in payload.points]
            clusters = get_kmeans_clusters(payload.num_clusters, points)
            return {
                "success": True,
                "count": len(clusters),
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

            routing_name, secondary_name, routing, secondary = _resolve_strategies(payload)

            builder = PRSG(
                groups=groups,
                source_location=source_location,
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
                    "network_type": payload.network_type.value,
                    "routing_strategy": routing_name,
                    "secondary_strategy": secondary_name,
                }
            )
            return {"success": True, "summary": summary}
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/graph/compare")
    def compare_graph_builds(payload: StrategyCompareRequest) -> dict:
        runs = []
        for idx, build in enumerate(payload.builds, start=1):
            result = build_graph(build)
            runs.append({"run": idx, **result["summary"]})
        return {"success": True, "runs": runs}

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
            catalog = DatasetSystem.from_json(Path(payload.catalog_path))
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
        return {
            "success": True,
            "system_name": payload.system_name,
            "output_path": str(out),
            "download_url": f"/api/system/{payload.system_name}/download",
        }

    @app.get("/api/system/{system_name}/download")
    def download_system(system_name: str):
        system = state.systems.get(system_name)
        if system is None:
            raise HTTPException(status_code=404, detail=f"Unknown system {system_name}")

        out = Path(tempfile.gettempdir()) / f"{system_name}.json"
        system.to_json(out)
        return FileResponse(
            path=out,
            filename=f"{system_name}.json",
            media_type="application/json",
        )

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
