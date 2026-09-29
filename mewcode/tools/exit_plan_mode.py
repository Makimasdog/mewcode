"""
exit_plan_mode.py — 退出 Plan 模式工具
================================================

【这个模块做什么】
退出 Plan 模式，将计划呈现给用户审批。

【Plan 模式工作流】
1. Agent 进入 Plan 模式（只读，不能执行工具）
2. Agent 分析代码并编写计划
3. 调用 ExitPlanMode 提交计划
4. 用户审批计划
5. 审批通过后，Agent 退出 Plan 模式并执行计划

【安全约束】
- 必须在 Plan 模式下才能调用
- 必须先写入计划文件
"""
from __future__ import annotations

from typing import Callable

from pydantic import BaseModel

from mewcode.tools.base import Tool, ToolResult


class ExitPlanModeParams(BaseModel):
    """ExitPlanMode 参数模型（无参数）"""
    pass


class ExitPlanModeTool(Tool):
    """
    退出 Plan 模式工具 — 提交计划供用户审批。
    
    特性:
    - 纯状态切换工具（无副作用）
    - 检查是否在 Plan 模式下
    - 检查计划文件是否存在
    """
    name = "ExitPlanMode"
    description = (
        "Exit plan mode and present the plan for user approval. "
        "Call this when your plan is complete and written to the plan file."
    )
    params_model = ExitPlanModeParams
    category = "read"

    def __init__(
        self,
        is_plan_mode: Callable[[], bool] | None = None,
        plan_exists: Callable[[], bool] | None = None,
    ) -> None:
        self._is_plan_mode = is_plan_mode  # 回调：是否在 Plan 模式
        self._plan_exists = plan_exists    # 回调：计划文件是否存在

    async def execute(self, params: ExitPlanModeParams) -> ToolResult:
        # 1. 检查是否在 Plan 模式下
        if self._is_plan_mode is not None and not self._is_plan_mode():
            return ToolResult(
                output="You are not in plan mode. This tool is only for exiting plan mode after writing a plan.",
                is_error=True,
            )
        # 2. 检查计划文件是否存在
        if self._plan_exists is not None and not self._plan_exists():
            return ToolResult(
                output="No plan file found. Please write your plan to the plan file before calling ExitPlanMode.",
                is_error=True,
            )
        # 3. 返回成功提示
        return ToolResult(
            output=(
                "Plan mode will be exited after this turn. "
                "The user will be shown the plan approval dialog. "
                "Do not call any more tools — end your turn now."
            )
        )
