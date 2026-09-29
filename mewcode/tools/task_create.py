"""
task_create.py — 任务创建工具
================================================

【这个模块做什么】
在团队任务板中创建新任务，支持依赖关系追踪。

【任务依赖】
- blocks: 本任务阻塞哪些任务
- blocked_by: 本任务被哪些任务阻塞

【使用场景】
团队协作时，将工作拆解为任务并分配给成员。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel

from mewcode.tools.base import Tool, ToolResult

if TYPE_CHECKING:
    from mewcode.teams.manager import TeamManager


class TaskCreateParams(BaseModel):
    """TaskCreate 参数模型"""
    title: str           # 任务标题
    description: str = ""  # 任务描述
    assignee: str = ""    # 负责人
    blocks: list[str] | None = None      # 本任务阻塞的任务 ID 列表
    blocked_by: list[str] | None = None  # 阻塞本任务的任务 ID 列表


class TaskCreateTool(Tool):
    """
    任务创建工具 — 在团队任务板中创建新任务。
    
    特性:
    - 支持任务依赖关系（blocks/blocked_by）
    - 支持分配负责人
    """
    name = "TaskCreate"
    description = (
        "Create a shared task in the team's task board. "
        "Supports dependency tracking with blocks/blocked_by fields."
    )
    params_model = TaskCreateParams
    category = "command"
    is_concurrency_safe = True


    def __init__(self, team_manager: TeamManager, team_name: str, agent_name: str = "") -> None:
        self._team_manager = team_manager
        self._team_name = team_name
        self._agent_name = agent_name


    async def execute(self, params: BaseModel) -> ToolResult:
        p: TaskCreateParams = params  # type: ignore[assignment]

        store = self._team_manager.get_task_store(self._team_name)
        if store is None:
            return ToolResult(output=f"Task store not found for team '{self._team_name}'", is_error=True)

        # 创建任务
        task = store.create(
            title=p.title,
            description=p.description,
            assignee=p.assignee,
            blocks=p.blocks,
            blocked_by=p.blocked_by,
            created_by=self._agent_name,
        )

        return ToolResult(
            output=(
                f"Task created:\n"
                f"  ID: {task.id}\n"
                f"  Title: {task.title}\n"
                f"  Status: {task.status}\n"
                f"  Assignee: {task.assignee or '(unassigned)'}"
            )
        )
