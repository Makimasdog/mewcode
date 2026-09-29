"""
worktree 模块 — Git Worktree 工作区管理
=========================================

【什么是 Git Worktree】
Git worktree 允许从同一个仓库创建多个独立的工作目录，
每个工作目录有自己的分支和文件状态，互不干扰。

【为什么 Agent 需要 Worktree】
当多个 Agent 并行工作时，如果都修改同一个仓库，会产生冲突。
Worktree 为每个 Agent 提供独立的工作空间，实现真正的并行。

【核心组件】
- WorktreeManager: 核心管理器，负责 worktree 的完整生命周期
- Worktree/WorktreeSession: 数据模型
- changes: 变更检测（git status/rev-list）
- session: 会话持久化（支持进程重启恢复）
- setup: 创建后初始化（复制配置、设置 hooks、符号链接）
- cleanup: 自动清理过期 worktree
- integration: Agent 集成辅助（名称生成、上下文提示）
- slug: 名称验证与扁平化

【工作流程】
    Agent 请求隔离工作区
    ↓
    WorktreeManager.create()  →  git worktree add + 初始化
    ↓
    WorktreeManager.enter()   →  切换工作目录 + 保存会话
    ↓
    Agent 在 worktree 中工作...
    ↓
    WorktreeManager.exit()    →  恢复工作目录 + 可选删除
    ↓
    cleanup 定期清理过期 worktree

【存储结构】
    <repo>/.mewcode/worktrees/      # worktree 存储目录
    <repo>/.mewcode/worktree_session.json  # 会话持久化文件
"""


from mewcode.worktree.changes import (
    Changes,               # 变更统计
    CleanupResult,         # 清理结果
    count_worktree_changes, # 统计变更数
    has_worktree_changes,  # 检查是否有变更
)
from mewcode.worktree.cleanup import cleanup_stale_worktrees, start_stale_cleanup_task
from mewcode.worktree.manager import WorktreeError, WorktreeManager
from mewcode.worktree.models import Worktree, WorktreeSession
from mewcode.worktree.session import load_worktree_session, save_worktree_session
from mewcode.worktree.slug import flatten_slug, validate_slug


__all__ = [
    "Changes",
    "CleanupResult",
    "Worktree",
    "WorktreeError",
    "WorktreeManager",
    "WorktreeSession",
    "cleanup_stale_worktrees",
    "count_worktree_changes",
    "flatten_slug",
    "has_worktree_changes",
    "load_worktree_session",
    "save_worktree_session",
    "start_stale_cleanup_task",
    "validate_slug",
]

