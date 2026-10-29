# ruff: noqa: E501, PLR0912, PLR0915
"""Extract a Python module group into a service, with an anti-corruption layer in the monolith (CODEWRIGHT.md 5.18
step 7, Extract mode: same language).

No model rewrites code here. The extraction is mechanical and reversible:

1. The group's files are **copied** into `services/<name>/src/` at the same dotted paths, so their imports keep
   working, together with the unowned files they import (shared helpers) and the shims of services extracted before.
2. Every function the rest of the monolith uses from the group is exposed by the service as `POST
   /rpc/<module>/<function>` (JSON arguments and result).
3. In the monolith each such file keeps its code as `_local_<name>.py` and becomes a **shim** with the same function
   names that asks `codewright_acl.call`: the share of calls sent to the service is `CUTOVER_PERCENT_<SERVICE>`
   (0 = this repository's code, the default; 100 = the service). Between the two, a call to an unreachable service
   falls back to the local code. This is the canary (10 → 50 → 100) and the rollback.
4. After the last step the local code is removed (`remove_local`), only if the tests still pass afterwards.

What it cannot do is reported as `blocked` with the reason, never guessed: a name other modules use that is not a
function (a class or constant cannot cross a process), `from x import *`, a dependency on another group's code that
has not been extracted, and any language but Python (Go, TypeScript and C++ need the compiler).
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent.decomposition import boundaries as b
from agent.microservices.foundation import safe_name

ACL_FILE = "codewright_acl.py"
LOCAL_PREFIX = "_local_"
SHIM_MARK = "# codewright:shim"
MAX_FILES = 60


@dataclass
class Plan:
    service: str
    files: list[str] = field(default_factory=list)  # the group's own Python files
    shared: list[str] = field(default_factory=list)  # unowned files they import (copied)
    shims_used: list[str] = field(default_factory=list)  # shims of earlier services the group imports (copied)
    entries: dict[str, list[str]] = field(default_factory=dict)  # file → the functions the monolith uses from it
    is_async: dict[str, list[str]] = field(default_factory=dict)  # file → which of those are `async def`
    third_party: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    blocked: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items()}


def _is_shim(work: Path, rel: str) -> bool:
    try:
        return SHIM_MARK in (work / rel).read_text(encoding="utf-8", errors="replace")[:400]
    except OSError:
        return False


def _package(rel: str, roots: list[str]) -> list[str]:
    parts = (b.py_dotted(rel, roots) or "").split(".")
    return parts if rel.endswith("__init__.py") else parts[:-1]


def used_members(
    rel: str, source: str, files: set[str], roots: list[str], targets: set[str]
) -> tuple[set[tuple[str, str]], bool]:
    """The (file, name) pairs of `targets` that `rel` uses, and whether it star-imports one of them."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set(), False
    package = _package(rel, roots)
    aliases: dict[str, str] = {}  # how the file refers to a target module → that file
    members: set[tuple[str, str]] = set()
    star = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                found = b.py_file(a.name, files, roots)
                if found in targets:
                    aliases[a.asname or a.name] = found
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                keep = package[: len(package) - (node.level - 1)] if node.level > 1 else package
                base = ".".join([*keep, *([node.module] if node.module else [])])
            else:
                base = node.module or ""
            for a in node.names:
                sub = b.py_file(f"{base}.{a.name}", files, roots)
                if a.name != "*" and sub in targets:
                    aliases[a.asname or a.name] = sub
                    continue
                home = b.py_file(base, files, roots)
                if home in targets:
                    if a.name == "*":
                        star = True
                    else:
                        members.add((home, a.name))
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            try:
                key = ast.unparse(node.value)
            except ValueError:
                continue
            if key in aliases:
                members.add((aliases[key], node.attr))
    return members, star


