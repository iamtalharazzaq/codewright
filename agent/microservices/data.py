# ruff: noqa: E501, S608
"""The data side of a microservices conversion (CODEWRIGHT.md 5.18 steps 8 and 9, Phase 17).

Phase 16 wrote one expand migration per service (`dbsplit.py`). This adds what makes the split safe to run:

- **Stages** with a check and a rollback between them: *expand* (schema, tables moved, a compatibility view left
  behind), *check* (the view and the moved table hold the same rows), *contract* (drop the compatibility views, only
  after every caller uses the service). `apply.sh` and `rollback.sh` run a stage, or undo it, in the right order.
- **Sagas with compensation** (`libs/sagas/saga.py`): the orchestrator for work that spans services. Each step has an
  undo; a failing step undoes the completed ones in reverse; every state change is stored, so a crashed orchestrator
  resumes where it stopped. `platform/sagas.json` holds the designed sagas and `libs/sagas/test_sagas.py` tests
  **every path** of each one: success, a failure at each step, a failing undo, a crash and resume.
- **The frontend against the gateway**: the API address the frontend uses is pointed at the gateway.

Everything is generated from the design, not by a model. Nothing here is applied to a real database.
"""

from __future__ import annotations

import json
import re
from typing import Any

from agent.microservices.dbsplit import MIGRATIONS, q
from agent.microservices.foundation import GATEWAY_PORT

SAGAS_JSON = "platform/sagas.json"
SAGA_DIR = "libs/sagas"

SAGA_PY = '''"""Saga orchestration with compensation (libs/sagas/saga.py). Standard library only.

A saga is a list of steps; each has `do(context)` and `undo(context)`. If a step fails, the steps that completed are
undone in reverse order. Every change of state is saved to a store (in memory, or in the service's `saga_state`
table), so an orchestrator that crashed resumes where it stopped: `run` with the same `saga_id`.

Steps must be idempotent: after a crash the step that was running is run again.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

RUNNING, COMPLETED, COMPENSATING, COMPENSATED, FAILED = "running", "completed", "compensating", "compensated", "failed"


class Store(Protocol):
    def load(self, saga_id: str) -> dict[str, Any] | None: ...

    def save(self, saga_id: str, state: dict[str, Any]) -> None: ...


class MemoryStore:
    def __init__(self) -> None:
        self.states: dict[str, dict[str, Any]] = {}

    def load(self, saga_id: str) -> dict[str, Any] | None:
        state = self.states.get(saga_id)
        return json.loads(json.dumps(state)) if state else None

    def save(self, saga_id: str, state: dict[str, Any]) -> None:
        self.states[saga_id] = json.loads(json.dumps(state))


class SqlStore:
    """`<schema>.saga_state` of the database split, through a DB-API connection (psycopg style, `%s` parameters)."""

    def __init__(self, connection: Any, schema: str) -> None:
        self.connection, self.table = connection, f'"{schema}".saga_state'

    def load(self, saga_id: str) -> dict[str, Any] | None:
        with self.connection.cursor() as cur:
            cur.execute(f"SELECT name, step, status, context FROM {self.table} WHERE id = %s", (saga_id,))
            row = cur.fetchone()
        if row is None:
            return None
        context = row[3] if isinstance(row[3], dict) else json.loads(row[3])
        return {"id": saga_id, "name": row[0], "step": row[1], "status": row[2], **context}

    def save(self, saga_id: str, state: dict[str, Any]) -> None:
        kept = {k: v for k, v in state.items() if k not in ("id", "name", "step", "status")}
        with self.connection.cursor() as cur:
            cur.execute(
                f"INSERT INTO {self.table} (id, name, step, status, context) VALUES (%s, %s, %s, %s, %s) "
                "ON CONFLICT (id) DO UPDATE SET step = EXCLUDED.step, status = EXCLUDED.status, "
                "context = EXCLUDED.context, updated_at = now()",
                (saga_id, state["name"], state["step"], state["status"], json.dumps(kept)),
            )
        self.connection.commit()


@dataclass(frozen=True)
class Step:
    name: str
    do: Callable[[dict[str, Any]], dict[str, Any] | None]
    undo: Callable[[dict[str, Any]], None]


class SagaFailed(Exception):
    def __init__(self, saga: str, step: str, error: str, compensation_errors: list[str]) -> None:
        super().__init__(f"{saga}: {step} failed ({error})" + (f"; {len(compensation_errors)} undo(s) failed" if compensation_errors else ""))
        self.saga, self.step, self.error, self.compensation_errors = saga, step, error, compensation_errors


def run(name: str, steps: list[Step], context: dict[str, Any], store: Store, saga_id: str | None = None) -> dict[str, Any]:
    """Run (or resume) a saga. Returns the final context; raises `SagaFailed` once the completed steps are undone."""
    saga_id = saga_id or str(uuid.uuid4())
    loaded = store.load(saga_id)
    state = loaded or {"id": saga_id, "name": name, "step": 0, "status": RUNNING, "context": dict(context)}
    if loaded is None:
        store.save(saga_id, state)  # a crash before the first step still leaves a record `run` can resume from
    if state["status"] == COMPLETED:
        return dict(state["context"])
    if state["status"] == RUNNING:
        while state["step"] < len(steps):
            step = steps[state["step"]]
            try:
                out = step.do(state["context"])
            except Exception as exc:  # noqa: BLE001  (any failure of a step starts the compensation)
                state.update(status=COMPENSATING, failed_step=step.name, error=str(exc), compensation_errors=[])
                store.save(saga_id, state)
                break
            state["context"].update(out or {})
            state["step"] += 1
            store.save(saga_id, state)
        else:
            state["status"] = COMPLETED
            store.save(saga_id, state)
            return dict(state["context"])
    if state["status"] == COMPENSATING:
        errors: list[str] = state.setdefault("compensation_errors", [])
        while state["step"] > 0:
            step = steps[state["step"] - 1]
            try:
                step.undo(state["context"])
            except Exception as exc:  # noqa: BLE001  (the others are still undone; the failure is reported)
                errors.append(f"{step.name}: {exc}")
            state["step"] -= 1
            store.save(saga_id, state)
        state["status"] = FAILED if errors else COMPENSATED
        store.save(saga_id, state)
    raise SagaFailed(name, state.get("failed_step", "?"), state.get("error", ""), list(state.get("compensation_errors", [])))
'''

