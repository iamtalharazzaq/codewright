"""Packaging stateless parts as serverless functions (Phase 17): the entry-point analysis is the one an extraction
uses (`agent.microservices.extract`); only the packaging (a handler instead of an RPC router, a deploy manifest
instead of a Dockerfile) and never touching the monolith's own copy are new."""

from __future__ import annotations

import importlib
import shutil
import sys
from pathlib import Path

import yaml

from agent.decomposition import boundaries as b
from agent.microservices import extract as ex
from agent.microservices import serverless as sv
from agent.tests.microservices.test_foundation_extract import SHOP, project

# `util` is left out, same as the real `to_be` design's groups: unowned, it is copied as a shared helper rather than
# blocking the extraction on an unbuilt dependency.
RULES = {"modules": {"payment": ["shop/payment"], "order": ["shop/order"]}}


def test_stateless_groups_are_backend_groups_with_no_table_and_no_saga() -> None:
    design = {
        "groups": [
            {"name": "frontend", "kind": "frontend", "tables": []},
            {"name": "order", "kind": "backend", "tables": ["orders"]},
            {"name": "notification", "kind": "backend", "tables": []},
            {"name": "checkout", "kind": "backend", "tables": [], "sagas": ["checkout"]},
        ]
    }
    assert sv.stateless_groups(design) == ["notification"]


def test_apply_package_copies_the_group_and_writes_a_handler_and_a_manifest(tmp_path: Path) -> None:
    work = project(tmp_path, SHOP)
    plan_x = ex.plan_extraction(work, RULES, "payment")
    assert not plan_x.blocked, plan_x.blocked
    roots = b.py_roots(work)
    before = sv.apply_package(work, plan_x, roots, "payment_service", "python3.12")
    assert (work / "services/payment/src/shop/payment/service.py").is_file()
    assert (work / "services/payment/src/payment_service/handler.py").is_file()
    assert (work / "services/payment/deploy/template.yaml").is_file()
    assert (work / "services/payment/tests/test_handler.py").is_file()
    # The monolith's own copy is never touched: no shim, no `_local_` file, nothing removed.
    assert "def charge" in (work / "shop/payment/service.py").read_text(encoding="utf-8")
    assert not (work / "codewright_acl.py").exists()
    manifest = yaml.safe_load((work / "services/payment/deploy/template.yaml").read_text(encoding="utf-8"))
    assert any("charge" in k for k in manifest["Resources"])
    handler = (work / "services/payment/src/payment_service/handler.py").read_text(encoding="utf-8")
    assert "shop.payment.service" in handler and "charge" in handler
    ex.restore(work, before)
    shutil.rmtree(work / "services/payment", ignore_errors=True)  # restore only undoes files, same as an extraction
    assert not (work / "services/payment").exists()


def test_the_handler_answers_an_exposed_function_and_refuses_an_unexposed_one(tmp_path: Path) -> None:
    exposed = {"shop.payment.service": ["charge"]}
    (tmp_path / "shop/payment").mkdir(parents=True)
    (tmp_path / "shop/__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "shop/payment/__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "shop/payment/service.py").write_text(
        "def charge(amount):\n    return {'charged': amount}\n", encoding="utf-8"
    )
    (tmp_path / "handler.py").write_text(sv.handler_source("pkg", exposed), encoding="utf-8")
    sys.path.insert(0, str(tmp_path))
    try:
        handler = importlib.import_module("handler")
        answer = handler.handler({"module": "shop.payment.service", "function": "charge", "args": [5], "kwargs": {}})
        assert answer == {"statusCode": 200, "body": {"result": {"charged": 5}}}
        assert handler.handler({"module": "shop.payment.service", "function": "refund"})["statusCode"] == 404
    finally:
        sys.path.remove(str(tmp_path))
        sys.modules.pop("handler", None)


def test_deploy_manifest_is_valid_yaml_with_one_function_per_exposed_name() -> None:
    manifest = sv.deploy_manifest("notification", "notification_service", {"a.b": ["send", "retry"]}, "python3.12")
    assert manifest["AWSTemplateFormatVersion"] and len(manifest["Resources"]) == 2
    rendered = yaml.safe_load(yaml.safe_dump(manifest))
    assert rendered == manifest
