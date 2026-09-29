"""
cleanup.py — Worktree 自动清理
=====================================

【这个模块做什么】
自动清理过期的临时 worktree，避免磁盘空间浪费。

【清理策略】
只清理同时满足以下所有条件的 worktree：
1. 名称匹配临时模式（agent-*/wf_*/bridge-*/job-*）
2. 不是当前活跃的 worktree
3. 最后修改时间超过阈值（默认 24 小时）
4. 没有未提交的变更
5. 没有未推送到远程的提交

【安全设计】
清理前进行多重检查，确保不会丢失用户的工作。
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from mewcode.worktree.changes import has_unpushed_commits, has_worktree_changes
from mewcode.worktree.manager import WorktreeManager

log = logging.getLogger(__name__)

# 临时 worktree 名称匹配模式
# 只有匹配这些模式的 worktree 才会被自动清理
EPHEMERAL_PATTERNS = [
    re.compile(r"^agent-a[0-9a-f]{7}$"),           # agent-a1b2c3d4
    re.compile(r"^wf_[0-9a-f]{8}-[0-9a-f]{3}-\d+$"),  # wf_uuid-num
    re.compile(r"^wf-\d+$"),                          # wf-123
    re.compile(r"^bridge-[A-Za-z0-9_]+(-[A-Za-z0-9_]+)*$"),  # bridge-name
    re.compile(r"^job-[a-zA-Z0-9._-]{1,55}-[0-9a-f]{8}$"),   # job-name-hash
]


def _is_ephemeral(name: str) -> bool:
    """检查 worktree 名称是否匹配临时模式"""
    return any(p.match(name) for p in EPHEMERAL_PATTERNS)


async def cleanup_stale_worktrees(manager: WorktreeManager, cutoff_hours: int) -> int:
    """
    清理过期的临时 worktree。
    
    流程：
    1. 遍历 worktree 目录
    2. 过滤出临时 worktree（名称匹配模式）
    3. 跳过当前活跃的 worktree
    4. 检查最后修改时间是否超过阈值
    5. 检查是否有未提交变更或未推送提交
    6. 满足所有条件则删除
    
    参数:
        manager: WorktreeManager 实例
        cutoff_hours: 过期阈值（小时）
    返回:
        清理的 worktree 数量
    """
    cutoff = datetime.now() - timedelta(hours=cutoff_hours)
    removed = 0
    worktree_dir = Path(manager.worktree_dir)

    if not worktree_dir.exists():
        return 0

    for entry in worktree_dir.iterdir():
        if not entry.is_dir():
            continue
        name = entry.name

        # 只清理临时 worktree
        if not _is_ephemeral(name):
            continue

        # 跳过当前活跃的 worktree
        if manager.current_session and manager.current_session.worktree_name == name:
            continue

        # 检查最后修改时间
        try:
            mtime = datetime.fromtimestamp(entry.stat().st_mtime)
            if mtime > cutoff:
                continue
        except OSError:
            continue

        head_sha = WorktreeManager.read_worktree_head_sha(str(entry))
        if head_sha is None:
            continue

        # 安全检查：有变更则保留
        if has_worktree_changes(str(entry), head_sha):
            continue

        # 安全检查：有未推送提交则保留
        if has_unpushed_commits(str(entry)):
            continue

        # 所有检查通过，执行删除
        try:
            flat_name = name
            if flat_name in manager.active:
                await manager._remove_worktree(flat_name, manager.active[flat_name])
            else:
                result = manager._run_git(
                    ["worktree", "remove", "--force", str(entry)]
                )
                if result.returncode == 0:
                    await asyncio.sleep(0.1)
                    manager._run_git(["branch", "-D", f"worktree-{flat_name}"])
            removed += 1
            log.info("Cleaned up stale worktree: %s", name)
        except Exception as e:
            log.warning("Failed to clean up stale worktree %s: %s", name, e)

    return removed


async def start_stale_cleanup_task(
    manager: WorktreeManager,
    interval: int,
    cutoff_hours: int,
) -> None:
    """
    启动后台清理任务。
    
    定期执行 cleanup_stale_worktrees，保持磁盘整洁。
    
    参数:
        manager: WorktreeManager 实例
        interval: 清理间隔（秒）
        cutoff_hours: 过期阈值（小时）
    """
    while True:
        await asyncio.sleep(interval)
        try:
            count = await cleanup_stale_worktrees(manager, cutoff_hours)
            if count:
                log.info("Stale worktree cleanup removed %d worktrees", count)
        except Exception as e:
            log.warning("Stale worktree cleanup error: %s", e)

