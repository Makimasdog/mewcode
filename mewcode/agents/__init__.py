"""
agents — 子 Agent 系统
========================

本模块实现了 MewCode 的子 Agent 机制，让主 Agent 可以派生子 Agent 执行独立任务。

【模块组成】

┌─────────────────────────────────────────────────────────┐
│  parser.py    │ 解析 Agent 定义文件（.md）              │
│  loader.py    │ 从多个来源加载 Agent 定义（支持热重载）  │
│  fork.py      │ 对话 Fork 机制（复制对话给子 Agent）   │
│  trace.py     │ Agent 追踪树（记录父子关系和资源消耗）  │
│  task_manager │ 后台任务管理（启动/重试/超时/恢复）    │
│  tool_filter  │ 工具过滤（不同角色用不同工具）         │
│  notification │ 任务完成通知（子 Agent → 主 Agent）    │
└─────────────────────────────────────────────────────────┘

【工作流程】
1. AgentLoader 加载 Agent 定义（从内置/项目/用户目录）
2. 主 Agent 决定委托任务 → 通过 fork.py 创建对话副本
3. tool_filter 为子 Agent 筛选可用工具
4. 子 Agent 在后台运行（task_manager 管理）
5. trace.py 追踪 Agent 执行状态
6. 完成后通过 notification 通知主 Agent
"""


# --- 解析器：解析 Agent 定义文件 ---
from mewcode.agents.parser import AgentDef, AgentParseError, parse_agent_file
# --- 加载器：从多个来源加载 Agent 定义 ---
from mewcode.agents.loader import AgentLoader
# --- 工具过滤器：为子 Agent 筛选可用工具 ---
from mewcode.agents.tool_filter import resolve_agent_tools
# --- Fork 机制：创建对话副本给子 Agent ---
from mewcode.agents.fork import build_forked_messages, ForkError
# --- 追踪树：记录 Agent 父子关系和执行状态 ---
from mewcode.agents.trace import TraceManager, TraceNode
# --- 任务管理器：后台任务的启动/取消/恢复 ---
from mewcode.agents.task_manager import TaskManager, BackgroundTask
# --- 通知：子 Agent 完成任务后通知主 Agent ---
from mewcode.agents.notification import format_task_notification, inject_task_notifications


__all__ = [
    "AgentDef",
    "AgentParseError",
    "parse_agent_file",
    "AgentLoader",
    "resolve_agent_tools",
    "build_forked_messages",
    "ForkError",
    "TraceManager",
    "TraceNode",
    "TaskManager",
    "BackgroundTask",
    "format_task_notification",
    "inject_task_notifications",
]

