"""
runtime — 持久化 Agent 运行时与多 Agent 编排
=============================================================

【这个模块做什么】
提供 Agent 运行的完整基础设施：
- 数据模型: AgentRun、RunEvent、RunStatus
- 持久化存储: RunStore（JSON 快照 + JSONL 事件日志）
- 运行时服务: AgentRuntime（提交、执行、取消、恢复）
- DAG 编排: DAGScheduler（依赖感知的多 Agent 调度）
- HTTP 服务: FastAPI 适配器（可选依赖）

【模块结构】
runtime/
├── models.py     数据模型（AgentRun、RunEvent、RunStatus）
├── store.py      持久化存储（JSON + JSONL）
├── service.py    运行时服务（AgentRuntime）
├── dag.py        DAG 编排（DAGScheduler）
├── bootstrap.py  装配工厂（从配置构建运行时）
├── http.py       FastAPI 适配器
└── server.py     HTTP 服务入口

【核心设计】
1. 持久化优先: 每次状态变化都写入磁盘，进程崩溃后可恢复
2. 事件驱动: 所有状态变化产生事件，支持 SSE 实时推送
3. 依赖注入: 通过工厂函数解耦运行时与具体实现
4. DAG 编排: 支持多 Agent 依赖感知的并行调度

【使用场景】
- CLI: 直接调用 AgentRuntime.submit()
- HTTP: 通过 FastAPI 适配器暴露 RESTful API
- 多 Agent: 使用 DAGScheduler 编排多个 Agent 协作
"""

from mewcode.runtime.dag import DAGNode, DAGRun, DAGScheduler, NodeStatus
from mewcode.runtime.models import AgentRun, RunEvent, RunStatus
from mewcode.runtime.service import AgentRuntime

__all__ = [
    "AgentRun",
    "AgentRuntime",
    "DAGNode",
    "DAGRun",
    "DAGScheduler",
    "NodeStatus",
    "RunEvent",
    "RunStatus",
]
