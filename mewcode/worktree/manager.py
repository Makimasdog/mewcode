"""
manager.py — Worktree 核心管理器
=====================================

【这个模块做什么】
WorktreeManager 是 worktree 系统的核心编排器，提供完整的 worktree 生命周期管理：
- create: 创建新 worktree（含后置初始化）
- enter: 进入 worktree（切换工作目录）
- exit: 退出 worktree（恢复原工作目录）
- auto_cleanup: 根据变更情况自动决定是否删除
- restore_session: 从持久化会话中恢复

【设计亮点】
- 异步锁保护：所有修改操作都通过 asyncio.Lock 保护
- 快速恢复：直接从文件系统读取 HEAD SHA，无需启动 git 子进程
- 会话持久化：支持进程重启后自动恢复
- 安全删除：删除前检查未提交变更和未推送提交
"""
from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path

from mewcode.cache import FileCache
from mewcode.worktree.changes import (
    CleanupResult,
    Changes,
    count_worktree_changes,
    has_worktree_changes,
)
from mewcode.worktree.models import Worktree, WorktreeSession
from mewcode.worktree.session import load_worktree_session, save_worktree_session
from mewcode.worktree.setup import perform_post_creation_setup
from mewcode.worktree.slug import flatten_slug, validate_slug

log = logging.getLogger(__name__)

# 禁止 git 弹出交互式密码输入
GIT_ENV = {"GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": ""}


class WorktreeError(Exception):
    """Worktree 操作失败时抛出的异常"""
    pass


