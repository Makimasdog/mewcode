"""
engine.py — Hook 执行引擎
=====================================

【这个模块做什么】
HookEngine 是 Hook 系统的核心执行引擎。
它负责：
1. 管理所有已注册的 Hook
2. 根据事件和条件查找匹配的 Hook
3. 执行 Hook 的动作
4. 收集执行结果和通知

【执行流程】
当 Agent 触发事件时：
    HookEngine.run_hooks(event, ctx)
    ↓
    find_matching_hooks(event, ctx)  # 查找匹配的 Hook
    ↓
    对每个匹配的 Hook：
        1. 检查条件是否满足
        2. 执行动作（command/prompt/http/agent）
        3. 收集结果到通知队列

【特殊处理】
- pre_tool_use: 特殊处理，可以拒绝工具执行（返回 ToolRejectedError）
- prompt 类型: 结果会被收集到 _prompt_messages，稍后注入 LLM 对话
- async_exec: 异步执行，不阻塞主流程
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from mewcode.hooks.executors import execute_action
from mewcode.hooks.models import ActionResult, Hook, HookContext, ToolRejectedError

log = logging.getLogger(__name__)


@dataclass
class HookNotification:
    """Hook 执行通知，用于 UI 显示或日志记录"""
    hook_id: str      # 执行的 Hook ID
    event: str        # 触发的事件
    output: str       # 执行输出
    success: bool     # 是否成功


class HookEngine:
    """
    Hook 执行引擎。
    
    管理所有 Hook 的生命周期，处理事件触发和动作执行。
    """
    def __init__(self, hooks: list[Hook] | None = None) -> None:
        self.hooks: list[Hook] = hooks or []
        self._prompt_messages: list[str] = []      # 待注入 LLM 的提示消息
        self._notifications: list[HookNotification] = []  # 执行通知队列


    def find_matching_hooks(self, event: str, ctx: HookContext) -> list[Hook]:
        """
        查找匹配当前事件和条件的 Hook。
        
        匹配条件：
        1. Hook 的事件与当前事件相同
        2. Hook 未被执行过（考虑 once 限制）
        3. Hook 的条件满足（如果有条件）
        """
        matched: list[Hook] = []
        for hook in self.hooks:
            if hook.event != event:
                continue
            if not hook.should_run():
                continue
            if hook.condition is not None and not hook.condition.evaluate(ctx):
                continue
            matched.append(hook)
        return matched


    async def run_hooks(self, event: str, ctx: HookContext) -> None:
        """
        执行匹配指定事件的所有 Hook。
        
        支持同步和异步两种执行模式：
        - async_exec=True: 异步执行，不等待结果
        - async_exec=False: 同步执行，等待完成后继续
        """
        matched = self.find_matching_hooks(event, ctx)
        for hook in matched:
            hook.mark_executed()
            if hook.async_exec:
                # 异步执行：创建后台任务，不等待完成
                asyncio.ensure_future(self._run_single(hook, ctx))
            else:
                # 同步执行：等待完成
                await self._run_single(hook, ctx)


    async def _run_single(self, hook: Hook, ctx: HookContext) -> None:
        """
        执行单个 Hook 的动作。
        
        执行完成后：
        - prompt 类型的结果会被收集到 _prompt_messages
        - 所有结果都会被记录到通知队列
        """
        try:
            result = await execute_action(hook.action, ctx)
            # prompt 类型的结果需要注入 LLM 对话
            if hook.action.type == "prompt" and result.success:
                self._prompt_messages.append(result.output)
            # 记录执行通知
            self._notifications.append(
                HookNotification(
                    hook_id=hook.id,
                    event=hook.event,
                    output=result.output,
                    success=result.success,
                )
            )
            if not result.success:
                log.warning(
                    "Hook '%s' action failed: %s", hook.id, result.output
                )
        except Exception as e:
            log.warning("Hook '%s' execution error: %s", hook.id, e)
            self._notifications.append(
                HookNotification(
                    hook_id=hook.id,
                    event=hook.event,
                    output=str(e),
                    success=False,
                )
            )


    async def run_pre_tool_hooks(
        self, ctx: HookContext
    ) -> ToolRejectedError | None:
        """
        执行工具使用前的 Hook（pre_tool_use）。
        
        这是特殊的 Hook 执行方法，因为它可以拒绝工具执行：
        - 如果任何 Hook 设置了 reject=true，返回 ToolRejectedError
        - 工具执行会被取消，Agent 会收到拒绝消息
        
        返回:
            ToolRejectedError: 如果工具被拒绝
            None: 如果所有 Hook 都通过
        """
        matched = self.find_matching_hooks("pre_tool_use", ctx)
        for hook in matched:
            hook.mark_executed()
            try:
                result = await execute_action(hook.action, ctx)
                self._notifications.append(
                    HookNotification(
                        hook_id=hook.id,
                        event="pre_tool_use",
                        output=result.output,
                        success=result.success,
                    )
                )
                # 如果设置了 reject，返回拒绝错误
                if hook.reject:
                    return ToolRejectedError(
                        tool=ctx.tool_name,
                        reason=result.output,
                        hook_id=hook.id,
                    )
            except Exception as e:
                log.warning("Hook '%s' execution error: %s", hook.id, e)
        return None

    def get_prompt_messages(self) -> list[str]:
        """
        获取并清空待注入 LLM 的提示消息。
        
        调用后会清空内部队列，避免重复注入。
        """
        messages = list(self._prompt_messages)
        self._prompt_messages.clear()
        return messages


    def drain_notifications(self) -> list[HookNotification]:
        """
        获取并清空通知队列。
        
        调用后会清空内部队列，避免重复处理。
        """
        notifications = list(self._notifications)
        self._notifications.clear()
        return notifications
