"""
enter_worktree.py — 进入 Worktree 工具
================================================

【这个模块做什么】
创建并进入隔离的 Git worktree 工作区。

【为什么需要这个】
- 为 Agent 提供独立的工作区，不污染主目录
- 支持并行开发，互不干扰
- 可以随时退出并选择保留或删除

【工作流程】
1. 检查是否已在 worktree 中
2. 生成或验证名称
3. 创建 worktree (git worktree add)
4. 进入 worktree 会话
"""
from __future__ import annotations

import secrets
from typing import TYPE_CHECKING, Optional

from pydantic import BaseModel, Field

from mewcode.tools.base import Tool, ToolResult
from mewcode.worktree.slug import validate_slug

if TYPE_CHECKING:
    from mewcode.worktree.manager import WorktreeManager


class EnterWorktreeParams(BaseModel):
    """EnterWorktree 参数模型"""
    name: Optional[str] = Field(
        default=None,
        description=(
            'Optional name for the worktree. Each "/"-separated segment may '
            "contain only letters, digits, dots, underscores, and dashes; "
            "max 64 chars total. A random name is generated if not provided."
        ),
    )


class EnterWorktreeTool(Tool):
    """
    进入 Worktree 工具 — 创建并进入隔离的 Git worktree。
    
    特性:
    - 自动生成随机名称（如未提供）
    - 名称验证（防止路径穿越）
    - 延迟加载（should_defer=True）
    """
    name = "EnterWorktree"
    description = (
        "Creates an isolated worktree (via git) and switches the session into it"
    )
    params_model = EnterWorktreeParams
    category = "command"
    should_defer = True


    def __init__(self, worktree_manager: WorktreeManager) -> None:
        self._manager = worktree_manager


    async def execute(self, params: EnterWorktreeParams) -> ToolResult:
        # 1. 检查是否已在 worktree 中
        if self._manager.get_current_session() is not None:
            return ToolResult(
                output="Already in a worktree session", is_error=True
            )

        # 2. 生成或验证名称
        slug = params.name or f"wt-{secrets.token_hex(4)}"

        err = validate_slug(slug)
        if err:
            return ToolResult(output=f"Invalid worktree name: {err}", is_error=True)

        # 3. 创建并进入 worktree
        try:
            wt = await self._manager.create(slug)
            session = await self._manager.enter(slug)
        except Exception as e:
            return ToolResult(
                output=f"Error creating worktree: {e}", is_error=True
            )

        branch_info = f" on branch {wt.branch}" if wt.branch else ""
        return ToolResult(
            output=(
                f"Created worktree at {session.worktree_path}{branch_info}. "
                "The session is now working in the worktree. "
                "Use ExitWorktree to leave mid-session, or exit the session to be prompted."
            )
        )