class WorktreeManager:
    """
    Worktree 核心管理器。
    
    管理 worktree 的完整生命周期：创建、进入、退出、清理、恢复。
    所有修改操作都通过异步锁保护，确保并发安全。
    """
    def __init__(
        self,
        repo_root: str,
        symlink_directories: list[str] | None = None,
        worktree_dir: str | None = None,
        file_cache: FileCache | None = None,
    ) -> None:
        """
        初始化 WorktreeManager。
        
        参数:
            repo_root: Git 仓库根目录
            symlink_directories: 创建 worktree 时需要符号链接的目录
            worktree_dir: worktree 存储目录（默认 .mewcode/worktrees）
            file_cache: 文件缓存（进入 worktree 后需要清空）
        """
        self.repo_root = repo_root
        self.symlink_directories = symlink_directories or []
        self.worktree_dir = worktree_dir or str(
            Path(repo_root) / ".mewcode" / "worktrees"
        )
        self.file_cache = file_cache or FileCache()
        self._mewcode_dir = Path(repo_root) / ".mewcode"
        self._lock = asyncio.Lock()                    # 并发保护锁
        self.active: dict[str, Worktree] = {}          # 活跃的 worktree 列表
        self.current_session: WorktreeSession | None = None  # 当前会话

    def _run_git(self, args: list[str], cwd: str | None = None) -> subprocess.CompletedProcess[str]:
        """执行 git 命令，注入环境变量以禁止交互式提示"""
        env = {**os.environ, **GIT_ENV}
        return subprocess.run(
            ["git"] + args,
            cwd=cwd or self.repo_root,
            capture_output=True,
            text=True,
            timeout=60,
            stdin=subprocess.DEVNULL,
            env=env,
        )

    # ------------------------------------------------------------------
    # 快速恢复：直接从文件系统读取 HEAD SHA，无需启动 git 子进程
    # 这是性能优化：避免每次检查都 fork 一个 git 进程
    # ------------------------------------------------------------------

    @staticmethod
    def read_worktree_head_sha(wt_path: str) -> str | None:
        """
        从文件系统直接读取 worktree 的 HEAD SHA。
        
        比调用 git rev-parse 快得多，因为不需要 fork 子进程。
        通过解析 .git 文件找到实际的 gitdir，然后读取 HEAD。
        """
        wt = Path(wt_path)
        git_file = wt / ".git"
        if not git_file.exists():
            return None

        try:
            content = git_file.read_text(encoding="utf-8").strip()
            if not content.startswith("gitdir:"):
                return None
            gitdir = Path(content.split(":", 1)[1].strip())
            if not gitdir.is_absolute():
                gitdir = (wt / gitdir).resolve()

            commondir_file = gitdir / "commondir"
            if commondir_file.exists():
                commondir_rel = commondir_file.read_text(encoding="utf-8").strip()
                commondir = (gitdir / commondir_rel).resolve()
            else:
                commondir = gitdir

            head_file = gitdir / "HEAD"
            if not head_file.exists():
                return None
            head_content = head_file.read_text(encoding="utf-8").strip()

            if head_content.startswith("ref:"):
                ref_path = head_content.split(":", 1)[1].strip()
                ref_file = gitdir / ref_path
                if not ref_file.exists():
                    ref_file = commondir / ref_path
                if ref_file.exists():
                    return ref_file.read_text(encoding="utf-8").strip()
                packed_refs = commondir / "packed-refs"
                if packed_refs.exists():
                    for line in packed_refs.read_text(encoding="utf-8").splitlines():
                        if line.strip() and not line.startswith("#"):
                            parts = line.split()
                            if len(parts) == 2 and parts[1] == ref_path:
                                return parts[0]
                return None
            return head_content
        except OSError:
            return None

    # ------------------------------------------------------------------
    # 创建 worktree
    # 流程：验证名称 → 检查复用 → git worktree add → 后置初始化
    # ------------------------------------------------------------------

    async def create(self, name: str, base_branch: str = "HEAD") -> Worktree:
        """
        创建新的 worktree。
        
        流程：
        1. 验证名称合法性
        2. 检查是否已存在（支持快速恢复）
        3. 执行 git worktree add
        4. 执行后置初始化（复制配置、设置 hooks、创建符号链接）
        
        参数:
            name: worktree 名称
            base_branch: 基于哪个分支/提交创建
        返回:
            Worktree 对象
        """
        async with self._lock:
            err = validate_slug(name)
            if err:
                raise WorktreeError(err)

            if name in self.active:
                raise WorktreeError(f"worktree already exists: {name}")

            flat_slug = flatten_slug(name)
            wt_path = os.path.join(self.worktree_dir, flat_slug)
            branch_name = f"worktree-{flat_slug}"

            # 检查是否可以复用已存在的 worktree（快速恢复）
            head_sha = self.read_worktree_head_sha(wt_path)
            if head_sha is not None:
                log.info("Fast recovery: reusing existing worktree at %s", wt_path)
                wt = Worktree(
                    name=name,
                    path=wt_path,
                    branch=branch_name,
                    based_on=base_branch,
                    head_commit=head_sha,
                )
                self.active[name] = wt
                return wt

            os.makedirs(self.worktree_dir, exist_ok=True)

            result = self._run_git([
                "worktree", "add",
                "-B", branch_name, wt_path, base_branch,
            ])
            if result.returncode != 0:
                raise WorktreeError(
                    f"git worktree add failed: {result.stderr.strip()}"
                )

            # 执行后置初始化（复制配置、设置 hooks、创建符号链接）
            perform_post_creation_setup(
                self.repo_root,
                wt_path,
                symlink_directories=self.symlink_directories,
            )

            head_sha = self.read_worktree_head_sha(wt_path) or ""
            wt = Worktree(
                name=name,
                path=wt_path,
                branch=branch_name,
                based_on=base_branch,
                head_commit=head_sha,
            )
            self.active[name] = wt
            return wt

    # ------------------------------------------------------------------
    # 进入 worktree：切换工作目录，保存原始状态
    # ------------------------------------------------------------------

    async def enter(self, name: str) -> WorktreeSession:
        """
        进入指定的 worktree。
        
        流程：
        1. 记录当前工作目录和 Git 状态
        2. 清空文件缓存（旧工作区的缓存已失效）
        3. 创建并保存会话
        
        参数:
            name: worktree 名称
        返回:
            WorktreeSession 对象
        """
        wt = self.active.get(name)
        if wt is None:
            raise WorktreeError(f"worktree not found: {name}")

        original_cwd = os.getcwd()
        original_branch = self._get_current_branch()
        original_head = self._get_head_commit()

        # 切换工作区后，旧工作区缓存的文件内容已失效，整体清空
        self.file_cache.clear()

        session = WorktreeSession(
            original_cwd=original_cwd,
            worktree_path=wt.path,
            worktree_name=name,
            original_branch=original_branch,
            original_head_commit=original_head,
        )
        self.current_session = session
        save_worktree_session(self._mewcode_dir, session)
        return session

    # ------------------------------------------------------------------
    # 退出 worktree：恢复原工作目录，可选删除 worktree
    # ------------------------------------------------------------------


    async def exit(
        self,
        name: str,
        action: str = "keep",
        discard_changes: bool = False,
    ) -> None:
        """
        退出 worktree。
        
        参数:
            name: worktree 名称
            action: "keep" 保留 / "remove" 删除
            discard_changes: 是否强制删除（即使有未提交变更）
        """
        wt = self.active.get(name)
        if wt is None:
            raise WorktreeError(f"worktree not found: {name}")

        if action == "remove" and not discard_changes:
            changes = count_worktree_changes(wt.path, wt.head_commit)
            if changes.uncommitted > 0 or changes.new_commits > 0:
                raise WorktreeError(
                    f"worktree has changes ({changes.uncommitted} uncommitted, "
                    f"{changes.new_commits} new commits). "
                    "Set discard_changes=True to force removal."
                )

        self.current_session = None
        save_worktree_session(self._mewcode_dir, None)

        if action == "remove":
            await self._remove_worktree(name, wt)

    # ------------------------------------------------------------------
    # 删除 worktree（内部方法）
    # 流程：git worktree remove → 删除分支 → 从活跃列表移除
    # ------------------------------------------------------------------

    async def _remove_worktree(self, name: str, wt: Worktree) -> None:
        """删除 worktree 及其关联的 Git 分支"""
        result = self._run_git(["worktree", "remove", "--force", wt.path])
        if result.returncode != 0:
            log.warning("git worktree remove failed: %s", result.stderr.strip())

        await asyncio.sleep(0.1)

        flat_slug = flatten_slug(name)
        branch_name = f"worktree-{flat_slug}"
        self._run_git(["branch", "-D", branch_name])

        self.active.pop(name, None)

    # ------------------------------------------------------------------
    # 自动清理：根据变更情况决定是否删除
    # ------------------------------------------------------------------


    async def auto_cleanup(self, name: str, head_commit: str) -> CleanupResult:
        """
        自动清理 worktree。
        
        如果有变更则保留，无变更则删除。
        
        参数:
            name: worktree 名称
            head_commit: 创建时的 HEAD 提交
        返回:
            CleanupResult（kept=True 表示保留）
        """
        wt = self.active.get(name)
        if wt is None:
            return CleanupResult(kept=False)

        if has_worktree_changes(wt.path, head_commit):
            return CleanupResult(kept=True, path=wt.path, branch=wt.branch)

        await self._remove_worktree(name, wt)
        return CleanupResult(kept=False)

    # ------------------------------------------------------------------
    # 列出 / 查询
    # ------------------------------------------------------------------

    def list_worktrees(self) -> list[Worktree]:
        """获取所有活跃的 worktree 列表"""
        return list(self.active.values())


    def get_current_session(self) -> WorktreeSession | None:
        """获取当前的 worktree 会话"""
        return self.current_session

    # ------------------------------------------------------------------
    # 从持久化的 session 中恢复（支持进程重启后恢复）
    # ------------------------------------------------------------------

    def restore_session(self) -> WorktreeSession | None:
        """
        从磁盘恢复 worktree 会话。
        
        流程：
        1. 加载持久化的会话文件
        2. 验证 worktree 是否仍然存在
        3. 恢复活跃 worktree 列表和当前会话
        """
        session = load_worktree_session(self._mewcode_dir)
        if session is None:
            return None
        wt_path = session.worktree_path
        head_sha = self.read_worktree_head_sha(wt_path)
        if head_sha is None:
            save_worktree_session(self._mewcode_dir, None)
            return None

        wt = Worktree(
            name=session.worktree_name,
            path=wt_path,
            branch=f"worktree-{flatten_slug(session.worktree_name)}",
            based_on="unknown",
            head_commit=head_sha,
        )
        self.active[session.worktree_name] = wt
        self.current_session = session
        return session

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------


    def _get_current_branch(self) -> str:
        """获取当前 Git 分支名"""
        try:
            result = self._run_git(["rev-parse", "--abbrev-ref", "HEAD"])
            return result.stdout.strip() if result.returncode == 0 else "HEAD"
        except (subprocess.SubprocessError, OSError):
            return "HEAD"

    def _get_head_commit(self) -> str:
        """获取当前 HEAD 提交的 SHA"""
        try:
            result = self._run_git(["rev-parse", "HEAD"])
            return result.stdout.strip() if result.returncode == 0 else ""
        except (subprocess.SubprocessError, OSError):
            return ""
