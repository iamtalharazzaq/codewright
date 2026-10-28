"""TypeScript and JavaScript packs (one implementation, two packs): React (Vite), Next.js, Node (Express, NestJS),
libraries and CLIs. npm/pnpm/yarn · Vitest/Jest · eslint, tsc.

A `package.json` belongs to the TypeScript pack when it has a `tsconfig.json`, depends on `typescript`, or most of
its sources are `.ts`/`.tsx`; otherwise to the JavaScript pack. Playwright end-to-end tests need browsers, which the
Node image doesn't ship yet; they run from Phase 7 (verification).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from agent.language_packs import compose, reports, templates
from agent.language_packs.base import (
    REPORTS,
    Component,
    Contract,
    DockerSpec,
    GraphFragment,
    InstrumentationSpec,
    RunSpec,
    ServiceSpec,
    Step,
    TestCase,
    TestReport,
    Toolchain,
    line_of,
    manifests,
    read,
    read_json,
    rel,
    walk,
)

TS = (".ts", ".tsx", ".mts", ".cts")
JS = (".js", ".jsx", ".mjs", ".cjs")
FRAMEWORKS = {
    "next": "next",
    "react": "react",
    "vite": "vite",
    "express": "express",
    "@nestjs/core": "nestjs",
    "fastify": "fastify",
    "koa": "koa",
    "vitest": "vitest",
    "jest": "jest",
    "@playwright/test": "playwright",
    "prisma": "prisma",
    "@prisma/client": "prisma",
    "typeorm": "typeorm",
    "drizzle-orm": "drizzle",
    "commander": "commander",
    "yargs": "yargs",
    "eslint": "eslint",
}
SERVERS = {"express", "nestjs", "fastify", "koa"}

_ROUTE = re.compile(
    r"\b(app|router|server|api|\w+Router)\.(get|post|put|patch|delete|all|use)\(\s*[\"'`]([^\"'`]+)[\"'`]"
)
_NEST_CONTROLLER = re.compile(r"@Controller\(\s*[\"'`]?([^\"'`)]*)[\"'`]?\s*\)")
_NEST_METHOD = re.compile(r"@(Get|Post|Put|Patch|Delete|All)\(\s*[\"'`]?([^\"'`)]*)[\"'`]?\s*\)")
_REQUIRE = re.compile(r"""(?:const|let|var|import)\s+(\w+)\s*(?:=\s*require\(\s*|from\s+)["'](\.[^"']+)["']""")
_MOUNT = re.compile(r"""\b\w+\.use\(\s*["'`](/[^"'`]*)["'`]\s*,\s*(\w+)\s*\)""")
_COMPONENT = re.compile(r"^export\s+(?:default\s+)?(?:function|const)\s+([A-Z]\w*)", re.MULTILINE)
_RR_ROUTE = re.compile(r"""<Route\b[^>]*\bpath=["']([^"']+)["']|\bpath:\s*["'](/[^"']*)["']""")
_ENTITY = re.compile(r"@Entity\([^)]*\)\s*(?:export\s+)?class\s+(\w+)")
_PRISMA_MODEL = re.compile(r"^model\s+(\w+)\s*\{", re.MULTILINE)
_LISTEN = re.compile(r"\.listen\(\s*(?:process\.env\.PORT\s*(?:\|\||\?\?)\s*)?(\d{2,5})")


COVERAGE_PLUGINS = ("@vitest/coverage-v8", "@vitest/coverage-istanbul")


def _deps(pkg: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for key in ("dependencies", "devDependencies", "peerDependencies"):
        if isinstance(pkg.get(key), dict):
            out.update(pkg[key])
    return out


def _manager(root: Path, repo: Path) -> str:
    for folder in (root, *root.parents):
        if (folder / "pnpm-lock.yaml").exists():
            return "pnpm"
        if (folder / "yarn.lock").exists():
            return "yarn"
        if (folder / "package-lock.json").exists():
            return "npm-ci"
        if folder == repo:
            break
    return "npm"


def is_typescript(root: Path, pkg: dict[str, Any]) -> bool:
    if (root / "tsconfig.json").exists() or "typescript" in _deps(pkg):
        return True
    ts = sum(1 for _ in walk(root, TS, limit=2000))
    js = sum(1 for _ in walk(root, JS, limit=2000))
    return ts > js


class NodePack:
    toolchain: Toolchain = "node"

    def __init__(self, typescript: bool) -> None:
        self.typescript = typescript
        self.name = "typescript" if typescript else "javascript"
        self.language = "TypeScript" if typescript else "JavaScript"

    # ── detect ───────────────────────────────────────────────────────────────
    def detect(self, repo: Path) -> list[Component]:
        components = []
        for manifest in manifests(repo, "package.json"):
            root = manifest.parent
            pkg = read_json(manifest)
            if not pkg or (isinstance(pkg.get("workspaces"), (list, dict)) and not _deps(pkg).keys() - {"typescript"}):
                continue  # a bare monorepo root: its packages are components of their own
            if is_typescript(root, pkg) != self.typescript:
                continue
            deps = _deps(pkg)
            frameworks = sorted({fw for dep, fw in FRAMEWORKS.items() if dep in deps})
            raw_scripts = pkg.get("scripts")
            scripts: dict[str, Any] = raw_scripts if isinstance(raw_scripts, dict) else {}
            bins = pkg.get("bin")
            bin_files = list(bins.values()) if isinstance(bins, dict) else ([bins] if isinstance(bins, str) else [])
            if "next" in frameworks:
                kind = "web"
            elif SERVERS & set(frameworks):
                kind = "api"
            elif "react" in frameworks or "vite" in frameworks:
                kind = "web"
            elif bin_files:
                kind = "cli"
            elif "start" in scripts or (pkg.get("main") and not pkg.get("types")):
                kind = "app"
            else:
                kind = "library"
            entry = [str(b) for b in bin_files] or ([str(pkg["main"])] if pkg.get("main") else [])
            components.append(
                Component(
                    pack=self.name,
                    path=rel(root, repo),
                    kind=kind,
                    frameworks=frameworks,
                    entrypoints=entry,
                    manifest="package.json",
                    details={
                        "name": pkg.get("name", ""),
                        "manager": _manager(root, repo),
                        "scripts": sorted(scripts),
                        "has_tsconfig": (root / "tsconfig.json").exists(),
                        "module": pkg.get("type", "commonjs"),
                        "coverage": next((d for d in COVERAGE_PLUGINS if d in deps), ""),
                    },
                )
            )
        return components

    # ── parse ────────────────────────────────────────────────────────────────
    def _mounts(self, files: list[Path]) -> dict[Path, str]:
        """Express/Koa routers mounted with `app.use("/prefix", router)`: router file → prefix."""
        prefixes: dict[Path, str] = {}
        for f in files:
            src = read(f, 400_000)
            imports = dict(_REQUIRE.findall(src))
            for prefix, var in _MOUNT.findall(src):
                if var not in imports:
                    continue
                base = (f.parent / imports[var]).resolve()
                candidates = [base, *(base.with_suffix(e) for e in TS + JS), *(base / f"index{e}" for e in TS + JS)]
                if found := next((c for c in candidates if c.is_file()), None):
                    prefixes[found] = prefix.rstrip("/")
        return prefixes

    def parse(self, repo: Path, component: Component) -> GraphFragment:  # noqa: PLR0912  (one branch per framework)
        root = repo / component.path
        g = GraphFragment()
        exts = TS + JS
        files = list(walk(root, (*exts, ".prisma")))
        mounts = self._mounts([f for f in files if f.suffix != ".prisma"])
        mounted = set(mounts.values())
        for f in files:
            name = rel(f, repo)
            src = read(f, 400_000)
            prefix = mounts.get(f.resolve(), "")
            if f.suffix == ".prisma":
                for m in _PRISMA_MODEL.finditer(src):
                    g.node("model", m.group(1), name, line_of(src, m.start()), orm="prisma")
                continue
            local = f.relative_to(root).as_posix()
            if "next" in component.frameworks:
                self._next_route(g, local, name)
            if ".test." in f.name or ".spec." in f.name or "__tests__" in local:
                continue
            for m in _ROUTE.finditer(src):
                method = m.group(2).upper()
                if method == "USE" and (not m.group(3).startswith("/") or m.group(3).rstrip("/") in mounted):
                    continue  # middleware, or a router mount (the router's own routes carry the prefix)
                path = ((prefix + m.group(3)).rstrip("/") or "/") if prefix else m.group(3)
                g.node(
                    "route",
                    f"{'ANY' if method in {'ALL', 'USE'} else method} {path}",
                    name,
                    line_of(src, m.start()),
                )
            if ctrl := _NEST_CONTROLLER.search(src):
                base = "/" + ctrl.group(1).strip("/") if ctrl.group(1) else ""
                for m in _NEST_METHOD.finditer(src):
                    path = (base + ("/" + m.group(2).strip("/") if m.group(2) else "")) or "/"
                    g.node("route", f"{m.group(1).upper()} {path}", name, line_of(src, m.start()))
            if f.suffix in {".tsx", ".jsx"}:
                for m in _COMPONENT.finditer(src):
                    g.node("component", m.group(1), name, line_of(src, m.start()))
                for m in _RR_ROUTE.finditer(src):
                    path = m.group(1) or m.group(2)
                    g.node("page", path, name, line_of(src, m.start()), router="react-router")
            for m in _ENTITY.finditer(src):
                g.node("model", m.group(1), name, line_of(src, m.start()), orm="typeorm")
        return g

    def _next_route(self, g: GraphFragment, local: str, name: str) -> None:
        parts = local.split("/")
        if parts and parts[0] == "src":
            parts = parts[1:]
        if not parts:
            return
        stem = parts[-1].rsplit(".", 1)[0]
        segments = [p for p in parts[1:-1] if not (p.startswith("(") and p.endswith(")")) and not p.startswith("@")]
        path = "/" + "/".join(segments)
        if parts[0] == "app" and stem in {"page", "route"}:
            g.node(
                "page" if stem == "page" else "route",
                path if stem == "page" else f"ANY {path}",
                name,
                1,
                router="next-app",
            )
        elif parts[0] == "pages" and not stem.startswith("_"):
            sub = [*segments, *([] if stem == "index" else [stem])]
            kind = "route" if sub and sub[0] == "api" else "page"
            label = "/" + "/".join(sub)
            g.node(kind, f"ANY {label}" if kind == "route" else label, name, 1, router="next-pages")

    # ── build / test / lint / run ────────────────────────────────────────────
    def _install(self, component: Component) -> Step:
        manager = component.details.get("manager", "npm")
        cmd = {
            "pnpm": ["pnpm", "install", "--frozen-lockfile"],
            "yarn": ["sh", "-c", "yarn install --immutable || yarn install --frozen-lockfile"],
            "npm-ci": ["npm", "ci", "--no-audit", "--no-fund"],
            "npm": ["npm", "install", "--no-audit", "--no-fund"],
        }[manager]
        return Step("install", "node", cmd, component.path)

    def _script(self, component: Component, script: str) -> list[str]:
        manager = component.details.get("manager", "npm")
        return ["pnpm" if manager == "pnpm" else "yarn" if manager == "yarn" else "npm", "run", script]

    def build_steps(self, repo: Path, component: Component) -> list[Step]:
        steps = [self._install(component)]
        scripts = component.details.get("scripts", [])
        if "build" in scripts:
            steps.append(Step("build", "node", self._script(component, "build"), component.path, "none"))
        elif self.typescript and component.details.get("has_tsconfig"):
            steps.append(Step("build", "node", ["npx", "--no-install", "tsc", "--noEmit"], component.path, "none"))
        return steps

    def test_steps(self, repo: Path, component: Component) -> list[Step]:
        fw = set(component.frameworks)
        wd = component.path
        cover = f"{REPORTS}/coverage"
        if "vitest" in fw:
            cmd = ["npx", "--no-install", "vitest", "run", "--reporter=default", "--reporter=junit",
                   f"--outputFile.junit={REPORTS}/junit.xml"]  # fmt: skip
            if component.details.get("coverage"):  # @vitest/coverage-v8 or -istanbul is installed
                cmd += [
                    "--coverage.enabled=true",
                    "--coverage.reporter=cobertura",
                    f"--coverage.reportsDirectory={cover}",
                ]
            return [Step("test", "node", cmd, wd, "none", report="junit")]
        if "jest" in fw:  # coverage is built into Jest
            cmd = ["npx", "--no-install", "jest", "--ci", "--json", f"--outputFile={REPORTS}/jest.json", "--coverage",
                   "--coverageReporters=cobertura", f"--coverageDirectory={cover}"]  # fmt: skip
            return [Step("test", "node", cmd, wd, "none", report="jest-json")]
        if "test" in component.details.get("scripts", []):
            return [Step("test", "node", self._script(component, "test"), wd, "none")]
        return []

    def lint_steps(self, repo: Path, component: Component) -> list[Step]:
        steps = []
        wd = component.path
        if "lint" in component.details.get("scripts", []):
            steps.append(Step("lint", "node", self._script(component, "lint"), wd, "none"))
        elif "eslint" in component.frameworks:
            steps.append(Step("eslint", "node", ["npx", "--no-install", "eslint", "."], wd, "none"))
        if self.typescript and component.details.get("has_tsconfig"):
            steps.append(Step("tsc", "node", ["npx", "--no-install", "tsc", "--noEmit", "-p", "."], wd, "none"))
        return steps

    def run_spec(self, repo: Path, component: Component) -> RunSpec | None:
        cf = compose.find(repo, component.path)
        app = compose.app_for(cf, component.path)
        env = dict(app.env) if app else {}
        services = list(cf.services) if cf and component.kind == "api" else []
        prepare = [self._install(component)]
        fw = set(component.frameworks)
        wd = component.path
        label = component.details.get("name") or component.path
        if "next" in fw:
            cmd = ["npx", "--no-install", "next", "dev", "-H", "0.0.0.0", "-p", "3000"]
            return RunSpec("web", "node", cmd, wd, 3000, env, services, prepare, label)
        if "vite" in fw:
            cmd = ["npx", "--no-install", "vite", "--host", "0.0.0.0", "--port", "5173", "--strictPort"]
            return RunSpec("web", "node", cmd, wd, 5173, env, services, prepare, label)
        if component.kind == "api":
            port = (app.port if app else None) or self._port(repo, component) or 3000
            env.setdefault("PORT", str(port))
            env.setdefault("HOST", "0.0.0.0")
            scripts = component.details.get("scripts", [])
            if "build" in scripts:
                prepare.append(Step("build", "node", self._script(component, "build"), wd, "none"))
            if "start" in scripts:
                cmd = self._script(component, "start")
            elif "dev" in scripts:
                cmd = self._script(component, "dev")
            else:
                cmd = ["node", component.entrypoints[0] if component.entrypoints else "index.js"]
            return RunSpec("web", "node", cmd, wd, port, env, services, prepare, label)
        if component.kind in {"cli", "app"}:
            scripts = component.details.get("scripts", [])
            if "build" in scripts:
                prepare.append(Step("build", "node", self._script(component, "build"), wd, "none"))
            if "start" in scripts:
                cmd = self._script(component, "start")
            else:
                cmd = ["node", component.entrypoints[0] if component.entrypoints else "index.js"]
            return RunSpec("terminal", "node", cmd, wd, env=env, prepare=prepare, name=label)
        return None

    def _port(self, repo: Path, component: Component) -> int | None:
        for f in walk(repo / component.path, TS + JS, limit=3000):
            if m := _LISTEN.search(read(f, 200_000)):
                return int(m.group(1))
        return None

    def read_report(self, repo: Path, component: Component, step: Step, output: str) -> TestReport:
        base = repo / component.path / REPORTS
        if step.report == "junit":
            report = reports.junit([base / "junit.xml"], "vitest")
        elif step.report == "jest-json":
            report = jest_json(base / "jest.json")
        else:
            return TestReport(tool="npm test", found=False)
        report.coverage = reports.cobertura(base / "coverage" / "cobertura-coverage.xml", report.tool)
        return report

    # ── generate ─────────────────────────────────────────────────────────────
    def scaffold_service(self, spec: ServiceSpec, out: Path) -> None:
        templates.scaffold(spec, out)

    def client_stub(self, contract: Contract, out: Path) -> Path:
        cls = "".join(w.title() for w in re.split(r"\W+", contract.service) if w) + "Client"
        ts = self.typescript
        lines = [
            f"// Client for the {contract.service} API. Generated by Codewright; edit freely.",
            "",
            f"export class {cls} {{",
            f'  constructor({"private readonly baseUrl: string" if ts else "baseUrl"} = "{contract.base_url}") {{',
            *([] if ts else ["    this.baseUrl = baseUrl;"]),
            "  }",
            "",
            f"  {'private async' if ts else 'async'} call(method{': string' if ts else ''}, "
            f"path{': string' if ts else ''}, body{'?: unknown' if ts else ''}){': Promise<unknown>' if ts else ''} {{",
            "    const response = await fetch(this.baseUrl.replace(/\\/$/, '') + path, {",
            "      method,",
            '      headers: { "Content-Type": "application/json" },',
            "      body: body === undefined ? undefined : JSON.stringify(body),",
            "    });",
            "    if (!response.ok) throw new Error(`${method} ${path}: ${response.status}`);",
            "    const text = await response.text();",
            "    return text ? JSON.parse(text) : undefined;",
            "  }",
        ]
        for ep in contract.endpoints:
            params = re.findall(r"\{(\w+)\}", ep.path)
            args = [f"{p}{': string' if ts else ''}" for p in params] + (
                [f"body{': unknown' if ts else ''}"] if ep.request else []
            )
            path = "`" + re.sub(r"\{(\w+)\}", r"${encodeURIComponent(\1)}", ep.path) + "`"
            lines += [
                "",
                f"  /** {ep.method} {ep.path} */",
                f"  {ep.name}({', '.join(args)}){': Promise<unknown>' if ts else ''} {{",
                f'    return this.call("{ep.method}", {path}{", body" if ep.request else ""});',
                "  }",
            ]
        lines.append("}")
        name = re.sub(r"\W+", "-", contract.service.lower()) + "-client" + (".ts" if ts else ".js")
        target = out / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return target

    def docker_base(self) -> DockerSpec:
        return DockerSpec(
            "node",
            "node:22-bookworm-slim",
            "FROM node:22-bookworm-slim AS build\nWORKDIR /app\nCOPY package*.json ./\nRUN npm ci\nCOPY . .\n"
            "RUN npm run build --if-present\n\nFROM node:22-bookworm-slim\nWORKDIR /app\nENV NODE_ENV=production\n"
            'COPY --from=build /app ./\nUSER node\nEXPOSE {port}\nCMD ["npm", "start"]\n',
        )

    def instrumentation(self) -> InstrumentationSpec:
        return InstrumentationSpec(
            packages=[
                "@opentelemetry/sdk-node",
                "@opentelemetry/auto-instrumentations-node",
                "@opentelemetry/exporter-trace-otlp-grpc",
            ],
            env={
                "OTEL_EXPORTER_OTLP_ENDPOINT": "http://jaeger:4317",
                "OTEL_SERVICE_NAME": "{name}",
                "NODE_OPTIONS": "--require @opentelemetry/auto-instrumentations-node/register",
            },
            notes="Auto-instrumentation covers http, express, pg and redis without code changes.",
        )


def jest_json(path: Path) -> TestReport:
    report = TestReport(tool="jest", found=path.is_file())
    if not report.found:
        return report
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except ValueError:
        report.found = False
        return report
    cases = []
    for suite in data.get("testResults", []):
        for t in suite.get("assertionResults", []):
            status = {"passed": "passed", "failed": "failed"}.get(t.get("status"), "skipped")
            message = "\n".join(t.get("failureMessages") or [])[:2000]
            cases.append(TestCase(t.get("fullName", "?"), status, message, suite.get("name", "")))  # type: ignore[arg-type]
    for suite in data.get("testResults", []):
        if suite.get("status") == "failed" and not suite.get("assertionResults"):
            cases.append(TestCase(suite.get("name", "?"), "error", (suite.get("message") or "")[:2000]))
    reports.count(report, cases)
    return report
