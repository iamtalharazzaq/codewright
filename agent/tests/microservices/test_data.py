"""The data side of a microservices conversion (Phase 17): the saga library's generated tests actually pass (run
for real, in a subprocess), the stage files and scripts are consistent, and the frontend's hardcoded API addresses
are pointed at the gateway."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from agent.microservices import data, dbsplit

PLAN: dict[str, Any] = {
    "services": [
        {
            "service": "order", "schema": "order", "tables": ["orders"], "drop_fks": [],
            "produces": ["order.placed"], "consumes": [], "sagas": ["checkout"],
        },
        {
            "service": "payment", "schema": "payment", "tables": ["payments"],
            "drop_fks": [{"table": "payments", "column": "order_id", "ref_table": "orders", "ref_column": "id", "constraint": "payments_order_id_fkey"}],  # noqa: E501
            "produces": [], "consumes": ["order.placed"], "sagas": [],
        },
    ],
    "unassigned_tables": [],
    "foreign_keys": 1,
}  # fmt: skip
PLATFORM: dict[str, Any] = {
    "sagas": [
        {
            "name": "checkout",
            "orchestrator": "order",
            "steps": ["reserve_stock", "charge_payment"],
            "compensations": ["release_stock", "refund_payment"],
        }
    ]
}


def test_the_saga_state_check_constraint_accepts_compensated() -> None:
    """The 1-line fix: `saga.py`'s COMPENSATED status must be a value the table's CHECK constraint allows."""
    entry = {**PLAN["services"][0], "schema": "order"}
    up, _down = dbsplit.render(entry, {})
    assert "'compensated'" in up
    constraint = next(line for line in up.splitlines() if "saga_state" in line and "CHECK" in line)
    assert all(s in constraint for s in ("'running'", "'completed'", "'compensating'", "'compensated'", "'failed'"))


def test_stage_files_cover_expand_check_and_contract_in_order() -> None:
    files = data.stage_files(PLAN)
    assert f"{dbsplit.MIGRATIONS}/001_order.check.sql" in files
    assert f"{dbsplit.MIGRATIONS}/101_order_contract.up.sql" in files
    assert f"{dbsplit.MIGRATIONS}/101_order_contract.down.sql" in files
    assert f"{dbsplit.MIGRATIONS}/apply.sh" in files and f"{dbsplit.MIGRATIONS}/rollback.sh" in files
    assert f"{dbsplit.MIGRATIONS}/STAGES.md" in files
    check = files[f"{dbsplit.MIGRATIONS}/001_order.check.sql"]
    assert "count(*)" in check and "RAISE EXCEPTION" in check
    up, down = (
        files[f"{dbsplit.MIGRATIONS}/101_order_contract.up.sql"],
        files[f"{dbsplit.MIGRATIONS}/101_order_contract.down.sql"],
    )
    assert 'DROP VIEW IF EXISTS public."orders"' in up and 'CREATE VIEW public."orders"' in down
    apply_sh = files[f"{dbsplit.MIGRATIONS}/apply.sh"]
    assert "001_order.up.sql" in apply_sh and "002_payment.up.sql" in apply_sh
    assert "001_order.check.sql" in apply_sh and "002_payment.check.sql" in apply_sh
    rollback_sh = files[f"{dbsplit.MIGRATIONS}/rollback.sh"]
    assert "101_order_contract.down.sql" in rollback_sh


def test_stage_files_with_no_owning_service_says_so() -> None:
    empty = {
        "services": [
            {
                "service": "notify",
                "schema": "notify",
                "tables": [],
                "drop_fks": [],
                "produces": [],
                "consumes": [],
                "sagas": [],
            }
        ],
        "unassigned_tables": [],
    }
    files = data.stage_files(empty)
    assert "No service owns a table in this design" in files[f"{dbsplit.MIGRATIONS}/STAGES.md"]
    assert not any(f.endswith(".check.sql") for f in files)


def test_saga_files_are_only_written_when_the_design_has_sagas() -> None:
    assert data.saga_files({"sagas": []}) == {}
    files = data.saga_files(PLATFORM)
    assert {f"{data.SAGA_DIR}/saga.py", f"{data.SAGA_DIR}/test_sagas.py", data.SAGAS_JSON} <= set(files)
    assert json.loads(files[data.SAGAS_JSON])["sagas"][0]["name"] == "checkout"
    assert data.saga_paths(PLATFORM) == 3  # success + a failure at each of the 2 steps


def test_the_generated_saga_tests_actually_pass(tmp_path: Path) -> None:
    """Every path data.py claims to cover (success, a failure at each step, a failing undo, a crash and resume) is
    run for real, not just asserted about: the generated test file is written and executed with pytest."""
    files = data.saga_files(PLATFORM)
    for rel, text in files.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "pytest", str(tmp_path / data.SAGA_DIR / "test_sagas.py"), "-q"],
        capture_output=True, text=True, check=False, cwd=tmp_path,
    )  # fmt: skip
    assert result.returncode == 0, result.stdout + result.stderr
    assert "failed" not in result.stdout.lower() or "0 failed" in result.stdout.lower()


def test_gateway_rewrite_only_touches_api_looking_lines_and_leaves_the_gateway_port_alone() -> None:
    text = (
        'export const API_URL = "http://localhost:3001/api";\n'
        'const DEV_SERVER = "http://localhost:5173";\n'  # the frontend's own dev address: not an API line
        'const already = "http://localhost:8080/foo";\n'  # already the gateway port
    )
    new_text, changed = data.gateway_rewrite(text, gateway_port=8080)
    assert "http://localhost:8080/api" in new_text
    assert "http://localhost:5173" in new_text  # untouched: no API hint on that line
    assert len(changed) == 1


def test_gateway_routes_doc_lists_live_and_pending_services() -> None:
    design = {"groups": [{"name": "frontend", "kind": "frontend"}]}
    routes = {
        "services": {"payment": {"prefix": "/payment/", "live": True}, "order": {"prefix": "/order/", "live": False}}
    }
    doc = data.gateway_routes_doc(design, routes)
    assert "| `/order/` | order service | not yet (monolith) |" in doc
    assert "| `/payment/` | payment service | yes |" in doc
