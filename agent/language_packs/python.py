"""Python pack: FastAPI, Flask, Django, SQLAlchemy, CLI (argparse/typer/click). uv/pip · pytest · ruff, mypy.

Dependencies go into `<component>/.venv` (made with `--system-site-packages`, so the image's pytest, ruff and mypy
are there even when the project doesn't list them).
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from agent.language_packs import compose, reports, templates
from agent.language_packs.base import (
    REPORTS,
    STATE,
    Component,
    Contract,
    DockerSpec,
    GraphFragment,
    InstrumentationSpec,
    RunSpec,
    ServiceSpec,
    Step,
    TestReport,
    Toolchain,
    line_of,
    manifests,
    read,
    rel,
    walk,
)

MARKERS = ("pyproject.toml", "setup.py", "setup.cfg", "requirements.txt")
FRAMEWORKS = {
    "fastapi": "fastapi",
    "flask": "flask",
    "django": "django",
    "sqlalchemy": "sqlalchemy",
    "typer": "typer",
    "click": "click",
    "pydantic": "pydantic",
    "celery": "celery",
}
WEB = {"fastapi", "flask", "django"}
VENV_PY = ".venv/bin/python"

# Rewrites the pinned version of one package in requirements*.txt / pyproject.toml; exits 1 if it is in neither.
BUMP_SCRIPT = r"""import pathlib, re, sys
pkg, ver = sys.argv[1:3]
name = "[-_.]".join(map(re.escape, re.split(r"[-_.]", pkg)))
pat = re.compile(r"(?im)^(\s*[\"']?)(" + name + r")(\[[^\]]*\])?\s*(==|>=|~=|<=|<|>|!=)\s*[\w.*+-]+")
hit = False
for f in list(pathlib.Path(".").glob("requirements*.txt")) + [pathlib.Path("pyproject.toml")]:
    if not f.is_file():
        continue
    text = f.read_text()
    op = lambda m: m.group(4) if m.group(4) in ("==", ">=", "~=") else "=="
    new = pat.sub(lambda m: m.group(1) + m.group(2) + (m.group(3) or "") + op(m) + ver, text)
    if new != text:
        f.write_text(new)
        print("updated", f)
        hit = True
sys.exit(0 if hit else 1)
"""

_ROUTE = re.compile(
    r"@(\w+)\.(get|post|put|patch|delete|route|api_route|websocket)\(\s*[\"']([^\"']*)[\"']", re.IGNORECASE
)
_ROUTER_PREFIX = re.compile(
    r"(\w+)\s*=\s*(?:APIRouter|Blueprint)\((?:[^)]*?prefix\s*=\s*|[\"'][\w-]+[\"']\s*,[^)]*?url_prefix\s*=\s*)[\"']([^\"']*)[\"']"
)
_INCLUDE = re.compile(r"include_router\(\s*(?:\w+\.)?(\w+)(?:\s*,\s*prefix\s*=\s*[\"']([^\"']*)[\"'])?")
_DJANGO_PATH = re.compile(r"\b(?:re_)?path\(\s*r?[\"']([^\"']*)[\"']\s*,\s*([\w.]+)")
_SA_MODEL = re.compile(
    r"^class\s+(\w+)\(([^)]*\b(?:Base|DeclarativeBase|db\.Model|SQLModel|Model)\b[^)]*)\):", re.MULTILINE
)
_TABLENAME = re.compile(r"__tablename__\s*=\s*[\"'](\w+)[\"']")
_DJANGO_MODEL = re.compile(r"^class\s+(\w+)\(\s*models\.Model\s*\):", re.MULTILINE)
_TYPER_CMD = re.compile(r"@(\w+)\.command\((?:[\"']([\w-]+)[\"'])?[^)]*\)\s*\ndef\s+(\w+)")
_ARGPARSE_SUB = re.compile(r"add_parser\(\s*[\"']([\w-]+)[\"']")
_APP = re.compile(r"^(\w+)\s*=\s*(FastAPI|Flask)\(", re.MULTILINE)
_MAIN = re.compile(r"^if\s+__name__\s*==\s*[\"']__main__[\"']\s*:", re.MULTILINE)


def _pyproject(root: Path) -> dict[str, object]:
    path = root / "pyproject.toml"
    if not path.exists():
        return {}
    try:
        return tomllib.loads(read(path))
    except tomllib.TOMLDecodeError:
        return {}


def _module_name(path: Path, root: Path) -> str:
    parts = list(path.relative_to(root).with_suffix("").parts)
    if parts and parts[0] == "src":
        parts = parts[1:]
    return ".".join(parts)


def _nested_manifest_dirs(repo: Path, component: Component) -> list[str]:
    """Subdirectories of `component` with their own Python manifest -- a scaffolded microservice under
    `services/<name>` (CODEWRIGHT.md 5.16), say. `detect()` folds these into this component since the outer root
    always wins, but each has its own dependencies, never installed into this component's venv, so this
    component's own pytest run must not also collect their tests."""
    base = repo / component.path
    found = {
        rel(path.parent, base)
        for marker in MARKERS
        for path in manifests(base, marker, max_depth=3)
        if path.parent != base
    }
    return sorted(found)


