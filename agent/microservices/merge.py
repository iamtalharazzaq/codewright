# ruff: noqa: E501, RUF001
"""Merge services back into the monolith (CODEWRIGHT.md 5.18, target: `merge`), Phase 17.

The mechanical reverse of `agent.microservices.extract`: a service that was extracted behind an anti-corruption
layer is folded back by restoring each shim's local code, deleting the service's own copy, and dropping the
gateway route. Detected from the working tree (the shim mark, `_local_<stem>.py`, `services/<name>/`), not from a
design, so a project merges cleanly however its services got there.

What it cannot do, never guessed: a shim whose local copy is gone (the service was already cut over to 100% and
`finalize`d) has nothing to restore, so merging it mechanically is refused with the reason; only the monolith's
side of the strangler is undone here (the service's own repository, if it has one, is not touched).
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent.decomposition import boundaries as b
from agent.microservices import extract as ex
from agent.microservices import foundation as fd

CALLS = re.compile(r"\b(?:call|acall|remote)\(\s*[\"']([\w.-]+)[\"']\s*,")  # `remote`: a shim already finalized
restore = ex.restore  # the merge of a service is undone the same way an extraction is: write back every file's text


class CannotMerge(Exception):
    pass


@dataclass
class Move:
    service: str
    shims: list[str] = field(default_factory=list)  # monolith files whose shim calls this service
    service_dir: str = ""
    reason: str = ""

    def title(self) -> str:
        return f"Merge `{self.service}` back into the monolith"


def detect(work: Path) -> dict[str, list[str]]:
    """Service name → the shim files in the monolith that call it, found from the shim mark and the literal service
    name every generated shim calls `codewright_acl` with (never guessed: a shim that calls more than one service
    name, which Codewright never generates, is skipped for each)."""
    found: dict[str, list[str]] = {}
    for rel in ex.shim_files(work):
        text = (work / rel).read_text(encoding="utf-8", errors="replace")
        for service in sorted(set(CALLS.findall(text))):
            found.setdefault(service, []).append(rel)
    return found


def plan(work: Path, names: list[str] | None = None) -> tuple[list[Move], list[str]]:
    """(moves, notes): one move per service to fold back, in no particular order (each is independent); `names`
    restricts which services to merge (default: every one found in the working tree)."""
    detected = detect(work)
    notes: list[str] = []
    moves: list[Move] = []
    chosen = sorted(names) if names is not None else sorted(detected)
    for name in chosen:
        shims = detected.get(name)
        svc_dir = ex.service_dir(name)
        if not shims:
            if (work / svc_dir).is_dir():
                moves.append(
                    Move(name, [], svc_dir, "scaffolded but not extracted, so nothing in the monolith changes")
                )
            else:
                notes.append(f"`{name}`: not found in the working tree; nothing to merge.")
            continue
        moves.append(Move(name, sorted(shims), svc_dir, f"{len(shims)} shim file(s) in the monolith call it"))
    return moves, notes


def _acl_test_path(work: Path, service: str) -> Path:
    """Where `extract.apply_extraction` scaffolds this service's shim acceptance test (CODEWRIGHT.md 5.17's
    cutover-percentage check) - the same `tests/` detection it uses, so a real merge finds the real file."""
    tests = "tests" if (work / "tests").is_dir() else ""
    return work / f"{tests}/test_acl_{fd.safe_name(service)}.py".lstrip("/")


def apply_merge(work: Path, move: Move) -> dict[str, str | None]:
    """Restore each shim's local code, then delete the service's own copy, its runbook, and the shim's own
    acceptance test (it only makes sense while the shim is live - once merged back there is no cutover percentage
    to check and the test fails on the restored, unwrapped function). Returns every touched file's text before
    (None = did not exist), so `restore` undoes it exactly."""
    before: dict[str, str | None] = {}
    for rel in move.shims:
        path = Path(rel)
        local_rel = (path.parent / f"{ex.LOCAL_PREFIX}{path.stem}.py").as_posix().removeprefix("./")
        local_path = work / local_rel
        if not local_path.is_file():
            raise CannotMerge(
                f"`{rel}` has no local copy (`{local_rel}`); it was already cut over to 100% and finalized, so "
                "there is nothing left in the monolith to restore"
            )
        before.setdefault(rel, (work / rel).read_text(encoding="utf-8"))
        (work / rel).write_text(local_path.read_text(encoding="utf-8"), encoding="utf-8")
        before.setdefault(local_rel, local_path.read_text(encoding="utf-8"))
        local_path.unlink()
    svc_dir = work / move.service_dir
    for p in sorted(svc_dir.rglob("*")):
        if p.is_file() and not any(part in b.SKIP for part in p.relative_to(svc_dir).parts):
            rel = p.relative_to(work).as_posix()
            before.setdefault(rel, p.read_text(encoding="utf-8", errors="replace"))
    if svc_dir.is_dir():
        shutil.rmtree(svc_dir, ignore_errors=True)
    runbook = work / f"docs/runbooks/cutover-{fd.safe_name(move.service)}.md"
    if runbook.is_file():
        rel = runbook.relative_to(work).as_posix()
        before.setdefault(rel, runbook.read_text(encoding="utf-8"))
        runbook.unlink()
    acl_test = _acl_test_path(work, move.service)
    if acl_test.is_file():
        rel = acl_test.relative_to(work).as_posix()
        before.setdefault(rel, acl_test.read_text(encoding="utf-8"))
        acl_test.unlink()
    return before


def acl_still_used(work: Path) -> bool:
    return any(ex.SHIM_MARK in (work / f).read_text(encoding="utf-8", errors="replace")[:400] for f in b.code_files(work) if f.endswith(".py"))  # fmt: skip


def drop_gateway_route(work: Path, service: str) -> list[str]:
    """Remove `service`'s entry from `gateway/routes.json` and regenerate `nginx.conf` to match."""
    routes_path = work / "gateway/routes.json"
    if not routes_path.is_file():
        return []
    routes = json.loads(routes_path.read_text(encoding="utf-8"))
    key = fd.safe_name(service)
    if key not in routes.get("services", {}):
        return []
    del routes["services"][key]
    routes_path.write_text(json.dumps(routes, indent=2) + "\n", encoding="utf-8")
    changed = ["gateway/routes.json"]
    nginx_path = work / "gateway/nginx.conf"
    if nginx_path.is_file():
        nginx_path.write_text(fd.render_nginx(routes), encoding="utf-8")
        changed.append("gateway/nginx.conf")
    return changed


def remove_unused_acl(work: Path) -> list[str]:
    """Once no shim calls any service any more, `codewright_acl.py` is dead code; remove every copy of it."""
    if acl_still_used(work):
        return []
    removed = [f for f in b.code_files(work) if Path(f).name == ex.ACL_FILE]
    for rel in removed:
        (work / rel).unlink(missing_ok=True)
    return removed


def brief(outcomes: list[dict[str, Any]], notes: list[str]) -> str:
    done = [o for o in outcomes if o["done"]]
    skipped = [o for o in outcomes if not o["done"]]
    lines = [f"**Merge services back into the monolith**: {len(done)} of {len(outcomes)} service(s) merged."]
    lines += [f"- ✅ {o['title']} ({o['reason']})" for o in done]
    lines += [f"- ⏭️ {o['title']}: {o['note']}" for o in skipped]
    lines += [f"- ℹ️ {n}" for n in notes]
    return "\n".join(lines)
