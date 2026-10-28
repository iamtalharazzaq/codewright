"""Add a feature (CODEWRIGHT.md Section 5.13) as whole runs, with a fake sandbox and canned model answers."""

from __future__ import annotations

from pathlib import Path

from agent.playbooks.feature.graph import FeaturePlan, FeatureStep, validate_plan
from agent.tests.conftest import FakeProject, FakeServices
from agent.tests.playbooks.helpers import approve_all, cfg, compiled, drive, gates_of, initial_state, llm_returning
from agent.tests.playbooks.test_code_playbooks import GREEN, RED, fenced, repo
from agent.tests.playbooks.test_upgrade_db_playbooks import REPLAY_OK
from agent.tools.workspace import git

FILES = {
    "pyproject.toml": '[project]\nname = "x"\nversion = "0.1.0"\n',
    "shop/items.py": "ITEMS: list[str] = []\n\n\ndef add_item(name: str) -> None:\n    ITEMS.append(name)\n",
    "shop/__init__.py": "",
}
STORIES = {
    "title": "Wishlist",
    "stories": ["As a shopper, I want a wishlist so that I can save items."],
    "criteria": ["An item can be added to the wishlist", "Adding it twice keeps one entry"],
}
PLAN = {
    "goal": "Keep a wishlist of items",
    "steps": [
        {"file": "shop/wishlist.py", "change": "Add wishlist functions", "new": True},
        {"file": "shop/test_wishlist_codewright.py", "change": "Test both criteria", "new": True},
        {"file": "shop/items.py", "change": "Expose the wishlist", "new": False},
        {"file": "shop/extra_a.py", "change": "More", "new": True},
        {"file": "shop/extra_b.py", "change": "More", "new": True},
    ],
    "screens": [],
    "risks": "none",
}
WISHLIST = (
    "WISHLIST: list[str] = []\n\n\ndef add(name: str) -> None:\n"
    "    if name not in WISHLIST:\n        WISHLIST.append(name)\n"
)
TESTS = (
    "from shop.wishlist import WISHLIST, add\n\n\ndef test_add_twice():\n"
    "    add('a')\n    add('a')\n    assert WISHLIST == ['a']\n"
)
ITEMS = FILES["shop/items.py"] + "from shop.wishlist import add as wishlist_add  # noqa\n"


def _project(tmp_path: Path, results: list[list[dict]]) -> FakeProject:  # type: ignore[type-arg]
    work = repo(tmp_path, FILES)
    return FakeProject(
        work,
        test_results=results,
        hits=[{"path": "shop/items.py"}],
        recordings=[{"id": "rec1"}],
        verifications={"replay": [REPLAY_OK]},
    )


async def test_a_feature_is_designed_built_tested_and_committed(tmp_path: Path) -> None:
    project = _project(tmp_path, [[GREEN]])
    client, _ = llm_returning(
        STORIES, PLAN, fenced(WISHLIST), fenced(TESTS), fenced(ITEMS), fenced("A = 1"), fenced("B = 2")
    )
    services = FakeServices(clients={"remote_gpu": client}, project=project)
    state, prompts = await drive(
        compiled("feature", services), cfg(), initial_state("feature", tmp_path, request="add a wishlist"), approve_all
    )
    assert gates_of(prompts) == ["approve_plan", "approve_result"]
    assert state["built"] is True and sorted(state["changed"]) == sorted(
        ["shop/wishlist.py", "shop/test_wishlist_codewright.py", "shop/items.py", "shop/extra_a.py", "shop/extra_b.py"]
    )
    assert "WISHLIST" in (project.work / "shop/wishlist.py").read_text(encoding="utf-8")
    assert git(project.work, "log", "-1", "--format=%s") == "Add feature: Wishlist"
    assert state["published"]["branch"].startswith("codewright/feature-")
    assert "Replay: identical behavior" in state["done_summary"] and "Acceptance" in state["plan_brief"]


async def test_a_feature_that_never_gets_green_is_removed_completely(tmp_path: Path) -> None:
    project = _project(tmp_path, [[GREEN], [RED]])  # green baseline, red ever after
    client, _ = llm_returning(
        STORIES, PLAN, fenced(WISHLIST), fenced(TESTS), fenced(ITEMS), fenced("A = 1"), fenced("B = 2")
    )
    services = FakeServices(clients={"remote_gpu": client}, project=project)
    state, _ = await drive(
        compiled("feature", services), cfg(), initial_state("feature", tmp_path, request="add a wishlist"), approve_all
    )
    assert state["built"] is False and state["changed"] == []
    assert not (project.work / "shop/wishlist.py").exists()  # the new file is gone
    assert (project.work / "shop/items.py").read_text(encoding="utf-8") == FILES["shop/items.py"]  # exactly as it was
    assert "Nothing was added" in state["done_summary"] and git(project.work, "log", "-1", "--format=%s") == "init"


