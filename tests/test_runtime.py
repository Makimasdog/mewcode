from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from mewcode.runtime.dag import DAGNode, DAGScheduler, NodeStatus
from mewcode.runtime.bootstrap import _runtime_permission_mode, build_runtime
from mewcode.runtime.models import AgentRun, RunStatus
from mewcode.runtime.service import AgentRuntime
from mewcode.runtime.store import RunStore
from mewcode.config import AppConfig, ProviderConfig
from mewcode.permissions import (
    DangerousCommandDetector, PathSandbox, PermissionChecker, PermissionMode, RuleEngine,
)
from mewcode.tools import create_default_registry
from mewcode.tools.dag_tools import DAGCreateTool


class FakeAgent:
    def __init__(self, result: str = "ok", delay: float = 0, failures: int = 0) -> None:
        self.result = result
        self.delay = delay
        self.failures = failures
        self.calls = 0
        self.client = type("Client", (), {"model": "test-model"})()

    async def run_to_completion(self, task, conversation=None, event_callback=None):
        self.calls += 1
        if event_callback:
            event_callback({
                "type": "stream_text", "text": task,
                "phase": "thinking", "iteration": 1,
            })
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.failures > 0:
            self.failures -= 1
            raise RuntimeError("transient")
        return self.result


def test_web_default_permission_allows_writes_and_dag_but_keeps_guards(tmp_path: Path):
    assert _runtime_permission_mode("default") == PermissionMode.DONT_ASK
    assert _runtime_permission_mode("plan") == PermissionMode.PLAN
    checker = PermissionChecker(
        detector=DangerousCommandDetector(),
        sandbox=PathSandbox(str(tmp_path)),
        rule_engine=RuleEngine(),
        mode=_runtime_permission_mode("default"),
    )
    registry = create_default_registry()
    write = registry.get("WriteFile")
    bash = registry.get("Bash")
    assert write is not None and bash is not None
    assert checker.check(write, {"file_path": str(tmp_path / "result.txt")}).effect == "allow"
    assert checker.check(DAGCreateTool(object(), work_dir=str(tmp_path)), {}).effect == "allow"
    assert checker.check(write, {"file_path": str(Path.home() / "outside.txt")}).effect == "deny"
    assert checker.check(bash, {"command": "rm -rf /"}).effect == "deny"


def test_web_runtime_factory_uses_noninteractive_permission_mode(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("mewcode.runtime.bootstrap.create_client", lambda provider: object())
    config = AppConfig(providers=[ProviderConfig(
        name="test", protocol="openai-compat", base_url="http://localhost/v1", model="test",
    )])
    runtime = build_runtime(config, work_dir=str(tmp_path))
    agent = runtime.agent_factory(AgentRun(task="create a file"))
    assert agent.permission_mode == PermissionMode.DONT_ASK
    assert agent.registry.get("DAGCreate") is not None
    assert agent.permission_checker.check(agent.registry.get("DAGCreate"), {}).effect == "allow"


@pytest.mark.asyncio
async def test_runtime_persists_events_and_retries(tmp_path: Path):
    agents: list[FakeAgent] = []

    def factory(_run):
        agent = FakeAgent(result="done", failures=1 if not agents else 0)
        agents.append(agent)
        return agent

    runtime = AgentRuntime(
        agent_factory=factory,
        store=RunStore(tmp_path / "runs"),
    )
    run = runtime.submit("hello", max_attempts=2)
    for _ in range(30):
        await asyncio.sleep(0.05)
        if runtime.get(run.id).status in {RunStatus.COMPLETED, RunStatus.FAILED}:
            break

    stored = runtime.get(run.id)
    assert stored is not None
    assert stored.status == RunStatus.COMPLETED
    assert stored.attempt == 2
    event_types = [event.event_type for event in runtime.events(run.id)]
    assert "run_retrying" in event_types
    assert "stream_text" in event_types
    progress = next(event for event in runtime.events(run.id) if event.event_type == "stream_text")
    assert progress.payload["phase"] == "thinking"
    assert progress.payload["iteration"] == 1
    assert progress.payload["model"] == "test-model"
    assert progress.payload["attempt"] in {1, 2}
    retry = next(event for event in runtime.events(run.id) if event.event_type == "run_retrying")
    assert retry.payload["error_category"] == "execution"
    assert retry.payload["delay_seconds"] == 1
    assert event_types[-1] == "run_completed"
    assert len(agents) == 2


@pytest.mark.asyncio
async def test_runtime_cancel_is_durable(tmp_path: Path):
    runtime = AgentRuntime(
        agent_factory=lambda _run: FakeAgent(delay=10),
        store=RunStore(tmp_path / "runs"),
    )
    run = runtime.submit("slow")
    await asyncio.sleep(0.02)
    assert runtime.cancel(run.id) is True
    await asyncio.sleep(0.02)
    assert runtime.get(run.id).status == RunStatus.CANCELLED
    assert runtime.events(run.id)[-1].event_type == "run_cancelled"


def test_dag_validation_rejects_cycle(tmp_path: Path):
    scheduler = DAGScheduler(tmp_path)
    with pytest.raises(ValueError, match="cycle"):
        scheduler.create([
            DAGNode(id="a", task="a", dependencies=["b"]),
            DAGNode(id="b", task="b", dependencies=["a"]),
        ])


@pytest.mark.asyncio
async def test_dag_runs_ready_nodes_in_parallel_and_passes_outputs(tmp_path: Path):
    scheduler = DAGScheduler(tmp_path, max_parallel=2)
    run = scheduler.create([
        DAGNode(id="explore", task="explore"),
        DAGNode(id="tests", task="tests"),
        DAGNode(id="review", task="review", dependencies=["explore", "tests"]),
    ])
    calls: list[str] = []

    async def execute(node, dependencies):
        calls.append(node.id)
        await asyncio.sleep(0.01)
        if dependencies:
            assert set(dependencies) == {"explore", "tests"}
        return f"result:{node.id}"

    completed = await scheduler.run(run, execute)
    assert completed.status == NodeStatus.COMPLETED
    assert calls[:2] == ["explore", "tests"]
    assert calls[2] == "review"
    assert completed.nodes["review"].result == "result:review"
    assert scheduler.load(run.id).status == NodeStatus.COMPLETED