SAGA_TEST_PY = '''"""Every path of every designed saga (libs/sagas/test_sagas.py), generated from platform/sagas.json."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import saga  # noqa: E402

DEFINITIONS = json.loads((Path(__file__).resolve().parents[2] / "platform" / "sagas.json").read_text(encoding="utf-8"))["sagas"]
PATHS = [(d["name"], d["steps"], k) for d in DEFINITIONS for k in range(len(d["steps"]) + 1)]  # k = the step that fails
IDS = [f"{n}-{'succeeds' if k == len(s) else 'fails-at-' + s[k]}" for n, s, k in PATHS]
LONG = [(d["name"], d["steps"]) for d in DEFINITIONS if len(d["steps"]) >= 2]


class Crash(BaseException):
    """The orchestrator dies (not an Exception: nothing in the saga may catch it)."""


def build(names, log, fail_at=None, crash_at=None, undo_fails=(), crash_undo_at=None):
    def make(i, name):
        def do(ctx):
            if i == fail_at:
                raise RuntimeError("boom")
            if i == crash_at:
                raise Crash()
            log.append(("do", name))
            return {name: True}

        def undo(ctx):
            if name == crash_undo_at:
                raise Crash()
            if name in undo_fails:
                raise RuntimeError("cannot undo")
            log.append(("undo", name))

        return saga.Step(name, do, undo)

    return [make(i, n) for i, n in enumerate(names)]


@pytest.mark.parametrize(("name", "names", "fail_at"), PATHS, ids=IDS)
def test_every_path(name, names, fail_at):
    log, store = [], saga.MemoryStore()
    steps = build(names, log, fail_at=fail_at)
    if fail_at == len(names):
        result = saga.run(name, steps, {"start": 1}, store, "s1")
        assert log == [("do", n) for n in names]
        assert all(result[n] for n in names) and result["start"] == 1
        assert store.load("s1")["status"] == saga.COMPLETED
        return
    with pytest.raises(saga.SagaFailed) as caught:
        saga.run(name, steps, {}, store, "s1")
    done = names[:fail_at]
    assert log == [("do", n) for n in done] + [("undo", n) for n in reversed(done)]
    assert caught.value.step == names[fail_at] and caught.value.compensation_errors == []
    assert store.load("s1")["status"] == saga.COMPENSATED


@pytest.mark.parametrize(("name", "names"), LONG, ids=[n for n, _ in LONG])
def test_a_failing_undo_is_reported_and_the_others_still_run(name, names):
    log, store = [], saga.MemoryStore()
    steps = build(names, log, fail_at=len(names) - 1, undo_fails={names[0]})
    with pytest.raises(saga.SagaFailed) as caught:
        saga.run(name, steps, {}, store, "s1")
    assert [n for kind, n in log if kind == "undo"] == list(reversed(names[1:-1]))
    assert len(caught.value.compensation_errors) == 1 and store.load("s1")["status"] == saga.FAILED


@pytest.mark.parametrize(("name", "names"), [(d["name"], d["steps"]) for d in DEFINITIONS], ids=[d["name"] for d in DEFINITIONS])
def test_a_crashed_orchestrator_resumes_without_repeating_finished_steps(name, names):
    for crash_at in range(len(names)):
        log, store = [], saga.MemoryStore()
        with pytest.raises(Crash):
            saga.run(name, build(names, log, crash_at=crash_at), {}, store, "s1")
        assert store.load("s1")["step"] == crash_at and store.load("s1")["status"] == saga.RUNNING
        saga.run(name, build(names, log), {}, store, "s1")
        assert [n for kind, n in log if kind == "do"] == names
        assert store.load("s1")["status"] == saga.COMPLETED


@pytest.mark.parametrize(("name", "names"), LONG, ids=[n for n, _ in LONG])
def test_a_crash_while_undoing_resumes_the_undo(name, names):
    log, store = [], saga.MemoryStore()
    steps = build(names, log, fail_at=len(names) - 1, crash_undo_at=names[0])
    with pytest.raises(Crash):
        saga.run(name, steps, {}, store, "s1")
    assert store.load("s1")["status"] == saga.COMPENSATING
    with pytest.raises(saga.SagaFailed):
        saga.run(name, build(names, log, fail_at=len(names) - 1), {}, store, "s1")
    undone = [n for kind, n in log if kind == "undo"]
    assert undone == list(reversed(names[:-1])) and store.load("s1")["status"] == saga.COMPENSATED


def test_a_completed_saga_is_not_run_again():
    store = saga.MemoryStore()
    names = DEFINITIONS[0]["steps"]
    log = []
    saga.run("x", build(names, log), {}, store, "s1")
    saga.run("x", build(names, log), {}, store, "s1")
    assert len(log) == len(names)
'''


