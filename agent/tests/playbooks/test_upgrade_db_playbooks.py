"""Upgrade and Database change (CODEWRIGHT.md Sections 5.11 and 5.12) as whole runs, with a fake sandbox."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent.language_packs.base import Step
from agent.playbooks.db_change import sql as dbsql
from agent.playbooks.upgrade.graph import choose
from agent.playbooks.upgrade.outdated import Outdated, named_in, parse_outdated, version_in
from agent.tests.conftest import FakeProject, FakeServices
from agent.tests.playbooks.helpers import approve_all, cfg, compiled, drive, gates_of, initial_state, llm_returning
from agent.tests.playbooks.test_code_playbooks import GREEN, RED, fenced, repo
from agent.tools.workspace import git
from agent.verification import dbtrial

PYPROJECT = '[project]\nname = "x"\nversion = "0.1.0"\n'
REQS = "requests==2.0.0\nflask==2.0.0\n"
OUTDATED = json.dumps(
    [
        {"name": "requests", "version": "2.0.0", "latest_version": "2.5.0"},
        {"name": "flask", "version": "2.0.0", "latest_version": "3.0.0"},
        {"name": "not-ours", "version": "1.0.0", "latest_version": "9.0.0"},
    ]
)
REPLAY_OK = {"ok": True, "error": None, "report": {"counts": {"regression": 0, "exchanges": 7}}}
RED_IN_FILE = {**RED, "steps": [{"ok": False, "output_tail": "calc.py:3: error: undefined name old_api"}]}


class BumpingProject(FakeProject):
    """A fake whose `upgrade` step really rewrites the pinned version, as the Python pack's bump script does."""

    async def run_step(self, step: Step) -> dict[str, Any]:
        answer = await super().run_step(step)
        if step.name == "upgrade":
            package, version = step.cmd[-2:]
            path = self.work / "requirements.txt"
            path.write_text(
                "".join(
                    f"{package}=={version}\n" if line.startswith(package + "==") else line
                    for line in path.read_text(encoding="utf-8").splitlines(keepends=True)
                ),
                encoding="utf-8",
            )
        return answer


def _upgrade_project(tmp_path: Path, test_results: list[list[dict[str, Any]]], **kwargs: Any) -> BumpingProject:
    work = repo(
        tmp_path, {"pyproject.toml": PYPROJECT, "requirements.txt": REQS, "calc.py": "def f():\n    return 1\n"}
    )
    return BumpingProject(
        work,
        test_results=test_results,
        step_results={"outdated": [{"ok": True, "exit_code": 0, "output": OUTDATED}]},
        recordings=[{"id": "rec1"}],
        verifications={"replay": [REPLAY_OK]},
        **kwargs,
    )


# ── Upgrade ──────────────────────────────────────────────────────────────────
def test_outdated_listings_are_read_per_registry(tmp_path: Path) -> None:
    go = '{"Path":"app","Main":true}\n{"Path":"github.com/gin-gonic/gin","Version":"v1.9.0","Update":{"Version":"v1.10.0"}}\n{"Path":"x/y","Version":"v1.0.0","Indirect":true,"Update":{"Version":"v2.0.0"}}'  # noqa: E501
    found = parse_outdated("go", ".", go, tmp_path)
    assert [(o.package, o.current, o.latest) for o in found] == [("github.com/gin-gonic/gin", "v1.9.0", "v1.10.0")]
    node = parse_outdated(
        "node", "web", 'noise {"react":{"current":"18.0.0","wanted":"18.3.1","latest":"19.0.0"}}', tmp_path
    )
    assert [(o.package, o.same_major) for o in node] == [("react", False)]
    assert named_in("please upgrade gin to 1.10", found) == found and version_in("to v1.10.1") == "1.10.1"


async def test_upgrade_bumps_the_named_package_tests_it_and_commits_it(tmp_path: Path) -> None:
    project = _upgrade_project(tmp_path, [[GREEN]])
    services = FakeServices(project=project)
    state, prompts = await drive(
        compiled("upgrade", services),
        cfg(),
        initial_state("upgrade", tmp_path, request="upgrade requests", use_llm=False),
        approve_all,
    )
    assert gates_of(prompts) == ["approve_plan", "approve_result"]
    assert [u["package"] for u in state["upgrades"]] == ["requests"]  # flask is a major jump and was not named
    assert [(o["package"], o["done"]) for o in state["outcomes"]] == [("requests", True)]
    assert "requests==2.5.0" in (project.work / "requirements.txt").read_text(encoding="utf-8")
    assert "flask==2.0.0" in (project.work / "requirements.txt").read_text(encoding="utf-8")
    assert "Upgrade requests 2.0.0 to 2.5.0" in git(project.work, "log", "-1", "--format=%s")
    assert state["published"]["branch"].startswith("codewright/upgrade-")
    assert "identical behavior" in state["done_summary"] and "Release notes were not read" in state["done_summary"]
    assert "not-ours" not in state["plan_brief"]  # only direct dependencies in the manifests count


