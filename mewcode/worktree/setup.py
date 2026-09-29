"""
setup.py — Worktree 创建后初始化
=====================================

【这个模块做什么】
Git worktree 创建后，需要做一些额外的初始化工作，让新 worktree 可以立即使用：
1. 复制本地配置文件（settings.local.json、.env）
2. 设置 Git hooks 路径（支持 Husky）
3. 创建符号链接（如 node_modules、.venv）
4. 复制被 .gitignore 忽略但需要的文件（通过 .worktreeinclude）

【为什么需要这些】
Git worktree 只复制被 Git 跟踪的文件。但实际开发中，
很多本地配置和环境文件不被 Git 跟踪，需要手动同步。
"""
from __future__ import annotations

import fnmatch
import logging
import os
import shutil
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)

# 需要从主仓库复制到 worktree 的本地配置文件
LOCAL_CONFIG_FILES = [
    "settings.local.json",  # 本地 IDE 设置
    ".env",                 # 环境变量
]


def perform_post_creation_setup(
    repo_root: str,
    wt_path: str,
    symlink_directories: list[str] | None = None,
) -> None:
    """
    执行 worktree 创建后的所有初始化步骤。
    
    参数:
        repo_root: 主仓库根目录
        wt_path: 新 worktree 的路径
        symlink_directories: 需要创建符号链接的目录列表
    """
    root = Path(repo_root)
    wt = Path(wt_path)

    _copy_local_configs(root, wt)     # 1. 复制本地配置
    _setup_git_hooks(root, wt)         # 2. 设置 Git hooks
    _create_symlinks(root, wt, symlink_directories or [])  # 3. 创建符号链接
    _copy_ignored_files(root, wt)      # 4. 复制被忽略但需要的文件


def _copy_local_configs(root: Path, wt: Path) -> None:
    """复制本地配置文件（settings.local.json、.env）到 worktree"""
    for name in LOCAL_CONFIG_FILES:
        src = root / name
        if src.exists():
            dst = wt / name
            try:
                shutil.copy2(str(src), str(dst))
                log.debug("Copied %s to worktree", name)
            except OSError as e:
                log.warning("Failed to copy %s: %s", name, e)


def _setup_git_hooks(root: Path, wt: Path) -> None:
    """
    设置 worktree 的 Git hooks 路径。
    
    优先检测 Husky（.husky 目录），否则使用默认的 .git/hooks。
    通过 git config core.hooksPath 设置。
    """
    hooks_path: str | None = None

    husky_dir = root / ".husky"
    if husky_dir.is_dir():
        hooks_path = str(husky_dir)
    else:
        git_hooks = root / ".git" / "hooks"
        if git_hooks.is_dir():
            hooks_path = str(git_hooks)

    if hooks_path is None:
        return

    try:
        subprocess.run(
            ["git", "config", "core.hooksPath", hooks_path],
            cwd=str(wt),
            capture_output=True,
            timeout=10,
        )
        log.debug("Set core.hooksPath to %s in worktree", hooks_path)
    except (subprocess.SubprocessError, OSError) as e:
        log.warning("Failed to set hooks path: %s", e)


def _create_symlinks(root: Path, wt: Path, directories: list[str]) -> None:
    """
    为指定目录创建符号链接。
    
    常用于 node_modules、.venv 等大型依赖目录，
    避免在每个 worktree 中重复安装。
    """
    for dirname in directories:
        src = root / dirname
        dst = wt / dirname
        if not src.exists():
            continue
        if dst.exists() or dst.is_symlink():
            continue
        try:
            os.symlink(str(src), str(dst))
            log.debug("Symlinked %s to worktree", dirname)
        except OSError as e:
            log.warning("Failed to symlink %s: %s", dirname, e)


def _copy_ignored_files(root: Path, wt: Path) -> None:
    """
    复制被 .gitignore 忽略但通过 .worktreeinclude 指定需要的文件。
    
    .worktreeinclude 文件格式（类似 .gitignore）：
        # 注释行
        .env.local
        dist/*
    
    这些文件不被 Git 跟踪，但对开发环境很重要。
    """
    include_file = root / ".worktreeinclude"
    if not include_file.exists():
        return

    try:
        patterns = [
            line.strip()
            for line in include_file.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
    except OSError:
        return

    if not patterns:
        return

    try:
        result = subprocess.run(
            [
                "git", "ls-files",
                "--others", "--ignored", "--exclude-standard", "--directory",
            ],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return
        ignored_files = [f.rstrip("/") for f in result.stdout.splitlines() if f.strip()]
    except (subprocess.SubprocessError, OSError):
        return

    for rel_path in ignored_files:
        if not any(fnmatch.fnmatch(rel_path, pat) for pat in patterns):
            continue
        src = root / rel_path
        dst = wt / rel_path
        if not src.is_file():
            continue
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(src), str(dst))
            log.debug("Copied ignored file %s to worktree", rel_path)
        except OSError as e:
            log.warning("Failed to copy ignored file %s: %s", rel_path, e)
