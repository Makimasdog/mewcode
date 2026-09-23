from __future__ import annotations

import asyncio
import enum
import json
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class NodeStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


@dataclass
class DAGNode:
    id: str
    task: str
    dependencies: list[str] = field(default_factory=list)
    agent_type: str | None = None
    description: str = ""
    max_attempts: int = 1
    status: NodeStatus = NodeStatus.PENDING
    result: str = ""
    error: str = ""
    artifacts: dict[str, Any] = field(default_factory=dict)
    started_at: float | None = None
    ended_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        data = self.__dict__.copy()
        data["status"] = self.status.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DAGNode:
        data = dict(data)
        data["status"] = NodeStatus(data.get("status", NodeStatus.PENDING.value))
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class DAGRun:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    nodes: dict[str, DAGNode] = field(default_factory=dict)
    status: NodeStatus = NodeStatus.PENDING
    error: str = ""
    created_at: float = field(default_factory=time.time)
    ended_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "nodes": {key: node.to_dict() for key, node in self.nodes.items()},
            "status": self.status.value,
            "error": self.error,
            "created_at": self.created_at,
            "ended_at": self.ended_at,
        }


NodeExecutor = Callable[[DAGNode, dict[str, str]], Awaitable[str]]


class DAGScheduler:
    """Dependency-aware scheduler for Agent nodes.

    Nodes whose dependencies are complete are launched together. The executor
    is intentionally injected, so the scheduler can run AgentTool, a remote
    Agent Runtime, or a deterministic test double without knowing either API.
    """

    def __init__(
        self,
        store_dir: str | Path = ".mewcode/dag-runs",
        max_parallel: int = 4,
    ) -> None:
        self.store_dir = Path(store_dir)
        self.store_dir.mkdir(parents=True, exist_ok=True)
        self.max_parallel = max(1, max_parallel)
        self.runs: dict[str, DAGRun] = {}

    @staticmethod
    def validate(nodes: list[DAGNode]) -> None:
        ids = [node.id for node in nodes]
        if len(ids) != len(set(ids)):
            raise ValueError("DAG node ids must be unique")
        known = set(ids)
        for node in nodes:
            missing = set(node.dependencies) - known
            if missing:
                raise ValueError(f"Node {node.id} depends on unknown nodes: {sorted(missing)}")
        remaining = {node.id: set(node.dependencies) for node in nodes}
        while remaining:
            ready = [node_id for node_id, deps in remaining.items() if not deps]
            if not ready:
                raise ValueError("DAG contains a dependency cycle")
            for node_id in ready:
                remaining.pop(node_id)
            for deps in remaining.values():
                deps.difference_update(ready)

    def create(self, nodes: list[DAGNode], run_id: str | None = None) -> DAGRun:
        self.validate(nodes)
        run = DAGRun(id=run_id or uuid.uuid4().hex[:12], nodes={n.id: n for n in nodes})
        self.runs[run.id] = run
        self._save(run)
        return run

    async def run(
        self,
        run: DAGRun,
        executor: NodeExecutor,
        *,
        max_parallel: int | None = None,
        fail_fast: bool = True,
    ) -> DAGRun:
        self.validate(list(run.nodes.values()))
        parallel = max(1, max_parallel or self.max_parallel)
        run.status = NodeStatus.RUNNING
        self._save(run)
        outputs: dict[str, str] = {}

        while True:
            pending = [n for n in run.nodes.values() if n.status == NodeStatus.PENDING]
            if not pending:
                break

            for node in pending:
                if any(run.nodes[d].status in {NodeStatus.FAILED, NodeStatus.BLOCKED, NodeStatus.CANCELLED} for d in node.dependencies):
                    node.status = NodeStatus.BLOCKED
                    node.error = "dependency failed"

            ready = [
                node for node in pending
                if node.status == NodeStatus.PENDING
                and all(run.nodes[d].status == NodeStatus.COMPLETED for d in node.dependencies)
            ][:parallel]

            if not ready:
                if any(n.status == NodeStatus.BLOCKED for n in run.nodes.values()):
                    continue
                run.status = NodeStatus.FAILED
                run.error = "DAG stalled: no runnable nodes"
                break

            tasks = [asyncio.create_task(self._run_node(node, outputs, executor)) for node in ready]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for node, result in zip(ready, results):
                if isinstance(result, BaseException):
                    node.status = NodeStatus.FAILED
                    node.error = str(result)
                    if fail_fast:
                        for other in run.nodes.values():
                            if other.status == NodeStatus.PENDING:
                                other.status = NodeStatus.BLOCKED
                                other.error = f"blocked by failed node {node.id}"
                        run.status = NodeStatus.FAILED
                        run.error = f"node {node.id} failed: {node.error}"
                        self._save(run)
                        return run
                else:
                    outputs[node.id] = node.result
            self._save(run)

        if any(n.status == NodeStatus.FAILED for n in run.nodes.values()):
            run.status = NodeStatus.FAILED
        elif any(n.status == NodeStatus.BLOCKED for n in run.nodes.values()):
            run.status = NodeStatus.BLOCKED
        else:
            run.status = NodeStatus.COMPLETED
        run.ended_at = time.time()
        self._save(run)
        return run

    async def _run_node(
        self,
        node: DAGNode,
        outputs: dict[str, str],
        executor: NodeExecutor,
    ) -> None:
        node.status = NodeStatus.RUNNING
        node.started_at = time.time()
        dependency_context = {dependency: outputs[dependency] for dependency in node.dependencies}
        last_error = ""
        for attempt in range(max(1, node.max_attempts)):
            try:
                node.result = await executor(node, dependency_context)
                node.status = NodeStatus.COMPLETED
                node.ended_at = time.time()
                return
            except asyncio.CancelledError:
                node.status = NodeStatus.CANCELLED
                node.ended_at = time.time()
                raise
            except Exception as exc:
                last_error = str(exc)
                if attempt + 1 < max(1, node.max_attempts):
                    await asyncio.sleep(min(2**attempt, 4))
        node.status = NodeStatus.FAILED
        node.error = last_error or "node failed"
        node.ended_at = time.time()
        raise RuntimeError(node.error)

    def _save(self, run: DAGRun) -> None:
        path = self.store_dir / f"{run.id}.json"
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(run.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)

    def load(self, run_id: str) -> DAGRun | None:
        path = self.store_dir / f"{run_id}.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            run = DAGRun(
                id=str(data["id"]),
                nodes={k: DAGNode.from_dict(v) for k, v in data.get("nodes", {}).items()},
                status=NodeStatus(data.get("status", NodeStatus.PENDING.value)),
                error=str(data.get("error", "")),
                created_at=float(data.get("created_at", time.time())),
                ended_at=data.get("ended_at"),
            )
            self.runs[run.id] = run
            return run
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            return None
