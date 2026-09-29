"""
team_delete.py — 团队删除工具
================================================

【这个模块做什么】
删除 Agent 团队，清理所有相关资源。

【清理内容】
- 终止所有终端 pane 进程
- 删除 Git worktree
- 清理邮箱和团队目录
- 恢复父 Agent 的完整工具集（如果启用了协调者模式）

【安全约束】
- 要求所有成员处于空闲状态
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel

from mewcode.tools.base import Tool, ToolResult

if TYPE_CHECKING:
    from mewcode.agent import Agent
    from mewcode.teams.manager import TeamManager


class TeamDeleteParams(BaseModel):
    """TeamDelete 参数模型"""
    team_name: str  # 团队名称


class TeamDeleteTool(Tool):
    """
    团队删除工具 — 删除 Agent 团队并清理资源。
    
    特性:
    - 终止所有终端 pane 进程
    - 删除 Git worktree
    - 清理邮箱和团队目录
    - 恢复父 Agent 的完整工具集
    """
    name = "TeamDelete"
    description = (
        "Delete an Agent Team. Terminates all pane processes, removes worktrees, "
        "cleans up mailbox and team directory. Requires all members to be idle."
    )
    params_model = TeamDeleteParams
    category = "command"
    is_concurrency_safe = False


    def __init__(self, team_manager: TeamManager, parent_agent: Agent | None = None) -> None:
        self._team_manager = team_manager
        self._parent_agent = parent_agent


    async def execute(self, params: BaseModel) -> ToolResult:
        p: TeamDeleteParams = params  # type: ignore[assignment]

        from mewcode.teams.manager import TeamError

        # 删除团队（包括进程、worktree、邮箱等）
        try:
            self._team_manager.delete_team(p.team_name)
        except TeamError as e:
            return ToolResult(output=str(e), is_error=True)
        except Exception as e:
            return ToolResult(output=f"Failed to delete team: {e}", is_error=True)

        # 如果启用了协调者模式，恢复父 Agent 的完整工具集
        coordinator_note = ""
        if self._parent_agent and self._parent_agent.coordinator_mode:
            full_registry = getattr(self._parent_agent, '_full_registry', None)
            if full_registry is not None:
                self._parent_agent.registry = full_registry
                self._parent_agent._full_registry = None
            self._parent_agent.coordinator_mode = False
            coordinator_note = "\nCoordinator Mode deactivated: full tools restored."

        return ToolResult(output=f"Team '{p.team_name}' deleted successfully.{coordinator_note}")
