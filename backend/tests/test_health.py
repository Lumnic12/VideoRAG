"""
Tests — Phase 0 health check
Run: cd backend && python -m pytest tests/ -v --tb=short
"""
import pytest
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_root_returns_200():
    resp = client.get("/")
    assert resp.status_code == 200


def test_health_endpoint_shape():
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert "status" in data
    assert "redis" in data
    assert "celery" in data
    assert "version" in data


def test_health_v1_alias():
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json()["version"] == "0.1.0"


def test_query_stub():
    resp = client.post("/api/v1/query", json={"question": "What is SSIM?"})
    assert resp.status_code == 200
    data = resp.json()
    assert "answer" in data
    assert "sources" in data


def test_upload_rejects_non_video(tmp_path):
    fake_file = tmp_path / "not_a_video.txt"
    fake_file.write_text("hello")
    with open(fake_file, "rb") as f:
        resp = client.post(
            "/api/v1/upload",
            files={"file": ("not_a_video.txt", f, "text/plain")},
        )
    assert resp.status_code == 422


def test_task_status_stub():
    resp = client.get("/api/v1/tasks/some-fake-task-id")
    assert resp.status_code == 200
    data = resp.json()
    assert data["task_id"] == "some-fake-task-id"
    assert data["status"] in ("pending", "processing", "done", "error")
