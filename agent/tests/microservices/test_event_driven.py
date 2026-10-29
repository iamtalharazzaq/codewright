"""Introducing events between parts that should be decoupled (Phase 17): the bus and the subscription wiring are
real and exercised for real; the producer's call site is deliberately left for a human to review (the module
docstring says why), so this only checks that the review doc names it, never that it was rewritten."""

from __future__ import annotations

from pathlib import Path

from agent.microservices import event_driven as ev
from agent.microservices import foundation as fd
from agent.tests.microservices.test_foundation_extract import RULES, SHOP, project, run

EVENT = {"event": "order.changed", "producer": "order", "consumers": ["payment"], "why": "decouple payment"}
PLATFORM = {"events": [EVENT]}


def test_targets_finds_only_what_the_producers_own_files_call(tmp_path: Path) -> None:
    work = project(tmp_path, SHOP)
    found = ev.targets(work, RULES, "order", "payment")
    assert found == {"shop/payment/service.py": ["charge", "refund"]}


def test_targets_is_empty_when_the_producer_calls_nothing_of_the_consumer(tmp_path: Path) -> None:
    work = project(tmp_path, SHOP)
    assert ev.targets(work, RULES, "util", "payment") == {}


def test_apply_writes_the_bus_and_subscribes_the_existing_functions(tmp_path: Path) -> None:
    work = project(tmp_path, SHOP)
    before, info = ev.apply(work, RULES, PLATFORM)
    assert (work / "libs/events/bus.py").is_file() and (work / "libs/events/envelope.py").is_file()
    assert info == {
        "events": 1,
        "subscribed": {"order.changed": ["charge", "refund"]},
        "call_sites": {"order.changed": {"shop/payment/service.py": ["charge", "refund"]}},
    }
    text = (work / "shop/payment/service.py").read_text(encoding="utf-8")
    assert "# codewright:event-subscriber:order.changed" in text
    assert "_codewright_subscribe('order.changed', charge)" in text
    assert "_codewright_subscribe('order.changed', refund)" in text
    assert "def charge" in text  # the original function is untouched, only appended to
    doc = (work / ev.REVIEW_DOC_PATH).read_text(encoding="utf-8")
    assert "order.changed" in doc and "shop/payment/service.py" in doc and "publish(" in doc
    ev.restore(work, before)
    assert not (work / "libs/events/bus.py").exists() and not (work / "libs/events/envelope.py").exists()
    assert "codewright:event-subscriber" not in (work / "shop/payment/service.py").read_text(encoding="utf-8")


def test_apply_is_idempotent_across_reruns(tmp_path: Path) -> None:
    work = project(tmp_path, SHOP)
    ev.apply(work, RULES, PLATFORM)
    before_text = (work / "shop/payment/service.py").read_text(encoding="utf-8")
    before, info = ev.apply(work, RULES, PLATFORM)  # nothing new to write: the marker is already there
    assert (work / "shop/payment/service.py").read_text(encoding="utf-8") == before_text
    assert info["subscribed"] == {}  # already subscribed; nothing added this time
    assert "shop/payment/service.py" not in before  # not touched, so not in the undo map either


def test_no_events_writes_nothing() -> None:
    before, info = ev.apply(Path("/nonexistent"), RULES, {"events": []})
    assert before == {} and info["events"] == 0


def test_review_doc_names_the_call_site_and_says_why_it_was_not_rewritten() -> None:
    doc = ev.review_doc([EVENT], {"order.changed": {"shop/payment/service.py": ["charge", "refund"]}})
    assert "order → payment" in doc
    assert "shop/payment/service.py" in doc and "charge, refund" in doc
    assert "nothing uses its return value" in doc


def test_review_doc_says_when_no_call_site_was_found() -> None:
    doc = ev.review_doc([EVENT], {})
    assert "No call from the producer's own files" in doc


def test_the_bus_delivers_to_a_subscriber_with_the_envelope(tmp_path: Path) -> None:
    """The in-process registry is exercised for real: subscribe, publish, and the envelope's shape round-trips."""
    (tmp_path / "libs/events").mkdir(parents=True)
    (tmp_path / "libs/__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "libs/events/__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "libs/events/envelope.py").write_text(fd.ENVELOPE_PY, encoding="utf-8")
    (tmp_path / "libs/events/bus.py").write_text(ev.BUS_PY, encoding="utf-8")
    code = (
        "from libs.events.bus import publish, subscribe\n"
        "seen = []\n"
        "def handler(event):\n"
        "    seen.append(event)\n"
        "subscribe('order.changed', handler)\n"
        "subscribe('order.changed', handler)\n"  # the same handler again: still called once, not twice
        "publish('order.changed', 'order', {'order_id': 1})\n"
        "assert len(seen) == 1\n"
        "e = seen[0]\n"
        "assert e['type'] == 'order.changed' and e['source'] == 'order' and e['data'] == {'order_id': 1}\n"
        "assert set(['id', 'time', 'version']) <= set(e)\n"
        "print('ok')\n"
    )
    done = run(code, tmp_path)
    assert done.returncode == 0, done.stdout + done.stderr
