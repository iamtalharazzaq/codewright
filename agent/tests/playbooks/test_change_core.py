"""baseline_recording: skip a recording the recorder made against a dead app, so a later replay never calls
today's normal answers a regression against yesterday's downtime."""

from __future__ import annotations

from pathlib import Path

from agent.playbooks.change_core import baseline_recording
from agent.tests.conftest import FakeProject
from agent.tests.playbooks.test_code_playbooks import repo

DEAD = {"id": "rec-dead", "exchanges": 6, "server_errors": 5, "unanswered": 1}
GOOD = {"id": "rec-good", "exchanges": 6, "server_errors": 0, "unanswered": 0}
RECORDED = {"ok": True, "error": None, "report": None}


async def test_an_all_failed_recording_is_not_reused_as_the_baseline(tmp_path: Path) -> None:
    project = FakeProject(repo(tmp_path, {"x.py": "x = 1\n"}), recordings=[DEAD, GOOD])
    recording_id, note = await baseline_recording(project)
    assert recording_id == "rec-good"
    assert "rec-good" in note
    assert project.verified == []  # found a usable one; never had to record


async def test_recording_fresh_when_every_existing_one_is_dead(tmp_path: Path) -> None:
    project = FakeProject(repo(tmp_path, {"x.py": "x = 1\n"}), recordings=[DEAD], verifications={"record": [RECORDED]})
    recording_id, note = await baseline_recording(project)
    assert recording_id is None  # FakeProject.recordings() doesn't change after verify("record") is called
    assert note == "Nothing was recorded"
    assert project.verified == ["record"]


async def test_a_recording_with_no_health_fields_is_trusted(tmp_path: Path) -> None:
    project = FakeProject(repo(tmp_path, {"x.py": "x = 1\n"}), recordings=[{"id": "rec1"}])
    recording_id, _ = await baseline_recording(project)
    assert recording_id == "rec1"