def _defs(source: str) -> dict[str, str]:
    """Top-level names a file defines: name → 'function' | 'async' | 'other'."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {}
    out: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.AsyncFunctionDef):
            out[node.name] = "async"
        elif isinstance(node, ast.FunctionDef):
            out[node.name] = "function"
        elif isinstance(node, ast.ClassDef):
            out[node.name] = "other"
        elif isinstance(node, ast.Assign | ast.AnnAssign):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            out.update({t.id: "other" for t in targets if isinstance(t, ast.Name)})
    return out


def third_party_imports(work: Path, files: list[str], project_files: set[str], roots: list[str]) -> list[str]:
    import sys  # noqa: PLC0415  (stdlib_module_names)

    names: set[str] = set()
    for rel in files:
        try:
            tree = ast.parse((work / rel).read_text(encoding="utf-8", errors="replace"))
        except (SyntaxError, OSError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
                names.add(node.module.split(".")[0])
    local = {(b.py_dotted(f, roots) or "").split(".")[0] for f in project_files}
    return sorted(n for n in names if n and n not in sys.stdlib_module_names and n not in local)


def plan_extraction(work: Path, rules: dict[str, Any], name: str, libraries: frozenset[str] = frozenset()) -> Plan:
    """What extracting group `name` would copy, expose and leave behind, or why it cannot be done. Groups in
    `libraries` hold shared code with no service of its own: it is copied into the service, not called."""
    plan = Plan(name)
    all_files = [f for f in b.code_files(work) if not f.startswith("services/")]  # services hold copies, not callers
    known = set(all_files)
    roots = b.py_roots(work)
    own = [f for f in all_files if b.module_for(rules, f) == name]
    plan.files = [f for f in own if f.endswith(".py")]
    if other := [f for f in own if not f.endswith(".py")]:
        plan.notes.append(f"{len(other)} file(s) in another language stay in the monolith (only Python is extracted)")
    if not plan.files:
        plan.blocked = "the group has no Python files; Go, TypeScript and C++ need the compiler to extract"
        return plan
    if len(plan.files) > MAX_FILES:
        plan.blocked = f"{len(plan.files)} files is more than a mechanical extraction should move at once"
        return plan
    targets = set(plan.files)
    for rel in all_files:
        if rel in targets or not rel.endswith(".py"):
            continue
        text = (work / rel).read_text(encoding="utf-8", errors="replace")
        members, star = used_members(rel, text, known, roots, targets)
        if star:
            plan.blocked = f"{rel} uses `from ... import *` on the group's code; the names it uses cannot be found"
            return plan
        for file, member in sorted(members):
            plan.entries.setdefault(file, [])
            if member not in plan.entries[file]:
                plan.entries[file].append(member)
    for file, names in list(plan.entries.items()):
        defs = _defs((work / file).read_text(encoding="utf-8", errors="replace"))
        for n in list(names):
            kind = defs.get(n)
            if kind in ("function", "async"):
                if kind == "async":
                    plan.is_async.setdefault(file, []).append(n)
            elif kind == "other" or kind is None:
                # a submodule used as an attribute (`service.helpers`) is not a name of this file
                if b.py_file(f"{(b.py_dotted(file, roots) or '').rsplit('.', 1)[0]}.{n}", known, roots) in targets:
                    names.remove(n)
                    continue
                plan.blocked = (
                    f"`{n}` in {file} is used by other modules but is not a function; "
                    "a class, constant or re-exported name cannot cross a process"
                )
                return plan
        if not names:
            del plan.entries[file]
    if not plan.entries:
        plan.notes.append("no other module calls the group's functions: it is copied, nothing in the monolith changes")
    # What the group imports from outside itself.
    shared: set[str] = set()
    queue = list(plan.files)
    while queue:
        rel = queue.pop()
        for _line, spec, target in b.py_imports(
            rel, (work / rel).read_text(encoding="utf-8", errors="replace"), known, roots
        ):
            if target is None or target in targets or target in shared or target in plan.shims_used:
                continue
            owner = b.module_for(rules, target)
            if Path(target).name == "__init__.py" and owner != name:
                continue  # a package's own `__init__` stays in the monolith; the service gets an empty one
            if _is_shim(work, target):
                plan.shims_used.append(target)
            elif owner is None or owner == name or owner in libraries:
                shared.add(target)
                queue.append(target)
            else:
                plan.blocked = (
                    f"{rel} imports `{spec}` from the {owner} group, which has not been extracted: "
                    f"build {owner} first, or change the design so {name} does not call it"
                )
                return plan
    plan.shared = sorted(shared)
    plan.third_party = third_party_imports(work, [*plan.files, *plan.shared], known, roots)
    return plan


# ── generated files ──────────────────────────────────────────────────────────
ACL_SOURCE = '''"""The anti-corruption layer of the strangler: sends calls for extracted code to its service, by share.

