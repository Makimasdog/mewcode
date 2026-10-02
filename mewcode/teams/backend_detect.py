"""
backend_detect.py — 后端检测（自动选择终端分窗格方案）
=============================================================

【这个模块做什么】
检测当前系统环境，自动选择最合适的终端后端来运行团队成员。

【三种后端及其适用条件】
┌─────────────────────────────────────────────────────────────┐
│  后端          │ 适用条件                          │ 特点    │
├─────────────────────────────────────────────────────────────┤
│  IN_PROCESS    │ 默认 / 非交互模式                 │ 最简单  │
│  TMUX          │ tmux 已安装                       │ 跨平台  │
│  ITERM2        │ macOS + iTerm2 + it2 CLI          │ 原生体验│
└─────────────────────────────────────────────────────────────┘

【检测优先级】
1. 如果 teammate_mode == "in-process" 或非交互模式 → IN_PROCESS
2. 如果当前在 tmux 会话中 → TMUX（在已有会话中分窗格）
3. 如果是 iTerm2 且 it2 CLI 可用 → ITERM2
4. 如果 tmux 已安装 → TMUX（创建新会话）
5. 都不满足 → 抛出 BackendDetectionError

【为什么默认是 IN_PROCESS？】
- 不需要额外安装任何工具
- 可以实时追踪进度（TeammateProgress）
- 适合大多数用户

【对外接口】
- detect_backend()        检测执行后端（默认 in-process）
- detect_pane_backend()   检测分窗格后端（用户明确要求 tmux 时使用）
- BackendDetectionError   检测失败异常
"""

from __future__ import annotations

import os
import shutil

from mewcode.teams.models import BackendType


class BackendDetectionError(Exception):
    """终端后端检测失败（没有可用的终端分窗格方案）"""
    pass


def _in_tmux_session() -> bool:
    """检查当前是否在 tmux 会话中（通过 TMUX 环境变量判断）"""
    return bool(os.environ.get("TMUX"))


def _in_iterm2() -> bool:
    """检查当前是否在 iTerm2 终端中（macOS 专属）"""
    return os.environ.get("TERM_PROGRAM") == "iTerm.app"


def _it2_available() -> bool:
    """检查 it2 CLI 工具是否可用（iTerm2 的命令行控制工具）"""
    return shutil.which("it2") is not None


def _tmux_installed() -> bool:
    """检查 tmux 是否已安装"""
    return shutil.which("tmux") is not None


def detect_backend(
    teammate_mode: str = "",
    is_interactive: bool = True,
) -> BackendType:
    """
    检测执行后端。

    当前默认返回 IN_PROCESS（实时进度追踪），
    未来可能根据配置和环境自动选择更合适的后端。
    """
    return BackendType.IN_PROCESS


def detect_pane_backend(
    teammate_mode: str = "",
    is_interactive: bool = True,
) -> BackendType:
    """
    检测分窗格后端（用户明确要求使用终端分窗格时调用）。

    检测流程：
    1. 非交互模式或指定 in-process → 直接返回 IN_PROCESS
    2. 在 tmux 会话中 → 使用 TMUX（在现有会话中分窗格）
    3. iTerm2 + it2 → 使用 ITERM2
    4. tmux 已安装 → 使用 TMUX（创建新会话）
    5. 都不满足 → 抛出错误，提示安装方案

    抛出：
        BackendDetectionError: 没有可用的终端后端
    """
    if teammate_mode == "in-process" or not is_interactive:
        return BackendType.IN_PROCESS

    if _in_tmux_session():
        return BackendType.TMUX

    if _in_iterm2() and _it2_available():
        return BackendType.ITERM2

    if _tmux_installed():
        return BackendType.TMUX

    raise BackendDetectionError(
        "No suitable terminal backend found for Agent Team.\n"
        "Install one of the following:\n"
        "  - tmux: brew install tmux\n"
        "  - iTerm2 + it2 CLI: https://iterm2.com/utilities/it2check\n"
        "Or set 'teammate_mode: \"in-process\"' in config.yaml to use in-process backend."
    )
