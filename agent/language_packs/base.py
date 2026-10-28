"""The Language Pack interface (CODEWRIGHT.md Section 8.3) and the types every pack shares.

A pack is **pure**: it reads files and returns plans (commands, run specs, scaffolds, graph fragments). Nothing here
executes project code; `agent.language_packs.executor` runs a pack's steps in the sandbox (ADR 0020). That split
differs from the spec's sketch (`build(path) -> CommandResult`), so packs can be tested without Docker and every
command visibly goes through the sandbox.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol

from agent.tools.secrets import SKIP_DIRS

Toolchain = Literal["python", "go", "node", "cpp", "tools", "browser"]  # the last two: verification (Phase 7)
STATE = ".codewright"  # Codewright's own files inside a component (reports, built binaries); excluded from git
REPORTS = f"{STATE}/reports"  # test reports
EXTRA_SKIP = {"graphify-out", ".codewright", "coverage", "out", ".turbo", ".cache", "third_party", "external"}


# ── what a pack finds ────────────────────────────────────────────────────────
@dataclass
class Component:
    """One buildable part of a project: a Go module, a Python project, a Node package, a CMake project."""

    pack: str
    path: str  # relative to the project root, "." for the root
    kind: str  # web, api, cli, library, app
    frameworks: list[str] = field(default_factory=list)
    entrypoints: list[str] = field(default_factory=list)  # files or packages that start the program
    manifest: str = ""  # go.mod, pyproject.toml, package.json, CMakeLists.txt
    details: dict[str, Any] = field(default_factory=dict)  # pack-specific facts (package manager, scripts…)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GraphFragment:
    """Framework-level meaning a pack adds to the code graph: routes, models, commands, pages, events."""

    nodes: list[dict[str, Any]] = field(default_factory=list)
    edges: list[dict[str, Any]] = field(default_factory=list)

    def node(self, kind: str, label: str, file: str, line: int, **meta: Any) -> str:
        node_id = f"{kind}:{label}"
        if not any(n["id"] == node_id for n in self.nodes):
            self.nodes.append({"id": node_id, "kind": kind, "label": label, "file": file, "line": line, **meta})
        return node_id

    def edge(self, source: str, target: str, kind: str, confidence: float = 0.8) -> None:
        self.edges.append({"source": source, "target": target, "kind": kind, "confidence": confidence})

    def as_dict(self) -> dict[str, Any]:
        nodes = sorted(self.nodes, key=lambda n: (n["kind"], n["file"], n["line"], n["label"]))
        edges = sorted(self.edges, key=lambda e: (e["kind"], e["source"], e["target"]))
        return {"nodes": nodes, "edges": edges}


# ── what a pack plans ────────────────────────────────────────────────────────
@dataclass
class Step:
    """One command for the sandbox runner."""

    name: str  # install, build, test, lint, typecheck…
    toolchain: Toolchain
    cmd: list[str]
    workdir: str = "."  # relative to the project root
    network: Literal["registry", "none"] = "registry"
    timeout_s: int | None = None
    env: dict[str, str] = field(default_factory=dict)
    report: str | None = None  # test report format to read afterwards: junit, go-json, ctest-junit
    optional: bool = False  # a failure is reported but doesn't fail the action (e.g. a linter that isn't set up)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ServiceNeed:
    """A sidecar the app needs (from the project's docker-compose file): its hostname, image and environment."""

    name: str
    image: str
    env: dict[str, str] = field(default_factory=dict)


@dataclass
class RunSpec:
    kind: Literal["web", "terminal"]
    toolchain: Toolchain
    cmd: list[str]
    workdir: str = "."
    port: int | None = None
    env: dict[str, str] = field(default_factory=dict)
    services: list[ServiceNeed] = field(default_factory=list)
    prepare: list[Step] = field(default_factory=list)  # install/build steps to run first
    name: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CommandResult:
    step: str
    exit_code: int
    duration_s: float
    output_tail: str = ""
    timed_out: bool = False
    oom_killed: bool = False

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


@dataclass
class TestCase:
    name: str
    status: Literal["passed", "failed", "skipped", "error"]
    message: str = ""
    file: str = ""


@dataclass
class FileCoverage:
    file: str
    covered: int
    total: int

    @property
    def percent(self) -> float:
        return round(100 * self.covered / self.total, 1) if self.total else 100.0


@dataclass
class Coverage:
    """Line (statement) coverage of one test run: the total and the files with the least."""

    tool: str
    covered: int = 0
    total: int = 0
    files: list[FileCoverage] = field(default_factory=list)  # least covered first, capped

    @property
    def percent(self) -> float:
        return round(100 * self.covered / self.total, 1) if self.total else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "covered": self.covered,
            "total": self.total,
            "percent": self.percent,
            "files": [{**asdict(f), "percent": f.percent} for f in self.files],
        }


