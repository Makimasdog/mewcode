from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from mewcode.runtime.dag import DAGNode, DAGScheduler, NodeStatus
from mewcode.runtime.models import RunStatus
from mewcode.runtime.service import AgentRuntime
from mewcode.runtime.store import RunStore


class FakeAgent:
    def __init__(self, result: str = "ok", delay: float = 0, failures: int = 0) -> None:
        self.result = result
        self.delay = delay
        self.failures = failures
        self.calls = 0

    async def run_to_completion(self, task, conversation=None, event_callback=None):
        self.calls += 1
        if event_callback:
            event_callback({"type": "stream_text", "text": task})
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.failures > 0:
            self.failures -= 1
            raise RuntimeError("transient")
        return self.result


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