async def test_an_upgrade_that_stays_red_is_reverted_exactly(tmp_path: Path) -> None:
    project = _upgrade_project(tmp_path, [[GREEN], [RED]])  # green baseline, then red forever
    services = FakeServices(project=project)
    state, _ = await drive(
        compiled("upgrade", services),
        cfg(),
        initial_state("upgrade", tmp_path, request="upgrade requests", use_llm=False),
        approve_all,
    )
    assert [o["done"] for o in state["outcomes"]] == [False]
    assert (project.work / "requirements.txt").read_text(encoding="utf-8") == REQS  # exactly as it was
    assert "reverted" in state["result_brief"] and state["changed"] == []


async def test_a_breaking_upgrade_gets_the_code_adapted_until_it_is_green(tmp_path: Path) -> None:
    project = _upgrade_project(tmp_path, [[GREEN], [RED_IN_FILE], [GREEN]])
    client, _ = llm_returning(fenced("def f():\n    return new_api()\n"))
    services = FakeServices(clients={"remote_gpu": client}, project=project)
    state, _ = await drive(
        compiled("upgrade", services),
        cfg(),
        initial_state("upgrade", tmp_path, request="upgrade requests"),
        approve_all,
    )
    assert [(o["done"], o["rounds"]) for o in state["outcomes"]] == [(True, 2)]
    assert "new_api" in (project.work / "calc.py").read_text(encoding="utf-8")
    assert sorted(state["outcomes"][0]["files"]) == ["calc.py", "requirements.txt"]


async def test_with_nothing_named_only_same_major_upgrades_are_planned(tmp_path: Path) -> None:
    project = _upgrade_project(tmp_path, [[GREEN]])
    services = FakeServices(project=project)
    state, _ = await drive(
        compiled("upgrade", services),
        cfg(),
        initial_state("upgrade", tmp_path, request="bring my dependencies up to date", use_llm=False),
        approve_all,
    )
    assert [u["package"] for u in state["upgrades"]] == ["requests"]


def test_choose_takes_the_version_the_request_names() -> None:
    go = [Outdated("github.com/gin-gonic/gin", "v1.9.0", "v1.10.0", ".", "go")]
    assert choose("upgrade gin to 1.9.1", go)[0]["to"] == "v1.9.1"
    assert choose("upgrade gin", go)[0]["to"] == "v1.10.0"


# ── Database change ──────────────────────────────────────────────────────────
INIT_UP = "create table products (id serial primary key, category_id int, name text);\n"
PLAN = {
    "goal": "Speed up product lookups by category",
    "name": "Add products category index",
    "up_sql": "create index if not exists idx_products_category on products (category_id);",
    "down_sql": "drop index if exists idx_products_category;",
    "queries": ["select * from products where category_id = 1"],
    "risk": "none",
}
TRIAL_OK = {
    "ok": True,
    "seeded": [],
    "rows_before": 0,
    "up": {"ok": True, "error": ""},
    "down": {"ok": True, "error": ""},
    "changes": {
        "tables_added": [],
        "tables_removed": [],
        "rows_changed": {},
        "data_changed": [],
        "schema_added": ["index: idx_products_category"],
        "schema_removed": [],
    },
    "rollback_restores": True,
    "rollback_differences": None,
    "queries": [{"query": "select * from products where category_id = 1", "before": "Seq Scan", "after": "Index Scan"}],
}
TRIAL_BAD = {
    **TRIAL_OK,
    "ok": False,
    "up": {"ok": False, "error": 'ERROR: relation "product" does not exist'},
    "rollback_restores": False,
}


def _db_project(tmp_path: Path, trial: Any) -> FakeProject:
    work = repo(
        tmp_path,
        {"pyproject.toml": PYPROJECT, "migrations/0001_init.up.sql": INIT_UP, "migrations/0001_init.down.sql": "x;\n"},
    )
    return FakeProject(
        work, test_results=[[GREEN]], trial=trial, recordings=[{"id": "rec1"}], verifications={"replay": [REPLAY_OK]}
    )