def test_the_design_labels_files_from_the_workspace_and_drops_unsafe_paths(tmp_path: Path) -> None:
    project = _project(tmp_path, [[GREEN]])
    plan = FeaturePlan(
        goal="g",
        steps=[
            FeatureStep(file="shop/missing.py", change="x", new=False),  # mislabelled: it is a new file
            FeatureStep(file="shop/items.py", change="x", new=True),  # mislabelled: it is a change
            FeatureStep(file="../outside.py", change="x", new=True),
            FeatureStep(file="node_modules/x.js", change="x", new=True),
            FeatureStep(file="shop/items.py", change="again", new=False),
        ],
    )
    plan, dropped = validate_plan(project, plan)
    assert [(s.file, s.new) for s in plan.steps] == [("shop/missing.py", True), ("shop/items.py", False)]
    assert len(dropped) == 3 and "listed twice" in dropped[-1]


# ── Feature by analogy ───────────────────────────────────────────────────────
LAYERED = {
    "pyproject.toml": FILES["pyproject.toml"],
    "shop/model/wishlist.py": "class Wishlist:\n    pass\n",
    "shop/service/wishlist.py": "def list_wishlist():\n    return []\n",
    "shop/api/wishlist_handlers.py": "def get_wishlist():\n    return []\n",
    "shop/api/test_wishlist_handlers.py": "def test_get():\n    assert True\n",
    "shop/api/routes.py": "from shop.api.wishlist_handlers import get_wishlist\n\nROUTES = {'/w': get_wishlist}\n",
    "migrations/0001_init.up.sql": "create table wishlists (id text primary key, user_id text);\n",
    "migrations/0001_init.down.sql": "drop table wishlists;\n",
}


def test_existing_features_are_found_by_their_layers(tmp_path: Path) -> None:
    from agent.playbooks.feature import analogy  # noqa: PLC0415

    work = repo(tmp_path, LAYERED)
    assert list(analogy.features(work)) == ["wishlist"]  # routes.py is wiring, not a feature
    (work / "shop/api/menu.py").write_text("# wishlist\n" + "x = 1\n" * 800, encoding="utf-8")
    long_tail = "    is_wishlist = 1\n" + "x = 1\n" * 800  # a local name is not a declaration to copy
    (work / "shop/types.py").write_text("class WishlistItem:\n    id: str\n" + long_tail, encoding="utf-8")
    made = analogy.plan(work, "wishlist", "price_alert", "r", analogy.features(work)["wishlist"])
    assert (
        "shop/api/menu.py" not in [s.file for s in made.steps]
        and "wire PriceAlert in there by hand" in made.left_out[-1]
    )
    assert made.appends == {"shop/types.py": "class WishlistItem:"}  # declared there: the new one is appended
    found = analogy.features(work)
    assert analogy.closest("Wishlists", found) == "wishlist" == analogy.closest("the Wishlist feature", found)
    assert analogy.closest("none", found) == ""
    assert analogy.closest_in(["shop/api/wishlist_handlers.py"], found) == "wishlist"
    assert analogy.stem_of("internal/user/port/http/wishlist_handlers_test.go") == "wishlist"
    assert analogy.stem_of("internal/user/repository/mocks/WishlistRepository.go") == "wishlist"
    assert (
        analogy.rename("x/mocks/WishlistRepository.go", "wishlist", "price_alert") == "x/mocks/PriceAlertRepository.go"
    )


