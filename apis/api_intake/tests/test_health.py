from fastapi.testclient import TestClient

from app.main import create_app


def test_health_returns_200_with_dependency_statuses():
    client = TestClient(create_app())
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] in {"ok", "degraded"}
    assert set(body["dependencies"]) == {"postgres", "neo4j", "redis"}
    for status in body["dependencies"].values():
        assert status in {"ok", "unavailable", "not_configured"}


def test_health_degraded_when_dependencies_not_configured():
    client = TestClient(create_app())
    body = client.get("/health").json()
    if all(s == "not_configured" for s in body["dependencies"].values()):
        assert body["status"] == "degraded"
