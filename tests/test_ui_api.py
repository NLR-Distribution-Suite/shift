import pytest

fastapi = pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

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


def test_ui_api_session_summary(client: TestClient):
    response = client.get("/api/session/summary")
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert isinstance(body["graphs"], list)
