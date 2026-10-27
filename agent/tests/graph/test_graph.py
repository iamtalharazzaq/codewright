from __future__ import annotations

from pathlib import Path

import pytest

from agent.graphify import GraphStore
from agent.knowledge_graph import diff, enrich, hygiene, module_graph, module_of
from agent.tools.code_search import Embedder, chunk_tree
from agent.tools.workspace import Workspace, git

GH_TOKEN = "ghp_" + "C" * 36


def test_module_of() -> None:
    assert module_of("internal/order/service/order.go") == "internal/order"
    assert module_of("pkg/redis/redis.go") == "pkg/redis"
    assert module_of("web/src/App.tsx") == "web"
    assert module_of("main.go") == "(root)"
    assert module_of("node_modules/x/index.js") is None
    assert module_of(".github/workflows/ci.yml") is None


RAW = {
    "nodes": [
        {"id": "o", "file_type": "code", "source_file": "internal/order/order.go"},
        {"id": "o2", "file_type": "code", "source_file": "internal/order/repo.go"},
        {"id": "u", "file_type": "code", "source_file": "internal/user/user.go"},
        {"id": "n", "file_type": "code", "source_file": "internal/notification/notify.go"},
        {"id": "doc", "file_type": "document", "source_file": "README.md"},
    ],
    "links": [
        {"source": "o", "target": "u", "relation": "calls", "confidence": "EXTRACTED"},
        {"source": "o", "target": "u", "relation": "references", "confidence": "EXTRACTED"},
        {"source": "o", "target": "n", "relation": "imports_from", "confidence": "INFERRED"},
        {"source": "o", "target": "o2", "relation": "calls"},  # inside a module: not an edge
        {"source": "o", "target": "u", "relation": "contains"},  # structural: ignored
    ],
}


def test_module_graph_groups_symbols_and_counts_dependencies() -> None:
    graph = module_graph(RAW)
    assert [n["id"] for n in graph["nodes"]] == ["internal/notification", "internal/order", "internal/user"]
    order = next(n for n in graph["nodes"] if n["id"] == "internal/order")
    assert order["file_count"] == 2 and order["languages"] == {"Go": 2}
    edges = {(e["source"], e["target"]): e for e in graph["edges"]}
    assert set(edges) == {("internal/order", "internal/user"), ("internal/order", "internal/notification")}
    assert edges[("internal/order", "internal/user")]["weight"] == 2
    assert edges[("internal/order", "internal/notification")]["sources"][0]["confidence"] == "INFERRED"


def test_diff_marks_new_changed_and_removed() -> None:
    before = module_graph(RAW)
    raw2 = {
        "nodes": [
            *[n for n in RAW["nodes"] if n["id"] != "n"],
            {"id": "o3", "file_type": "code", "source_file": "internal/order/new.go"},
            {"id": "p", "file_type": "code", "source_file": "internal/payment/pay.go"},
        ],
        "links": [*RAW["links"][:2], {"source": "p", "target": "o", "relation": "calls"}],
    }
    d = diff(before, module_graph(raw2))
    assert d["added"] == ["internal/payment"]
    assert d["changed"] == ["internal/order"]
    assert d["removed"] == ["internal/notification"]
    assert d["edges_added"] == ["internal/payment->internal/order"]
    assert d["edges_removed"] == ["internal/order->internal/notification"]
    assert diff(None, before)["added"] == [n["id"] for n in before["nodes"]]


def test_enrich_adds_git_cochange(tmp_path: Path) -> None:
    ws = Workspace(tmp_path, "p")
    ws.create()
    git(ws.work, "init", "-q", "-b", "main")
    for i in range(3):
        for mod in ("internal/order", "internal/user"):
            (ws.work / mod).mkdir(parents=True, exist_ok=True)
            (ws.work / mod / "x.go").write_text(f"package x // {i}\n")
        ws.commit_all(f"change {i}")
    graph = enrich(module_graph(RAW), ws.work)
    edge = next(e for e in graph["edges"] if {e["source"], e["target"]} == {"internal/order", "internal/user"})
    assert {"source": "git_cochange", "confidence": 0.3, "commits": 3} in edge["sources"]


def test_hygiene_reports_isolated_and_mutual(tmp_path: Path) -> None:
    (tmp_path / "internal" / "order").mkdir(parents=True)
    (tmp_path / "internal" / "order" / "order.go").write_text("package order\n")
    (tmp_path / "internal" / "order" / "empty.go").write_text("")
    graph = module_graph(RAW)
    graph["edges"].append({"source": "internal/user", "target": "internal/order", "weight": 1, "sources": []})
    report = hygiene(RAW, graph, tmp_path)
    assert report["files_without_symbols"] == ["internal/order/empty.go"]
    assert report["mutual_dependencies"] == ["internal/order <-> internal/user"]
    assert report["isolated_modules"] == []


@pytest.fixture
def fixture_project(tmp_path: Path) -> Path:
    """A tiny shop: order uses user and notification; payment uses order."""
    work = tmp_path / "work"
    files = {
        "shop/user.py": "class User:\n    def __init__(self, name):\n        self.name = name\n",
        "shop/notification.py": "def notify(user, text):\n    return f'{user.name}: {text}'\n",
        "shop/order.py": (
            "from shop.user import User\nfrom shop.notification import notify\n\n"
            "def place_order(name):\n    user = User(name)\n    return notify(user, 'order placed')\n"
        ),
        "shop/payment.py": "from shop.order import place_order\n\ndef pay(name):\n    return place_order(name)\n",
    }
    for rel, text in files.items():
        (work / rel).parent.mkdir(parents=True, exist_ok=True)
        (work / rel).write_text(text)
    return work


def test_graphify_build_versions_and_queries(fixture_project: Path, tmp_path: Path) -> None:
    store = GraphStore(tmp_path / "graph")
    v1 = store.build(fixture_project, "import")
    assert v1.number == 1 and v1.nodes > 0
    assert store.raw.exists() and store.modules() is not None
    assert store.build(fixture_project).number == 1  # nothing changed: no new version

    explained = store.explain("place_order()")
    assert "place_order" in explained and "notify" in explained
    path = store.path("pay()", "notify()")
    assert "place_order" in path

    (fixture_project / "shop" / "refund.py").write_text(
        "from shop.payment import pay\n\ndef refund(n):\n    return pay(n)\n"
    )
    v2 = store.build(fixture_project, "build")
    assert v2.number == 2
    assert v2.diff["changed"] == ["shop"]
    assert [v["number"] for v in store.versions()] == [1, 2]


def test_chunks_are_masked_and_skip_vendored(tmp_path: Path) -> None:
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "main.py").write_text("\n".join(f"line {i}" for i in range(130)) + f"\nTOKEN='{GH_TOKEN}'\n")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "x.js").write_text("x")
    chunks = chunk_tree(tmp_path)
    assert [(c.path, c.start_line, c.end_line) for c in chunks] == [
        ("app/main.py", 1, 60),
        ("app/main.py", 61, 120),
        ("app/main.py", 121, 131),
    ]
    assert GH_TOKEN not in chunks[-1].content


async def test_embedder_without_a_server_turns_itself_off() -> None:
    embedder = Embedder("http://127.0.0.1:9/v1", "m", 4)
    assert await embedder.embed(["hello"]) is None
    assert embedder.available is False
    assert await Embedder(None, "m", 4).embed(["x"]) is None
