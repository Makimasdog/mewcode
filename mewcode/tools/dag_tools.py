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

import re
import hashlib
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from mewcode.runtime.dag import DAGNode, DAGScheduler, NodeStatus
from mewcode.paper_audit import audit_paper_artifacts
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
    artifact_dir: str | None = Field(
        default=None, description="Exact paper experiment directory for protocol/artifact checks."
    )


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
        self._work_dir = work_dir
        self._scheduler = DAGScheduler(store_dir=f"{work_dir}/.mewcode/dag-runs")

    @property
    def scheduler(self) -> DAGScheduler:
        """获取 DAG 调度器"""
        return self._scheduler

    async def execute(self, params: BaseModel) -> ToolResult:
        p: DAGCreateParams = params  # type: ignore[assignment]
        artifact_root = None
        protocol_hash = None
        if p.artifact_dir:
            artifact_root = (Path(self._work_dir) / p.artifact_dir).resolve()
            if not artifact_root.is_relative_to(Path(self._work_dir).resolve()):
                return ToolResult(output="artifact_dir must be inside work_dir", is_error=True)
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
            nonlocal protocol_hash
            self._validate_dependency_evidence(node, dependency_outputs)
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
            protocol_context = self._protocol_context(node.agent_type, artifact_root)
            if artifact_root and node.agent_type in {"PaperStudy", "Verification"}:
                path = artifact_root / "protocol.md"
                if not path.is_file():
                    raise RuntimeError("Paper protocol artifact is missing")
                current_hash = hashlib.sha256(path.read_bytes()).hexdigest()
                if protocol_hash and protocol_hash != current_hash:
                    raise RuntimeError("Protocol changed after PaperProtocol completed")
                protocol_hash = current_hash
            if protocol_context:
                context += "\n\n" + protocol_context
            prompt = node.task + context
            result = await self._agent_tool.execute(
                AgentToolParams(
                    prompt=prompt,
                    description=node.description or f"DAG node {node.id}",
                    subagent_type=node.agent_type,
                    run_in_background=False,
                    force_foreground=True,
                )
            )
            if result.is_error:
                raise RuntimeError(result.output)
            if result.output.lstrip().startswith("Sub-agent launched in background."):
                raise RuntimeError(
                    f"DAG node {node.id} returned a background task handle instead of its result"
                )
            self._validate_node_result(node, result.output)
            if artifact_root and node.agent_type == "PaperProtocol":
                path = artifact_root / "protocol.md"
                if not path.is_file():
                    raise RuntimeError("PaperProtocol did not write protocol.md")
                protocol_hash = hashlib.sha256(path.read_bytes()).hexdigest()
            if artifact_root and protocol_hash:
                if hashlib.sha256((artifact_root / "protocol.md").read_bytes()).hexdigest() != protocol_hash:
                    raise RuntimeError("Protocol changed during implementation or verification")
            if node.agent_type == "Verification":
                audit = audit_paper_artifacts(self._work_dir, artifact_root=artifact_root)
                if audit.checked and not audit.passed:
                    raise RuntimeError(audit.render())
                if audit.checked:
                    result.output = result.output.rstrip() + "\n\n" + audit.render()
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

    def _protocol_context(self, agent_type: str | None, artifact_root: Path | None = None) -> str:
        """Attach the active protocol path and hash to paper worker prompts."""
        if agent_type not in {"PaperStudy", "Verification"}:
            return ""
        protocols = [artifact_root / "protocol.md"] if artifact_root else [
            path for path in (Path(self._work_dir) / "paper_repro").glob("*/protocol.md")
            if path.is_file()
        ]
        protocols = [path for path in protocols if path.is_file()]
        if not protocols:
            return ""
        path = max(protocols, key=lambda item: item.stat().st_mtime)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        return (
            "ACTIVE PROTOCOL (read-only): " + str(path) + "\n"
            "PROTOCOL SHA-256: " + digest + "\n"
            "Do not modify this protocol or silently change its thresholds."
        )

    @staticmethod
    def _validate_dependency_evidence(
        node: DAGNode, dependency_outputs: dict[str, str]
    ) -> None:
        """Reject paper-DAG hand-offs that contain no auditable evidence.

        A language model can produce a plausible implementation or PASS report
        even when an upstream node only returned metadata.  These checks are
        intentionally narrow and apply only to the built-in paper workflow;
        ordinary DAGs keep their original free-form behavior.
        """
        combined = "\n".join(dependency_outputs.values())
        lowered = combined.lower()

        if node.agent_type in {"PaperProtocol", "PaperStudy"} and dependency_outputs:
            insufficient_markers = (
                "no protocol",
                "nothing to implement",
                "no algorithmic content",
                "does not contain the mathematical",
                "cannot be extracted",
                "no textual content",
                "unable to retrieve verbatim",
                "extraction failed",
                "insufficient evidence",
                "insufficient information",
                "insufficient_evidence",
            )
            if any(marker in lowered for marker in insufficient_markers):
                raise RuntimeError(
                    "upstream paper evidence is insufficient for reproduction; "
                    "PaperStudy must not substitute a standard algorithm"
                )

    @staticmethod
    def _validate_node_result(node: DAGNode, result: str) -> None:
        """Validate evidence emitted by paper-workflow nodes themselves."""
        lowered = result.lower()
        if node.agent_type == "PaperSearch":
            required = (
                "http status:",
                "pdf pages:",
                "section 2.1 excerpt:",
                "section 3.4 excerpt:",
            )
            if not all(token in lowered for token in required):
                raise RuntimeError(
                    "PaperSearch result lacks auditable source evidence "
                    "(HTTP status, PDF pages, and section-specific excerpts are required)"
                )

        if node.agent_type == "Verification":
            if "verdict:" not in lowered:
                raise RuntimeError(
                    "verification report is missing VERDICT; "
                    "the node must classify the observed execution"
                )
            if "exit code:" not in lowered or "command:" not in lowered:
                raise RuntimeError(
                    "verification report lacks COMMAND/EXIT CODE evidence; "
                    "a PASS verdict cannot be accepted"
                )
            verdict = re.search(r"verdict\s*:\s*(pass|fail|partial)\b", lowered)
            if verdict is None:
                raise RuntimeError("verification report has an invalid VERDICT value")
            if verdict.group(1) != "pass":
                raise RuntimeError(
                    f"verification returned VERDICT: {verdict.group(1).upper()}"
                )
            exit_codes = re.findall(r"exit code\s*:\s*(-?\d+)", lowered)
            if not exit_codes or any(int(code) != 0 for code in exit_codes):
                raise RuntimeError("verification contains missing or nonzero EXIT CODE")


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
