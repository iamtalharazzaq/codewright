from fastapi.testclient import TestClient

from app.main import app


def login(client: TestClient) -> dict[str, str]:
    client.post("/api/auth/register", json={"email": "a@example.com", "name": "A", "password": "long-password"})
    token = client.post("/api/auth/login", json={"email": "a@example.com", "password": "long-password"}).json()
    return {"Authorization": f"Bearer {token['access_token']}"}


def test_notes_need_a_login() -> None:
    with TestClient(app) as client:
        assert client.get("/api/notes").status_code == 401


def test_create_read_update_delete() -> None:
    with TestClient(app) as client:
        auth = login(client)
        note = client.post("/api/notes", json={"title": "Plan", "body": "one two", "tags": ["b", "a", "b"]}, headers=auth)
        assert note.status_code == 201 and note.json()["tags"] == ["a", "b"]
        nid = note.json()["id"]
        assert client.patch(f"/api/notes/{nid}", json={"title": "Plan 2"}, headers=auth).json()["title"] == "Plan 2"
        assert client.get("/api/notes/stats/summary", headers=auth).json()["average_words"] == 2.0
        assert client.delete(f"/api/notes/{nid}", headers=auth).status_code == 204
        assert client.get(f"/api/notes/{nid}", headers=auth).status_code == 404
