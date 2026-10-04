"""HTTP adapter and lightweight console coverage.

FastAPI is an optional server dependency, so the tests are skipped in the
minimal CLI environment.
"""
from __future__ import annotations

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from mewcode.runtime.http import CONSOLE_HTML, create_app
from mewcode.runtime.models import AgentRun, RunStatus


class FakeRuntime:
    def __init__(self) -> None:
        failed = AgentRun(id="failed-1", task="retry me", status=RunStatus.FAILED)
        self.runs = {failed.id: failed}

    def list_runs(self):
        return list(self.runs.values())

    def get(self, run_id):
        return self.runs.get(run_id)

    def submit(self, task, **kwargs):
        run = AgentRun(
            task=task,
            session_id=kwargs.get("session_id", ""),
            max_attempts=kwargs.get("max_attempts", 1),
            timeout_seconds=kwargs.get("timeout_seconds"),
            metadata=kwargs.get("metadata", {}),
        )
        self.runs[run.id] = run
        return run

    def cancel(self, run_id):
        return True

    async def subscribe(self, run_id, after=0):
        if False:
            yield None


def test_console_is_served_and_contains_core_actions():
    client = TestClient(create_app(FakeRuntime()))
    response = client.get("/")
    assert response.status_code == 200
    assert "MewCode 控制台" in response.text
    assert "/v1/runs" in response.text
    assert "EventSource" in response.text
    assert "运行概览" in response.text
    assert "stat-total" in response.text
    assert "搜索任务或运行 ID" in response.text
    assert "focusComposer" in response.text
    assert "与 LLM 对话" in response.text
    assert "tool_result" in response.text


def test_health_endpoint_returns_runtime_liveness():
    client = TestClient(create_app(FakeRuntime()))
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "mewcode-runtime",
        "runs": 1,
    }


def test_list_and_retry_endpoints():
    runtime = FakeRuntime()
    client = TestClient(create_app(runtime))

    response = client.get("/v1/runs?status=failed")
    assert response.status_code == 200
    assert response.json()["runs"][0]["id"] == "failed-1"

    response = client.post("/v1/runs/failed-1/retry")
    assert response.status_code == 202
    retried = response.json()
    assert retried["task"] == "retry me"
    assert retried["metadata"]["retry_of"] == "failed-1"


def test_submit_accepts_session_for_follow_up_chat():
    runtime = FakeRuntime()
    client = TestClient(create_app(runtime))

    response = client.post(
        "/v1/runs",
        json={"task": "继续刚才的分析", "session_id": "web-session-1"},
    )

    assert response.status_code == 202
    assert response.json()["session_id"] == "web-session-1"
