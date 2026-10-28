"""Language Packs (Phase 5): golden tests on a fixture per pack, plus the shared pieces (reports, compose, templates,
client stubs, the unsupported-language check, the no-production guard)."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from agent.language_packs import PACKS, detect_project, pack, reports, templates, unsupported_project
from agent.language_packs import compose as compose_mod
from agent.language_packs.base import Component, Contract, ServiceSpec
from agent.language_packs.executor import (
    copy_samples,
    exclude_from_git,
    job_spec,
    migrations,
    plan,
    production_like,
)
from agent.language_packs.node import jest_json
from agent.tests.language_packs.golden import EXPECTED, FIXTURES, snapshot

FIXTURE_PACK = {
    "python_fastapi": "python",
    "go_gin": "go",
    "ts_next": "typescript",
    "js_express": "javascript",
    "cpp_cmake": "cpp",
}


def test_exactly_five_packs() -> None:
    assert sorted(PACKS) == ["cpp", "go", "javascript", "python", "typescript"]


@pytest.mark.parametrize("fixture", sorted(FIXTURE_PACK))
def test_golden(fixture: str) -> None:
    """Detection, framework parsing, build/test/lint plans and the run spec match the reviewed snapshot."""
    expected = json.loads((EXPECTED / f"{fixture}.json").read_text(encoding="utf-8"))
    assert snapshot(fixture) == expected, "pack output changed: run `python -m agent.tests.language_packs.golden`"
    assert [c["component"]["pack"] for c in expected["components"]] == [FIXTURE_PACK[fixture]]


def _labels(fixture: str, kind: str) -> list[str]:
    graph = snapshot(fixture)["components"][0]["graph"]
    return sorted(n["label"] for n in graph["nodes"] if n["kind"] == kind)


def test_framework_meaning() -> None:
    # spot checks that make the golden files readable: prefixes are followed through routers and groups
    assert _labels("go_gin", "route") == ["GET /api/v1/users/:id", "GET /health", "POST /api/v1/users"]
    assert _labels("go_gin", "model") == ["User"]  # the DTO without gorm tags isn't a model
    assert _labels("python_fastapi", "route") == ["GET /api/orders/{order_id}", "GET /health", "POST /api/orders"]
    assert _labels("python_fastapi", "model") == ["Order"]
    assert _labels("js_express", "route") == ["DELETE /todos/:id", "GET /health", "GET /todos", "POST /todos"]
    assert _labels("ts_next", "page") == ["/", "/about", "/pricing"]  # (marketing) route group dropped
    assert _labels("ts_next", "route") == ["ANY /api/items"]
    assert _labels("cpp_cmake", "target") == ["calc", "calc_core", "calc_tests"]


def test_mixed_project(tmp_path: Path) -> None:
    """A Go backend with a TypeScript frontend: two components, each with its own pack."""
    shutil.copytree(FIXTURES / "go_gin", tmp_path, dirs_exist_ok=True)
    shutil.copytree(FIXTURES / "ts_next", tmp_path / "web")
    found = [(c.pack, c.path, c.kind) for c in detect_project(tmp_path)]
    assert found == [("go", ".", "api"), ("typescript", "web", "web")]


def test_javascript_vs_typescript(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"name": "x", "dependencies": {"react": "19.3.0", "vite": "8.3.4"}}')
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.jsx").write_text("export default function App() { return null; }")
    assert [c.pack for c in detect_project(tmp_path)] == ["javascript"]
    (tmp_path / "tsconfig.json").write_text("{}")
    assert [c.pack for c in detect_project(tmp_path)] == ["typescript"]


def test_dependency_folders_are_skipped(tmp_path: Path) -> None:
    shutil.copytree(FIXTURES / "js_express", tmp_path, dirs_exist_ok=True)
    nested = tmp_path / "node_modules" / "express"
    nested.mkdir(parents=True)
    (nested / "package.json").write_text('{"name": "express"}')
    assert [c.path for c in detect_project(tmp_path)] == ["."]


# ── reports ──────────────────────────────────────────────────────────────────
def test_junit_report(tmp_path: Path) -> None:
    xml = tmp_path / "junit.xml"
    xml.write_text(
        """<?xml version="1.0"?><testsuites><testsuite name="s">
        <testcase classname="t.a" name="ok"/>
        <testcase classname="t.a" name="bad"><failure message="assert 1 == 2">trace</failure></testcase>
        <testcase classname="t.b" name="later"><skipped/></testcase>
        <testcase classname="t.b" name="boom"><error message="ImportError"/></testcase>
        </testsuite></testsuites>"""
    )
    r = reports.junit([xml, tmp_path / "missing.xml"], "pytest")
    assert (r.passed, r.failed, r.skipped, r.errors, r.total, r.ok) == (1, 1, 1, 1, 4, False)
    assert r.cases[0].name == "t.a::bad" and r.cases[0].message == "assert 1 == 2"  # failures first


def test_junit_refuses_entities(tmp_path: Path) -> None:
    xml = tmp_path / "junit.xml"
    xml.write_text('<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "a">]><testsuite><testcase name="&a;"/></testsuite>')
    assert not reports.junit([xml], "pytest").found


def test_go_json_report() -> None:
    lines = [
        {"Action": "run", "Package": "p/a", "Test": "TestOK"},
        {"Action": "pass", "Package": "p/a", "Test": "TestOK"},
        {"Action": "pass", "Package": "p/a", "Test": "TestOK/sub"},
        {"Action": "output", "Package": "p/a", "Test": "TestBad", "Output": "    a_test.go:9: want 2\n"},
        {"Action": "fail", "Package": "p/a", "Test": "TestBad"},
        {"Action": "skip", "Package": "p/a", "Test": "TestLater"},
        {"Action": "fail", "Package": "p/a"},
        {"Action": "output", "Package": "p/broken", "Output": "broken.go:3: undefined: x\n"},
        {"Action": "fail", "Package": "p/broken"},
    ]
    r = reports.go_json("\n".join(json.dumps(x) for x in lines) + "\nnot json\n")
    assert (r.passed, r.failed, r.skipped, r.errors) == (1, 1, 1, 1)
    assert "want 2" in next(c.message for c in r.cases if c.status == "failed")
    assert "undefined: x" in next(c.message for c in r.cases if c.status == "error")


def test_jest_report(tmp_path: Path) -> None:
    data = {
        "testResults": [
            {
                "name": "a.test.js",
                "assertionResults": [
                    {"fullName": "adds", "status": "passed"},
                    {"fullName": "subtracts", "status": "failed", "failureMessages": ["expected 1"]},
                    {"fullName": "later", "status": "pending"},
                ],
            }
        ]
    }
    (tmp_path / "jest.json").write_text(json.dumps(data))
    r = jest_json(tmp_path / "jest.json")
    assert (r.passed, r.failed, r.skipped) == (1, 1, 1)
    assert not jest_json(tmp_path / "none.json").found


# ── compose, samples, migrations, guards ─────────────────────────────────────
def test_compose_sidecars_and_env() -> None:
    cf = compose_mod.find(FIXTURES / "python_fastapi")
    assert cf is not None
    assert [(s.name, s.image) for s in cf.services] == [("db", "postgres:16-alpine")]
    assert cf.skipped == ["mailhog/mailhog"]  # not an allowed sidecar image
    app = compose_mod.app_for(cf, ".")
    assert app and app.env["DATABASE_URL"] == "postgresql://app:secret@db:5432/shop" and app.port == 8000


def test_compose_never_reads_the_host_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DB_PASSWORD", "from-the-host")
    assert compose_mod.substitute("${DB_PASSWORD:-secret} $DB_PASSWORD ${DB_PASSWORD}") == "secret  "


def test_production_guard() -> None:
    env = {
        "DATABASE_URL": "postgres://u:p@db:5432/x",
        "CACHE": "redis://localhost:6379",
        "PROD": "postgresql://u:p@prod-db.internal.example.com/x",
        "API": "https://api.example.com",  # an HTTP API isn't a database
    }
    assert production_like(env, ["db"]) == ["PROD → prod-db.internal.example.com"]


def test_sample_configs_and_migrations(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)  # noqa: S603, S607
    (tmp_path / "config.sample.yaml").write_text("port: 1")
    (tmp_path / ".env.example").write_text("A=1")
    (tmp_path / "settings.example.json").write_text("{}")
    (tmp_path / "settings.json").write_text("{}")  # already there: left alone
    (tmp_path / "migrations").mkdir()
    for name in ("0002_b.up.sql", "0001_a.up.sql", "0001_a.down.sql"):
        (tmp_path / "migrations" / name).write_text("select 1;")
    c = Component("go", ".", "api")
    assert copy_samples(tmp_path, c) == [".env.example → .env", "config.sample.yaml → config.yaml"]
    assert (tmp_path / "config.yaml").read_text() == "port: 1"
    exclude_from_git(tmp_path)
    exclude = (tmp_path / ".git" / "info" / "exclude").read_text().split()
    assert {"/config.yaml", "/.env", ".codewright/", "node_modules/", ".venv/"} <= set(exclude)
    assert [m.name for m in migrations(tmp_path, c)] == ["0001_a.up.sql", "0002_b.up.sql"]


def test_unsupported_project() -> None:
    assert unsupported_project({"Java": 120, "SQL": 10}) == ("Java", ["Go", "TypeScript"])
    assert unsupported_project({"PHP": 40, "JavaScript": 5}) == ("PHP", ["TypeScript", "Python"])
    assert unsupported_project({"Go": 100, "Java": 10}) is None
    assert unsupported_project({"Java": 50, "TypeScript": 40}) is None  # a real supported part to work on
    assert unsupported_project({}) is None


def test_go_test_report_is_kept_in_a_file() -> None:
    step = pack("go").test_steps(FIXTURES / "go_gin", detect_project(FIXTURES / "go_gin")[0])[0]
    spec = job_spec(step)
    assert spec["network"] == "none" and spec["cmd"][0] == "bash"
    assert "set -o pipefail" in spec["cmd"][2] and "tee .codewright/reports/go-test.json" in spec["cmd"][2]


def test_tests_run_offline() -> None:
    for fixture in FIXTURE_PACK:
        repo = FIXTURES / fixture
        c = detect_project(repo)[0]
        steps = plan(repo, c, "test")
        assert steps[-1].network == "none", fixture
        assert steps[0].name in {"install", "configure"}, fixture


# ── templates ────────────────────────────────────────────────────────────────
TEMPLATE_PACK = {
    "cli-python": ("python", "cli"),
    "api-go": ("go", "api"),
    "web-react-ts": ("typescript", "web"),
    "web-react-js": ("javascript", "web"),
    "cli-cpp": ("cpp", "cli"),
}


def test_one_template_per_language() -> None:
    found = {t.name: t.pack for t in templates.available()}
    assert found == {name: p for name, (p, _) in TEMPLATE_PACK.items()}


@pytest.mark.parametrize("name", sorted(TEMPLATE_PACK))
def test_scaffold(name: str, tmp_path: Path) -> None:
    out = tmp_path / "out"
    pack(TEMPLATE_PACK[name][0]).scaffold_service(ServiceSpec("Todo Keeper", name, "Keeps todos", 8099), out)
    files = [p for p in out.rglob("*") if p.is_file()]
    leftovers = [str(p.relative_to(out)) for p in files if re.search(r"\{\{\w+\}\}", p.read_text(encoding="utf-8"))]
    leftovers += [str(p.relative_to(out)) for p in files if "{{" in str(p)]
    assert not leftovers, f"unfilled placeholders in {leftovers}"
    for required in ("GUIDE.md", "GRAPHIFY.md", "mcp.example.json", ".github/workflows/ci.yml"):
        assert (out / required).is_file(), required
    assert "graphify update" in (out / ".github/workflows/ci.yml").read_text()
    assert not (out / "manifest.yaml").exists()
    [component] = detect_project(out)
    assert (component.pack, component.kind) == TEMPLATE_PACK[name]
    assert pack(component.pack).run_spec(out, component) is not None
    assert "Todo Keeper" in (out / "GUIDE.md").read_text()


def test_scaffold_refuses_a_non_empty_folder(tmp_path: Path) -> None:
    (tmp_path / "keep.txt").write_text("mine")
    with pytest.raises(FileExistsError):
        templates.scaffold(ServiceSpec("x", "api-go"), tmp_path)


# ── generators ───────────────────────────────────────────────────────────────
CONTRACT = Contract.from_openapi(
    {
        "servers": [{"url": "http://orders:8080"}],
        "paths": {
            "/orders": {
                "post": {
                    "operationId": "createOrder",
                    "requestBody": {"content": {"application/json": {"schema": {"$ref": "#/c/s/NewOrder"}}}},
                    "responses": {"201": {"content": {"application/json": {"schema": {"$ref": "#/c/s/Order"}}}}},
                }
            },
            "/orders/{id}": {"get": {"responses": {"200": {}}}, "parameters": []},
        },
    },
    "orders",
)


def test_contract_from_openapi() -> None:
    assert [(e.method, e.path, e.name, e.request, e.response) for e in CONTRACT.endpoints] == [
        ("POST", "/orders", "createOrder", "NewOrder", "Order"),
        ("GET", "/orders/{id}", "getOrdersId", None, None),
    ]


@pytest.mark.parametrize("name", sorted(PACKS))
def test_client_stub(name: str, tmp_path: Path) -> None:
    path = pack(name).client_stub(CONTRACT, tmp_path)
    text = path.read_text()
    assert "http://orders:8080" in text or name == "cpp"
    assert re.search(r"createOrder|create_order", text, re.I) and re.search(r"getOrdersId|get_orders_id", text, re.I)
    if name == "python":
        compile(text, str(path), "exec")


@pytest.mark.parametrize("name", sorted(PACKS))
def test_docker_and_instrumentation(name: str) -> None:
    p = pack(name)
    assert p.docker_base().dockerfile.startswith("FROM ")
    assert p.instrumentation().env["OTEL_EXPORTER_OTLP_ENDPOINT"].startswith("http://")