async def test_a_feature_is_built_like_an_existing_one(tmp_path: Path) -> None:
    work = repo(tmp_path, LAYERED)
    project = FakeProject(
        work, test_results=[[GREEN]], hits=[{"path": "shop/api/routes.py"}], verifications={"replay": [REPLAY_OK]}
    )
    contents = [fenced(f"def made_{i}():\n    return {i}") for i in range(7)]
    client, bodies = llm_returning(STORIES, {"analog": "wishlist", "name": "PriceAlert"}, *contents)
    services = FakeServices(clients={"remote_gpu": client}, project=project)
    state, _ = await drive(
        compiled("feature", services),
        cfg(),
        initial_state("feature", tmp_path, request="add price alerts"),
        approve_all,
    )
    assert state["analog"] == "wishlist" and state["built"] is True
    assert sorted(state["changed"]) == [
        "migrations/0002_add_price_alert.down.sql",
        "migrations/0002_add_price_alert.up.sql",
        "shop/api/price_alert_handlers.py",
        "shop/api/routes.py",
        "shop/api/test_price_alert_handlers.py",
        "shop/model/price_alert.py",
        "shop/service/price_alert.py",
    ]
    assert state["templates"]["shop/model/price_alert.py"] == "shop/model/wishlist.py"
    first_file = bodies[2]["messages"][1]["content"]
    assert "by adapting shop/model/wishlist.py" in first_file and "class Wishlist" in first_file  # the model first
    # model, its migration pair, service, then the handler: it sees the names the earlier files declare
    handlers = bodies[6]["messages"][1]["content"]
    assert "by adapting shop/api/wishlist_handlers.py" in handlers and "def made_0()" in handlers
    assert "adapted from `shop/model/wishlist.py`" in state["plan_brief"]


def test_declarations_list_the_names_new_files_define(tmp_path: Path) -> None:
    from agent.playbooks.feature.graph import declarations  # noqa: PLC0415

    (tmp_path / "a.go").write_text(
        "package a\n\ntype PriceAlert struct {\n\tUserID string\n}\n\nfunc NewPriceAlert() {}\n", encoding="utf-8"
    )
    text = declarations(tmp_path, ["a.go", "missing.go"])
    assert (
        "type PriceAlert struct" in text
        and "UserID string" in text
        and "func NewPriceAlert()" in text
        and "missing" not in text
    )


def test_the_nearest_layers_come_first() -> None:
    from agent.playbooks.feature.graph import nearest_first  # noqa: PLC0415

    files = ["a/model/x.go", "a/repository/x.go", "a/service/x.go", "a/model/x_test.go"]
    assert nearest_first("a/port/http/x_handlers.go", files)[:3] == [
        "a/service/x.go",
        "a/repository/x.go",
        "a/model/x.go",
    ]


async def test_a_migration_that_fails_on_postgres_keeps_the_feature_out(tmp_path: Path) -> None:
    from agent.tests.playbooks.test_upgrade_db_playbooks import TRIAL_BAD, TRIAL_OK  # noqa: PLC0415

    for trial, committed in ((TRIAL_OK, True), (TRIAL_BAD, False)):
        work = repo(tmp_path / str(committed), LAYERED)
        project = FakeProject(work, test_results=[[GREEN]], trial=trial, verifications={"replay": [REPLAY_OK]})
        contents = [fenced(f"def made_{i}():\n    return {i}") for i in range(7)]
        client, _ = llm_returning(STORIES, {"analog": "wishlist", "name": "price_alert"}, *contents)
        services = FakeServices(clients={"remote_gpu": client}, project=project)
        state, _ = await drive(
            compiled("feature", services), cfg(), initial_state("feature", tmp_path, request="r"), approve_all
        )
        assert project.trials[0][0] == "migrations/0002_add_price_alert.up.sql"
        assert (git(work, "log", "-1", "--format=%s") != "init") is committed
        assert ("Migration applied cleanly" in state["result_brief"]) is committed


def test_entry_files_are_found_in_any_language(tmp_path: Path) -> None:
    from agent.playbooks.feature.graph import entry_files  # noqa: PLC0415

    for f in ("cmd/api/main.go", "web/src/App.tsx", "shop/urls.py", "node_modules/x/index.js", "lib/util.py"):
        (tmp_path / f).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / f).write_text("x\n", encoding="utf-8")
    assert entry_files(tmp_path) == ["shop/urls.py", "cmd/api/main.go", "web/src/App.tsx"]


async def test_feature_files_are_written_under_the_build_rules_not_the_refactor_rules(tmp_path: Path) -> None:
    project = _project(tmp_path, [[GREEN]])
    client, bodies = llm_returning(STORIES, PLAN, *[fenced(f"X = {i}") for i in range(5)])
    services = FakeServices(clients={"remote_gpu": client}, project=project)
    await drive(compiled("feature", services), cfg(), initial_state("feature", tmp_path, request="r"), approve_all)
    systems = [b["messages"][0]["content"] for b in bodies[2:]]
    assert systems and all("writing ONE file of a new feature" in s for s in systems)