@dataclass
class TestReport:
    tool: str
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    errors: int = 0
    cases: list[TestCase] = field(default_factory=list)  # failures first, capped
    found: bool = True  # False when the tool produced no report (nothing ran, or it crashed before reporting)
    coverage: Coverage | None = None

    @property
    def total(self) -> int:
        return self.passed + self.failed + self.skipped + self.errors

    @property
    def ok(self) -> bool:
        return self.found and self.failed == 0 and self.errors == 0

    def as_dict(self) -> dict[str, Any]:
        out = {**asdict(self), "total": self.total, "ok": self.ok}
        out["coverage"] = self.coverage.as_dict() if self.coverage else None
        return out


# ── what a pack generates ────────────────────────────────────────────────────
@dataclass
class ServiceSpec:
    """A new service/app to scaffold from a template."""

    name: str  # kebab-case, e.g. "order-service"
    template: str  # templates/apps/<template> or templates/services/<template>
    description: str = ""
    port: int = 8080


@dataclass
class Endpoint:
    method: str
    path: str  # /orders/{id}
    name: str  # getOrder
    request: str | None = None  # type name of the JSON body
    response: str | None = None


@dataclass
class Contract:
    """The subset of an OpenAPI document a client stub needs."""

    service: str
    base_url: str
    endpoints: list[Endpoint]

    @classmethod
    def from_openapi(cls, doc: dict[str, Any], service: str) -> Contract:
        endpoints: list[Endpoint] = []
        for path, ops in sorted(doc.get("paths", {}).items()):
            for method, op in sorted(ops.items()):
                if method.lower() not in {"get", "post", "put", "patch", "delete"}:
                    continue
                name = op.get("operationId") or _operation_name(method, path)
                body = op.get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema", {})
                ok: dict[str, Any] = next(
                    (r for code, r in op.get("responses", {}).items() if str(code).startswith("2")), {}
                )
                result = ok.get("content", {}).get("application/json", {}).get("schema", {})
                endpoints.append(
                    Endpoint(method.upper(), path, name, _ref_name(body), _ref_name(result)),
                )
        servers = doc.get("servers") or [{"url": "http://localhost:8080"}]
        return cls(service, servers[0]["url"], endpoints)


def _ref_name(schema: dict[str, Any]) -> str | None:
    ref = schema.get("$ref", "")
    return ref.rsplit("/", 1)[-1] if ref else None


def _operation_name(method: str, path: str) -> str:
    words = [w for w in re.split(r"[/{}_-]+", path) if w]
    return method.lower() + "".join(w[:1].upper() + w[1:] for w in words)


@dataclass
class DockerSpec:
    toolchain: Toolchain
    base_image: str
    dockerfile: str  # a Dockerfile for a generated service, with {name} and {port} placeholders filled


@dataclass
class InstrumentationSpec:
    """How a generated service gets OpenTelemetry tracing (Section 12: OpenTelemetry + Jaeger)."""

    packages: list[str]
    env: dict[str, str]
    notes: str


