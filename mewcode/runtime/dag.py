"""
dag.py — DAG 调度器（依赖感知的多 Agent 编排）
=============================================================

【这个模块做什么】
实现基于有向无环图 (DAG) 的多 Agent 编排：
- DAGNode: 定义任务节点及其依赖关系
- DAGRun: 表示一次 DAG 执行
- DAGScheduler: 调度器，自动处理依赖和并行执行

【什么是 DAG】
DAG = Directed Acyclic Graph（有向无环图）
- 节点 = 任务
- 边 = 依赖关系（A → B 表示 A 必须在 B 之前执行）
- 无环 = 不能有循环依赖

【执行流程】
1. 验证: 检查节点 ID 唯一性、依赖存在性、无循环
2. 调度: 找出所有依赖已完成的节点
3. 并行: 同时执行多个就绪节点（受 max_parallel 限制）
4. 重试: 单个节点失败时支持自动重试
5. 传播: 节点失败时，依赖它的节点被标记为 BLOCKED

【与 tools/dag_tools.py 的关系】
- dag_tools.py: Agent 工具层，提供 DAG 创建和状态查询工具
- dag.py: 执行引擎层，实际调度 DAG 执行
"""
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
    """
    DAG 节点状态枚举。
    
    状态流转：
    PENDING → RUNNING → COMPLETED/FAILED/CANCELLED
    PENDING → BLOCKED (依赖节点失败)
    """
    PENDING = "pending"        # 待执行
    RUNNING = "running"        # 执行中
    COMPLETED = "completed"    # 已完成
    FAILED = "failed"          # 失败
    BLOCKED = "blocked"        # 被阻塞（依赖失败）
    CANCELLED = "cancelled"    # 已取消


@dataclass
class DAGNode:
    """
    DAG 节点 — 表示一个待执行的任务。
    
    核心字段：
    - id: 节点唯一标识
    - task: 任务描述
    - dependencies: 依赖节点 ID 列表（这些节点必须先完成）
    - agent_type: 指定执行该任务的 Agent 类型（可选）
    - max_attempts: 失败重试次数
    """
    id: str
    task: str
    dependencies: list[str] = field(default_factory=list)
    agent_type: str | None = None
    description: str = ""
    max_attempts: int = 1
    status: NodeStatus = NodeStatus.PENDING
    result: str = ""
    error: str = ""
    artifacts: dict[str, Any] = field(default_factory=dict)  # 执行产物
    started_at: float | None = None
    ended_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典"""
        data = self.__dict__.copy()
        data["status"] = self.status.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DAGNode:
        """从字典反序列化"""
        data = dict(data)
        data["status"] = NodeStatus(data.get("status", NodeStatus.PENDING.value))
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class DAGRun:
    """
    DAG 执行记录 — 表示一次完整的 DAG 执行。
    
    包含所有节点及其状态，用于持久化和状态查询。
    """
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    nodes: dict[str, DAGNode] = field(default_factory=dict)  # 节点 ID → 节点
    status: NodeStatus = NodeStatus.PENDING
    error: str = ""
    created_at: float = field(default_factory=time.time)
    ended_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典"""
        return {
            "id": self.id,
            "nodes": {key: node.to_dict() for key, node in self.nodes.items()},
            "status": self.status.value,
            "error": self.error,
            "created_at": self.created_at,
            "ended_at": self.ended_at,
        }


# 节点执行器类型：接收节点和依赖输出，返回执行结果
NodeExecutor = Callable[[DAGNode, dict[str, str]], Awaitable[str]]


