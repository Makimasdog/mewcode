"""
changes.py — Worktree 变更检测
=====================================

【这个模块做什么】
检测 worktree 中的文件变更和新提交，用于：
- 退出 worktree 时检查是否有未保存的工作
- 清理过期 worktree 时确认是否安全删除

【检测内容】
- uncommitted: 未提交的变更数（git status）
- new_commits: 基于原始提交后的新提交数（git rev-list）
- unpushed: 是否有未推送到远程的提交

【安全设计】
所有 git 命令都设置 GIT_TERMINAL_PROMPT=0 和 GIT_ASKPASS=""，
避免 git 弹出密码输入提示而卡住进程。
"""
from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass

log = logging.getLogger(__name__)

# 禁止 git 弹出交互式密码输入
GIT_ENV = {"GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": ""}


def _run_git(args: list[str], cwd: str) -> subprocess.CompletedProcess[str]:
    """执行 git 命令，注入环境变量以禁止交互式提示"""
    import os
    env = {**os.environ, **GIT_ENV}
    return subprocess.run(
        ["git"] + args,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )


@dataclass
class Changes:
    """Worktree 变更统计"""
    uncommitted: int = 0   # 未提交的文件变更数
    new_commits: int = 0   # 新增的提交数


def count_worktree_changes(wt_path: str, head_commit: str) -> Changes:
    """
    统计 worktree 的变更情况。
    
    参数:
        wt_path: worktree 路径
        head_commit: 创建时的 HEAD 提交 SHA
    返回:
        Changes 对象，包含未提交变更数和新提交数
    """
    changes = Changes()
    # 检查未提交的变更（git status --porcelain）
    try:
        status = _run_git(["status", "--porcelain"], cwd=wt_path)
        if status.returncode == 0:
            changes.uncommitted = len(
                [line for line in status.stdout.splitlines() if line.strip()]
            )
    except (subprocess.SubprocessError, OSError):
        changes.uncommitted = 1  # 出错时保守估计有变更

    # 检查新提交数（从原始 head_commit 到当前 HEAD）
    try:
        rev_list = _run_git(
            ["rev-list", "--count", f"{head_commit}..HEAD"], cwd=wt_path
        )
        if rev_list.returncode == 0:
            changes.new_commits = int(rev_list.stdout.strip())
    except (subprocess.SubprocessError, OSError, ValueError):
        changes.new_commits = 1

    return changes


def has_worktree_changes(wt_path: str, head_commit: str) -> bool:
    """检查 worktree 是否有任何变更（未提交或新提交）"""
    c = count_worktree_changes(wt_path, head_commit)
    return c.uncommitted > 0 or c.new_commits > 0


@dataclass
class CleanupResult:
    """Worktree 清理结果"""
    kept: bool       # 是否保留（有变更则保留）
    path: str = ""   # worktree 路径
    branch: str = "" # 关联分支名


def has_unpushed_commits(wt_path: str) -> bool:
    """
    检查 worktree 是否有未推送到远程的提交。
    
    用于清理前确认：如果有未推送的提交，则不能安全删除。
    出错时保守返回 True（假设有未推送的提交）。
    """
    try:
        result = _run_git(
            ["rev-list", "--max-count=1", "HEAD", "--not", "--remotes"],
            cwd=wt_path,
        )
        return bool(result.stdout.strip()) if result.returncode == 0 else True
    except (subprocess.SubprocessError, OSError):
        return True
