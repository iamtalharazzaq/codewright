from fastapi.testclient import TestClient

from app.main import app
from app.repo import MemoryRepo
from app.security import make_token, read_token


def client() -> TestClient:
    app.state.repo = MemoryRepo()  # every test starts empty
    return TestClient(app)


def sign_up(c: TestClient, email: str) -> dict[str, str]:
    res = c.post("/api/auth/register", json={"email": email, "password": "password123"})
    assert res.status_code == 201
    return {"Authorization": f"Bearer {res.json()['token']}"}


def test_health() -> None:
    assert client().get("/health").json() == {"status": "ok"}


def test_register_login_and_me() -> None:
    c = client()
    headers = sign_up(c, "Ada@example.com")
    assert c.get("/api/me", headers=headers).json()["email"] == "ada@example.com"
    assert c.post("/api/auth/login", json={"email": "ada@example.com", "password": "password123"}).status_code == 200
    assert c.post("/api/auth/login", json={"email": "ada@example.com", "password": "wrong-password"}).status_code == 401
    dup = c.post("/api/auth/register", json={"email": "ada@example.com", "password": "password123"})
    assert dup.status_code == 409


def test_items_need_a_token_and_belong_to_their_owner() -> None:
    c = client()
    assert c.get("/api/items").status_code == 401
    ada, bob = sign_up(c, "ada@example.com"), sign_up(c, "bob@example.com")
    created = c.post("/api/items", json={"name": " Buy milk "}, headers=ada)
    assert created.status_code == 201 and created.json()["name"] == "Buy milk"
    item_id = created.json()["id"]
    assert c.get("/api/items", headers=bob).json() == []
    assert c.put(f"/api/items/{item_id}", json={"name": "x"}, headers=bob).status_code == 404
    assert c.put(f"/api/items/{item_id}", json={"name": "Buy milk", "done": True}, headers=ada).json()["done"] is True
    assert c.delete(f"/api/items/{item_id}", headers=bob).status_code == 404
    assert c.delete(f"/api/items/{item_id}", headers=ada).status_code == 204


def test_only_the_first_user_is_admin() -> None:
    c = client()
    ada, bob = sign_up(c, "ada@example.com"), sign_up(c, "bob@example.com")
    assert [u["email"] for u in c.get("/api/admin/users", headers=ada).json()] == ["ada@example.com", "bob@example.com"]
    assert c.get("/api/admin/users", headers=bob).status_code == 403


def test_tokens_expire_and_cannot_be_forged() -> None:
    token = make_token("s3cret", 7, now=1_000.0)
    assert read_token("s3cret", token, now=1_001.0) == 7
    assert read_token("s3cret", token, now=1_000.0 + 8 * 24 * 3600) is None
    assert read_token("other", token, now=1_001.0) is None
    assert read_token("s3cret", "garbage") is None