# ── the interface ────────────────────────────────────────────────────────────
class LanguagePack(Protocol):
    name: str  # python, go, typescript, javascript, cpp
    language: str  # Python, Go, TypeScript, JavaScript, C++
    toolchain: Toolchain

    def detect(self, repo: Path) -> list[Component]: ...
    def parse(self, repo: Path, component: Component) -> GraphFragment: ...
    def build_steps(self, repo: Path, component: Component) -> list[Step]: ...
    def test_steps(self, repo: Path, component: Component) -> list[Step]: ...
    def lint_steps(self, repo: Path, component: Component) -> list[Step]: ...
    def run_spec(self, repo: Path, component: Component) -> RunSpec | None: ...
    def read_report(self, repo: Path, component: Component, step: Step, output: str) -> TestReport: ...
    def scaffold_service(self, spec: ServiceSpec, out: Path) -> None: ...
    def client_stub(self, contract: Contract, out: Path) -> Path: ...
    def docker_base(self) -> DockerSpec: ...
    def instrumentation(self) -> InstrumentationSpec: ...


# ── helpers shared by packs ──────────────────────────────────────────────────
def walk(root: Path, suffixes: tuple[str, ...], *, limit: int = 20_000) -> Iterator[Path]:
    """Source files under `root`, skipping dependency, build and output folders."""
    count = 0
    skip = SKIP_DIRS | EXTRA_SKIP
    stack = [root]
    while stack:
        folder = stack.pop()
        try:
            entries = sorted(folder.iterdir())
        except OSError:
            continue
        for entry in entries:
            if entry.is_symlink():
                continue
            if entry.is_dir():
                if entry.name not in skip and not entry.name.startswith("."):
                    stack.append(entry)
            elif entry.suffix in suffixes:
                count += 1
                if count > limit:
                    return
                yield entry


def manifests(root: Path, name: str, *, max_depth: int = 4) -> list[Path]:
    """Every `name` file (go.mod, package.json…) under root, shallowest first, outside skipped folders."""
    found: list[Path] = []
    skip = SKIP_DIRS | EXTRA_SKIP

    def visit(folder: Path, depth: int) -> None:
        candidate = folder / name
        if candidate.is_file():
            found.append(candidate)
        if depth >= max_depth:
            return
        try:
            children = sorted(p for p in folder.iterdir() if p.is_dir() and not p.is_symlink())
        except OSError:
            return
        for child in children:
            if child.name not in skip and not child.name.startswith("."):
                visit(child, depth + 1)

    visit(root, 0)
    return found


def rel(path: Path, root: Path) -> str:
    r = path.relative_to(root).as_posix()
    return r or "."


def read(path: Path, limit: int = 400_000) -> str:
    try:
        return path.read_bytes()[:limit].decode("utf-8", errors="replace")
    except OSError:
        return ""


def read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(read(path))
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def line_of(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def tail(text: str, lines: int = 60) -> str:
    return "\n".join(text.rstrip().splitlines()[-lines:])


def fill(text: str, values: dict[str, str]) -> str:
    """Template placeholders: `{{name}}` (kebab-case), `{{name_snake}}`, `{{Name}}`, `{{title}}`, `{{description}}`,
    `{{port}}`. Only these exact keys are replaced, so code that happens to contain braces is left alone."""
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", value)
    return text


def template_values(spec: ServiceSpec) -> dict[str, str]:
    words = [w for w in re.split(r"[^A-Za-z0-9]+", spec.name) if w]
    return {
        "name": "-".join(w.lower() for w in words),
        "name_snake": "_".join(w.lower() for w in words),
        "Name": "".join(w[:1].upper() + w[1:].lower() for w in words),
        "title": " ".join(w[:1].upper() + w[1:].lower() for w in words),
        "description": spec.description or f"{spec.name}, generated by Codewright",
        "port": str(spec.port),
    }
