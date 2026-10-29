"""The microservices conversion (Phase 16): its steps on a small real Python project, and a whole run on a Go design
(scaffolded services). The sandbox and the replay are fakes; the generated files and the git history are real."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent.playbooks.architecture_change import microservices as ms
from agent.playbooks.registry import get_playbook
from agent.tests.conftest import FakeProject, FakeServices
from agent.tests.decomposition.test_engine import goshop_like
from agent.tests.microservices.test_foundation_extract import DESIGN, LANGS, PLATFORM, RULES, SHOP
from agent.tests.playbooks.helpers import approve_all, cfg, compiled, drive, gates_of, initial_state
from agent.tests.playbooks.test_architecture_design import REPLAY_OK
from agent.tests.playbooks.test_code_playbooks import GREEN, RED, repo
from agent.tools.workspace import git

FILES = {
    **SHOP,
    "shop/payment/store.py": "def save(db):\n    db.execute('INSERT INTO payments (id) VALUES (1)')\n",
    "shop/order/store.py": "def save(db):\n    db.execute('INSERT INTO orders (id) VALUES (1)')\n",
    "db/schema.sql": "CREATE TABLE orders (id int PRIMARY KEY);\n"
    "CREATE TABLE payments (id int PRIMARY KEY, order_id int REFERENCES orders(id));\n",
}
REGRESSION = {"ok": False, "error": None, "report": {"counts": {"regression": 2, "exchanges": 9}}}


def make(
    tmp_path: Path, results: list[list[dict[str, Any]]] | None = None, **kw: Any
) -> tuple[FakeProject, FakeServices, dict[str, Any]]:
    work = repo(tmp_path, FILES)
    project = FakeProject(
        work,
        test_results=results or [[GREEN]],
        recordings=[{"id": "rec1"}],
        verifications={"replay": [REPLAY_OK]},
        **kw,
    )
    services = FakeServices(project=project)
    state: dict[str, Any] = {
        **initial_state("architecture_change", tmp_path, target="microservices", mode="conversion", use_llm=False),
        "to_be": {"target": "microservices", "design": DESIGN, "platform": PLATFORM},
        "language_plan": {n: {"language": lang, "mode": "extract", "current": lang} for n, lang in LANGS.items()},
        "baseline": {"tests_green": True, "recording": "rec1"},
        "ms_rules": RULES,
        "feedback": {},
    }
    return project, services, state


async def foundation(services: FakeServices, state: dict[str, Any]) -> dict[str, Any]:
    return {**state, **await ms.foundation(services, state)}


async def test_the_foundation_is_written_committed_and_checked(tmp_path: Path) -> None:
    project, services, state = make(tmp_path)
    state = await foundation(services, state)
    work = project.work
    assert state["foundation"]["ok"], state["foundation"]
    assert (work / "gateway/nginx.conf").is_file()
    assert git(work, "log", "-1", "--format=%s").startswith("Microservices: gateway")
    assert git(work, "status", "--porcelain").strip() == ""
    assert "no image was built" in state["foundation_brief"].lower()


async def test_a_foundation_that_changes_behavior_is_undone(tmp_path: Path) -> None:
    project, services, state = make(tmp_path)
    project._verifications = {"replay": [REGRESSION]}
    state = await foundation(services, state)
    assert state["foundation"]["ok"] is False and not (project.work / "gateway").exists()


async def test_a_red_baseline_writes_nothing(tmp_path: Path) -> None:
    project, services, state = make(tmp_path)
    state["baseline"] = {"tests_green": False}
    state = await foundation(services, state)
    assert state["foundation"]["ok"] is False and not (project.work / "gateway").exists()


async def test_a_python_service_is_extracted_behind_an_acl_and_committed(tmp_path: Path) -> None:
    project, services, state = make(tmp_path)
    state = await foundation(services, state)
    out = await ms.build_one(services, state, "payment")
    work = project.work
    assert out["status"] == "extracted", out
    assert (work / "codewright_acl.py").is_file()
    assert git(work, "log", "-1", "--format=%s").startswith("Extract the payment service")
    assert git(work, "status", "--porcelain").strip() == ""
    assert "not deployed" in ms.service_brief(out)


async def test_a_service_whose_tests_fail_is_undone(tmp_path: Path) -> None:
    project, services, state = make(tmp_path, [[GREEN], [RED]])
    state = await foundation(services, state)
    head = git(project.work, "rev-parse", "HEAD")
    out = await ms.build_one(services, state, "payment")
    assert out["status"] == "undone"
    assert git(project.work, "status", "--porcelain").strip() == "" and git(project.work, "rev-parse", "HEAD") == head
    assert not (project.work / "services/payment").exists()


async def test_a_replay_regression_undoes_the_service(tmp_path: Path) -> None:
    project, services, state = make(tmp_path)
    state = await foundation(services, state)
    project._verifications = {"replay": [REGRESSION]}
    out = await ms.build_one(services, state, "payment")
    assert out["status"] == "undone" and "regression" in out["reason"]


async def test_a_non_python_service_is_scaffolded_and_says_why(tmp_path: Path) -> None:
    project, services, state = make(tmp_path)
    state = await foundation(services, state)
    out = await ms.build_one(services, state, "notification")  # TypeScript
    assert out["status"] == "scaffolded" and "compiler" in out["reason"]
    assert (project.work / "services/notification").is_dir()


async def test_finalize_removes_the_local_code_and_routes_the_service(tmp_path: Path) -> None:
    project, services, state = make(tmp_path)
    state = await foundation(services, state)
    state["feedback"] = {"build_service": "finalize"}
    out = await ms.build_one(services, state, "payment")
    assert out["status"] == "extracted" and out.get("finalized") is True, out
    routes = json.loads((project.work / "gateway/routes.json").read_text())
    assert routes["services"]["payment"]["live"] is True


async def test_the_database_split_writes_up_and_down_and_reports_the_trial(tmp_path: Path) -> None:
    project, services, state = make(tmp_path, trial={"ok": True})
    state = await foundation(services, state)
    state["service_results"] = {"payment": {"status": "extracted"}, "order": {"status": "extracted"}}
    state = {**state, **await ms.db_split(services, state)}
    files = sorted(p.name for p in (project.work / "migrations/microservices").iterdir())
    assert any(f.endswith(".up.sql") for f in files) and any(f.endswith(".down.sql") for f in files)
    up = next((project.work / "migrations/microservices").glob("*payment.up.sql")).read_text()
    down = next((project.work / "migrations/microservices").glob("*payment.down.sql")).read_text()
    assert 'CREATE SCHEMA IF NOT EXISTS "payment"' in up and 'SET SCHEMA "payment"' in up
    assert 'DROP CONSTRAINT IF EXISTS "payments_order_id_fkey"' in up  # crosses payment → order
    assert 'ADD CONSTRAINT "payments_order_id_fkey"' in down and 'DROP SCHEMA IF EXISTS "payment"' in down
    assert "applied and rolled back cleanly" in state["db_split_brief"]
    assert git(project.work, "status", "--porcelain").strip() == ""


def test_the_report_lists_services_catalogs_and_what_was_not_done(tmp_path: Path) -> None:
    state: dict[str, Any] = {
        "to_be": {"target": "microservices", "design": DESIGN, "platform": PLATFORM},
        "service_results": {
            "payment": {
                "status": "extracted",
                "language": "Python",
                "tests": 3,
                "behavior": {"checked": True, "ok": True},
            },
            "notification": {"status": "scaffolded", "language": "TypeScript", "reason": "needs its compiler"},
        },
    }
    text = "\n".join(ms.report_lines(state))
    assert "| payment | Python | extracted | 3 | 0 regressions |" in text
    assert "needs its compiler" in text and "No image was built" in text


def test_the_flow_is_real_for_microservices_conversion() -> None:
    spec = get_playbook("architecture_change").spec
    flow = spec.flow({"target": "microservices", "mode": "conversion"})
    assert "foundation" in flow and "restructure" not in flow
    spec.inputs.model_validate({"target": "microservices", "mode": "conversion"})


async def test_a_whole_conversion_of_a_go_shop_scaffolds_each_service_and_ends_honestly(tmp_path: Path) -> None:
    work = repo(tmp_path, {"main.go": "package main\n"})
    project = FakeProject(
        work, goshop_like(), test_results=[[GREEN]], recordings=[{"id": "rec1"}], verifications={"replay": [REPLAY_OK]}
    )
    services = FakeServices(project=project)
    state, prompts = await drive(
        compiled("architecture_change", services),
        cfg(),
        initial_state("architecture_change", tmp_path, target="microservices", mode="conversion"),
        approve_all,
    )
    gates = gates_of(prompts)
    assert gates[:4] == ["gate1", "gate2", "gate3", "gate4"] and gates[-1] == "gate8"
    assert state["foundation"]["ok"] and state["service_results"]
    assert all(r["status"] == "scaffolded" for r in state["service_results"].values())
    assert "No image was built" in state["report_brief"]
    assert git(work, "status", "--porcelain").strip() == ""
