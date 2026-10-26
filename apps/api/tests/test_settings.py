from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from pydantic import ValidationError

from monoshift_api.settings import REPO_ROOT, ModelsConfig


def test_repo_models_yaml_is_valid() -> None:
    models = ModelsConfig.from_yaml(REPO_ROOT / "config" / "models.yaml")
    assert set(models.profiles) == {"remote_gpu", "local_cpu"}
    assert models.default_profile == "remote_gpu"
    assert all(p.max_parallel_llm_jobs == 1 for p in models.profiles.values())


def test_default_profile_must_exist(tmp_path: Path) -> None:
    data = yaml.safe_load((REPO_ROOT / "config" / "models.yaml").read_text())
    del data["profiles"]["remote_gpu"]
    path = tmp_path / "models.yaml"
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(ValidationError, match="default_profile"):
        ModelsConfig.from_yaml(path)


def test_settings_view_exposes_no_secrets(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MONOSHIFT_REMOTE_GPU_API_KEY", "super-secret-value")
    res = client.get("/api/settings")
    assert res.status_code == 200
    body = res.json()
    assert body["default_llm_profile"] == "remote_gpu"
    assert body["external_llm_enabled"] is False
    assert body["llm_profiles"]["remote_gpu"]["api_key_configured"] is True
    assert body["llm_profiles"]["local_cpu"]["api_key_configured"] is False
    assert "super-secret-value" not in res.text
    assert "unused" not in res.text  # the database URL (with its password) is never returned
