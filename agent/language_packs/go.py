"""Go pack: net/http, Gin, Echo, chi, gRPC, GORM, cobra. go build · go test · go vet + gofmt."""

from __future__ import annotations

import re
from pathlib import Path

from agent.language_packs import compose, reports, templates
from agent.language_packs.base import (
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

FRAMEWORKS = {
    "github.com/gin-gonic/gin": "gin",
    "github.com/labstack/echo": "echo",
    "github.com/go-chi/chi": "chi",
    "github.com/gofiber/fiber": "fiber",
    "google.golang.org/grpc": "grpc",
    "gorm.io/gorm": "gorm",
    "github.com/jinzhu/gorm": "gorm",
    "github.com/spf13/cobra": "cobra",
    "github.com/urfave/cli": "urfave-cli",
    "github.com/jmoiron/sqlx": "sqlx",
    "github.com/jackc/pgx": "pgx",
    "github.com/redis/go-redis": "go-redis",
}
SERVER_FRAMEWORKS = {"gin", "echo", "chi", "fiber", "grpc", "net/http"}
CLI_FRAMEWORKS = {"cobra", "urfave-cli"}

_ROUTE = re.compile(
    r"\b(\w+)\.(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS|Any|Get|Post|Put|Patch|Delete)\(\s*\"([^\"]*)\"\s*,\s*([^)\n]*)"
)
_GROUP = re.compile(r"\b(\w+)\s*:?=\s*(\w+)\.(?:Group|Route)\(\s*\"([^\"]*)\"")
_HANDLE = re.compile(r"\b(?:http\.)?(?:\w+\.)?(HandleFunc|Handle)\(\s*\"([^\"]+)\"\s*,\s*([^)\n]*)")
_STRUCT = re.compile(r"^type\s+(\w+)\s+struct\s*\{(.*?)^\}", re.MULTILINE | re.DOTALL)
_COBRA = re.compile(r"cobra\.Command\{[^}]*?Use:\s*\"([\w-]+)", re.DOTALL)
_PROTO_SERVICE = re.compile(r"^service\s+(\w+)\s*\{(.*?)^\}", re.MULTILINE | re.DOTALL)
_RPC = re.compile(r"rpc\s+(\w+)\s*\(\s*(?:stream\s+)?([\w.]+)\s*\)\s*returns\s*\(\s*(?:stream\s+)?([\w.]+)")
_MAIN = re.compile(r"^package\s+main\b.*?^func\s+main\s*\(", re.MULTILINE | re.DOTALL)
_LISTEN = re.compile(r"""(?:ListenAndServe|\.Run|\.Start|Listen)\(\s*["'][^"':]*:(\d{2,5})["']""")


def _module(go_mod: str) -> str:
    match = re.search(r"^module\s+(\S+)", go_mod, re.MULTILINE)
    return match.group(1) if match else ""


def _go_version(go_mod: str) -> str:
    match = re.search(r"^go\s+(\d+\.\d+)", go_mod, re.MULTILINE)
    return match.group(1) if match else ""


class GoPack:
    name = "go"
    language = "Go"
    toolchain: Toolchain = "go"

    # ── detect ───────────────────────────────────────────────────────────────
    def detect(self, repo: Path) -> list[Component]:
        components = []
        for go_mod in manifests(repo, "go.mod"):
            root = go_mod.parent
            text = read(go_mod)
            frameworks = sorted({fw for path, fw in FRAMEWORKS.items() if path in text})
            mains: list[str] = []
            serves_http = False
            for f in walk(root, (".go",)):
                if f.name.endswith("_test.go"):
                    continue
                src = read(f, 200_000)
                if _MAIN.search(src):
                    mains.append(rel(f.parent, root))
                if "net/http" in src and ("ListenAndServe" in src or "http.Server{" in src):
                    serves_http = True
            if serves_http and not SERVER_FRAMEWORKS & set(frameworks):
                frameworks.append("net/http")
            mains = sorted(set(mains), key=lambda p: (not p.startswith("cmd/"), p))
            if not mains:
                kind = "library"
            elif SERVER_FRAMEWORKS & set(frameworks):
                kind = "api"
            else:
                kind = "cli"
            components.append(
                Component(
                    pack=self.name,
                    path=rel(root, repo),
                    kind=kind,
                    frameworks=sorted(frameworks),
                    entrypoints=["./" + m if m != "." else "." for m in mains],
                    manifest="go.mod",
                    details={
                        "module": _module(text),
                        "go": _go_version(text),
                        "has_go_sum": (root / "go.sum").exists(),
                    },
                )
            )
        return components

    # ── parse ────────────────────────────────────────────────────────────────
    def parse(self, repo: Path, component: Component) -> GraphFragment:  # noqa: PLR0912  (one branch per framework)
        root = repo / component.path
        g = GraphFragment()
        for f in walk(root, (".go", ".proto")):
            name = rel(f, repo)
            src = read(f, 400_000)
            if f.suffix == ".proto":
                for svc in _PROTO_SERVICE.finditer(src):
                    sid = g.node("grpc_service", svc.group(1), name, line_of(src, svc.start()))
                    for rpc in _RPC.finditer(svc.group(2)):
                        rid = g.node(
                            "rpc", f"{svc.group(1)}.{rpc.group(1)}", name, line_of(src, svc.start(2) + rpc.start())
                        )
                        g.edge(sid, rid, "declares", 1.0)
                continue
            if f.name.endswith("_test.go"):
                continue
            prefixes: dict[str, str] = {}
            for grp in _GROUP.finditer(src):
                prefixes[grp.group(1)] = prefixes.get(grp.group(2), "") + grp.group(3)
            for m in _ROUTE.finditer(src):
                var, method, path, handler = m.groups()
                full = (prefixes.get(var, "") + path) or "/"
                handler = handler.strip().split(",")[-1].strip()
                if handler.startswith("func"):
                    handler = ""  # an inline handler: no name to link to
                rid = g.node("route", f"{method.upper()} {full}", name, line_of(src, m.start()), handler=handler)
                if handler:
                    g.edge(rid, f"handler:{handler}", "handled_by", 0.7)
            for m in _HANDLE.finditer(src):
                rid = g.node("route", f"ANY {m.group(2)}", name, line_of(src, m.start()), handler=m.group(3).strip())
                g.edge(rid, f"handler:{m.group(3).strip()}", "handled_by", 0.7)
            for m in _STRUCT.finditer(src):
                body = m.group(2)
                if "gorm.Model" in body or 'gorm:"' in body:
                    g.node("model", m.group(1), name, line_of(src, m.start()), orm="gorm")
            for m in _COBRA.finditer(src):
                g.node("command", m.group(1), name, line_of(src, m.start()))
        return g

    # ── build / test / lint / run ────────────────────────────────────────────
    def build_steps(self, repo: Path, component: Component) -> list[Step]:
        wd = component.path
        return [
            Step("install", "go", ["go", "mod", "download"], wd),
            Step("build", "go", ["go", "build", "./..."], wd),
        ]

    def test_steps(self, repo: Path, component: Component) -> list[Step]:
        # Offline: modules are already in the cache after `install`, and tests get no network at all.
        offline = {"GOFLAGS": "-buildvcs=false -mod=mod", "GOPROXY": "off"}
        return [
            Step("test", "go", ["go", "test", "-json", "./..."], component.path, "none", env=offline, report="go-json")
        ]

    def lint_steps(self, repo: Path, component: Component) -> list[Step]:
        wd = component.path
        return [
            Step("vet", "go", ["go", "vet", "./..."], wd, "none", env={"GOPROXY": "off"}),
            Step(
                "gofmt", "go", ["sh", "-c", 'out=$(gofmt -l .); [ -z "$out" ] || { echo "$out"; exit 1; }'], wd, "none"
            ),
        ]

    def run_spec(self, repo: Path, component: Component) -> RunSpec | None:
        if not component.entrypoints:
            return None
        cf = compose.find(repo, component.path)
        app = compose.app_for(cf, component.path)
        main = self._preferred_main(component)
        binary = f"{STATE}/bin/app"
        prepare = [
            Step("install", "go", ["go", "mod", "download"], component.path),
            Step("build", "go", ["go", "build", "-o", binary, main], component.path),
        ]
        if component.kind != "api":
            return RunSpec("terminal", "go", ["./" + binary], component.path, prepare=prepare, name=main)
        port = (app.port if app else None) or self._port(repo, component) or 8080
        env = dict(app.env) if app else {}
        services = [s for s in (cf.services if cf else []) if not app or not app.depends_on or s.name in app.depends_on]
        return RunSpec(
            "web", "go", ["./" + binary], component.path, port, env, services, prepare, name=app.name if app else main
        )

    def _preferred_main(self, component: Component) -> str:
        for preferred in ("./cmd/api", "./cmd/server", "./cmd/app", "./cmd/web", "."):
            if preferred in component.entrypoints:
                return preferred
        return component.entrypoints[0]

    def _port(self, repo: Path, component: Component) -> int | None:
        for f in walk(repo / component.path, (".go",)):
            if m := _LISTEN.search(read(f, 200_000)):
                return int(m.group(1))
        return None

    def read_report(self, repo: Path, component: Component, step: Step, output: str) -> TestReport:
        return reports.go_json(output)

    # ── generate ─────────────────────────────────────────────────────────────
    def scaffold_service(self, spec: ServiceSpec, out: Path) -> None:
        templates.scaffold(spec, out)

    def client_stub(self, contract: Contract, out: Path) -> Path:
        pkg = re.sub(r"\W", "", contract.service.lower()) or "client"
        lines = [
            f"// Package {pkg} is a client for the {contract.service} API. Generated by Codewright; edit freely.",
            f"package {pkg}",
            "",
            "import (",
            '\t"bytes"',
            '\t"context"',
            '\t"encoding/json"',
            '\t"fmt"',
            '\t"net/http"',
            '\t"strings"',
            ")",
            "",
            "type Client struct {",
            "\tBaseURL string",
            "\tHTTP    *http.Client",
            "}",
            "",
            f'func New(baseURL string) *Client {{\n\tif baseURL == "" {{\n\t\tbaseURL = "{contract.base_url}"\n\t}}'
            '\n\treturn &Client{BaseURL: strings.TrimRight(baseURL, "/"), HTTP: http.DefaultClient}\n}',
            "",
            "func (c *Client) do(ctx context.Context, method, path string, in, out any) error {",
            "\tvar body bytes.Buffer",
            "\tif in != nil {",
            "\t\tif err := json.NewEncoder(&body).Encode(in); err != nil {",
            "\t\t\treturn err",
            "\t\t}",
            "\t}",
            "\treq, err := http.NewRequestWithContext(ctx, method, c.BaseURL+path, &body)",
            "\tif err != nil {",
            "\t\treturn err",
            "\t}",
            '\treq.Header.Set("Content-Type", "application/json")',
            "\tresp, err := c.HTTP.Do(req)",
            "\tif err != nil {",
            "\t\treturn err",
            "\t}",
            "\tdefer resp.Body.Close()",
            "\tif resp.StatusCode >= 300 {",
            '\t\treturn fmt.Errorf("%s %s: %s", method, path, resp.Status)',
            "\t}",
            "\tif out == nil {",
            "\t\treturn nil",
            "\t}",
            "\treturn json.NewDecoder(resp.Body).Decode(out)",
            "}",
        ]
        for ep in contract.endpoints:
            params = re.findall(r"\{(\w+)\}", ep.path)
            fmt_path = re.sub(r"\{\w+\}", "%s", ep.path)
            name = ep.name[:1].upper() + ep.name[1:]
            args = ["ctx context.Context", *(f"{p} string" for p in params)]
            if ep.request:
                args.append("in any")
            path_expr = f'fmt.Sprintf("{fmt_path}", {", ".join(params)})' if params else f'"{ep.path}"'
            lines += [
                "",
                f"// {name} calls {ep.method} {ep.path}.",
                f"func (c *Client) {name}({', '.join(args)}, out any) error {{",
                f'\treturn c.do(ctx, "{ep.method}", {path_expr}, {"in" if ep.request else "nil"}, out)',
                "}",
            ]
        path = out / f"{pkg}.go"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def docker_base(self) -> DockerSpec:
        return DockerSpec(
            "go",
            "golang:1.26-bookworm",
            "FROM golang:1.26-bookworm AS build\nWORKDIR /src\nCOPY go.mod go.sum* ./\nRUN go mod download\n"
            "COPY . .\nRUN CGO_ENABLED=0 go build -trimpath -ldflags='-s -w' -o /out/app ./cmd/{name}\n\n"
            "FROM gcr.io/distroless/static-debian12:nonroot\nCOPY --from=build /out/app /app\nEXPOSE {port}\n"
            'ENTRYPOINT ["/app"]\n',
        )

    def instrumentation(self) -> InstrumentationSpec:
        return InstrumentationSpec(
            packages=[
                "go.opentelemetry.io/otel",
                "go.opentelemetry.io/otel/sdk",
                "go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracegrpc",
                "go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp",
            ],
            env={"OTEL_EXPORTER_OTLP_ENDPOINT": "http://jaeger:4317", "OTEL_SERVICE_NAME": "{name}"},
            notes="Wrap the HTTP handler with otelhttp.NewHandler; Gin: go.opentelemetry.io/contrib/.../otelgin.",
        )
