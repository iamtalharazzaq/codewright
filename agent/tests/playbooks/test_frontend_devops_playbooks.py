"""Frontend (5.14) and DevOps (5.15) as whole runs with a fake sandbox, plus their pure parts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from agent.playbooks.devops import files as dev
from agent.playbooks.frontend import a11y, migrate
from agent.tests.conftest import FakeProject, FakeServices
from agent.tests.playbooks.helpers import approve_all, cfg, compiled, drive, gates_of, initial_state
from agent.tests.playbooks.test_code_playbooks import GREEN, repo
from agent.tools.workspace import git

VITE_PKG = {
    "name": "shop-ui",
    "scripts": {"dev": "vite", "build": "tsc && vite build", "preview": "vite preview"},
    "dependencies": {"react": "^18.3.0", "react-dom": "^18.3.0"},
    "devDependencies": {"vite": "^5.0.0", "@vitejs/plugin-react": "^4.0.0", "typescript": "^5.0.0"},
}
VITE_FILES = {
    "package.json": json.dumps(VITE_PKG),
    "tsconfig.json": json.dumps({"compilerOptions": {"jsx": "react-jsx"}, "include": ["src"]}),
    "vite.config.ts": "export default { server: { proxy: { '/api': 'http://localhost:8080' } } }\n",
    "index.html": '<html><head><title>Shop</title><meta name="description" content="A shop"></head><body><div id="root"></div></body></html>\n',  # noqa: E501
    "src/main.tsx": "import './index.css'\nimport App from './App'\nrender(<App />)\n",
    "src/App.tsx": 'export default function App() {\n  const u = import.meta.env.VITE_API_URL\n  return <img src="/a.png" />\n}\n',  # noqa: E501
    "src/index.css": ".btn { color: #777777; background: #888888; }\n:focus { outline: none; }\n",
    ".gitignore": "node_modules\n",
}


# ── accessibility ────────────────────────────────────────────────────────────
def test_contrast_is_computed_and_repaired() -> None:
    assert round(a11y.contrast("#000000", "#ffffff")) == 21
    better = a11y.readable("#777777", "#888888")
    assert a11y.contrast(better, "#888888") >= 4.5


def test_scan_finds_and_fixes_what_source_proves(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text('<html><head></head><body><img src="a.png"><input type="text"></body></html>')
    (tmp_path / "a.css").write_text(".b { color: #777; background: #888; }\n:focus { outline: none; }\n")
    changed, found = a11y.scan(tmp_path, fix=True)
    rules = {f.rule: f.fixed for f in found}
    assert rules == {
        "img-alt": True,
        "html-lang": True,
        "viewport": True,
        "control-name": False,
        "contrast": True,
        "focus-outline": True,
    }
    assert (
        'lang="en"' in changed["index.html"]
        and 'alt=""' in changed["index.html"]
        and "viewport" in changed["index.html"]
    )
    assert "#777" not in changed["a.css"]
    _, again = a11y.scan(tmp_path, fix=False)  # the scan itself changes nothing on disk
    assert {f.rule for f in again} >= {"img-alt", "contrast"}


# ── migration ────────────────────────────────────────────────────────────────
def _component(work: Path) -> Any:
    from agent.language_packs import detect_project

    return next(c for c in detect_project(work) if c.kind == "web")


def test_vite_app_becomes_next_with_the_app_kept_whole(tmp_path: Path) -> None:
    work = repo(tmp_path, VITE_FILES)
    m = migrate.migration(work, _component(work))
    ops = {o.path: o for o in m.operations}
    assert m.supported
    assert (
        ops["index.html"].content is None
        and ops["src/main.tsx"].content is None
        and ops["vite.config.ts"].content is None
    )
    pkg = json.loads(ops["package.json"].content or "")
    assert (
        pkg["scripts"]["build"] == "next build"
        and "next" in pkg["dependencies"]
        and "vite" not in pkg["devDependencies"]
    )
    layout = ops["src/app/layout.tsx"].content or ""
    assert 'title: "Shop"' in layout and "'../index.css'" in layout
    assert "import('../../App')" in (ops["src/app/[[...slug]]/client.tsx"].content or "")
    assert "process.env.NEXT_PUBLIC_API_URL" in (ops["src/App.tsx"].content or "")
    assert "destination: 'http://localhost:8080/api/:path*'" in (ops["next.config.mjs"].content or "")
    assert ".next" in (ops[".gitignore"].content or "")


def test_a_project_that_is_not_vite_is_not_guessed_at(tmp_path: Path) -> None:
    work = repo(
        tmp_path, {"package.json": json.dumps({"name": "x", "dependencies": {"react": "18"}}), "src/index.tsx": ""}
    )
    comps = [c for c in __import__("agent.language_packs", fromlist=["x"]).detect_project(work)]
    assert not migrate.can_migrate(comps[0])


async def test_frontend_migrates_modernizes_and_commits_each_stage(tmp_path: Path) -> None:
    work = repo(tmp_path, VITE_FILES)
    shots = {"screens": [{"ok": True, "error": None, "report": {"id": "s1", "summary": {"pages": 2, "changed": 0}}}]}
    project = FakeProject(work, verifications=shots, test_results=[[GREEN]])
    services = FakeServices(project=project)
    state, prompts = await drive(
        compiled("frontend", services),
        cfg(),
        initial_state("frontend", tmp_path, request="Move to Next.js and make the UI modern and accessible"),
        approve_all,
    )
    assert gates_of(prompts) == ["approve_plan", "approve_result"]
    assert state["stages"] == ["migrate", "modernize"], state["plan_brief"]
    assert [k for k, v in state["outcomes"].items() if v["done"]] == ["migrate", "modernize"]
    log = git(work, "log", "--format=%s", "-3")
    assert "Next.js" in log and "accessible UI" in log
    assert not (work / "index.html").exists() and (work / "src/codewright-modern.css").is_file()
    assert "codewright-modern.css" in (work / "src/app/layout.tsx").read_text(encoding="utf-8")
    assert 'lang="en"' in (work / "src/app/layout.tsx").read_text(encoding="utf-8")
    assert "Parity after the migration" in state["done_summary"] and "Before / after" in state["done_summary"]
    assert state["published"]["branch"].startswith("codewright/frontend-")


async def test_a_migration_that_stays_red_is_undone_exactly(tmp_path: Path) -> None:
    work = repo(tmp_path, VITE_FILES)

    class BuildFails(FakeProject):
        """The baseline build is fine, then every later build fails (as a broken migration would)."""

        async def sandbox(self, action: str, paths: list[str] | None = None) -> list[dict[str, Any]]:
            self.actions.append(action)
            ok = len(self.actions) == 1
            return [{"component": ".", "step": action, "ok": ok, "output": "" if ok else "next: error"}]

    services = FakeServices(project=BuildFails(work, test_results=[[GREEN]]))
    before = {p: (work / p).read_text(encoding="utf-8") for p in VITE_FILES}
    state, _ = await drive(
        compiled("frontend", services),
        cfg(),
        initial_state("frontend", tmp_path, request="Move to Next.js"),
        approve_all,
    )
    assert state["outcomes"]["migrate"]["done"] is False
    assert {p: (work / p).read_text(encoding="utf-8") for p in VITE_FILES} == before
    assert not (work / "src/app").exists()


async def test_no_frontend_means_nothing_to_do(tmp_path: Path) -> None:
    work = repo(tmp_path, {"main.py": "print(1)\n"})
    services = FakeServices(project=FakeProject(work))
    state, _ = await drive(
        compiled("frontend", services), cfg(), initial_state("frontend", tmp_path, request="modern"), approve_all
    )
    assert state["stages"] == [] and "nothing to do" in state["plan_brief"]


# ── DevOps ───────────────────────────────────────────────────────────────────
PY_FILES = {
    "pyproject.toml": '[project]\nname = "api"\nversion = "0.1.0"\ndependencies = ["fastapi", "psycopg[binary]", "redis"]\n',
    "uv.lock": "",
    "app/main.py": "from fastapi import FastAPI\napp = FastAPI()\n@app.get('/healthz')\ndef h():\n    return 1\n",
}
GO_FILES = {
    "go.mod": "module example.com/svc\n\ngo 1.22\n",
    "go.sum": "",
    "main.go": 'package main\n\nimport "net/http"\n\nfunc main() { http.ListenAndServe(":9000", nil) }\n',
}


def test_generated_files_follow_the_project_and_pass_their_own_checks(tmp_path: Path) -> None:
    work = repo(tmp_path, GO_FILES)
    files, notes = dev.plan_files(work, "dockerize it and add kubernetes")
    paths = {f.path for f in files}
    assert {"Dockerfile", ".dockerignore", "docker-compose.yml", ".github/workflows/ci.yml"} <= paths
    assert any(p.startswith("k8s/") for p in paths)
    docker = next(f.content for f in files if f.path == "Dockerfile")
    assert "golang:1.22-alpine" in docker and "distroless" in docker and "USER nonroot" in docker
    ci = yaml.safe_load(next(f.content for f in files if f.path.endswith("ci.yml")))
    assert "images" in ci["jobs"] and any("go" in k for k in ci["jobs"])
    assert dev.check_files(work, files) == []
    assert notes == []


def test_existing_files_are_never_overwritten_and_databases_get_sidecars(tmp_path: Path) -> None:
    work = repo(tmp_path, {**PY_FILES, "Dockerfile": "FROM scratch\n"})
    files, notes = dev.plan_files(work, "")
    assert "Dockerfile" not in {f.path for f in files} and any(
        "Dockerfile" in n and "left as it is" in n for n in notes
    )
    compose = yaml.safe_load(next(f.content for f in files if f.path == "docker-compose.yml"))
    assert {"postgres", "redis"} <= set(compose["services"])
    svc = next(s for n, s in compose["services"].items() if "build" in s)
    assert svc["healthcheck"]["test"][1].endswith("/healthz || exit 1")


def test_a_bad_dockerfile_is_caught() -> None:
    bad = dev.GeneratedFile("Dockerfile", 'FROM python:latest\nCOPY nothing.txt /x\nCMD ["x"]\n', "")
    problems = {p["problem"] for p in dev.check_files(Path("/nonexistent"), [bad])}
    assert any("pinned" in p for p in problems) and any("root" in p for p in problems)


async def test_devops_writes_checks_and_commits_the_files(tmp_path: Path) -> None:
    work = repo(tmp_path, GO_FILES)
    services = FakeServices(project=FakeProject(work, test_results=[[GREEN]]))
    state, prompts = await drive(
        compiled("devops", services), cfg(), initial_state("devops", tmp_path, request="Dockerize it"), approve_all
    )
    assert gates_of(prompts) == ["approve_plan", "approve_result"]
    assert (work / "Dockerfile").is_file() and (work / ".github/workflows/ci.yml").is_file()
    assert state["findings"] == [] and all(c["ok"] for c in state["ci"])
    assert "not built" in state["done_summary"]
    assert "Docker, CI and deployment" in git(work, "log", "-1", "--format=%s")
    assert state["published"]["branch"].startswith("codewright/devops-")
