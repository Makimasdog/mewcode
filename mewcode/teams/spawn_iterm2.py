"""
spawn_iterm2.py — iTerm2 后端（macOS 专属的终端分窗格方案）
=============================================================

【这个模块做什么】
使用 iTerm2 的 it2 CLI 工具在分窗格中启动团队成员 Agent。
仅在 macOS + iTerm2 环境下可用。

【与 tmux 后端的对比】
┌─────────────────────────────────────────────────────────────┐
│  spawn_tmux.py    │ 跨平台，需要 tmux              │ 功能丰富│
│  spawn_iterm2.py  │ macOS 专属，需要 iTerm2 + it2  │ 原生体验│
└─────────────────────────────────────────────────────────────┘

iTerm2 后端更简单，因为：
- 不需要三级回退策略（it2 split-pane 一步到位）
- CLI 命令构建复用 spawn_tmux.py 的 build_cli_command()

【前提条件】
1. macOS 系统
2. iTerm2 终端已安装
3. it2 CLI 工具已安装（iTerm2 → Make iTerm2 Default Term App）

【对外接口】
- ITermPaneInfo           窗格信息数据类
- ITermSpawnError         启动异常
- spawn_iterm2_teammate() 启动团队成员
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass
class ITermPaneInfo:
    """iTerm2 窗格信息"""
    session_id: str  # iTerm2 会话 ID


class ITermSpawnError(Exception):
    """iTerm2 操作失败异常"""
    pass


def _run_it2(*args: str) -> str:
    """
    执行 it2 命令并返回输出。

    与 spawn_tmux.py 中的 _run_tmux 类似，
    封装 subprocess.run 统一处理超时和错误。
    """
    result = subprocess.run(
        ["it2", *args],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        raise ITermSpawnError(f"it2 {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def spawn_iterm2_teammate(
    team_name: str,
    teammate_name: str,
    worktree_path: str,
    prompt: str,
    agent_type: str = "",
    model: str = "",
    mailbox_dir: str = "",
) -> ITermPaneInfo:
    """
    在 iTerm2 中启动团队成员。

    流程：
    1. 复用 spawn_tmux.build_cli_command() 构建 CLI 命令
    2. 使用 it2 split-pane 创建分窗格并执行命令
    3. 返回 ITermPaneInfo

    注意：CLI 命令构建逻辑与 tmux 后端共享（避免重复代码）。
    """
    from mewcode.teams.spawn_tmux import build_cli_command

    cli_cmd = build_cli_command(
        team_name=team_name,
        teammate_name=teammate_name,
        worktree_path=worktree_path,
        prompt=prompt,
        agent_type=agent_type,
        model=model,
        mailbox_dir=mailbox_dir,
    )

    try:
        # 使用 it2 split-pane 创建分窗格并在其中执行命令
        session_id = _run_it2("split-pane", "--command", f"/bin/zsh -c '{cli_cmd}'")
    except ITermSpawnError as e:
        raise ITermSpawnError(f"Failed to spawn iTerm2 pane for {teammate_name}: {e}") from e

    log.info("Spawned iTerm2 teammate %s in session %s", teammate_name, session_id)
    return ITermPaneInfo(session_id=session_id)
