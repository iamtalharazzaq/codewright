from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from tests.conftest import AppFactory

FILES = {
    "shop/user.py": "class User:\n    def __init__(self, name):\n        self.name = name\n",
    "shop/order.py": "from shop.user import User\n\ndef place_order(name):\n    return User(name)\n",
    "billing/payment.py": (
        "from shop.order import place_order\n\ndef pay_invoice(name):\n    return place_order(name)\n"
    ),
}


def _graph(client: TestClient, project_id: str, versions: int) -> dict[str, Any]:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        data: dict[str, Any] = client.get(f"/api/projects/{project_id}/graph").json()
        if len(data["versions"]) >= versions and not data["building"]:
            return data
        time.sleep(0.1)
    raise AssertionError(f"no graph version {versions}: {data}")


def test_graph_builds_updates_and_searches(app_factory: AppFactory, tmp_path: Path) -> None:
    with app_factory() as client:
        project = client.post("/api/projects", data={"kind": "empty", "name": "shop"}).json()
        work = tmp_path / "workspaces" / project["id"] / "work"
        for rel, text in list(FILES.items())[:2]:
            (work / rel).parent.mkdir(parents=True, exist_ok=True)
            (work / rel).write_text(text)
        assert client.post(f"/api/projects/{project['id']}/graph", json={"paths": ["shop/user.py"]}).status_code == 202

        first = _graph(client, project["id"], 1)
        assert [n["id"] for n in first["graph"]["nodes"]] == ["shop"]

        # A file in a new module: a new version where it shows as added, linked to the old one.
        (work / "billing").mkdir()
        (work / "billing" / "payment.py").write_text(FILES["billing/payment.py"])
        client.post(f"/api/projects/{project['id']}/graph", json={"paths": ["billing/payment.py"]})
        second = _graph(client, project["id"], 2)
        assert second["versions"][-1]["diff"]["added"] == ["billing"]
        assert [(e["source"], e["target"]) for e in second["graph"]["edges"]] == [("billing", "shop")]
        assert client.get(f"/api/projects/{project['id']}/graph?version=1").json()["graph"]["nodes"][0]["id"] == "shop"

        answer = client.get(f"/api/projects/{project['id']}/graph/ask", params={"explain": "place_order()"}).json()
        assert "place_order" in answer["answer"]

        hits = client.get(f"/api/projects/{project['id']}/search", params={"q": "pay invoice"}).json()
        assert hits[0]["path"] == "billing/payment.py"
        assert hits[0]["match"] == "keyword"  # no embedding server in tests


def test_graph_of_unknown_project(app_factory: AppFactory) -> None:
    with app_factory() as client:
        assert client.get("/api/projects/00000000-0000-0000-0000-000000000000/graph").status_code == 404