class DAGScheduler:
    """
    DAG 调度器 — 依赖感知的多 Agent 编排引擎。
    
    核心能力：
    - 自动检测循环依赖
    - 并行执行无依赖的节点
    - 失败传播（节点失败时阻塞下游）
    - 单节点重试
    - 执行器注入（可接入 AgentTool、远程 Runtime 或测试替身）
    
    调度算法：
    1. 找出所有 PENDING 节点
    2. 检查依赖是否全部 COMPLETED
    3. 将就绪节点加入执行队列（受 max_parallel 限制）
    4. 并行执行，等待完成
    5. 重复直到所有节点完成或被阻塞
    """

    def __init__(
        self,
        store_dir: str | Path = ".mewcode/dag-runs",
        max_parallel: int = 4,
    ) -> None:
        self.store_dir = Path(store_dir)
        self.store_dir.mkdir(parents=True, exist_ok=True)
        self.max_parallel = max(1, max_parallel)  # 最大并行度
        self.runs: dict[str, DAGRun] = {}  # 运行 ID → DAGRun

    @staticmethod
    def validate(nodes: list[DAGNode]) -> None:
        """
        验证 DAG 合法性。
        
        检查项：
        1. 节点 ID 唯一性
        2. 依赖节点存在性
        3. 无循环依赖（拓扑排序）
        """
        ids = [node.id for node in nodes]
        if len(ids) != len(set(ids)):
            raise ValueError("DAG node ids must be unique")
        known = set(ids)
        for node in nodes:
            missing = set(node.dependencies) - known
            if missing:
                raise ValueError(f"Node {node.id} depends on unknown nodes: {sorted(missing)}")
        # 拓扑排序检测循环
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
        """
        创建 DAG 执行。
        
        流程：验证 → 创建 DAGRun → 持久化 → 返回
        """
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
        """
        执行 DAG。
        
        executor: 节点执行函数（注入依赖解耦）
        fail_fast: 是否快速失败（一个节点失败则取消所有）
        
        执行循环：
        1. 找出 PENDING 节点
        2. 检查依赖失败情况，标记 BLOCKED
        3. 找出就绪节点（依赖全部 COMPLETED）
        4. 并行执行（受 max_parallel 限制）
        5. 处理结果，更新状态
        6. 重复直到所有节点完成
        """
        self.validate(list(run.nodes.values()))
        parallel = max(1, max_parallel or self.max_parallel)
        run.status = NodeStatus.RUNNING
        self._save(run)
        outputs: dict[str, str] = {}  # 节点 ID → 执行结果（供下游使用）

        while True:
            pending = [n for n in run.nodes.values() if n.status == NodeStatus.PENDING]
            if not pending:
                break

            # 检查依赖失败情况，标记被阻塞的节点
            for node in pending:
                if any(run.nodes[d].status in {NodeStatus.FAILED, NodeStatus.BLOCKED, NodeStatus.CANCELLED} for d in node.dependencies):
                    node.status = NodeStatus.BLOCKED
                    node.error = "dependency failed"

            # 找出就绪的节点（依赖全部完成）
            ready = [
                node for node in pending
                if node.status == NodeStatus.PENDING
                and all(run.nodes[d].status == NodeStatus.COMPLETED for d in node.dependencies)
            ][:parallel]

            if not ready:
                if any(n.status == NodeStatus.BLOCKED for n in run.nodes.values()):
                    continue  # 还有被阻塞的节点，继续循环
                run.status = NodeStatus.FAILED
                run.error = "DAG stalled: no runnable nodes"
                break

            # 并行执行就绪节点
            tasks = [asyncio.create_task(self._run_node(node, outputs, executor)) for node in ready]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for node, result in zip(ready, results):
                if isinstance(result, BaseException):
                    node.status = NodeStatus.FAILED
                    node.error = str(result)
                    if fail_fast:
                        # 快速失败：阻塞所有未完成的节点
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

        # 确定最终状态
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
        """
        执行单个节点。
        
        特性：
        - 传入依赖节点的输出作为上下文
        - 支持重试（指数退避）
        - 支持取消
        """
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
                    await asyncio.sleep(min(2**attempt, 4))  # 指数退避
        node.status = NodeStatus.FAILED
        node.error = last_error or "node failed"
        node.ended_at = time.time()
        raise RuntimeError(node.error)

    def _save(self, run: DAGRun) -> None:
        """持久化 DAG 执行状态"""
        path = self.store_dir / f"{run.id}.json"
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(run.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)  # 原子替换

    def load(self, run_id: str) -> DAGRun | None:
        """加载 DAG 执行记录"""
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