Generated by Codewright (CODEWRIGHT.md 5.18). Standard library only. Per service (NAME in capitals):

    CUTOVER_PERCENT_NAME  share of calls sent to the service, 0..100 (default 0: the code in this repository)
    SERVICE_URL_NAME      the service's URL (default http://<name>:8000)
    CODEWRIGHT_ACL_MODE   "shadow": run the local code, also ask the service, log any difference to ACL_SHADOW_LOG
                          "loopback": run the local code but pass arguments and result through JSON, like a call would

A call that fails to reach the service falls back to the local code below 100%; at 100% it raises.
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

TIMEOUT_S = 5.0


class TransportError(Exception):
    """The service could not be reached (or answered 502-504)."""


class ServiceError(Exception):
    """The service ran the function and it raised."""

    def __init__(self, type_: str, message: str) -> None:
        super().__init__(f"{type_}: {message}")
        self.type = type_


def percent(service: str) -> int:
    try:
        return max(0, min(100, int(os.environ.get(f"CUTOVER_PERCENT_{service.upper()}", "0"))))
    except ValueError:
        return 0


def url(service: str) -> str:
    return os.environ.get(f"SERVICE_URL_{service.upper()}", f"http://{service.replace('_', '-')}:8000").rstrip("/")


def jsonable(value: Any) -> Any:
    return json.loads(json.dumps(value))


