from __future__ import annotations

from fastapi.testclient import TestClient

from monoshift_api import __version__


def test_liveness(client: TestClient) -> None:
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok", "version": __version__}


def test_readiness_reports_unreachable_database(client: TestClient) -> None:
    # conftest points MONOSHIFT_DATABASE_URL at a closed port.
    res = client.get("/api/health/ready")
    assert res.status_code == 503
    body = res.json()
    assert body["status"] == "unavailable"
    assert body["checks"]["database"] == "error"
    assert body["checks"]["run_manager"] == "unavailable"


def test_openapi_is_served_under_api(client: TestClient) -> None:
    assert client.get("/api/openapi.json").status_code == 200
