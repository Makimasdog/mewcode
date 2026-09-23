from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from mewcode.runtime.dag import DAGNode, DAGScheduler, NodeStatus
from mewcode.tools.agent_tool import AgentToolParams
from mewcode.tools.base import Tool, ToolResult

if TYPE_CHECKING:
    from mewcode.tools.agent_tool import AgentTool


class DAGNodeInput(BaseModel):
    id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9_-]+$")
    prompt: str = Field(min_length=1)
    description: str = ""
    subagent_type: str | None = None
    depends_on: list[str] = Field(default_factory=list)
    max_attempts: int = Field(default=1, ge=1, le=5)


class DAGCreateParams(BaseModel):
    name: str = "agent-dag"
    nodes: list[DAGNodeInput] = Field(min_length=1, max_length=32)
    max_parallel: int = Field(default=4, ge=1, le=16)
    fail_fast: bool = True


class DAGStatusParams(BaseModel):
    run_id: str = Field(min_length=1)


class DAGCreateTool(Tool):
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
        return self._scheduler

    async def execute(self, params: BaseModel) -> ToolResult:
        p: DAGCreateParams = params  # type: ignore[assignment]
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

        async def execute_node(node: DAGNode, dependency_outputs: dict[str, str]) -> str:
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

        completed = await self._scheduler.run(
            run,
            execute_node,
            max_parallel=p.max_parallel,
            fail_fast=p.fail_fast,
        )
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
    name = "DAGStatus"
    description = "Inspect a persisted Agent DAG run and all node statuses."
    params_model = DAGStatusParams
    category = "read"
    is_concurrency_safe = True

    def __init__(self, scheduler: DAGScheduler) -> None:
        self._scheduler = scheduler

    async def execute(self, params: BaseModel) -> ToolResult:
        p: DAGStatusParams = params  # type: ignore[assignment]
        run = self._scheduler.runs.get(p.run_id) or self._scheduler.load(p.run_id)
        if run is None:
            return ToolResult(output=f"DAG run not found: {p.run_id}", is_error=True)
        lines = [f"DAG {run.id}: {run.status.value}"]
        lines.extend(f"- {n.id}: {n.status.value}" for n in run.nodes.values())
        return ToolResult(output="\n".join(lines))