def saga_definitions(platform: dict[str, Any]) -> dict[str, Any]:
    return {
        "sagas": [
            {
                "name": s["name"],
                "orchestrator": s["orchestrator"],
                "steps": list(s["steps"]),
                "compensations": list(s["compensations"]),
            }
            for s in platform.get("sagas", [])
        ]
    }


def saga_files(platform: dict[str, Any]) -> dict[str, str]:
    """The saga library, its definitions and its tests: only when the design has sagas."""
    if not platform.get("sagas"):
        return {}
    return {
        f"{SAGA_DIR}/saga.py": SAGA_PY,
        f"{SAGA_DIR}/test_sagas.py": SAGA_TEST_PY,
        SAGAS_JSON: json.dumps(saga_definitions(platform), indent=2) + "\n",
    }


def saga_paths(platform: dict[str, Any]) -> int:
    """How many paths the generated tests walk (success and a failure at each step, per saga)."""
    return sum(len(s["steps"]) + 1 for s in platform.get("sagas", []))


# ── stages ───────────────────────────────────────────────────────────────────
def contract_sql(entry: dict[str, Any]) -> tuple[str, str]:
    """(up, down) of the contract stage: drop the compatibility views, once nothing reads the old tables any more."""
    schema = q(entry["schema"])
    up = [f"-- Codewright: contract stage for {entry['service']}. Apply it only when every caller uses the service."]
    down = [f"-- Bring back the compatibility views of {entry['service']}."]
    for t in entry["tables"]:
        up.append(f"DROP VIEW IF EXISTS public.{q(t)};")
        down.append(f"CREATE VIEW public.{q(t)} AS SELECT * FROM {schema}.{q(t)};")
    return "\n".join(up) + "\n", "\n".join(down) + "\n"


