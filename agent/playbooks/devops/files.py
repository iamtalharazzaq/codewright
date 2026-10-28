"""The files DevOps adds to a project: a Dockerfile per deployable component, `.dockerignore`, Compose, a CI workflow
and (when asked) Kubernetes manifests. They are written from templates per Language Pack, not by a model: a 9B model
invents base images and flags, and these files must be boring and correct. Nothing here knows a particular project.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from agent.language_packs import detect_project, pack
from agent.language_packs.base import Component, Step

DEPLOYABLE = {"web", "api", "app"}
DOCKERIGNORE = ".git\n.env\n.env.*\n!.env.example\nnode_modules\n.venv\n__pycache__\n*.pyc\n.codewright\ncoverage\n"
HEALTH = re.compile(r"""["'`](/(?:healthz?|health/live|ready|readyz|livez|ping))["'`]""")
DATABASES = {
    "postgres": (
        re.compile(r"psycopg|asyncpg|pgx|lib/pq|\"pg\"|postgres", re.I),
        "postgres:16-alpine",
        {"POSTGRES_PASSWORD": "change-me", "POSTGRES_DB": "app"},
        5432,
    ),
    "redis": (re.compile(r"redis", re.I), "redis:7-alpine", {}, 6379),
}


@dataclass
class Target:
    """A component that gets deployed."""

    component: Component
    name: str
    port: int
    health: str | None


@dataclass
class GeneratedFile:
    path: str
    content: str
    purpose: str


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "app"


def targets(work: Path) -> list[Target]:
    found: list[Target] = []
    taken: set[str] = set()
    for c in detect_project(work):
        if c.kind not in DEPLOYABLE:
            continue
        spec = pack(c.pack).run_spec(work, c)
        name = slug(c.details.get("name") or ("app" if c.path == "." else Path(c.path).name))
        while name in taken:
            name += "-x"
        taken.add(name)
        found.append(Target(c, name, (spec.port if spec and spec.port else None) or 8080, health_path(work / c.path)))
    return found


def health_path(root: Path) -> str | None:
    """A health route the code serves, found by reading its source (nothing is guessed)."""
    for f in list(root.rglob("*"))[:3000]:
        if f.suffix in {".py", ".go", ".ts", ".js", ".tsx", ".cpp"} and not {"node_modules", ".venv"} & set(f.parts):
            try:
                hit = HEALTH.search(f.read_text(encoding="utf-8", errors="ignore")[:200_000])
            except OSError:
                continue
            if hit:
                return hit.group(1)
    return None


def serving_port(t: Target) -> int:
    """The port the container listens on: a static web build is served by unprivileged nginx on 8080."""
    return 8080 if t.component.kind == "web" and "next" not in t.component.frameworks else t.port


# ── Dockerfiles ──────────────────────────────────────────────────────────────
def _node_cmds(manager: str) -> tuple[str, str, str]:
    """(enable, install, run-script prefix) for a package manager."""
    if manager == "pnpm":
        return "RUN corepack enable\n", "pnpm install --frozen-lockfile", "pnpm run"
    if manager == "yarn":
        return "RUN corepack enable\n", "yarn install --frozen-lockfile", "yarn run"
    return "", "npm ci --no-audit --no-fund" if manager == "npm-ci" else "npm install --no-audit --no-fund", "npm run"


def dockerfile(t: Target, work: Path) -> str:  # noqa: PLR0911, PLR0912  (one template per pack and kind)
    c = t.component
    d = c.details
    root = work / c.path
    if c.pack == "python":
        manager = d.get("manager", "pip")
        app = (d.get("apps") or [""])[0]
        cmd = (
            f'["python", "-m", "uvicorn", "{app}", "--host", "0.0.0.0", "--port", "{t.port}"]'
            if app
            else f'["python", "{c.entrypoints[0] if c.entrypoints else "main.py"}"]'
        )
        if manager == "uv":
            install = (
                "COPY pyproject.toml uv.lock ./\nRUN uv sync --frozen --no-dev --no-install-project\n"
                "COPY . .\nRUN uv sync --frozen --no-dev\nENV PATH=/app/.venv/bin:$PATH\n"
            )
            head = "COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /bin/uv\n"
        elif (root / "requirements.txt").exists():
            head, install = "", "COPY requirements.txt ./\nRUN pip install --no-cache-dir -r requirements.txt\nCOPY . .\n"
        else:
            head, install = "", "COPY . .\nRUN pip install --no-cache-dir .\n"
        return (
            f"FROM python:3.12-slim\nENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1\n{head}WORKDIR /app\n{install}"
            f"RUN useradd --system --uid 10001 app && chown -R app /app\nUSER app\nEXPOSE {t.port}\nCMD {cmd}\n"
        )
    if c.pack == "go":
        version = d.get("go") or "1.23"
        entry = c.entrypoints[0] if c.entrypoints else "."
        sums = "go.mod go.sum" if d.get("has_go_sum") else "go.mod"
        return (
            f"FROM golang:{version}-alpine AS build\nWORKDIR /src\nCOPY {sums} ./\nRUN go mod download\nCOPY . .\n"
            f"RUN CGO_ENABLED=0 go build -trimpath -o /out/app {entry}\n\n"
            f"FROM gcr.io/distroless/static-debian12:nonroot\nCOPY --from=build /out/app /app\nEXPOSE {t.port}\n"
            'USER nonroot\nENTRYPOINT ["/app"]\n'
        )
    if c.pack in {"typescript", "javascript", "node"}:
        enable, install, run = _node_cmds(d.get("manager", "npm"))
        scripts = d.get("scripts", [])
        lock = "".join(
            f" {f}"
            for f in ("package-lock.json", "yarn.lock", "pnpm-lock.yaml", ".npmrc", ".yarnrc.yml")
            if (root / f).exists()
        )
        deps = f"WORKDIR /app\nCOPY package.json{lock} ./\n{enable}RUN {install}\nCOPY . .\n"
        fw = set(c.frameworks)
        if "next" in fw:
            return (
                f"FROM node:22-slim\nENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1\n{deps}RUN {run} build\n"
                f"USER node\nEXPOSE {t.port}\nCMD [\"npx\", \"next\", \"start\", \"-H\", \"0.0.0.0\", \"-p\", \"{t.port}\"]\n"
            )
        if c.kind == "web":
            out = "dist" if "vite" in fw else "build"
            return (
                f"FROM node:22-slim AS build\n{deps}RUN {run} build\n\n"
                f"FROM nginxinc/nginx-unprivileged:1.27-alpine\nCOPY --from=build /app/{out} /usr/share/nginx/html\n"
                "EXPOSE 8080\n"
            )
        if "build" in scripts:
            build = f"RUN {run} build\n"
        else:
            build = ""
        if "start" in scripts:
            start = f'["{run.split()[0]}", "run", "start"]'
        else:
            start = f'["node", "{c.entrypoints[0] if c.entrypoints else "index.js"}"]'
        return (
            f"FROM node:22-slim\nENV NODE_ENV=production PORT={t.port} HOST=0.0.0.0\n{deps}{build}"
            f"USER node\nEXPOSE {t.port}\nCMD {start}\n"
        )
    # C++
    exe = next(iter(d.get("executables") or []), None) or "app"
    return (
        "FROM gcc:14 AS build\nRUN apt-get update && apt-get install -y --no-install-recommends cmake && "
        "rm -rf /var/lib/apt/lists/*\nWORKDIR /src\nCOPY . .\n"
        "RUN cmake -S . -B build -DCMAKE_BUILD_TYPE=Release && cmake --build build -j\n"
        f"RUN find build -type f -name '{exe}' -perm -u+x -exec cp {{}} /app \\;\n\n"
        f"FROM debian:bookworm-slim\nCOPY --from=build /app /usr/local/bin/app\nRUN useradd --system --uid 10001 app\n"
        f'USER app\nEXPOSE {t.port}\nENTRYPOINT ["/usr/local/bin/app"]\n'
    )


# ── Compose ──────────────────────────────────────────────────────────────────
def sidecars(work: Path) -> dict[str, tuple[str, dict[str, str], int]]:
    """Databases the dependency manifests mention."""
    text = ""
    for name in ("pyproject.toml", "requirements.txt", "go.mod", "package.json"):
        for m in list(work.rglob(name))[:12]:
            if not {"node_modules", ".venv"} & set(m.parts):
                text += m.read_text(encoding="utf-8", errors="ignore")[:40_000]
    return {n: (image, env, port) for n, (rx, image, env, port) in DATABASES.items() if rx.search(text)}


def compose_file(ts: list[Target], work: Path, observability: bool) -> str:
    services: dict[str, Any] = {}
    side = sidecars(work)
    for t in ts:
        port = serving_port(t)
        svc: dict[str, Any] = {
            "build": {"context": t.component.path},
            "ports": [f"{port}:{port}"],
            "restart": "unless-stopped",
        }
        env: dict[str, str] = {"PORT": str(port)}
        if observability:
            env["OTEL_SERVICE_NAME"] = t.name
        if "postgres" in side and t.component.kind in {"api", "app"}:
            env["DATABASE_URL"] = "postgres://postgres:change-me@postgres:5432/app?sslmode=disable"
        if "redis" in side and t.component.kind in {"api", "app"}:
            env["REDIS_URL"] = "redis://redis:6379"
        svc["environment"] = env
        if side and t.component.kind in {"api", "app"}:
            svc["depends_on"] = {n: {"condition": "service_healthy"} for n in side}
        if observability and t.health:
            svc["healthcheck"] = {
                "test": ["CMD-SHELL", f"wget -qO- http://localhost:{port}{t.health} || exit 1"],
                "interval": "30s",
                "timeout": "5s",
                "retries": 3,
            }
        services[t.name] = svc
    for n, (image, env, _port) in side.items():
        services[n] = {
            "image": image,
            "restart": "unless-stopped",
            "healthcheck": {
                "test": ["CMD-SHELL", "pg_isready -U postgres" if n == "postgres" else "redis-cli ping"],
                "interval": "10s",
                "timeout": "5s",
                "retries": 5,
            },
            **({"environment": env} if env else {}),
        }
    return yaml.safe_dump({"services": services}, sort_keys=False)


# ── CI ───────────────────────────────────────────────────────────────────────
SETUP = {
    "python": ["- uses: actions/setup-python@v5\n  with:\n    python-version: '3.12'"],
    "go": ["- uses: actions/setup-go@v5\n  with:\n    go-version-file: '{path}/go.mod'"],
    "node": ["- uses: actions/setup-node@v4\n  with:\n    node-version: 22"],
    "cpp": ["- run: sudo apt-get update && sudo apt-get install -y cmake"],
}


def _ci_steps(work: Path, c: Component) -> list[Step]:
    p = pack(c.pack)
    out: list[Step] = []
    for step in [*p.build_steps(work, c), *p.lint_steps(work, c), *p.test_steps(work, c)]:
        if not any(s.cmd == step.cmd and s.workdir == step.workdir for s in out):
            out.append(step)
    return out


def ci_steps(work: Path) -> list[tuple[Component, list[Step]]]:
    return [(c, _ci_steps(work, c)) for c in detect_project(work) if c.kind != "tools"]


def ci_workflow(work: Path, dockerfiles: list[str]) -> str:
    lines = ["name: CI", "on:", "  push:", "    branches: [main]", "  pull_request:", "", "jobs:"]
    for c, steps in ci_steps(work):
        job = slug(f"{c.pack}-{c.path}")
        lines += [f"  {job}:", "    runs-on: ubuntu-latest", "    steps:", "      - uses: actions/checkout@v4"]
        toolchain = "node" if c.pack in {"typescript", "javascript", "node"} else c.pack
        extra = ["- uses: astral-sh/setup-uv@v5"] if c.pack == "python" and c.details.get("manager") == "uv" else []
        for block in [*SETUP.get(toolchain, []), *extra]:
            lines += [f"      {ln}" for ln in block.format(path=c.path).splitlines()]
        for s in steps:
            if s.cmd[:1] == ["sh"] and s.cmd[1:2] == ["-c"]:
                run = s.cmd[2]
            else:
                run = shlex.join(s.cmd)
            lines += [f"      - name: {s.name}", f"        run: {_yaml_str(run)}"]
            if s.workdir not in {".", ""}:
                lines += [f"        working-directory: {s.workdir}"]
            if s.optional:
                lines += ["        continue-on-error: true"]
    if dockerfiles:
        lines += ["  images:", "    runs-on: ubuntu-latest", "    steps:", "      - uses: actions/checkout@v4"]
        for d in dockerfiles:
            context = str(Path(d).parent) or "."
            lines += [f"      - run: docker build -t {slug(context)}:ci -f {d} {context}"]
    return "\n".join(lines) + "\n"


def _yaml_str(text: str) -> str:
    return text if re.fullmatch(r"[\w./ =-]+", text) else "'" + text.replace("'", "''") + "'"


# ── Kubernetes ───────────────────────────────────────────────────────────────
def k8s_manifest(t: Target, observability: bool) -> str:
    port = serving_port(t)
    probe: dict[str, Any] = (
        {"httpGet": {"path": t.health, "port": port}} if t.health else {"tcpSocket": {"port": port}}
    )
    env = [{"name": "PORT", "value": str(port)}]
    if observability:
        env.append({"name": "OTEL_SERVICE_NAME", "value": t.name})
    container = {
        "name": t.name,
        "image": f"{t.name}:latest",
        "imagePullPolicy": "IfNotPresent",
        "ports": [{"containerPort": port}],
        "env": env,
        "readinessProbe": probe,
        "livenessProbe": {**probe, "initialDelaySeconds": 10},
        "resources": {"requests": {"cpu": "50m", "memory": "64Mi"}, "limits": {"cpu": "500m", "memory": "256Mi"}},
        "securityContext": {"allowPrivilegeEscalation": False, "readOnlyRootFilesystem": False, "runAsNonRoot": True},
    }
    labels = {"app": t.name}
    deployment = {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {"name": t.name, "labels": labels},
        "spec": {
            "replicas": 2,
            "selector": {"matchLabels": labels},
            "template": {"metadata": {"labels": labels}, "spec": {"containers": [container]}},
        },
    }
    service = {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {"name": t.name, "labels": labels},
        "spec": {"selector": labels, "ports": [{"port": 80, "targetPort": port}]},
    }
    return yaml.safe_dump_all([deployment, service], sort_keys=False)


# ── what to write ────────────────────────────────────────────────────────────
def wants(text: str) -> dict[str, bool]:
    low = text.lower()
    return {
        "kubernetes": bool(re.search(r"kubernetes|k8s|helm|cluster", low)),
        "observability": not re.search(r"no (?:observability|monitoring)", low),
    }


def plan_files(work: Path, request: str) -> tuple[list[GeneratedFile], list[str]]:
    """(files to add, notes on what was left alone). Existing files are never overwritten."""
    opts = wants(request)
    ts = targets(work)
    files: list[GeneratedFile] = []
    notes: list[str] = []

    def add(path: str, content: str, purpose: str) -> None:
        if (work / path).exists():
            notes.append(f"`{path}` already exists and was left as it is")
        else:
            files.append(GeneratedFile(path, content, purpose))

    for t in ts:
        base = "" if t.component.path == "." else t.component.path + "/"
        add(f"{base}Dockerfile", dockerfile(t, work), f"image for {t.name}")
        add(f"{base}.dockerignore", DOCKERIGNORE, f"keeps secrets and junk out of {t.name}'s image")
    if not ts:
        notes.append("No deployable component (web, API or app) was found, so no images were planned")
    existing = [f for f in ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml") if (work / f).exists()]
    if ts and existing:
        notes.append(f"`{existing[0]}` already exists and was left as it is")
    elif ts:
        add("docker-compose.yml", compose_file(ts, work, opts["observability"]), "runs the whole app locally")
    docker_paths = [
        f"{'' if t.component.path == '.' else t.component.path + '/'}Dockerfile" for t in ts
    ]
    add(".github/workflows/ci.yml", ci_workflow(work, docker_paths), "CI: build, lint and test every component")
    if opts["kubernetes"]:
        for t in ts:
            add(f"k8s/{t.name}.yaml", k8s_manifest(t, opts["observability"]), f"Kubernetes Deployment + Service for {t.name}")
    return files, notes


# ── checks on what was written ───────────────────────────────────────────────
def check_files(work: Path, files: list[GeneratedFile]) -> list[dict[str, str]]:
    """Static checks on the generated files. [{file, severity, problem}], empty when clean."""
    problems: list[dict[str, str]] = []

    def bad(path: str, severity: str, what: str) -> None:
        problems.append({"file": path, "severity": severity, "problem": what})

    for f in files:
        text = f.content
        if f.path.endswith("Dockerfile"):
            context = work / Path(f.path).parent
            froms = [ln for ln in text.splitlines() if ln.startswith("FROM ")]
            if any(re.search(r":latest\b|^FROM \S+$", ln.split(" AS ")[0]) and "scratch" not in ln for ln in froms):
                bad(f.path, "major", "a base image has no pinned version tag")
            last = text.rsplit("FROM ", 1)[-1]
            if "USER " not in last and "unprivileged" not in last:
                bad(f.path, "major", "the final image runs as root")
            for ln in text.splitlines():
                m = re.match(r"COPY (?!--from)(.+)\s+\S+$", ln)
                if m:
                    for src in m.group(1).split():
                        if src != "." and not any(context.glob(src)):
                            bad(f.path, "major", f"`COPY {src}` names a file that is not in the build context")
        elif f.path.endswith((".yml", ".yaml")):
            try:
                docs = list(yaml.safe_load_all(text))
            except yaml.YAMLError as err:
                bad(f.path, "critical", f"not valid YAML: {str(err)[:80]}")
                continue
            if f.path.endswith("docker-compose.yml"):
                for name, svc in (docs[0] or {}).get("services", {}).items():
                    if svc.get("privileged") or any("docker.sock" in str(v) for v in svc.get("volumes", [])):
                        bad(f.path, "critical", f"service `{name}` is privileged or mounts the Docker socket")
                    ctx = (svc.get("build") or {}).get("context")
                    if ctx and not (work / ctx).is_dir():
                        bad(f.path, "major", f"service `{name}` builds from `{ctx}`, which does not exist")
        if re.search(r"(?i)(secret|token|api[_-]?key)\s*[:=]\s*['\"]?[A-Za-z0-9]{16,}", text):
            bad(f.path, "critical", "looks like it contains a secret")
    return problems