class PythonPack:
    name = "python"
    language = "Python"
    toolchain: Toolchain = "python"

    def detect(self, repo: Path) -> list[Component]:  # noqa: PLR0912  (one branch per framework and manager)
        roots: list[Path] = []
        for marker in MARKERS:
            for found in manifests(repo, marker, max_depth=3):
                if not any(found.parent == r or r in found.parent.parents for r in roots):
                    roots.append(found.parent)
        roots = [r for r in roots if not any(o != r and o in r.parents for o in roots)]
        components = []
        for root in sorted(roots):
            manifest = next(m for m in MARKERS if (root / m).exists())
            deps_text = " ".join(read(root / m).lower() for m in MARKERS if (root / m).exists())
            frameworks = {fw for key, fw in FRAMEWORKS.items() if re.search(rf"\b{key}\b", deps_text)}
            entrypoints: list[str] = []
            apps: list[str] = []
            for f in walk(root, (".py",)):
                src = read(f, 200_000)
                if m := _APP.search(src):
                    apps.append(f"{_module_name(f, root)}:{m.group(1)}")
                    frameworks.add(m.group(2).lower())
                if _MAIN.search(src) and "test" not in f.name:
                    entrypoints.append(rel(f, root))
                if "argparse" in src and "ArgumentParser(" in src:
                    frameworks.add("argparse")
            if (root / "manage.py").exists():
                frameworks.add("django")
                entrypoints.insert(0, "manage.py")
            project = _pyproject(root)
            meta = project.get("project")
            scripts = dict(meta.get("scripts", {})) if isinstance(meta, dict) else {}
            if frameworks & WEB:
                kind = "api"
            elif scripts or entrypoints:
                kind = "cli"
            else:
                kind = "library"
            if (root / "uv.lock").exists():
                manager = "uv"
            elif (root / "poetry.lock").exists():
                manager = "poetry"
            elif (root / "pyproject.toml").exists() or (root / "setup.py").exists():
                manager = "pip-project"
            else:
                manager = "pip"
            components.append(
                Component(
                    pack=self.name,
                    path=rel(root, repo),
                    kind=kind,
                    frameworks=sorted(frameworks),
                    entrypoints=[*apps, *sorted(set(entrypoints), key=entrypoints.index)],
                    manifest=manifest,
                    details={"manager": manager, "scripts": scripts, "apps": apps},
                )
            )
        return components

    def parse(self, repo: Path, component: Component) -> GraphFragment:  # noqa: PLR0912  (one branch per framework)
        root = repo / component.path
        g = GraphFragment()
        mounts: dict[str, str] = {}
        sources: list[tuple[str, str]] = []
        for f in walk(root, (".py",)):
            src = read(f, 400_000)
            sources.append((rel(f, repo), src))
            for m in _INCLUDE.finditer(src):
                if m.group(2):
                    mounts[m.group(1)] = m.group(2)
        for name, src in sources:
            prefixes = {m.group(1): m.group(2) for m in _ROUTER_PREFIX.finditer(src)}
            for m in _ROUTE.finditer(src):
                var, method, path = m.groups()
                method = "ANY" if method.lower() in {"route", "api_route"} else method.upper()
                full = mounts.get(var, "") + prefixes.get(var, "") + path
                handler = re.search(r"\n\s*(?:async\s+)?def\s+(\w+)", src[m.end() :])
                rid = g.node("route", f"{method} {full or '/'}", name, line_of(src, m.start()))
                if handler:
                    g.edge(rid, f"handler:{handler.group(1)}", "handled_by", 0.9)
            if name.endswith("urls.py"):
                for m in _DJANGO_PATH.finditer(src):
                    rid = g.node("route", f"ANY /{m.group(1)}", name, line_of(src, m.start()))
                    g.edge(rid, f"handler:{m.group(2)}", "handled_by", 0.8)
            for m in _SA_MODEL.finditer(src):
                if m.group(2).strip() == "DeclarativeBase":
                    continue  # the declarative base itself, not a table
                nxt = re.search(r"^class\s", src[m.end() :], re.MULTILINE)
                body = src[m.end() : m.end() + (nxt.start() if nxt else 2000)]
                table = _TABLENAME.search(body)
                mid = g.node("model", m.group(1), name, line_of(src, m.start()), orm="sqlalchemy")
                if table:
                    g.edge(mid, f"table:{table.group(1)}", "maps_to", 0.9)
            for m in _DJANGO_MODEL.finditer(src):
                g.node("model", m.group(1), name, line_of(src, m.start()), orm="django")
            for m in _TYPER_CMD.finditer(src):
                g.node("command", m.group(2) or m.group(3).replace("_", "-"), name, line_of(src, m.start()))
            for m in _ARGPARSE_SUB.finditer(src):
                g.node("command", m.group(1), name, line_of(src, m.start()))
        return g

    def _install(self, component: Component) -> Step:
        manager = component.details.get("manager", "pip")
        venv = "uv venv --quiet --allow-existing --system-site-packages .venv"
        if manager == "uv":
            cmd = f"{venv} && uv sync --frozen --inexact --all-extras"
        elif manager in {"poetry", "pip-project"}:
            cmd = f"{venv} && uv pip install --python .venv -e '.[test,dev]' || uv pip install --python .venv -e ."
        else:
            extra = "".join(f" $([ -f {r} ] && echo -r {r})" for r in ("requirements-dev.txt", "requirements-test.txt"))
            cmd = f"{venv} && uv pip install --python .venv -r requirements.txt{extra}"
        return Step("install", "python", ["sh", "-c", cmd], component.path, env={"UV_PROJECT_ENVIRONMENT": ".venv"})

    def build_steps(self, repo: Path, component: Component) -> list[Step]:
        return [
            self._install(component),
            Step(
                "build", "python", [VENV_PY, "-m", "compileall", "-q", "-x", r"/\.venv/", "."], component.path, "none"
            ),
        ]

    def test_steps(self, repo: Path, component: Component) -> list[Step]:
        junit = f"{REPORTS}/junit.xml"
        ignore = "".join(f" --ignore={d}" for d in _nested_manifest_dirs(repo, component))
        pytest = f"-m pytest -q -p no:cacheprovider{ignore} --junitxml={junit}"
        # coverage.py is in the sandbox image (seen through the venv's system site-packages); without it, plain pytest
        omit = ".venv/*,*/tests/*,tests/*,*/test_*.py,test_*.py,*_test.py,*/conftest.py,conftest.py"
        script = (
            f"if {VENV_PY} -c 'import coverage' 2>/dev/null; then "
            f"{VENV_PY} -m coverage run --data-file={STATE}/.coverage --source=. --omit='{omit}' {pytest}; code=$?; "
            f"{VENV_PY} -m coverage xml -q --data-file={STATE}/.coverage -o {REPORTS}/coverage.xml || true; "
            f"exit $code; else exec {VENV_PY} {pytest}; fi"
        )
        return [Step("test", "python", ["sh", "-c", script], component.path, "none", report="junit")]

    def lint_steps(self, repo: Path, component: Component) -> list[Step]:
        wd = component.path
        return [
            Step(
                "ruff",
                "python",
                [VENV_PY, "-m", "ruff", "check", "--output-format", "concise", "--no-cache", "."],
                wd,
                "none",
            ),
            Step(
                "mypy",
                "python",
                [VENV_PY, "-m", "mypy", "--ignore-missing-imports", "--no-incremental", "--exclude", r"\.venv", "."],
                wd,
                "none",
                optional=True,
            ),
        ]

    def outdated_steps(self, repo: Path, component: Component) -> list[Step]:
        cmd = ["sh", "-c", "uv pip list --python .venv --outdated --format json 2>/dev/null"]
        return [Step("outdated", "python", cmd, component.path)]

    def upgrade_steps(self, repo: Path, component: Component, package: str, version: str) -> list[Step]:
        return [Step("upgrade", "python", ["python3", "-c", BUMP_SCRIPT, package, version], component.path, "none")]

    def audit_steps(self, repo: Path, component: Component) -> list[Step]:
        # Vulnerabilities of the venv's installed packages, from PyPI's own advisory data (no extra network host).
        cmd = [VENV_PY, "-m", "pip_audit", "--progress-spinner", "off", "--format", "json"]
        return [Step("pip-audit", "python", cmd, component.path, optional=True)]

    def run_spec(self, repo: Path, component: Component) -> RunSpec | None:
        cf = compose.find(repo, component.path)
        app = compose.app_for(cf, component.path)
        env = dict(app.env) if app else {}
        services = list(cf.services) if cf else []
        prepare = [self._install(component)]
        fw = set(component.frameworks)
        apps: list[str] = component.details.get("apps", [])
        if "django" in fw and "manage.py" in component.entrypoints:
            port = (app.port if app else None) or 8000
            cmd = [VENV_PY, "manage.py", "runserver", f"0.0.0.0:{port}"]
            return RunSpec("web", "python", cmd, component.path, port, env, services, prepare, "django")
        if apps:
            module, var = apps[0].split(":")
            src = component.path if not (repo / component.path / "src").is_dir() else f"{component.path}/src"
            if "fastapi" in fw or "flask" not in fw:
                port = (app.port if app else None) or 8000
                cmd = [VENV_PY, "-m", "uvicorn", apps[0], "--host", "0.0.0.0", "--port", str(port)]
            else:
                port = (app.port if app else None) or 5000
                cmd = [
                    VENV_PY,
                    "-m",
                    "flask",
                    "--app",
                    f"{module}:{var}",
                    "run",
                    "--host",
                    "0.0.0.0",
                    "--port",
                    str(port),
                ]
            env.setdefault("PYTHONPATH", "src" if src != component.path else ".")
            return RunSpec("web", "python", cmd, component.path, port, env, services, prepare, module)
        scripts: dict[str, str] = component.details.get("scripts", {})
        if scripts:
            name = next(iter(scripts))
            return RunSpec(
                "terminal", "python", [f".venv/bin/{name}"], component.path, env=env, prepare=prepare, name=name
            )
        mains = [e for e in component.entrypoints if e.endswith(".py")]
        if mains:
            return RunSpec(
                "terminal", "python", [VENV_PY, mains[0]], component.path, env=env, prepare=prepare, name=mains[0]
            )
        return None

    def read_report(self, repo: Path, component: Component, step: Step, output: str) -> TestReport:
        base = repo / component.path / REPORTS
        report = reports.junit([base / "junit.xml"], "pytest")
        report.coverage = reports.cobertura(base / "coverage.xml", "coverage.py")
        return report

    def scaffold_service(self, spec: ServiceSpec, out: Path) -> None:
        templates.scaffold(spec, out)

    def client_stub(self, contract: Contract, out: Path) -> Path:
        cls = "".join(w.title() for w in re.split(r"\W+", contract.service) if w) + "Client"
        lines = [
            f'"""Client for the {contract.service} API. Generated by Codewright; edit freely."""',
            "",
            "from __future__ import annotations",
            "",
            "from typing import Any",
            "",
            "import httpx",
            "",
            "",
            f"class {cls}:",
            f'    def __init__(self, base_url: str = "{contract.base_url}", client: httpx.Client | None = None)'
            " -> None:",
            '        self.http = client or httpx.Client(base_url=base_url.rstrip("/"), timeout=30)',
            "",
            "    def _call(self, method: str, path: str, body: Any = None) -> Any:",
            "        response = self.http.request(method, path, json=body)",
            "        response.raise_for_status()",
            "        return response.json() if response.content else None",
        ]
        for ep in contract.endpoints:
            params = re.findall(r"\{(\w+)\}", ep.path)
            name = re.sub(r"(?<!^)(?=[A-Z])", "_", ep.name).lower()
            args = ["self", *(f"{p}: str" for p in params)] + (["body: Any"] if ep.request else [])
            path = "f" + repr(ep.path) if params else repr(ep.path)
            lines += [
                "",
                f"    def {name}({', '.join(args)}) -> Any:",
                f'        """{ep.method} {ep.path}"""',
                f'        return self._call("{ep.method}", {path}{", body" if ep.request else ""})',
            ]
        target = out / f"{re.sub(r'\W', '_', contract.service.lower())}_client.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return target

    def docker_base(self) -> DockerSpec:
        return DockerSpec(
            "python",
            "python:3.12-slim",
            "FROM python:3.12-slim\nCOPY --from=ghcr.io/astral-sh/uv:0.12.16 /uv /bin/uv\nWORKDIR /app\n"
            "COPY pyproject.toml uv.lock* ./\nRUN uv sync --frozen --no-dev --no-install-project\nCOPY . .\n"
            "RUN uv sync --frozen --no-dev\nRUN useradd --system --uid 10001 app\nUSER app\nEXPOSE {port}\n"
            'CMD [".venv/bin/python", "-m", "uvicorn", "{name_snake}.main:app", "--host", "0.0.0.0", '
            '"--port", "{port}"]\n',
        )

    def instrumentation(self) -> InstrumentationSpec:
        return InstrumentationSpec(
            packages=["opentelemetry-distro", "opentelemetry-exporter-otlp", "opentelemetry-instrumentation-fastapi"],
            env={"OTEL_EXPORTER_OTLP_ENDPOINT": "http://jaeger:4317", "OTEL_SERVICE_NAME": "{name}"},
            notes="Start with `opentelemetry-instrument uvicorn ...`, or FastAPIInstrumentor.instrument_app(app).",
        )