def check_sql(entry: dict[str, Any]) -> str:
    """The check stage: the compatibility view and the moved table hold the same number of rows. Raises on a mismatch."""
    schema = q(entry["schema"])
    lines = [f"-- Codewright: check stage for {entry['service']}: nothing is changed, a mismatch raises an error."]
    for t in entry["tables"]:
        lines.append(
            f"DO $$ BEGIN IF (SELECT count(*) FROM public.{q(t)}) <> (SELECT count(*) FROM {schema}.{q(t)}) "
            f"THEN RAISE EXCEPTION 'row counts of {t} differ between the view and the service table'; END IF; END $$;"
        )
    return "\n".join(lines) + "\n"


def stage_files(plan: dict[str, Any]) -> dict[str, str]:
    """Check and contract files, the apply and rollback scripts and the stage guide, for the split plan."""
    files: dict[str, str] = {}
    owning = [(i, e) for i, e in enumerate(plan["services"], 1) if e["tables"]]
    expand = [f"{i:03d}_{e['schema']}.up.sql" for i, e in enumerate(plan["services"], 1)]
    expand_down = [f"{i:03d}_{e['schema']}.down.sql" for i, e in enumerate(plan["services"], 1)]
    checks, contracts, contract_downs = [], [], []
    for i, e in owning:
        check = f"{i:03d}_{e['schema']}.check.sql"
        files[f"{MIGRATIONS}/{check}"] = check_sql(e)
        checks.append(check)
        up, down = contract_sql(e)
        name = f"{100 + i:03d}_{e['schema']}_contract"
        files[f"{MIGRATIONS}/{name}.up.sql"], files[f"{MIGRATIONS}/{name}.down.sql"] = up, down
        contracts.append(f"{name}.up.sql")
        contract_downs.append(f"{name}.down.sql")

    def arr(names: list[str]) -> str:
        return "(" + " ".join(f'"{n}"' for n in names) + ")"

    files[f"{MIGRATIONS}/apply.sh"] = f"""#!/usr/bin/env bash
# Apply one stage of the database split, in order. DATABASE_URL must point at the database to change.
# Usage: ./apply.sh expand | check | contract     (each file runs in its own transaction; the first failure stops)
set -euo pipefail
cd "$(dirname "$0")"
: "${{DATABASE_URL:?set DATABASE_URL}}"
case "${{1:-}}" in
  expand) files={arr(expand)} ;;
  check) files={arr(checks)} ;;
  contract) files={arr(contracts)} ;;
  *) echo "usage: $0 expand|check|contract" >&2; exit 2 ;;
esac
for f in "${{files[@]}}"; do
  echo "applying $f"
  psql "$DATABASE_URL" -v ON_ERROR_STOP=1 --single-transaction -f "$f"
done
"""
    files[f"{MIGRATIONS}/rollback.sh"] = f"""#!/usr/bin/env bash
# Undo one stage of the database split, in the reverse order. Undo contract before expand.
# Usage: ./rollback.sh contract | expand     (each file runs in its own transaction; the first failure stops)
set -euo pipefail
cd "$(dirname "$0")"
: "${{DATABASE_URL:?set DATABASE_URL}}"
case "${{1:-}}" in
  contract) files={arr(list(reversed(contract_downs)))} ;;
  expand) files={arr(list(reversed(expand_down)))} ;;
  *) echo "usage: $0 contract|expand" >&2; exit 2 ;;
esac
for f in "${{files[@]}}"; do
  echo "rolling back $f"
  psql "$DATABASE_URL" -v ON_ERROR_STOP=1 --single-transaction -f "$f"
done
"""
    files[f"{MIGRATIONS}/STAGES.md"] = stages_guide(plan, bool(owning))
    return files


