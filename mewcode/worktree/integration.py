"""
integration.py — Agent 集成辅助函数
=====================================

【这个模块做什么】
提供面向上层 Agent 的辅助函数：
- 生成随机 worktree 名称
- 构建 worktree 上下文提示（注入到子 Agent 的系统提示中）

【为什么需要 worktree 提示】
当子 Agent 在 worktree 中工作时，它需要知道：
- 自己当前的工作目录是 worktree，不是主仓库
- 父 Agent 对话中提到的文件路径指向主仓库，需要转换
- 编辑文件前必须重新读取（worktree 中的文件可能与主仓库不同）
"""

from __future__ import annotations

import secrets
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mewcode.worktree.manager import WorktreeManager


# 注入到子 Agent 的 worktree 上下文提示模板
WORKTREE_NOTICE_TEMPLATE = """\
[WORKTREE CONTEXT]
You have inherited the parent agent's conversation context.
You are currently working in an isolated Git Worktree: {wt_path}
The parent agent's working directory is: {parent_cwd}

IMPORTANT:
- File paths mentioned in the parent conversation refer to the PARENT directory.
- You must translate them to your local worktree path before reading or editing.
- Always re-read files before editing — your copy may differ from the parent's version.
[/WORKTREE CONTEXT]
"""


def generate_worktree_name() -> str:
    """
    生成随机的 worktree 名称。
    
    格式：agent-{8位十六进制随机数}
    例如：agent-a1b2c3d4
    """
    return f"agent-{secrets.token_hex(4)}"


def build_worktree_notice(parent_cwd: str, wt_path: str) -> str:
    """
    构建 worktree 上下文提示。
    
    这个提示会被注入到子 Agent 的系统提示中，
    告诉它正在 worktree 中工作，需要注意路径转换。
    
    参数:
        parent_cwd: 父 Agent 的工作目录
        wt_path: 当前 worktree 的路径
    """
    return WORKTREE_NOTICE_TEMPLATE.format(
        parent_cwd=parent_cwd,
        wt_path=wt_path,
    )

