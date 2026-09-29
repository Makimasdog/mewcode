"""
dag_tools.py — DAG 编排工具
================================================

【这个模块做什么】
以 DAG（有向无环图）方式编排多个子 Agent 的执行。

【为什么需要这个】
某些任务有依赖关系，例如：
探索 -> 实现 -> 测试 -> 审查
DAG 编排可以自动处理依赖和并行执行。

【核心组件】
- DAGCreateTool: 创建并执行 DAG
- DAGStatusTool: 查询 DAG 执行状态

【工作流程】
1. 定义节点（任务）和依赖关系
2. DAGScheduler 自动解析依赖图
3. 无依赖的节点并行执行
4. 依赖完成后，下游节点获取上游输出作为上下文
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from mewcode.runtime.dag import DAGNode, DAGScheduler, NodeStatus
from mewcode.tools.agent_tool import AgentToolParams
from mewcode.tools.base import Tool, ToolResult

if TYPE_CHECKING:
    from mewcode.tools.agent_tool import AgentTool


class DAGNodeInput(BaseModel):
    """DAG 节点输入定义"""
    id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9_-]+$")  # 节点 ID
    prompt: str = Field(min_length=1)    # 任务提示
    description: str = ""                # 节点描述
    subagent_type: str | None = None     # Agent 类型
    depends_on: list[str] = Field(default_factory=list)  # 依赖的节点 ID 列表
    max_attempts: int = Field(default=1, ge=1, le=5)     # 最大重试次数


class DAGCreateParams(BaseModel):
    """DAGCreate 参数模型"""
    name: str = "agent-dag"              # DAG 名称
    nodes: list[DAGNodeInput] = Field(min_length=1, max_length=32)  # 节点列表
    max_parallel: int = Field(default=4, ge=1, le=16)  # 最大并行数
    fail_fast: bool = True               # 是否快速失败


class DAGStatusParams(BaseModel):
    """DAGStatus 参数模型"""
    run_id: str = Field(min_length=1)   # DAG 运行 ID


class DAGCreateTool(Tool):
    """
    DAG 创建工具 — 以 DAG 方式编排多个子 Agent。
    
    特性:
    - 自动解析依赖关系
    - 无依赖节点并行执行
    - 下游节点获取上游输出作为上下文
    - 支持重试和快速失败
    """
    name = "DAGCreate"
    description = (
        "Run multiple sub-agents as a dependency-aware DAG. Nodes whose dependencies "
        "are complete run in parallel; dependency outputs are included in downstream prompts. "
        "Use this for explore -> implement -> test -> review workflows."
    )
    params_model = DAGCreateParams
    category = "command"
    is_concurrency_safe = False

    def __init__(self, agent_tool: AgentTool, work_dir: str = ".") -> None:
        self._agent_tool = agent_tool
        self._scheduler = DAGScheduler(store_dir=f"{work_dir}/.mewcode/dag-runs")

    @property
    def scheduler(self) -> DAGScheduler:
        """获取 DAG 调度器"""
        return self._scheduler

    async def execute(self, params: BaseModel) -> ToolResult:
        p: DAGCreateParams = params  # type: ignore[assignment]
        # 1. 构建 DAG 节点
        nodes = [
            DAGNode(
                id=node.id,
                task=node.prompt,
                dependencies=node.depends_on,
                agent_type=node.subagent_type,
                description=node.description,
                max_attempts=node.max_attempts,
            )
            for node in p.nodes
        ]
        try:
            run = self._scheduler.create(nodes)
        except ValueError as exc:
            return ToolResult(output=f"Invalid DAG: {exc}", is_error=True)

        # 2. 定义节点执行函数
        async def execute_node(node: DAGNode, dependency_outputs: dict[str, str]) -> str:
            # 将依赖的输出作为上下文注入
            context = ""
            if dependency_outputs:
                context = (
                    "\n\nThe following dependency nodes have completed. Use their outputs as "
                    "context and do not repeat their work:\n"
                    + "\n\n".join(
                        f"[{node_id}]\n{output}" for node_id, output in dependency_outputs.items()
                    )
                )
            prompt = node.task + context
            result = await self._agent_tool.execute(
                AgentToolParams(
                    prompt=prompt,
                    description=node.description or f"DAG node {node.id}",
                    subagent_type=node.agent_type,
                    run_in_background=False,
                )
            )
            if result.is_error:
                raise RuntimeError(result.output)
            return result.output

        # 3. 执行 DAG
        completed = await self._scheduler.run(
            run,
            execute_node,
            max_parallel=p.max_parallel,
            fail_fast=p.fail_fast,
        )
        # 4. 构建结果输出
        lines = [
            f"DAG '{p.name}' completed with status: {completed.status.value}",
            f"Run ID: {completed.id}",
        ]
        for node in completed.nodes.values():
            marker = "✓" if node.status == NodeStatus.COMPLETED else "✗"
            lines.append(f"{marker} {node.id}: {node.status.value}")
            if node.result:
                lines.append(node.result)
            if node.error:
                lines.append(f"error: {node.error}")
        return ToolResult(output="\n".join(lines), is_error=completed.status != NodeStatus.COMPLETED)


class DAGStatusTool(Tool):
    """DAG 状态查询工具 — 查看 DAG 运行状态"""
    name = "DAGStatus"
    description = "Inspect a persisted Agent DAG run and all node statuses."
    params_model = DAGStatusParams
    category = "read"
    is_concurrency_safe = True

    def __init__(self, scheduler: DAGScheduler) -> None:
        self._scheduler = scheduler

    async def execute(self, params: BaseModel) -> ToolResult:
        p: DAGStatusParams = params  # type: ignore[assignment]
        # 从内存或持久化存储中加载 DAG 运行
        run = self._scheduler.runs.get(p.run_id) or self._scheduler.load(p.run_id)
        if run is None:
            return ToolResult(output=f"DAG run not found: {p.run_id}", is_error=True)
        lines = [f"DAG {run.id}: {run.status.value}"]
        lines.extend(f"- {n.id}: {n.status.value}" for n in run.nodes.values())
        return ToolResult(output="\n".join(lines))
