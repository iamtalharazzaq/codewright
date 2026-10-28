"""The audit's As-Is facts (CODEWRIGHT.md Section 5.4 step 2, as in 5.18 step 3), computed from the code, not by the
model: the stack (Language Packs + compose), data stores, the database map, coupling, hotspots and test coverage by
file count, and the C4 / dependency / database diagrams drawn from them as Mermaid.
"""

from __future__ import annotations

import json
import math
import re
import subprocess
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from agent.knowledge_graph import module_of
from agent.language_packs import detect_project, pack
from agent.language_packs.compose import find as find_compose
from agent.playbooks.review_core import TEST_FILE, code_files
from agent.tools.workspace import git

MAX_DIAGRAM_MODULES = 24
_CREATE_TABLE = re.compile(r"create\s+table\s+(?:if\s+not\s+exists\s+)?[`\"\[]?(?:\w+\.)?(\w+)", re.I)
_STORE_HINTS = {
    "postgres": "PostgreSQL", "pgvector": "PostgreSQL", "postgis": "PostgreSQL", "mysql": "MySQL", "mariadb": "MariaDB",
    "mongo": "MongoDB", "redis": "Redis", "valkey": "Redis", "rabbitmq": "RabbitMQ", "kafka": "Kafka",
    "elasticsearch": "Elasticsearch", "minio": "S3 storage", "memcached": "Memcached", "nats": "NATS",
}  # fmt: skip
_FRAMEWORK_STORES = {
    "go-redis": "Redis", "redis": "Redis", "ioredis": "Redis", "gorm": "SQL database", "pgx": "PostgreSQL",
    "sqlalchemy": "SQL database", "prisma": "SQL database", "typeorm": "SQL database", "mongoose": "MongoDB",
    "django": "SQL database",
}  # fmt: skip


# ── stack ────────────────────────────────────────────────────────────────────
def stack(work: Path) -> dict[str, Any]:
    components: list[dict[str, Any]] = []
    for c in detect_project(work):
        try:
            fragment = pack(c.pack).parse(work, c)
            kinds = Counter(n["kind"] for n in fragment.nodes)
            nodes = fragment.nodes
        except Exception:  # a pack failing to parse one project must not stop the audit
            kinds, nodes = Counter(), []
        components.append(
            {
                "path": c.path,
                "pack": c.pack,
                "kind": c.kind,
                "frameworks": c.frameworks,
                "entrypoints": c.entrypoints,
                "counts": dict(kinds),
                "routes": [f"{n['label']} ({n['file']}:{n['line']})" for n in nodes if n["kind"] == "route"][:200],
                "models": sorted({n["label"] for n in nodes if n["kind"] == "model"}),
            }
        )
    compose = find_compose(work)
    stores: dict[str, str] = {}
    if compose is not None:
        for svc in compose.services:
            repo = svc.image.split("/")[-1].split(":")[0]
            if name := next((v for k, v in _STORE_HINTS.items() if k in repo), None):
                stores[svc.name] = name
        for image in compose.skipped:
            if name := next((v for k, v in _STORE_HINTS.items() if k in image), None):
                stores[image.split("/")[-1].split(":")[0]] = name
    for comp in components:
        for fw in comp["frameworks"]:
            if fw in _FRAMEWORK_STORES and _FRAMEWORK_STORES[fw] not in stores.values():
                stores[fw] = _FRAMEWORK_STORES[fw]
    if {"PostgreSQL", "MySQL", "MariaDB", "SQLite"} & set(stores.values()):
        # An ORM ("SQL database") names no store of its own when the real database is known.
        stores = {k: v for k, v in stores.items() if v != "SQL database"}
    return {
        "components": components,
        "data_stores": [{"name": k, "kind": v} for k, v in stores.items()],
        "compose": compose.path if compose else None,
    }


# ── the database map ─────────────────────────────────────────────────────────
def tables(work: Path, models: list[str]) -> list[str]:
    found: set[str] = set()
    for sql in work.rglob("*.sql"):
        if any(p in ("node_modules", ".git", "vendor") for p in sql.parts):
            continue
        try:
            found |= {t.lower() for t in _CREATE_TABLE.findall(sql.read_text(encoding="utf-8", errors="replace"))}
        except OSError:
            continue
    if not found:  # no SQL: the ORM models are the tables
        found = {m.lower() for m in models}
    return sorted(found)


