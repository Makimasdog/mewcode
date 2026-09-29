"""
session.py — Worktree 会话持久化
=====================================

【这个模块做什么】
将当前 worktree 会话状态序列化到磁盘，支持进程重启后恢复。

【存储位置】
    <repo>/.mewcode/worktree_session.json

【为什么需要持久化】
Agent 可能因崩溃或手动中断而退出，持久化会话后：
- 重启时可以自动恢复到之前的 worktree 状态
- 避免 worktree 成为「孤儿」资源
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from mewcode.worktree.models import WorktreeSession

log = logging.getLogger(__name__)

SESSION_FILENAME = "worktree_session.json"


def _session_path(mewcode_dir: Path) -> Path:
    """计算会话文件的完整路径"""
    return mewcode_dir / SESSION_FILENAME


def save_worktree_session(
    mewcode_dir: Path,
    session: WorktreeSession | None,
) -> None:
    """
    保存 worktree 会话到磁盘。
    
    参数:
        mewcode_dir: .mewcode 目录路径
        session: 会话对象，None 表示清空会话
    """
    path = _session_path(mewcode_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    if session is None:
        # 写入空 JSON 表示无活跃会话
        path.write_text("{}", encoding="utf-8")
        return
    data = {
        "original_cwd": session.original_cwd,
        "worktree_path": session.worktree_path,
        "worktree_name": session.worktree_name,
        "original_branch": session.original_branch,
        "original_head_commit": session.original_head_commit,
        "session_id": session.session_id,
        "hook_based": session.hook_based,
    }
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_worktree_session(mewcode_dir: Path) -> WorktreeSession | None:
    """
    从磁盘加载 worktree 会话。
    
    返回:
        WorktreeSession: 恢复的会话
        None: 无活跃会话或文件损坏
    """
    path = _session_path(mewcode_dir)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not data or "worktree_path" not in data:
            return None
        return WorktreeSession(
            original_cwd=data["original_cwd"],
            worktree_path=data["worktree_path"],
            worktree_name=data["worktree_name"],
            original_branch=data["original_branch"],
            original_head_commit=data["original_head_commit"],
            session_id=data.get("session_id", ""),
            hook_based=data.get("hook_based", False),
        )
    except (json.JSONDecodeError, KeyError) as e:
        log.warning("Failed to load worktree session: %s", e)
        return None