async def test_a_migration_is_planned_tried_up_and_down_and_committed(tmp_path: Path) -> None:
    project = _db_project(tmp_path, TRIAL_OK)
    client, _ = llm_returning(PLAN)
    services = FakeServices(clients={"remote_gpu": client}, project=project)
    state, prompts = await drive(
        compiled("db_change", services),
        cfg(),
        initial_state("db_change", tmp_path, request="add an index on products.category_id"),
        approve_all,
    )
    assert gates_of(prompts) == ["approve_plan", "approve_result"]
    up = "migrations/0002_add_products_category_index.up.sql"
    assert project.trials == [(up, ["select * from products where category_id = 1"])]
    assert (project.work / up).read_text(encoding="utf-8").startswith("create index if not exists")
    assert state["changed"] == [up, up.replace(".up.", ".down.")]
    assert "Rollback restores the starting state exactly" in state["done_summary"]
    assert "Seq Scan → Index Scan" in state["result_brief"] and "Data unchanged" in state["result_brief"]
    assert state["published"]["branch"].startswith("codewright/db-")
    assert git(project.work, "log", "-1", "--format=%s").startswith("Migration:")


async def test_sql_that_fails_in_postgres_is_corrected_with_its_error(tmp_path: Path) -> None:
    project = _db_project(tmp_path, [TRIAL_BAD, TRIAL_OK])
    fixed = {
        "up_sql": "create index if not exists idx on products (category_id);",
        "down_sql": "drop index if exists idx;",
    }
    client, bodies = llm_returning(PLAN, fixed)
    services = FakeServices(clients={"remote_gpu": client}, project=project)
    state, _ = await drive(
        compiled("db_change", services),
        cfg(),
        initial_state("db_change", tmp_path, request="index products"),
        approve_all,
    )
    assert state["tries"] == 2 and state["trial"]["ok"] is True
    assert 'relation "product" does not exist' in bodies[-1]["messages"][1]["content"]  # PostgreSQL's own error
    assert "idx on products" in (project.work / state["migration"]["up_file"]).read_text(encoding="utf-8")


async def test_a_migration_that_never_passes_is_not_committed(tmp_path: Path) -> None:
    project = _db_project(tmp_path, TRIAL_BAD)
    client, _ = llm_returning(PLAN, {"up_sql": "select 1;", "down_sql": "select 1;"})
    services = FakeServices(clients={"remote_gpu": client}, project=project)
    state, _ = await drive(
        compiled("db_change", services),
        cfg(),
        initial_state("db_change", tmp_path, request="index products"),
        approve_all,
    )
    assert state["tries"] == 5 and state["changed"] == []
    assert "Migration failed" in state["result_brief"] and "Nothing was added" in state["done_summary"]
    assert git(project.work, "log", "-1", "--format=%s") == "init"


async def test_an_engine_change_is_declined_honestly(tmp_path: Path) -> None:
    project = _db_project(tmp_path, TRIAL_OK)
    services = FakeServices(project=project)
    state, _ = await drive(
        compiled("db_change", services),
        cfg(),
        initial_state("db_change", tmp_path, request="migrate the database from MySQL to PostgreSQL"),
        approve_all,
    )
    assert state["migration"] == {} and project.trials == []
    assert "does not have yet" in state["done_summary"] and state["changed"] == []


def test_migration_helpers(tmp_path: Path) -> None:
    work = tmp_path
    (work / "db").mkdir()
    files = [work / "db" / "0007_a.up.sql"]
    assert dbsql.next_migration(files, work, "Add Index!") == ("db/0008_add_index.up.sql", "db/0008_add_index.down.sql")
    assert dbsql.next_migration([], work, "x")[0] == "migrations/0001_x.up.sql"
    assert dbsql.risky("DROP TABLE a; delete from b") == ["delete from", "drop table"] or dbsql.risky("DROP TABLE a")
    assert dbsql.wants_engine_change("convert MySQL to PostgreSQL") and not dbsql.wants_engine_change("add an index")


def test_trial_snapshots_are_read_and_compared() -> None:
    tables = " table_name | n | h\n------------+---+----\n products   | 3 | abc\n(1 row)\n"
    schema = " k | v\n---+---\n index | idx_a\n(1 row)\n"
    before = dbtrial.snapshot(tables, schema)
    assert before["tables"] == {"products": {"rows": "3", "checksum": "abc"}}
    after = dbtrial.snapshot(tables, schema.replace("(1 row)", " index | idx_b\n(2 rows)"))
    assert dbtrial.diff(before, after)["schema_added"] == ["index: idx_b"]
    assert dbtrial.identical(before, before) and not dbtrial.identical(before, after)
    assert dbtrial.plan_kind("Index Scan using idx on products") == "Index Scan"


def test_error_paths_are_found_from_the_component_they_were_reported_in(tmp_path: Path) -> None:
    from agent.playbooks.upgrade.graph import files_in  # noqa: PLC0415

    work = repo(tmp_path, {"go.mod": "module x\n", "web/package.json": '{"name": "w"}', "web/src/api/a.ts": "x\n"})
    assert files_in("src/api/a.ts(2,15): error TS2305", work) == ["web/src/api/a.ts"]