def db_map(work: Path, table_names: list[str], files: list[str]) -> list[dict[str, Any]]:
    """For each table: the modules whose code names it (table or model name), the likely owner and whether shared."""
    if not table_names:
        return []
    patterns = {t: re.compile(rf"\b{re.escape(t.rstrip('s'))}s?\b", re.I) for t in table_names}
    hits: dict[str, Counter[str]] = defaultdict(Counter)
    for f in files:
        module = module_of(f)
        if module is None or TEST_FILE.search(f) or "migration" in f.lower():
            continue
        try:
            text = (work / f).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for table, pattern in patterns.items():
            n = len(pattern.findall(text))
            if n:
                hits[table][module] += n
    rows = []
    for table in table_names:
        users = hits.get(table, Counter())
        owner = users.most_common(1)[0][0] if users else None
        rows.append(
            {
                "table": table,
                "owner": owner,
                "used_by": [m for m, _ in users.most_common(6)],
                "shared": len(users) > 1,
            }
        )
    return rows


# ── hotspots and coupling ────────────────────────────────────────────────────
def churn(work: Path, max_commits: int = 500) -> Counter[str]:
    try:
        log = git(work, "log", f"-{max_commits}", "--name-only", "--format=tformat:", check=False, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return Counter()
    return Counter(line.strip() for line in log.splitlines() if line.strip())


def hotspots(work: Path, files: list[str], commits: Counter[str], limit: int = 10) -> list[dict[str, Any]]:
    """Files that change often and are large: where bugs and slow changes concentrate (churn x size)."""
    rows: list[dict[str, Any]] = []
    for f in files:
        if TEST_FILE.search(f):
            continue
        try:
            lines = sum(1 for _ in (work / f).open(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        changes = commits.get(f, 0)
        rows.append(
            {"file": f, "module": module_of(f), "lines": lines, "commits": changes,
             "score": round((changes + 1) * math.log2(lines + 2), 1)}
        )  # fmt: skip
    return sorted(rows, key=lambda r: -float(r["score"]))[:limit]


def coupling(graph: dict[str, Any] | None) -> dict[str, Any]:
    if not graph:
        return {"modules": [], "fan_in": {}, "fan_out": {}}
    fan_in: Counter[str] = Counter()
    fan_out: Counter[str] = Counter()
    for e in graph["edges"]:
        if e.get("weight", 0) > 0 or e.get("user_fact"):
            fan_out[e["source"]] += 1
            fan_in[e["target"]] += 1
    rows = [
        {"module": n["id"], "files": n["file_count"], "fan_in": fan_in[n["id"]], "fan_out": fan_out[n["id"]]}
        for n in graph["nodes"]
    ]
    rows.sort(key=lambda r: -(r["fan_in"] + r["fan_out"]))
    return {"modules": rows, "fan_in": dict(fan_in), "fan_out": dict(fan_out)}


def test_ratio(files: list[str]) -> dict[str, Any]:
    tests = [f for f in files if TEST_FILE.search(f)]
    by_module: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for f in files:
        m = module_of(f)
        if m:
            by_module[m][1 if TEST_FILE.search(f) else 0] += 1
    untested = sorted(m for m, (code, test) in by_module.items() if code >= 2 and test == 0)
    return {"code_files": len(files) - len(tests), "test_files": len(tests), "modules_without_tests": untested}


def all_files(work: Path) -> list[str]:
    return code_files(work)


# ── diagrams (Mermaid, drawn here so they always parse) ──────────────────────
def _id(name: str) -> str:
    ident = re.sub(r"[^A-Za-z0-9]", "_", name).strip("_") or "x"
    return ident if ident[0].isalpha() else f"m_{ident}"


def _text(name: str) -> str:
    return re.sub(r"[\"<>{}\[\]|;#`]", " ", name).strip()[:50]


def context_diagram(name: str, facts: dict[str, Any]) -> str:
    """C4 level 1: the system, its users and the systems it talks to."""
    kinds = {c["kind"] for c in facts["components"]}
    lines = ["flowchart LR", '    user(["User"])', f'    sys["{_text(name)}<br/>(this system)"]']
    lines.append("    user -->|uses| sys" if kinds & {"web", "api", "app"} else "    user -->|runs| sys")
    for s in facts["data_stores"]:
        lines.append(f'    {_id("ext_" + s["name"])}[("{_text(s["kind"])}")]')
        lines.append(f"    sys --> {_id('ext_' + s['name'])}")
    return "\n".join(lines)


def container_diagram(facts: dict[str, Any]) -> str:
    """C4 level 2: the deployable parts (one per Language Pack component) and the data stores."""
    lines = ["flowchart LR", '    user(["User"])']
    comps = facts["components"]
    for c in comps:
        parts = [c["path"] if c["path"] != "." else "root", f"{c['pack']} {c['kind']}", ", ".join(c["frameworks"][:3])]
        label = "<br/>".join(_text(p) for p in parts if p)  # each part made safe; the line breaks stay
        lines.append(f'    {_id("c_" + c["path"])}["{label}"]')
    webs = [c for c in comps if c["kind"] == "web"]
    backs = [c for c in comps if c["kind"] in ("api", "app", "cli")] or [c for c in comps if c not in webs]
    for c in webs or backs[:1]:
        lines.append(f"    user --> {_id('c_' + c['path'])}")
    for w in webs:
        for b in backs:
            lines.append(f"    {_id('c_' + w['path'])} -->|calls| {_id('c_' + b['path'])}")
    for s in facts["data_stores"]:
        sid = _id("ext_" + s["name"])
        lines.append(f'    {sid}[("{_text(s["kind"])}")]')
        for b in backs:
            lines.append(f"    {_id('c_' + b['path'])} --> {sid}")
    return "\n".join(lines)


def dependency_diagram(graph: dict[str, Any] | None, limit: int = MAX_DIAGRAM_MODULES) -> str:
    """C4 level 3 / dependencies: the most connected modules and their links. User facts are drawn thick
    ("you said"); links the user disputed are dotted."""
    if not graph or not graph["nodes"]:
        return "flowchart LR\n    empty[No modules found]"
    degree: Counter[str] = Counter()
    edges = [e for e in graph["edges"] if e.get("weight", 0) > 0 or e.get("user_fact")]
    for e in edges:
        degree[e["source"]] += 1
        degree[e["target"]] += 1
    keep = {m for m, _ in degree.most_common(limit)} or {n["id"] for n in graph["nodes"][:limit]}
    lines = ["flowchart LR"]
    for n in graph["nodes"]:
        if n["id"] in keep:
            lines.append(f'    {_id(n["id"])}["{_text(n["id"])}"]')
    for e in edges:
        if e["source"] in keep and e["target"] in keep:
            a, b = _id(e["source"]), _id(e["target"])
            if e.get("disputed"):
                lines.append(f'    {a} -.->|"disputed"| {b}')
            elif e.get("user_fact"):
                lines.append(f'    {a} ==>|"you said"| {b}')
            else:
                lines.append(f"    {a} --> {b}")
    return "\n".join(lines)


def db_diagram(rows: list[dict[str, Any]], limit: int = 30) -> str:
    if not rows:
        return "flowchart LR\n    none[No database tables found]"
    lines = ["flowchart LR"]
    modules = sorted({m for r in rows[:limit] for m in r["used_by"]})
    for m in modules:
        lines.append(f'    {_id("mod_" + m)}["{_text(m)}"]')
    for r in rows[:limit]:
        tid = _id("tbl_" + r["table"])
        lines.append(f'    {tid}[("{_text(r["table"])}")]')
        for m in r["used_by"]:
            arrow = "==>" if m == r["owner"] else "-.->"
            lines.append(f"    {_id('mod_' + m)} {arrow} {tid}")
    return "\n".join(lines)


# ── dependencies ─────────────────────────────────────────────────────────────
_UNPINNED = re.compile(r"^(\*|latest|x|>=?[^,<]*|)$", re.I)


def dependency_inventory(work: Path) -> list[dict[str, Any]]:  # noqa: PLR0912  (one branch per manifest kind)
    """Dependencies per manifest, with the ones not pinned to a version range (they change under you).
    A vulnerability lookup needs a database (OSV, govulncheck) and the network; the audit says so in its notes."""
    rows: list[dict[str, Any]] = []
    for manifest in sorted(work.rglob("*")):
        rel = manifest.relative_to(work)
        if any(p in ("node_modules", "vendor", ".git", ".venv") for p in rel.parts) or not manifest.is_file():
            continue
        name = manifest.name
        try:
            text = manifest.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        deps: dict[str, str] = {}
        if name == "go.mod":
            for m in re.finditer(
                r"^\s*(?:require\s+)?([\w./-]+\.[\w./-]+)\s+(v[\w.+-]+)(\s*//\s*indirect)?", text, re.M
            ):
                if not m.group(3):
                    deps[m.group(1)] = m.group(2)
        elif name == "package.json":
            try:
                data = json.loads(text)
            except ValueError:
                continue
            deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
        elif name == "requirements.txt":
            for raw in text.splitlines():
                line = raw.split("#")[0].strip()
                if line and not line.startswith("-"):
                    m2 = re.match(r"([A-Za-z0-9_.\-\[\]]+)\s*(.*)", line)
                    if m2:
                        deps[m2.group(1)] = m2.group(2)
        elif name == "pyproject.toml":
            block = re.search(r"dependencies\s*=\s*\[(.*?)\]", text, re.S)
            for item in re.findall(r"[\"']([^\"']+)[\"']", block.group(1) if block else ""):
                m3 = re.match(r"([A-Za-z0-9_.\-\[\]]+)\s*(.*)", item)
                if m3:
                    deps[m3.group(1)] = m3.group(2)
        else:
            continue
        unpinned = sorted(k for k, v in deps.items() if _UNPINNED.match(str(v).strip()))
        rows.append({"manifest": rel.as_posix(), "count": len(deps), "unpinned": unpinned[:20]})
    return rows
