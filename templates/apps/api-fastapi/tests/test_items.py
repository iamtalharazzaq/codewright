from fastapi.testclient import TestClient

from {{name_snake}}.main import app
from {{name_snake}}.store import MemoryStore


def client() -> TestClient:
    app.state.store = MemoryStore()  # every test starts empty
    return TestClient(app)


def test_health() -> None:
    assert client().get("/health").json() == {"status": "ok"}


def test_crud_roundtrip() -> None:
    c = client()
    created = c.post("/api/items", json={"name": " Buy milk "})
    assert created.status_code == 201
    assert created.json() == {"id": 1, "name": "Buy milk", "done": False}
    assert c.put("/api/items/1", json={"name": "Buy milk", "done": True}).json()["done"] is True
    assert [i["id"] for i in c.get("/api/items").json()] == [1]
    assert c.delete("/api/items/1").status_code == 204
    assert c.get("/api/items/1").status_code == 404


def test_validation() -> None:
    c = client()
    assert c.post("/api/items", json={"name": ""}).status_code == 422
    assert c.get("/api/items/abc").status_code == 422
    assert c.delete("/api/items/99").status_code == 404
