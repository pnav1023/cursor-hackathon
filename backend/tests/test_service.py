from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from workflow_compiler.jobs import JobStore
from workflow_compiler import service

ROOT = Path(__file__).resolve().parents[2]
SPEC = ROOT / "fixtures" / "openemr" / "openapi.yaml"
WORKFLOWS = ROOT / "fixtures" / "openemr" / "workflows.json"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.delenv("COMPILE_API_KEY", raising=False)
    service.store = JobStore(tmp_path / "jobs")
    return TestClient(service.app)


def test_health(client) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_create_job_requires_video_or_workflows(client) -> None:
    with SPEC.open("rb") as handle:
        response = client.post("/v1/jobs", files={"spec": ("openapi.yaml", handle, "application/yaml")})
    assert response.status_code == 400
    assert "video" in response.json()["detail"].lower() or "workflows" in response.json()["detail"].lower()


def test_create_job_compiles_workflows(client, monkeypatch) -> None:
    monkeypatch.setattr(
        "workflow_compiler.jobs.run_compile",
        lambda **_kwargs: {
            "workflows": [],
            "plans": {},
            "skills": [{"name": "schedule-and-check-in-patient", "markdown": "# Skill\n"}],
        },
    )
    with WORKFLOWS.open("rb") as workflows, SPEC.open("rb") as spec:
        response = client.post(
            "/v1/jobs",
            files={
                "workflows": ("workflows.json", workflows, "application/json"),
                "spec": ("openapi.yaml", spec, "application/yaml"),
            },
        )
    assert response.status_code == 202
    job_id = response.json()["id"]
    assert response.json()["status"] in {"queued", "running", "done"}

    status = client.get(f"/v1/jobs/{job_id}")
    assert status.status_code == 200
    assert status.json()["status"] == "done"
    assert status.json()["skill_count"] == 1
    assert "markdown" not in status.json()["skills"][0]

    result = client.get(f"/v1/jobs/{job_id}/result")
    assert result.status_code == 200
    assert result.json()["skills"][0]["markdown"].startswith("# Skill")


def test_unknown_job_404(client) -> None:
    assert client.get("/v1/jobs/does-not-exist").status_code == 404


def test_api_key_required_when_configured(client, monkeypatch) -> None:
    monkeypatch.setenv("COMPILE_API_KEY", "secret")
    response = client.post("/v1/jobs")
    assert response.status_code == 401
    ok = client.get("/health")
    assert ok.status_code == 200
