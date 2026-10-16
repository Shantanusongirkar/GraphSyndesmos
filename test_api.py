
from fastapi.testclient import TestClient

from api import app

client = TestClient(app)


def test_health_returns_graph_node_count():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["graph_nodes"] > 0


def test_module_requires_name():
    response = client.get("/api/module")

    assert response.status_code == 422


def test_module_returns_expected_structure():
    response = client.get("/api/module", params={"name": "src"})

    assert response.status_code == 200

    data = response.json()
    assert data["module"] == "src"
    assert isinstance(data["results"], list)

    if data["results"]:
        first = data["results"][0]
        assert "file" in first
        assert "pull_requests" in first
        assert "contributors" in first
