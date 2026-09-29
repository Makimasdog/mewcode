"""
trace.py — Agent 追踪树
=========================

【这个模块做什么】
当主 Agent 派生出多个子 Agent 时，需要追踪它们的父子关系和执行状态。
TraceManager 维护一棵「Agent 追踪树」，记录：
- 每个 Agent 的唯一 ID 和父 Agent ID
- 每个 Agent 的 token 消耗、工具调用次数
- 每个 Agent 的运行状态（running/completed/failed）

【为什么要追踪？】
- 用户可以通过 /trace 命令查看 Agent 调用树
- 便于调试和性能分析（哪个子 Agent 消耗了多少 token）
- 父 Agent 可以了解子 Agent 的执行状态

【概念模型】
主 Agent (root)
├── 子 Agent A
│   └── 子 Agent A-1
└── 子 Agent B

每个节点是一个 TraceNode，通过 parent_id 和 trace_id 关联。
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field


@dataclass
class TraceNode:
    """
    Agent 追踪树中的一个节点。
    每个 Agent 启动时创建一个节点，记录其运行状态和资源消耗。
    """
    agent_id: str              # 唯一标识符
    parent_id: str | None      # 父 Agent ID（None 表示根节点）
    trace_id: str              # 追踪 ID（同一棵树的所有节点共享同一个 trace_id）
    agent_type: str            # Agent 类型名称
    input_tokens: int = 0      # 累计输入 token 消耗
    output_tokens: int = 0     # 累计输出 token 消耗
    tool_call_count: int = 0   # 工具调用次数
    start_time: float = field(default_factory=time.monotonic)  # 启动时间
    end_time: float | None = None   # 结束时间
    status: str = "running"    # 状态：running/completed/failed/cancelled


class TraceManager:
    """
    Agent 追踪树管理器。
    
    管理所有 Agent 节点的生命周期：创建、更新、完成、查询。
    """
    def __init__(self) -> None:
        self._nodes: dict[str, TraceNode] = {}  # {agent_id: 节点}


    def create(
        self,
        agent_type: str,
        parent_id: str | None = None,
        trace_id: str | None = None,
    ) -> TraceNode:
        """
        创建一个新的追踪节点。
        
        参数:
            agent_type: Agent 类型名称
            parent_id: 父 Agent ID（None 表示根节点）
            trace_id: 追踪 ID（不提供则自动生成）
        """
        agent_id = uuid.uuid4().hex[:12]
        if trace_id is None:
            trace_id = uuid.uuid4().hex[:12]

        node = TraceNode(
            agent_id=agent_id,
            parent_id=parent_id,
            trace_id=trace_id,
            agent_type=agent_type,
        )
        self._nodes[agent_id] = node
        return node

    def update(self, agent_id: str, **kwargs: int | str) -> None:
        """更新节点的属性（如 token 消耗、工具调用次数等）"""
        node = self._nodes.get(agent_id)
        if node is None:
            return
        for key, value in kwargs.items():
            if hasattr(node, key):
                setattr(node, key, value)


    def complete(self, agent_id: str, status: str = "completed") -> None:
        """标记节点为完成状态，记录结束时间"""
        node = self._nodes.get(agent_id)
        if node is None:
            return
        node.end_time = time.monotonic()
        node.status = status


    def get(self, agent_id: str) -> TraceNode | None:
        """获取指定 Agent 的追踪节点"""
        return self._nodes.get(agent_id)

    def get_tree(self, trace_id: str) -> list[TraceNode]:
        """获取同一追踪 ID 下的所有节点（即一棵树）"""
        return [n for n in self._nodes.values() if n.trace_id == trace_id]


    def remove(self, agent_id: str) -> None:
        """移除节点"""
        self._nodes.pop(agent_id, None)

    def complete_all_running(self, parent_id: str) -> None:
        """将指定父节点下所有正在运行的子节点标记为完成"""
        for node in self._nodes.values():
            if node.parent_id == parent_id and node.status == "running":
                node.status = "completed"
                node.end_time = time.monotonic()

    def get_total_tokens(self, trace_id: str) -> tuple[int, int]:
        """计算一棵追踪树的总 token 消耗（输入, 输出）"""
        total_in = 0
        total_out = 0
        for node in self._nodes.values():
            if node.trace_id == trace_id:
                total_in += node.input_tokens
                total_out += node.output_tokens
        return total_in, total_out