def stages_guide(plan: dict[str, Any], has_tables: bool) -> str:
    lines = [
        "# Database split: stages",
        "",
        "Generated by Codewright (CODEWRIGHT.md 5.18 step 8). **Codewright applied none of this to a real database**; "
        "it tried the expand stage and its rollback on a throwaway PostgreSQL when the sandbox has one (see the run report).",
        "Take a backup first. Run the stages where the database lives:",
        "",
        "| Stage | Command | What it does | Undo |",
        "|---|---|---|---|",
        "| 1. Expand | `DATABASE_URL=... ./apply.sh expand` | each service gets a schema and a role; its tables move into the schema and a view keeps the old name working; cross-service foreign keys are dropped; outbox, processed-events and saga tables are created | `./rollback.sh expand` |",
        "| 2. Check | `./apply.sh check` | the view and the moved table hold the same rows (raises if not) | nothing to undo |",
        "| 3. Contract | `./apply.sh contract` | drops the compatibility views, **only** after every caller uses the service | `./rollback.sh contract` |",
        "",
        "Order matters: undo the contract stage before the expand stage. Between stages the application keeps working "
        "(the monolith reads the views; the services read their schemas).",
        "",
        "## Events and sagas",
        "",
        "- **Outbox:** a service writes the event to its `outbox` table in the same transaction as the change; a relay "
        "publishes rows without `published_at` to the broker and sets it. Consumers record `event_id` in `processed_events` "
        "and skip an event they have seen.",
        "- **Sagas:** `libs/sagas/saga.py` runs a saga with compensation and stores its state in `<schema>.saga_state`; "
        "`libs/sagas/test_sagas.py` tests every path of the designed sagas (`platform/sagas.json`).",
        "",
    ]
    if not has_tables:
        lines.append("No service owns a table in this design, so the check and contract stages are empty.")
    return "\n".join(lines) + "\n"


# ── the frontend against the gateway ─────────────────────────────────────────
LOCAL_URL = re.compile(r"""(?P<q>["'`])https?://(?:localhost|127\.0\.0\.1):(?P<port>\d{2,5})(?=[/"'`?])""")
API_HINT = re.compile(r"api|fetch|axios|base|url|endpoint|\bhost\b|origin|proxy", re.I)  # \b: "localhost" isn't a hint


def gateway_rewrite(text: str, gateway_port: int = GATEWAY_PORT) -> tuple[str, list[str]]:
    """Point API addresses written as `http://localhost:<port>` at the gateway, on lines that talk about an API (the
    frontend's own dev address is left alone). Returns (new text, the changed lines)."""
    changed: list[str] = []
    out: list[str] = []
    for line in text.split("\n"):
        new = line
        if API_HINT.search(line):
            new = LOCAL_URL.sub(
                lambda m: (
                    m.group(0)
                    if int(m.group("port")) == gateway_port
                    else f"{m.group('q')}http://localhost:{gateway_port}"
                ),
                line,
            )
        if new != line:
            changed.append(new.strip()[:120])
        out.append(new)
    return "\n".join(out), changed


def gateway_routes_doc(design: dict[str, Any], routes: dict[str, Any]) -> str:
    lines = [
        "# Gateway routes",
        "",
        f"The frontend talks to the gateway only (`http://localhost:{GATEWAY_PORT}`). The gateway decides what answers:",
        "",
        "| Path prefix | Answered by | Live |",
        "|---|---|---|",
    ]
    for name, r in sorted((routes.get("services") or {}).items()):
        lines.append(
            f"| `{r.get('prefix', '/' + name + '/')}` | {name} service | {'yes' if r.get('live') else 'not yet (monolith)'} |"
        )
    lines += ["| `/` | monolith | until every service is live |", ""]
    return "\n".join(lines)
