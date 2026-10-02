"""
spawn_inprocess.py — 进程内执行（最简单的团队成员启动方式）
=============================================================

【这个模块做什么】
在当前 Python 进程内以 asyncio.Task 的方式启动一个团队成员 Agent。

【三种后端对比】
┌─────────────────────────────────────────────────────────────┐
│  spawn_inprocess.py  │ asyncio.Task，同进程内运行          │
│  spawn_tmux.py       │ tmux 分窗格，独立进程               │
│  spawn_iterm2.py     │ iTerm2 分窗格，独立进程             │
└─────────────────────────────────────────────────────────────┘

【为什么选择进程内？】
- 最简单：不需要 tmux 或 iTerm2
- 可追踪：直接访问 TeammateProgress 对象
- 低开销：不需要启动新进程
- 适合：大多数场景（除非用户需要实时查看每个成员的终端输出）

【核心组件】
- InProcessTeammateHandle:  成员句柄（封装 asyncio.Task + Agent + Progress）
- spawn_inprocess_teammate: 启动函数（创建 Task 并返回句柄）

【事件回调机制】
Agent 运行过程中产生的事件会通过回调函数更新到 TeammateProgress：
- tool_use 事件 → 记录工具调用
- usage 事件    → 记录 Token 消耗
- stream_text   → 更新最后一条消息

【对外接口】
- InProcessTeammateHandle    成员句柄类
- spawn_inprocess_teammate() 启动函数
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from mewcode.teams.progress import TeammateProgress, random_verb

if TYPE_CHECKING:
    from mewcode.agent import Agent
    from mewcode.conversation import ConversationManager
    from mewcode.teams.models import TeammateInfo

log = logging.getLogger(__name__)


class InProcessTeammateHandle:
    """
    进程内团队成员的执行句柄。

    封装了：
    - agent:   Agent 实例（可用于发送消息等操作）
    - task:    asyncio.Task（Agent 的执行任务）
    - name:    成员名称
    - progress: 进度追踪器（UI 用来显示实时状态）

    属性：
    - done:    任务是否完成
    - result:  任务结果（完成后才有值）
    """
    def __init__(
        self,
        agent: Agent,
        task: asyncio.Task[str],
        name: str,
        progress: TeammateProgress | None = None,
    ) -> None:
        self.agent = agent
        self.task = task
        self.name = name
        self.progress = progress


    @property
    def done(self) -> bool:
        """任务是否已完成"""
        return self.task.done()

    @property
    def result(self) -> str | None:
        """
        获取任务结果。

        - 已完成 → 返回结果字符串
        - 已取消或异常 → 返回 None
        - 未完成 → 返回 None
        """
        if self.task.done():
            try:
                return self.task.result()
            except (asyncio.CancelledError, Exception):
                return None
        return None


    def cancel(self) -> None:
        """取消任务（发送 CancelledError 到 Task）"""
        if not self.task.done():
            self.task.cancel()


def spawn_inprocess_teammate(
    agent: Agent,
    prompt: str,
    name: str,
    conversation: ConversationManager | None = None,
    member: TeammateInfo | None = None,
    team_name: str = "",
) -> InProcessTeammateHandle:
    """
    在进程内启动一个团队成员。

    流程：
    1. 创建 TeammateProgress 进度追踪器
    2. 将进度追踪器附加到成员信息（如果有）
    3. 注册事件回调（tool_use / usage / stream_text → 更新进度）
    4. 创建 asyncio.Task 执行 Agent
    5. 返回句柄（用于后续查询状态和取消）

    参数：
    - agent:        Agent 实例
    - prompt:       执行提示词
    - name:         成员名称
    - conversation: 预构建的对话管理器（可选，用于恢复会话）
    - member:       成员信息（可选，用于附加进度追踪器）
    - team_name:    团队名称（用于进度显示）
    """

    # ── step 1: 创建进度追踪器 ────
    progress = TeammateProgress(
        name=name,
        team_name=team_name,
        spinner_verb=random_verb(),
    )
    if member is not None:
        member.progress = progress

    # ── step 2: 事件回调（Agent → 进度追踪器）────
    def _on_event(event: dict[str, Any]) -> None:
        """Event callback wired into agent.run_to_completion."""
        event_type = event.get("type")
        if event_type == "tool_use":
            tool_name = event.get("toolName", "")
            args = event.get("args", {})
            progress.record_tool_use(tool_name, args)
        elif event_type == "usage":
            usage = event.get("usage", {})
            progress.record_tokens(
                usage.get("inputTokens", 0),
                usage.get("outputTokens", 0),
            )
        elif event_type == "stream_text":
            text = event.get("text")
            if text:
                with progress._lock:
                    progress.last_message = text

    # ── step 3: 异步执行包装 ────
    async def _run() -> str:
        try:
            if conversation is not None:
                # 有预构建的对话 → 使用已有对话（会话恢复场景）
                result = await agent.run_to_completion(
                    "", conversation, event_callback=_on_event,
                )
            else:
                # 无预构建对话 → 用 prompt 创建新对话
                result = await agent.run_to_completion(
                    prompt, event_callback=_on_event,
                )
            progress.status = "completed"
            return result
        except asyncio.CancelledError:
            progress.status = "stopped"
            raise
        except Exception:
            progress.status = "failed"
            raise

    # ── step 4: 创建 Task 并返回句柄 ────
    task = asyncio.create_task(_run(), name=f"teammate-{name}")
    log.info("Spawned in-process teammate %s (verb=%s)", name, progress.spinner_verb)
    return InProcessTeammateHandle(agent=agent, task=task, name=name, progress=progress)
