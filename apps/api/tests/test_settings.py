from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from pydantic import ValidationError

from agent.llm.config import ModelsConfig
from codewright_api.settings import REPO_ROOT

from .conftest import AppFactory


def test_repo_models_yaml_is_valid() -> None:
    models = ModelsConfig.from_yaml(REPO_ROOT / "config" / "models.yaml")
    assert set(models.profiles) == {"remote_gpu", "local_cpu"}
    assert all(p.server == "llamacpp" for p in models.profiles.values())
    assert all(p.max_parallel_llm_jobs == 1 for p in models.profiles.values())
    assert models.embeddings.dimensions == 1024


def test_default_profile_must_exist(tmp_path: Path) -> None:
    data = yaml.safe_load((REPO_ROOT / "config" / "models.yaml").read_text())
    data["default_profile"] = "remote_gpu"
    del data["profiles"]["remote_gpu"]
    path = tmp_path / "models.yaml"
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(ValidationError, match="default_profile"):
        ModelsConfig.from_yaml(path)


def test_settings_need_the_database(client: TestClient) -> None:
    # The run manager can't start without Postgres; the API says so instead of crashing.
    assert client.get("/api/health").status_code == 200
    assert client.put("/api/settings/llm", json={"active_profile": "local_cpu"}).status_code == 503


def test_switch_profile_and_replace_the_url(app_factory: AppFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REMOTE_GPU_API_KEY", "super-secret-value")
    with app_factory() as client:
        before = client.get("/api/settings").json()
        assert before["active_llm_profile"] == "remote_gpu"  # README Section 10: the GPU is the default

        res = client.put("/api/settings/llm", json={"active_profile": "local_cpu"})
        assert res.status_code == 200
        assert res.json()["active_llm_profile"] == "local_cpu"

        res = client.put(
            "/api/settings/llm",
            json={
                "active_profile": "remote_gpu",
                "profiles": {"remote_gpu": {"base_url": "http://100.64.0.7:8080/v1"}},
            },
        )
        assert res.status_code == 200
        body = res.json()
        assert body["active_llm_profile"] == "remote_gpu"
        assert body["llm_profiles"]["remote_gpu"]["base_url"] == "http://100.64.0.7:8080/v1"
        assert body["llm_profiles"]["remote_gpu"]["api_key_configured"] is True
        assert "super-secret-value" not in res.text

        # A new run uses the active profile unless the run picks one.
        run = client.post("/api/runs", json={"mode": "audit", "options": {"stub_delay_s": 0}}).json()
        assert run["llm_profile"] == "remote_gpu"
        client.post(f"/api/runs/{run['id']}/cancel")

        # Clearing the override falls back to the environment / models.yaml value.
        client.put("/api/settings/llm", json={"profiles": {"remote_gpu": {"base_url": ""}}})
        after = client.get("/api/settings").json()
        assert after["llm_profiles"]["remote_gpu"]["base_url"] == "http://127.0.0.1:9/v1"


def test_rejects_bad_urls(app_factory: AppFactory) -> None:
    with app_factory() as client:
        res = client.put("/api/settings/llm", json={"profiles": {"local_cpu": {"base_url": "gpu-box:8080"}}})
    assert res.status_code == 422


def test_health_reports_unreachable_servers(app_factory: AppFactory) -> None:
    with app_factory() as client:
        reports = client.get("/api/llm/health").json()
    assert {r["profile"]: r["status"] for r in reports} == {"remote_gpu": "unreachable", "local_cpu": "unreachable"}
