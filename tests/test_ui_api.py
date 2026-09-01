import pytest
import importlib

fastapi = pytest.importorskip("fastapi")

from fastapi.testclient import TestClient
from infrasys import Location

from shift.ui_api.app import create_app


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def test_ui_api_health(client: TestClient):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_ui_api_options(client: TestClient):
    response = client.get("/api/options")
    assert response.status_code == 200
    body = response.json()
    assert "network_types" in body
    assert "routing_strategies" in body
    assert "secondary_strategies" in body
    assert "cluster_balance_modes" in body
    assert "balanced" in body["cluster_balance_modes"]
    assert "unbalanced" in body["cluster_balance_modes"]
    assert "AutoDensitySecondaryStrategy" in body["secondary_strategies"]


def test_ui_api_session_summary(client: TestClient):
    response = client.get("/api/session/summary")
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert isinstance(body["graphs"], list)


def test_ui_api_area_aware_clusters(client: TestClient):
    payload = {
        "strategy": "area_aware",
        "num_clusters": 2,
        "target_area_per_transformer_m2": 8000,
        "dedicated_transformer_area_m2": 5000,
        "parcels": [
            {
                "name": "big",
                "geometry": [
                    {"longitude": -97.3000, "latitude": 32.7500},
                    {"longitude": -97.3000, "latitude": 32.7510},
                    {"longitude": -97.2990, "latitude": 32.7510},
                    {"longitude": -97.2990, "latitude": 32.7500},
                ],
            },
            {
                "name": "small-1",
                "geometry": [
                    {"longitude": -97.3050, "latitude": 32.7550},
                    {"longitude": -97.3050, "latitude": 32.7552},
                    {"longitude": -97.3048, "latitude": 32.7552},
                    {"longitude": -97.3048, "latitude": 32.7550},
                ],
            },
            {
                "name": "small-2",
                "geometry": [
                    {"longitude": -97.3060, "latitude": 32.7560},
                    {"longitude": -97.3060, "latitude": 32.7562},
                    {"longitude": -97.3058, "latitude": 32.7562},
                    {"longitude": -97.3058, "latitude": 32.7560},
                ],
            },
        ],
    }
    response = client.post("/api/clusters/build", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["strategy"] == "area_aware"
    assert body["uses_num_clusters"] is False
    assert "strategy_details" in body
    assert body["strategy_details"]["area_aware_num_clusters_input_used"] is False
    assert body["count"] >= 2


def test_ui_api_area_aware_num_clusters_ignored(client: TestClient):
    base_payload = {
        "strategy": "area_aware",
        "target_area_per_transformer_m2": 8000,
        "dedicated_transformer_area_m2": 5000,
        "parcels": [
            {
                "name": "big",
                "geometry": [
                    {"longitude": -97.3000, "latitude": 32.7500},
                    {"longitude": -97.3000, "latitude": 32.7510},
                    {"longitude": -97.2990, "latitude": 32.7510},
                    {"longitude": -97.2990, "latitude": 32.7500},
                ],
            },
            {
                "name": "small-1",
                "geometry": [
                    {"longitude": -97.3050, "latitude": 32.7550},
                    {"longitude": -97.3050, "latitude": 32.7552},
                    {"longitude": -97.3048, "latitude": 32.7552},
                    {"longitude": -97.3048, "latitude": 32.7550},
                ],
            },
            {
                "name": "small-2",
                "geometry": [
                    {"longitude": -97.3060, "latitude": 32.7560},
                    {"longitude": -97.3060, "latitude": 32.7562},
                    {"longitude": -97.3058, "latitude": 32.7562},
                    {"longitude": -97.3058, "latitude": 32.7560},
                ],
            },
        ],
    }

    response_a = client.post("/api/clusters/build", json={**base_payload, "num_clusters": 1})
    response_b = client.post("/api/clusters/build", json={**base_payload, "num_clusters": 10})

    assert response_a.status_code == 200
    assert response_b.status_code == 200
    body_a = response_a.json()
    body_b = response_b.json()

    assert body_a["uses_num_clusters"] is False
    assert body_b["uses_num_clusters"] is False
    assert body_a["count"] == body_b["count"]


def test_ui_api_capacity_distance_clusters(client: TestClient):
    payload = {
        "strategy": "capacity_distance",
        "target_kva_per_transformer": 40,
        "dedicated_transformer_load_kva": 120,
        "max_secondary_length_m": 70,
        "parcels": [
            {
                "name": "ind-1",
                "building_type": "industrial",
                "geometry": [
                    {"longitude": -97.3100, "latitude": 32.7600},
                    {"longitude": -97.3100, "latitude": 32.7610},
                    {"longitude": -97.3090, "latitude": 32.7610},
                    {"longitude": -97.3090, "latitude": 32.7600},
                ],
            },
            {
                "name": "res-1",
                "building_type": "residential",
                "geometry": [
                    {"longitude": -97.3050, "latitude": 32.7550},
                    {"longitude": -97.3050, "latitude": 32.7552},
                    {"longitude": -97.3048, "latitude": 32.7552},
                    {"longitude": -97.3048, "latitude": 32.7550},
                ],
            },
            {
                "name": "res-2",
                "building_type": "residential",
                "geometry": [
                    {"longitude": -97.3065, "latitude": 32.7564},
                    {"longitude": -97.3065, "latitude": 32.7566},
                    {"longitude": -97.3063, "latitude": 32.7566},
                    {"longitude": -97.3063, "latitude": 32.7564},
                ],
            },
        ],
    }
    response = client.post("/api/clusters/build", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["strategy"] == "capacity_distance"
    assert body["count"] >= 2


def test_ui_api_auto_build_feeders(client: TestClient, monkeypatch):
    ui_app_module = importlib.import_module("shift.ui_api.app")

    class DummyBuilder:
        def __init__(
            self,
            groups,
            source_location,
            buffer,
            routing_strategy,
            secondary_strategy,
            **kwargs,
        ):
            self._groups = groups

        def get_distribution_graph(self):
            class DummyEdge:
                name = "e1"
                length = None

            class DummyNode:
                def __init__(self, name):
                    self.name = name
                    self.assets = set()
                    self.location = Location(x=-97.33, y=32.75)

            class DummyGraph:
                vsource_node = "src"

                def get_nodes(self):
                    return [DummyNode("src")]

                def get_edges(self):
                    return []

                def get_dfs_tree(self):
                    return self

            return DummyGraph()

    monkeypatch.setattr(ui_app_module, "PRSG", DummyBuilder)

    payload = {
        "parcels": [
            {
                "name": "p1",
                "geometry": [
                    {"longitude": -97.3000, "latitude": 32.7500},
                    {"longitude": -97.3000, "latitude": 32.7510},
                    {"longitude": -97.2990, "latitude": 32.7510},
                    {"longitude": -97.2990, "latitude": 32.7500},
                ],
            },
            {
                "name": "p2",
                "geometry": [
                    {"longitude": -97.3100, "latitude": 32.7600},
                    {"longitude": -97.3100, "latitude": 32.7610},
                    {"longitude": -97.3090, "latitude": 32.7610},
                    {"longitude": -97.3090, "latitude": 32.7600},
                ],
            },
        ],
        "polygon": [
            {"longitude": -97.315, "latitude": 32.745},
            {"longitude": -97.295, "latitude": 32.745},
            {"longitude": -97.295, "latitude": 32.765},
            {"longitude": -97.315, "latitude": 32.765},
        ],
        "min_feeders": 1,
        "max_feeders": 3,
        "target_parcels_per_feeder": 1,
        "parcels_per_transformer": 1,
    }
    response = client.post("/api/feeders/auto-build", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["estimated_feeder_count"] >= 1
    assert isinstance(body["feeders"], list)


def test_ui_api_graph_build_auto_density_selects_openstreet(client: TestClient, monkeypatch):
    ui_app_module = importlib.import_module("shift.ui_api.app")

    class DummyBuilder:
        captured_secondary = None

        def __init__(
            self,
            groups,
            source_location,
            buffer,
            routing_strategy,
            secondary_strategy,
            **kwargs,
        ):
            DummyBuilder.captured_secondary = type(secondary_strategy).__name__

        def get_distribution_graph(self):
            class DummyNode:
                def __init__(self, name):
                    self.name = name
                    self.assets = set()
                    self.location = Location(x=-97.33, y=32.75)

            class DummyGraph:
                vsource_node = "src"

                def get_nodes(self):
                    return [DummyNode("src")]

                def get_edges(self):
                    return []

                def get_dfs_tree(self):
                    return self

            return DummyGraph()

    monkeypatch.setattr(ui_app_module, "PRSG", DummyBuilder)

    payload = {
        "groups": [
            {
                "center": {"longitude": -97.33, "latitude": 32.75},
                "points": [
                    {"longitude": -97.3300, "latitude": 32.7500},
                    {"longitude": -97.3301, "latitude": 32.7501},
                    {"longitude": -97.3299, "latitude": 32.7501},
                    {"longitude": -97.3302, "latitude": 32.7500},
                    {"longitude": -97.3300, "latitude": 32.7502},
                ],
            }
        ],
        "source_location": {"longitude": -97.33, "latitude": 32.75},
        "polygon": [
            {"longitude": -97.331, "latitude": 32.7495},
            {"longitude": -97.329, "latitude": 32.7495},
            {"longitude": -97.329, "latitude": 32.7505},
            {"longitude": -97.331, "latitude": 32.7505},
        ],
        "secondary_strategy": "AutoDensitySecondaryStrategy",
        "auto_secondary_density_threshold_per_km2": 1.0,
    }

    response = client.post("/api/graph/build", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["secondary_strategy"] == "OpenStreetSecondaryStrategy"
    assert DummyBuilder.captured_secondary == "OpenStreetSecondaryStrategy"


def test_ui_api_graph_build_auto_density_selects_delaunay(client: TestClient, monkeypatch):
    ui_app_module = importlib.import_module("shift.ui_api.app")

    class DummyBuilder:
        captured_secondary = None

        def __init__(
            self,
            groups,
            source_location,
            buffer,
            routing_strategy,
            secondary_strategy,
            **kwargs,
        ):
            DummyBuilder.captured_secondary = type(secondary_strategy).__name__

        def get_distribution_graph(self):
            class DummyNode:
                def __init__(self, name):
                    self.name = name
                    self.assets = set()
                    self.location = Location(x=-97.33, y=32.75)

            class DummyGraph:
                vsource_node = "src"

                def get_nodes(self):
                    return [DummyNode("src")]

                def get_edges(self):
                    return []

                def get_dfs_tree(self):
                    return self

            return DummyGraph()

    monkeypatch.setattr(ui_app_module, "PRSG", DummyBuilder)

    payload = {
        "groups": [
            {
                "center": {"longitude": -97.33, "latitude": 32.75},
                "points": [
                    {"longitude": -97.40, "latitude": 32.70},
                    {"longitude": -97.20, "latitude": 32.70},
                    {"longitude": -97.20, "latitude": 32.90},
                    {"longitude": -97.40, "latitude": 32.90},
                    {"longitude": -97.30, "latitude": 32.80},
                ],
            }
        ],
        "source_location": {"longitude": -97.33, "latitude": 32.75},
        "secondary_strategy": "AutoDensitySecondaryStrategy",
        "auto_secondary_density_threshold_per_km2": 10000.0,
    }

    response = client.post("/api/graph/build", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["secondary_strategy"] == "DelaunayStrategy"
    assert DummyBuilder.captured_secondary == "DelaunayStrategy"


def test_ui_api_cluster_balance_mode_balanced(client: TestClient):
    payload = {
        "strategy": "kmeans_count",
        "balance_mode": "balanced",
        "num_clusters": 3,
        "points": [
            {"longitude": -97.33, "latitude": 32.75},
            {"longitude": -97.331, "latitude": 32.751},
            {"longitude": -97.332, "latitude": 32.752},
            {"longitude": -97.34, "latitude": 32.76},
            {"longitude": -97.341, "latitude": 32.761},
            {"longitude": -97.342, "latitude": 32.762},
            {"longitude": -97.35, "latitude": 32.77},
            {"longitude": -97.351, "latitude": 32.771},
            {"longitude": -97.352, "latitude": 32.772},
        ],
    }

    response = client.post("/api/clusters/build", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["balance_mode"] == "balanced"
    sizes = [len(cluster["points"]) for cluster in body["clusters"]]
    assert max(sizes) - min(sizes) <= 1
