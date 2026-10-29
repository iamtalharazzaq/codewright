"""Import-boundary rules and the mechanical moves, on small real projects in a temp folder."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from agent.decomposition import boundaries as b
from agent.decomposition import moves as mv


def sh(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=False)  # noqa: S603


def project(tmp_path: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text, encoding="utf-8")
    return tmp_path


SHOP = {
    "shop/__init__.py": "",
    "shop/order/__init__.py": "from .service import place\n",
    "shop/order/service.py": "from shop.user import find_user\nfrom shop.util.money import fmt\n\n\ndef place(uid):\n    return fmt(find_user(uid))\n",  # noqa: E501
    "shop/user/__init__.py": "from .repo import find_user\n",
    "shop/user/repo.py": "def find_user(uid):\n    return uid\n",
    "shop/util/__init__.py": "",
    "shop/util/money.py": "def fmt(x):\n    return f'${x}'\n",
    "shop/util/slug.py": "def slug(x):\n    return x\n",
    "shop/web/__init__.py": "",
    "shop/web/views.py": "from shop.order.service import place\nfrom shop.order import service\nfrom shop.util.slug import slug\n",  # noqa: E501
}
RULES = {
    "version": 1,
    "style": "modular_monolith",
    "modules": {"order": ["shop/order"], "user": ["shop/user"], "util": ["shop/util"], "web": ["shop/web"]},
    "public": {"order": ["shop/order/__init__.py"], "user": ["shop/user/__init__.py"]},
    "allow": {"order": ["user", "util"], "user": [], "util": [], "web": ["order", "util"]},
}


def test_python_imports_are_resolved_to_project_files(tmp_path: Path) -> None:
    work = project(tmp_path, SHOP)
    imports = b.scan_imports(work, RULES)
    pairs = {(i.file, i.target) for i in imports}
    assert ("shop/order/service.py", "shop/user/__init__.py") in pairs  # `from shop.user import find_user`
    assert ("shop/order/__init__.py", "shop/order/service.py") in pairs  # a relative import
    assert ("shop/web/views.py", "shop/order/service.py") in pairs  # `from shop.order import service` is the module
    assert all(i.target != "os" for i in imports)  # third-party and standard library are never guessed


def test_check_reports_internals_and_forbidden_dependencies(tmp_path: Path) -> None:
    work = project(tmp_path, SHOP)
    found = b.run(work, RULES)
    messages = [v["message"] for v in found]
    assert any("web imports order's internals (shop/order/service.py)" in m for m in messages)
    assert not any("order may not depend on user" in m for m in messages)  # allowed, and via the public entry
    forbidden = {
        **SHOP,
        "shop/user/repo.py": "from shop.order import place\n\n\ndef find_user(uid):\n    return place(uid)\n",
    }
    found = b.run(project(tmp_path / "second", forbidden), RULES)
    assert any(v["rule"] == "not_allowed" and "user may not depend on order" in v["message"] for v in found)


def test_layers_flag_outward_dependencies_and_known_ones_do_not_fail(tmp_path: Path) -> None:
    files = {
        "api/h.py": "from core import m\n",
        "core/__init__.py": "",
        "core/m.py": "from api import h\n",
        "api/__init__.py": "",
    }
    rules = {
        "style": "layers",
        "modules": {"api": ["api"], "core": ["core"]},
        "layer_order": ["interface", "domain"],
        "layers": {"api": "interface", "core": "domain"},
    }
    work = project(tmp_path, files)
    found = b.run(work, rules)
    assert [v["file"] for v in found] == ["core/m.py"]  # domain → interface points outward
    rules["known"] = [found[0]["key"]]
    assert all(v["known"] for v in b.run(work, rules))


def test_table_owner_is_flagged_when_another_module_writes_it(tmp_path: Path) -> None:
    files = {
        "app/orders/models.py": "class Order:\n    __tablename__ = 'orders'\n",
        "app/billing/pay.py": 'SQL = "UPDATE orders SET paid = 1"\n',
    }
    rules = {
        "style": "modular_monolith",
        "modules": {"orders": ["app/orders"], "billing": ["app/billing"]},
        "allow": {},
    }
    work = project(tmp_path, files)
    tables = b.scan_tables(work, rules)
    assert tables["orders"] == {"owner": "orders", "writers": ["billing"]}
    assert [v["rule"] for v in b.check(rules, [], tables)] == ["table_owner"]


def test_moving_a_python_file_rewrites_every_import_of_it(tmp_path: Path) -> None:
    work = project(tmp_path, SHOP)
    move = mv.Move("move", "shop/util/slug.py", "shop/web", "only web uses it")
    edit = mv.make_edit(work, move)
    mv.apply_edit(work, edit)
    assert not (work / "shop/util/slug.py").exists()
    assert (work / "shop/web/slug.py").read_text(encoding="utf-8") == "def slug(x):\n    return x\n"
    assert "from shop.web.slug import slug" in (work / "shop/web/views.py").read_text(encoding="utf-8")


def test_a_moved_file_keeps_working_imports_of_its_own(tmp_path: Path) -> None:
    files = {
        **SHOP,
        "shop/util/helper.py": "from .money import fmt\nfrom . import slug\n\n\ndef h(x):\n    return fmt(slug.slug(x))\n",  # noqa: E501
        "shop/web/views.py": "from shop.util.helper import h\n",
    }
    work = project(tmp_path, files)
    mv.apply_edit(work, mv.make_edit(work, mv.Move("move", "shop/util/helper.py", "shop/web", "")))
    moved = (work / "shop/web/helper.py").read_text(encoding="utf-8")
    assert "from shop.util.money import fmt" in moved and "from shop.util import slug" in moved  # relative → absolute
    result = sh([sys.executable, "-c", "from shop.web.views import h; print(h('a'))"], work)
    assert result.returncode == 0 and result.stdout.strip() == "$a"


def test_a_module_imported_by_name_follows_the_move(tmp_path: Path) -> None:
    files = {**SHOP, "shop/web/views.py": "from shop.util import slug\n\nX = slug.slug('a')\n"}
    work = project(tmp_path, files)
    mv.apply_edit(work, mv.make_edit(work, mv.Move("move", "shop/util/slug.py", "shop/web", "")))
    assert (work / "shop/web/views.py").read_text(encoding="utf-8").startswith("from shop.web import slug")


def test_a_bare_import_without_alias_cannot_be_moved_safely(tmp_path: Path) -> None:
    files = {**SHOP, "shop/web/views.py": "import shop.util.slug\n\nX = shop.util.slug.slug('a')\n"}
    work = project(tmp_path, files)
    try:
        mv.make_edit(work, mv.Move("move", "shop/util/slug.py", "shop/web", ""))
    except mv.CannotMove as exc:
        assert "without an alias" in str(exc)
    else:
        raise AssertionError("expected CannotMove")


def test_restore_puts_every_file_back_exactly(tmp_path: Path) -> None:
    work = project(tmp_path, SHOP)
    before = {rel: (work / rel).read_text(encoding="utf-8") for rel in SHOP}
    undo = mv.apply_edit(work, mv.make_edit(work, mv.Move("move", "shop/util/slug.py", "shop/web", "")))
    mv.restore(work, undo)
    assert {rel: (work / rel).read_text(encoding="utf-8") for rel in SHOP} == before
    assert not (work / "shop/web/slug.py").exists()


def test_expose_points_importers_at_the_public_entry(tmp_path: Path) -> None:
    work = project(tmp_path, SHOP)
    edit = mv.make_edit(
        work, mv.Move("expose", "shop/order/service.py", "shop/order/__init__.py", "", ["shop/web/views.py"])
    )
    mv.apply_edit(work, edit)
    assert "from shop.order import place" in (work / "shop/web/views.py").read_text(encoding="utf-8")
    assert "from .service import place" in (work / "shop/order/__init__.py").read_text(encoding="utf-8")
    assert not [v for v in b.run(work, RULES) if v["file"] == "shop/web/views.py" and v["line"] == 1]  # line 1 is fixed


def test_planner_finds_the_file_only_one_module_uses_and_the_internal_import(tmp_path: Path) -> None:
    work = project(tmp_path, SHOP)
    planned, _ = mv.plan_moves(work, RULES)
    kinds = {(m.kind, m.file) for m in planned}
    assert ("move", "shop/util/slug.py") in kinds  # only web imports it
    assert ("expose", "shop/order/service.py") in kinds
    assert ("move", "shop/util/money.py") in kinds  # only order imports it


def test_typescript_move_rewrites_relative_specifiers(tmp_path: Path) -> None:
    files = {
        "src/cart/index.ts": "import { tax } from '../util/tax';\nexport const t = tax;\n",
        "src/util/tax.ts": "import { r } from './rate';\nexport const tax = r;\n",
        "src/util/rate.ts": "export const r = 1;\n",
        "src/pay/pay.ts": "import { tax } from '../util/tax.ts';\n",
    }
    work = project(tmp_path, files)
    mv.apply_edit(work, mv.make_edit(work, mv.Move("move", "src/util/tax.ts", "src/cart", "")))
    assert "from '../util/rate'" in (work / "src/cart/tax.ts").read_text(encoding="utf-8")
    assert "from './tax'" in (work / "src/cart/index.ts").read_text(encoding="utf-8")
    assert "from '../cart/tax.ts'" in (work / "src/pay/pay.ts").read_text(encoding="utf-8")


def test_the_checker_ships_with_the_project_and_enforces_the_rules(tmp_path: Path) -> None:
    work = project(tmp_path, SHOP)
    mv.write_rules(work, RULES, "# Architecture\n")
    run = [sys.executable, "architecture/check_boundaries.py"]
    failing = sh(run, work)
    assert failing.returncode == 1 and "internals" in failing.stdout
    assert sh([*run, "--update"], work).returncode == 0
    passing = sh(run, work)
    assert passing.returncode == 0 and "0 new violation(s)" in passing.stdout
