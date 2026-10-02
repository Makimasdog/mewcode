"""
spawn_tmux.py — tmux 后端（在终端分窗格中运行团队成员）
=============================================================

【这个模块做什么】
使用 tmux 在终端分窗格中启动团队成员 Agent。
每个成员拥有独立的终端窗格，用户可以实时看到每个 Agent 的输出。

【工作原理】
1. 在 tmux 中创建分窗格（split-window）
2. 构建 mewcode CLI 命令（包含团队名、成员名、工作目录等）
3. 通过 send-keys 将命令发送到分窗格中执行
4. 返回 TmuxPaneInfo（pane_id + session 名）用于后续管理

【tmux 分窗格创建策略（三级回退）】
┌─────────────────────────────────────────────────────────────┐
│  尝试 1: split-window   → 在当前窗口中分窗格               │
│  尝试 2: new-window     → 创建新窗口再分窗格               │
│  尝试 3: new-session    → 创建全新会话                     │
└─────────────────────────────────────────────────────────────┘
这种回退策略确保在各种 tmux 状态下都能成功创建窗格。

【CLI 命令构建】
最终在分窗格中执行的命令类似：
MEWCODE_TEAM_NAME=my-team MEWCODE_TEAMMATE_NAME=alice \\
  mewcode -p --work-dir /path/to/worktree '请实现用户登录功能'

【对外接口】
- TmuxPaneInfo             窗格信息数据类
- TmuxSpawnError           启动异常
- build_cli_command()      构建 CLI 命令字符串
- spawn_tmux_teammate()    启动团队成员
- send_keys_to_pane()      向窗格发送按键
- kill_pane()              关闭窗格
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass
class TmuxPaneInfo:
    """tmux 窗格信息（用于后续管理：发送按键、关闭等）"""
    pane_id: str   # tmux 窗格 ID（如 "%3"）
    session: str   # tmux 会话名称


class TmuxSpawnError(Exception):
    """tmux 操作失败异常"""
    pass


def _run_tmux(*args: str) -> str:
    """
    执行 tmux 命令并返回输出。

    封装 subprocess.run，统一处理：
    - 超时：10 秒
    - 错误：非零退出码时抛出 TmuxSpawnError
    """
    result = subprocess.run(
        ["tmux", *args],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        raise TmuxSpawnError(f"tmux {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def build_cli_command(
    team_name: str,
    teammate_name: str,
    worktree_path: str,
    prompt: str,
    agent_type: str = "",
    model: str = "",
    mailbox_dir: str = "",
) -> str:
    """
    构建团队成员的 CLI 启动命令。

    生成的命令格式：
    MEWCODE_TEAM_NAME=xxx MEWCODE_TEAMMATE_NAME=yyy [MEWCODE_MAILBOX_DIR=zzz] \\
      mewcode -p --work-dir <path> [--agent-type <type>] [--model <model>] '<prompt>'

    注意：prompt 中的单引号会被转义（' → '\\'）
    """
    parts = ["mewcode", "-p"]
    parts.extend(["--work-dir", worktree_path])
    if agent_type:
        parts.extend(["--agent-type", agent_type])
    if model:
        parts.extend(["--model", model])
    # 环境变量前缀（告诉子进程它的团队身份信息）
    env_parts = [
        f"MEWCODE_TEAM_NAME={team_name}",
        f"MEWCODE_TEAMMATE_NAME={teammate_name}",
    ]
    if mailbox_dir:
        env_parts.append(f"MEWCODE_MAILBOX_DIR={mailbox_dir}")
    env_prefix = " ".join(env_parts)
    cmd = " ".join(parts)
    full_prompt = prompt.replace("'", "'\\''")  # 转义单引号
    return f"{env_prefix} {cmd} '{full_prompt}'"


def spawn_tmux_teammate(
    team_name: str,
    teammate_name: str,
    worktree_path: str,
    prompt: str,
    agent_type: str = "",
    model: str = "",
    mailbox_dir: str = "",
) -> TmuxPaneInfo:
    """
    在 tmux 中启动团队成员。

    三级回退策略：
    1. 尝试 split-window（在现有窗口中分窗格）
    2. 失败 → 尝试 new-window + split-window（创建新窗口再分）
    3. 再失败 → new-session（创建全新会话）

    最后通过 send-keys 将 CLI 命令发送到新窗格中执行。
    """
    window_name = f"{team_name}-{teammate_name}"

    # ── 三级回退创建窗格 ────
    try:
        # 尝试 1: 在现有会话中分窗格
        pane_id = _run_tmux(
            "split-window",
            "-h",           # 水平分割
            "-P",           # 打印新窗格 ID
            "-F", "#{pane_id}",
            "-t", f"{team_name}",
        )
    except TmuxSpawnError:
        try:
            # 尝试 2: 创建新窗口再分窗格
            _run_tmux("new-window", "-t", f"{team_name}", "-n", window_name, "-P", "-F", "#{pane_id}")
            pane_id = _run_tmux(
                "split-window",
                "-h",
                "-P",
                "-F", "#{pane_id}",
                "-t", f"{team_name}:{window_name}",
            )
        except TmuxSpawnError:
            # 尝试 3: 创建全新会话
            _run_tmux("new-session", "-d", "-s", team_name, "-n", window_name)
            pane_id = _run_tmux(
                "list-panes",
                "-t", f"{team_name}:{window_name}",
                "-F", "#{pane_id}",
            ).split("\n")[0]

    # ── 构建命令并发送到窗格 ────
    cli_cmd = build_cli_command(
        team_name=team_name,
        teammate_name=teammate_name,
        worktree_path=worktree_path,
        prompt=prompt,
        agent_type=agent_type,
        model=model,
        mailbox_dir=mailbox_dir,
    )
    _run_tmux("send-keys", "-t", pane_id, cli_cmd, "Enter")

    log.info("Spawned tmux teammate %s in pane %s", teammate_name, pane_id)
    return TmuxPaneInfo(pane_id=pane_id, session=team_name)


def send_keys_to_pane(pane_id: str, keys: str = "") -> None:
    """向 tmux 窗格发送按键（用于远程控制成员 Agent）"""
    try:
        _run_tmux("send-keys", "-t", pane_id, keys, "Enter")
    except TmuxSpawnError:
        log.warning("Failed to send keys to tmux pane %s", pane_id)


def kill_pane(pane_id: str) -> None:
    """关闭 tmux 窗格（静默失败，窗格可能已经不存在）"""
    try:
        _run_tmux("kill-pane", "-t", pane_id)
    except TmuxSpawnError:
        pass
