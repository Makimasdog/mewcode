"""
tool_filter.py — 子 Agent 工具过滤器
=======================================

【这个模块做什么】
不同的 Agent 角色应该能用不同的工具。
例如：
- 子 Agent 不应该能调用 AskUser（只有主 Agent 才能问用户）
- 子 Agent 不应该能再创建子 Agent（防止无限嵌套）
- 后台 Agent 只能用白名单内的工具
- 协调者（Coordinator）只需要管理团队和派发任务的工具

本模块实现了多层过滤策略，确保每个 Agent 只能用该用的工具。

【过滤层级】
第 0 层：MCP 工具始终放行
第 1 层：全局禁用工具（所有子 Agent 都不能用）
第 2 层：自定义 Agent 额外限制
第 3 层：后台任务白名单
第 4 层：Agent 定义中的允许/禁用列表
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mewcode.tools import ToolRegistry

if TYPE_CHECKING:
    from mewcode.agents.parser import AgentDef
    from mewcode.teams.manager import TeamManager

# ===== 工具白名单/黑名单定义 =====

# 所有子 Agent 都不能用的工具（防止嵌套、防止直接问用户）
ALL_AGENT_DISALLOWED_TOOLS: frozenset[str] = frozenset({
    "TaskOutput",       # 任务输出（内部使用）
    "ExitPlanMode",     # 退出计划模式
    "EnterPlanMode",    # 进入计划模式
    "Agent",            # 创建子 Agent（防止嵌套）
    "AskUserQuestion",  # 问用户问题（只有主 Agent 才能问）
    "TaskStop",         # 停止任务
    "Workflow",         # 工作流
})

# 自定义 Agent 额外禁用的工具（与上面相同，用于非内置 Agent）
CUSTOM_AGENT_DISALLOWED_TOOLS: frozenset[str] = frozenset({
    "TaskOutput",
    "ExitPlanMode",
    "EnterPlanMode",
    "Agent",
    "AskUserQuestion",
    "TaskStop",
    "Workflow",
})

# 后台 Agent 可用的工具白名单（只读操作 + 基本文件操作）
ASYNC_AGENT_ALLOWED_TOOLS: frozenset[str] = frozenset({
    "ReadFile", "WebSearch", "TodoWrite", "Grep", "WebFetch",
    "Glob", "Bash", "EditFile", "WriteFile", "NotebookEdit",
    "Skill", "LoadSkill", "SyntheticOutput", "ToolSearch",
    "EnterWorktree", "ExitWorktree",
})

# 团队协作工具（任务管理 + 消息发送）
TEAMMATE_COORDINATION_TOOLS: frozenset[str] = frozenset({
    "TaskCreate", "TaskGet", "TaskList", "TaskUpdate", "SendMessage",
})

# 进程内队友的允许工具（基本工具 + 团队协作 + 定时任务）
IN_PROCESS_TEAMMATE_ALLOWED_TOOLS: frozenset[str] = (
    ASYNC_AGENT_ALLOWED_TOOLS | TEAMMATE_COORDINATION_TOOLS | frozenset({
        "CronCreate", "CronDelete", "CronList",
    })
)

# 协调者模式只能用这些工具（管理团队 + 派发任务）
COORDINATOR_MODE_ALLOWED_TOOLS: frozenset[str] = frozenset({
    "Agent", "SyntheticOutput", "TeamCreate", "TeamDelete",
})


def _is_mcp_tool(name: str) -> bool:
    """判断是否是 MCP 工具（以 "mcp__" 开头）"""
    return name.startswith("mcp__")


def resolve_agent_tools(
    parent_registry: ToolRegistry,
    definition: AgentDef,
    is_background: bool = False,
) -> ToolRegistry:
    """
    为子 Agent 解析可用工具。
    
    通过多层过滤，从父 Agent 的工具集中筛选出子 Agent 能用的工具。
    
    参数:
        parent_registry: 父 Agent 的工具注册表
        definition: 子 Agent 的定义（包含工具限制）
        is_background: 是否是后台任务
        
    返回:
        新的 ToolRegistry，只包含子 Agent 能用的工具
    """
    all_tools = {t.name: t for t in parent_registry.list_tools()}

    # 第 0 层：MCP 工具始终放行，先分离出来再做后续过滤
    mcp_tools = {name: tool for name, tool in all_tools.items() if _is_mcp_tool(name)}
    all_tools = {name: tool for name, tool in all_tools.items() if not _is_mcp_tool(name)}

    # 第 1 层：移除全局禁用工具
    for name in ALL_AGENT_DISALLOWED_TOOLS:
        all_tools.pop(name, None)

    # 第 2 层：自定义 Agent 额外限制
    if definition.source in ("project", "user", "plugin"):
        for name in CUSTOM_AGENT_DISALLOWED_TOOLS:
            all_tools.pop(name, None)

    # 第 3 层：后台任务只能用白名单内的工具
    if is_background:
        all_tools = {
            name: tool
            for name, tool in all_tools.items()
            if name in ASYNC_AGENT_ALLOWED_TOOLS
        }

    # 第 4 层：按 Agent 定义中的禁用/允许列表过滤
    if definition.disallowed_tools:
        for name in definition.disallowed_tools:
            all_tools.pop(name, None)

    if definition.tools:
        allowed_set = set(definition.tools)
        all_tools = {
            name: tool
            for name, tool in all_tools.items()
            if name in allowed_set
        }

    # 组装新的工具注册表（MCP 工具 + 过滤后的工具）
    filtered = ToolRegistry()
    for tool in mcp_tools.values():
        filtered.register(tool)
    for tool in all_tools.values():
        filtered.register(tool)
    return filtered


def build_teammate_tools(
    parent_registry: ToolRegistry,
    team_manager: TeamManager,
    team_name: str,
    agent_id: str,
    agent_name: str,
    backend_type: str,
    definition: AgentDef | None = None,
) -> ToolRegistry:
    """
    为团队成员 Agent 构建工具集。
    
    与 resolve_agent_tools 不同，这里会额外注入团队协作工具
    （TaskCreate、SendMessage 等），让队友之间可以互相通信和协作。
    """
    from mewcode.teams.models import BackendType
    from mewcode.tools.send_message import SendMessageTool
    from mewcode.tools.task_create import TaskCreateTool
    from mewcode.tools.task_get import TaskGetTool
    from mewcode.tools.task_list import TaskListTool
    from mewcode.tools.task_update import TaskUpdateTool

    if backend_type == BackendType.IN_PROCESS.value:
        all_tools = {t.name: t for t in parent_registry.list_tools()}
        filtered = {
            name: tool
            for name, tool in all_tools.items()
            if name in IN_PROCESS_TEAMMATE_ALLOWED_TOOLS
        }
    else:
        filtered = {t.name: t for t in parent_registry.list_tools()}
        filtered.pop("TeamCreate", None)
        filtered.pop("TeamDelete", None)

    # 应用 agent 定义中的工具限制
    if definition is not None:
        if definition.disallowed_tools:
            for name in definition.disallowed_tools:
                filtered.pop(name, None)
        if definition.tools:
            allowed_set = set(definition.tools) | TEAMMATE_COORDINATION_TOOLS
            filtered = {
                name: tool
                for name, tool in filtered.items()
                if name in allowed_set
            }

    coordination_tools = [
        TaskCreateTool(team_manager, team_name, agent_name),
        TaskGetTool(team_manager, team_name),
        TaskListTool(team_manager, team_name),
        TaskUpdateTool(team_manager, team_name),
        SendMessageTool(team_manager, team_name, agent_id, agent_name),
    ]

    registry = ToolRegistry()
    for tool in filtered.values():
        registry.register(tool)
    for tool in coordination_tools:
        registry.register(tool)

    return registry


def apply_coordinator_filter(registry: ToolRegistry) -> ToolRegistry:
    """
    应用协调者模式的工具过滤。
    协调者只需要管理团队和派发任务，不需要执行具体操作的工具。
    """
    all_tools = {t.name: t for t in registry.list_tools()}
    filtered = ToolRegistry()
    for name, tool in all_tools.items():
        if name in COORDINATOR_MODE_ALLOWED_TOOLS:
            filtered.register(tool)
    return filtered