def remote(service: str, module: str, function: str, args: Any, kwargs: Any, timeout: float = TIMEOUT_S) -> Any:
    body = json.dumps({"args": list(args), "kwargs": kwargs}).encode()
    request = urllib.request.Request(
        f"{url(service)}/rpc/{module}/{function}", data=body, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310  (the service's own URL)
            data = json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code in (502, 503, 504):
            raise TransportError(f"{service} answered {exc.code}") from exc
        try:
            data = json.load(exc)
        except ValueError as bad:
            raise TransportError(f"{service} answered {exc.code}") from bad
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
        raise TransportError(str(exc)) from exc
    if "error" in data:
        raise ServiceError(data["error"].get("type", "Error"), data["error"].get("message", ""))
    return data.get("result")


def _shadow(service: str, module: str, function: str, args: Any, kwargs: Any, expected: Any) -> None:
    try:
        same = jsonable(remote(service, module, function, args, kwargs, timeout=2.0)) == jsonable(expected)
    except Exception as exc:  # noqa: BLE001  (shadow traffic must never affect the real call)
        same, note = False, f"{type(exc).__name__}: {exc}"
    else:
        note = ""
    with open(os.environ.get("ACL_SHADOW_LOG", "acl-shadow.log"), "a", encoding="utf-8") as log:
        log.write(json.dumps({"service": service, "function": f"{module}.{function}", "same": same, "note": note}) + "\\n")


def _route(service: str) -> str:
    """'local' or 'remote' for this call, by the service's cut-over share."""
    share = percent(service)
    return "remote" if share >= 100 or (share > 0 and random.randrange(100) < share) else "local"  # noqa: S311


def call(service: str, module: str, function: str, args: Any, kwargs: Any, local: Callable[..., Any]) -> Any:
    mode = os.environ.get("CODEWRIGHT_ACL_MODE", "")
    if mode == "loopback":
        return jsonable(local(*jsonable(list(args)), **jsonable(kwargs)))
    if mode == "shadow":
        result = local(*args, **kwargs)
        _shadow(service, module, function, args, kwargs, result)
        return result
    if _route(service) == "local":
        return local(*args, **kwargs)
    try:
        return remote(service, module, function, args, kwargs)
    except TransportError:
        if percent(service) >= 100:
            raise
        return local(*args, **kwargs)


async def acall(service: str, module: str, function: str, args: Any, kwargs: Any, local: Callable[..., Any]) -> Any:
    mode = os.environ.get("CODEWRIGHT_ACL_MODE", "")
    if mode == "loopback":
        return jsonable(await local(*jsonable(list(args)), **jsonable(kwargs)))
    if mode == "shadow" or _route(service) == "local":
        result = await local(*args, **kwargs)
        if mode == "shadow":
            await asyncio.to_thread(_shadow, service, module, function, args, kwargs, result)
        return result
    try:
        return await asyncio.to_thread(remote, service, module, function, args, kwargs)
    except TransportError:
        if percent(service) >= 100:
            raise
        return await local(*args, **kwargs)
'''


def rpc_source(exposed: dict[str, list[str]], asyncs: dict[str, list[str]]) -> str:
    """The service's side: one endpoint that calls an exposed function with JSON arguments."""
    return f'''"""The service's RPC surface for the strangler (generated by Codewright, CODEWRIGHT.md 5.18).

Only the functions listed in EXPOSED can be called; the arguments and the result are JSON.
"""

from __future__ import annotations

import importlib
import inspect
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

EXPOSED: dict[str, list[str]] = {exposed!r}
router = APIRouter()


@router.post("/rpc/{{module}}/{{function}}")
async def rpc(module: str, function: str, body: dict[str, Any]) -> Any:
    if function not in EXPOSED.get(module, []):
        raise HTTPException(404, f"{{module}}.{{function}} is not exposed")
    fn = getattr(importlib.import_module(module), function)
    args, kwargs = body.get("args", []), body.get("kwargs", {{}})
    try:
        if inspect.iscoroutinefunction(fn):
            result = await fn(*args, **kwargs)
        else:
            result = await run_in_threadpool(fn, *args, **kwargs)
    except Exception as exc:  # noqa: BLE001  (the caller gets the type and message, as a ServiceError)
        return JSONResponse({{"error": {{"type": type(exc).__name__, "message": str(exc)}}}}, status_code=500)
    return {{"result": result}}
'''


def shim_source(service: str, module: str, local_module: str, names: list[str], asyncs: list[str]) -> str:
    lines = [
        SHIM_MARK,
        f'"""Anti-corruption layer for the {service} service: {module} (generated by Codewright, CODEWRIGHT.md 5.18).',
        "",
        f"The code that used to live here is `{local_module.rsplit('.', 1)[-1]}`. Calls go to the service by the share in",
        f'CUTOVER_PERCENT_{service.upper()} (0 = that local code, the default; 100 = the service)."""',
        "",
        "import functools",
        "",
        "from codewright_acl import acall, call",
        f"import {local_module} as _local",
        "",
    ]
    for n in names:
        is_async = n in asyncs
        lines += [
            "",
            f"@functools.wraps(_local.{n})",
            f"{'async ' if is_async else ''}def {n}(*args, **kwargs):",
            f"    return {'await acall' if is_async else 'call'}({service!r}, {module!r}, {n!r}, args, kwargs, _local.{n})",
            "",
        ]
    return "\n".join(lines) + "\n"


def remote_shim_source(service: str, module: str, names: list[str], asyncs: list[str]) -> str:
    """The shim once the local code is gone: every call goes to the service."""
    lines = [
        SHIM_MARK,
        f'"""Client of the {service} service for {module} (generated by Codewright). The local code was removed',
        'after the cut-over to 100%."""',
        "",
        "from codewright_acl import remote",
        "",
    ]
    for n in names:
        if n in asyncs:
            lines += [
                "",
                f"async def {n}(*args, **kwargs):",
                "    import asyncio",
                "",
                f"    return await asyncio.to_thread(remote, {service!r}, {module!r}, {n!r}, args, kwargs)",
                "",
            ]
        else:
            lines += [
                "",
                f"def {n}(*args, **kwargs):",
                f"    return remote({service!r}, {module!r}, {n!r}, args, kwargs)",
                "",
            ]
    return "\n".join(lines) + "\n"


def contract_test_source(package: str, exposed: dict[str, list[str]]) -> str:
    return f'''"""Contract test of the RPC surface (generated by Codewright)."""

import importlib

from fastapi.testclient import TestClient

from {package}.codewright_rpc import EXPOSED
from {package}.main import app

client = TestClient(app)


def test_every_exposed_function_exists() -> None:
    for module, names in EXPOSED.items():
        loaded = importlib.import_module(module)
        assert all(callable(getattr(loaded, n)) for n in names)


def test_an_unknown_function_is_not_found() -> None:
    assert client.post("/rpc/nothing/here", json={{"args": [], "kwargs": {{}}}}).status_code == 404


def test_a_function_that_raises_answers_with_its_error() -> None:
    module = next(iter(EXPOSED))
    name = EXPOSED[module][0]
    answer = client.post(f"/rpc/{{module}}/{{name}}", json={{"args": [object.__name__] * 40, "kwargs": {{"__unknown__": 1}}}})
    assert answer.status_code == 500 and answer.json()["error"]["type"] == "TypeError"
'''


def acl_test_source(service: str, module: str, name: str) -> str:
    """Monolith-side test of the cut-over mechanics for one service (the shim is real, the service is faked)."""
    return f'''"""The {service} shim: local by default, the service by share, local again when it cannot be reached
(generated by Codewright)."""

import codewright_acl as acl
import pytest

import {module} as shim


def test_the_default_is_the_local_code(monkeypatch):
    monkeypatch.delenv("CUTOVER_PERCENT_{service.upper()}", raising=False)
    monkeypatch.setattr(acl, "remote", lambda *a, **k: pytest.fail("the service must not be called at 0%"))
    assert hasattr(shim, "{name}") and hasattr(shim.{name}, "__wrapped__")


def test_at_100_percent_the_service_answers(monkeypatch):
    monkeypatch.setenv("CUTOVER_PERCENT_{service.upper()}", "100")
    monkeypatch.setattr(acl, "remote", lambda *a, **k: "from the service")
    assert acl.call({service!r}, {module!r}, {name!r}, (), {{}}, lambda: "local") == "from the service"


def test_an_unreachable_service_falls_back_below_100(monkeypatch):
    def down(*a, **k):
        raise acl.TransportError("down")

    monkeypatch.setenv("CUTOVER_PERCENT_{service.upper()}", "100")
    monkeypatch.setattr(acl, "remote", down)
    with pytest.raises(acl.TransportError):
        acl.call({service!r}, {module!r}, {name!r}, (), {{}}, lambda: "local")
    monkeypatch.setenv("CUTOVER_PERCENT_{service.upper()}", "50")
    monkeypatch.setattr(acl.random, "randrange", lambda n: 0)
    assert acl.call({service!r}, {module!r}, {name!r}, (), {{}}, lambda: "local") == "local"
'''


# ── applying ─────────────────────────────────────────────────────────────────
def _write(work: Path, rel: str, text: str, before: dict[str, str | None]) -> None:
    target = work / rel
    before.setdefault(rel, target.read_text(encoding="utf-8") if target.is_file() else None)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def restore(work: Path, before: dict[str, str | None]) -> None:
    for rel, text in before.items():
        if text is None:
            (work / rel).unlink(missing_ok=True)
        else:
            (work / rel).write_text(text, encoding="utf-8")


def service_dir(name: str) -> str:
    return f"services/{safe_name(name)}"


def py_root_of(rel: str, roots: list[str]) -> str:
    return next((r for r in sorted(roots, key=len, reverse=True) if r and rel.startswith(r + "/")), "")


def apply_extraction(work: Path, plan: Plan, roots: list[str], package: str) -> dict[str, str | None]:
    """Copy the group into the service and put the shims in the monolith. Returns every file's text before (None =
    the file did not exist), so `restore` undoes it exactly."""
    before: dict[str, str | None] = {}
    svc = service_dir(plan.service)
    copied = [*plan.files, *plan.shared, *plan.shims_used]
    parents: set[str] = set()
    for rel in copied:
        inner = rel[len(py_root_of(rel, roots)) :].lstrip("/")
        _write(work, f"{svc}/src/{inner}", (work / rel).read_text(encoding="utf-8"), before)
        parents |= {str(p) for p in Path(inner).parents if str(p) != "."}
    for folder in sorted(
        parents
    ):  # empty `__init__.py` for packages that had one: their exports belong to the monolith
        original = next(
            (f"{r}/{folder}/__init__.py".lstrip("/") for r in roots if (work / r / folder / "__init__.py").is_file()),
            None,
        )
        if original and not (work / svc / "src" / folder / "__init__.py").exists() and original not in copied:
            _write(work, f"{svc}/src/{folder}/__init__.py", "", before)
    if any(_is_shim(work, f) for f in plan.shims_used):
        _write(work, f"{svc}/src/{ACL_FILE}", ACL_SOURCE, before)
    exposed = {b.py_dotted(f, roots): names for f, names in sorted(plan.entries.items()) if b.py_dotted(f, roots)}
    asyncs = {b.py_dotted(f, roots): names for f, names in plan.is_async.items() if b.py_dotted(f, roots)}
    pkg_dir = f"{svc}/src/{package}"
    _write(work, f"{pkg_dir}/codewright_rpc.py", rpc_source(exposed, asyncs), before)  # type: ignore[arg-type]
    main = work / pkg_dir / "main.py"
    if main.is_file():
        text = main.read_text(encoding="utf-8")
        if "codewright_rpc" not in text:
            _write(
                work,
                f"{pkg_dir}/main.py",
                text.rstrip("\n")
                + f"\n\nfrom {package} import codewright_rpc  # noqa: E402\n\napp.include_router(codewright_rpc.router)\n",
                before,
            )
    _write(work, f"{svc}/tests/test_rpc.py", contract_test_source(package, exposed), before)  # type: ignore[arg-type]
    deps = ", ".join(f'"{d}"' for d in plan.third_party)
    pyproject = work / svc / "pyproject.toml"
    if deps and pyproject.is_file():
        text = pyproject.read_text(encoding="utf-8")
        _write(work, f"{svc}/pyproject.toml", text.replace('"uvicorn>=0.32"', f'"uvicorn>=0.32", {deps}', 1), before)
    # The monolith: the runtime of the strangler, the shims, and their tests.
    root = py_root_of(plan.files[0], roots) if plan.files else ""
    acl_rel = f"{root}/{ACL_FILE}".lstrip("/")
    _write(work, acl_rel, ACL_SOURCE, before)
    for rel, names in sorted(plan.entries.items()):
        path = Path(rel)
        local_name = f"{LOCAL_PREFIX}{path.stem}"
        local_rel = (path.parent / f"{local_name}.py").as_posix().removeprefix("./")
        original = (work / rel).read_text(encoding="utf-8")
        _write(work, local_rel, original, before)
        local_dotted = b.py_dotted(local_rel, roots) or local_name
        module = b.py_dotted(rel, roots) or path.stem
        _write(work, rel, shim_source(plan.service, module, local_dotted, names, plan.is_async.get(rel, [])), before)
    if plan.entries:
        first = sorted(plan.entries.items())[0]
        tests = "tests" if (work / "tests").is_dir() else ""
        module = b.py_dotted(first[0], roots) or Path(first[0]).stem
        _write(
            work,
            f"{tests}/test_acl_{safe_name(plan.service)}.py".lstrip("/"),
            acl_test_source(plan.service, module, first[1][0]),
            before,
        )
    return before


def remove_local(work: Path, plan: Plan, roots: list[str]) -> dict[str, str | None]:
    """After the cut-over to 100%: the shims become plain clients and the local copies of the code go. A group file
    nothing else in the monolith imports any more is deleted too. Returns the files' text before, for `restore`."""
    before: dict[str, str | None] = {}
    for rel, names in sorted(plan.entries.items()):
        path = Path(rel)
        module = b.py_dotted(rel, roots) or path.stem
        _write(work, rel, remote_shim_source(plan.service, module, names, plan.is_async.get(rel, [])), before)
        local = (path.parent / f"{LOCAL_PREFIX}{path.stem}.py").as_posix().removeprefix("./")
        if (work / local).is_file():
            before[local] = (work / local).read_text(encoding="utf-8")
            (work / local).unlink()
    # The group's other files: delete the ones no remaining file imports.
    rules = {"modules": {"_": ["."]}}
    gone = {f for f in plan.files if f not in plan.entries and Path(f).name != "__init__.py"}
    for _ in range(3):  # a file only imported by a deleted file is unused in turn
        monolith = [f for f in b.code_files(work) if not f.startswith("services/")]  # the copies import the same names
        imports = b.scan_imports(work, rules, only=monolith)
        still = {i.target for i in imports if i.file not in gone}
        unused = {f for f in gone if f not in still and (work / f).is_file()}
        if not unused:
            break
        for f in sorted(unused):
            before.setdefault(f, (work / f).read_text(encoding="utf-8"))
            (work / f).unlink()
            gone.discard(f)
    return before


def shim_files(work: Path) -> list[str]:
    return [f for f in b.code_files(work) if f.endswith(".py") and _is_shim(work, f)]
