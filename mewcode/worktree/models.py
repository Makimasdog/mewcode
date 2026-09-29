"""
models.py — Worktree 核心数据模型
=====================================

【这个模块做什么】
定义 Worktree 系统的两个基础数据结构：
- Worktree: 一个 Git worktree 工作区的元数据
- WorktreeSession: 当前活跃的 worktree 会话（用于持久化和恢复）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Worktree:
    """
    一个 Git worktree 工作区的元数据。
    
    Git worktree 允许从同一个仓库创建多个独立的工作目录，
    每个工作目录有自己的分支和文件状态，互不干扰。
    在 MewCode 中，每个 Agent/任务可以拥有独立的 worktree。
    """
    name: str           # worktree 名称（如 "agent-a1b2c3d4"）
    path: str           # worktree 在磁盘上的路径
    branch: str         # 关联的 Git 分支名（如 "worktree-agent-a1b2c3d4"）
    based_on: str       # 基于哪个分支/提交创建的（如 "HEAD"、"main"）
    head_commit: str    # 创建时的 HEAD 提交 SHA
    created: datetime = field(default_factory=datetime.now)  # 创建时间


@dataclass
class WorktreeSession:
    """
    当前活跃的 worktree 会话。
    
    记录进入 worktree 前的状态，用于退出时恢复。
    会话会被持久化到磁盘（worktree_session.json），支持进程重启后恢复。
    """
    original_cwd: str          # 进入 worktree 前的工作目录
    worktree_path: str         # worktree 路径
    worktree_name: str         # worktree 名称
    original_branch: str       # 进入前的 Git 分支
    original_head_commit: str  # 进入前的 HEAD 提交
    session_id: str = ""       # 关联的 Agent 会话 ID
    hook_based: bool = False   # 是否通过 Hook 触发进入

