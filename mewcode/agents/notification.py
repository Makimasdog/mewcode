"""
notification.py — 后台任务完成通知
=======================================

【这个模块做什么】
当后台子 Agent 完成任务后，需要通知主 Agent。
本模块负责：
1. 将任务结果格式化为通知消息
2. 将通知注入到主 Agent 的对话中

主 Agent 在每轮迭代开始时调用 inject_task_notifications()，
这样 LLM 就能看到子 Agent 的执行结果。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mewcode.conversation import ConversationManager

if TYPE_CHECKING:
    from mewcode.agents.task_manager import BackgroundTask

# 通知中结果的最大长度（超过则截断）
MAX_NOTIFICATION_RESULT_LENGTH = 5000


def format_task_notification(task: BackgroundTask) -> str:
    """
    将后台任务格式化为 XML 标签包裹的通知消息。
    
    格式示例：
        <task-notification>
        Task ID: abc123
        Agent: code-reviewer
        Status: completed
        Elapsed: 12.3s
        Tokens: input=5000, output=1200
        Result:
        代码审查完成，发现 2 个问题...
        </task-notification>
    """
    result = task.result
    if len(result) > MAX_NOTIFICATION_RESULT_LENGTH:
        result = result[:MAX_NOTIFICATION_RESULT_LENGTH] + "\n... (truncated)"

    # 计算任务耗时
    elapsed = ""
    if task.end_time is not None:
        secs = task.end_time - task.start_time
        if secs >= 60:
            elapsed = f"{secs / 60:.1f}m"
        else:
            elapsed = f"{secs:.1f}s"

    # 格式化 token 用量
    tokens = ""
    if task.progress.input_tokens or task.progress.output_tokens:
        tokens = (
            f"\nTokens: input={task.progress.input_tokens}, "
            f"output={task.progress.output_tokens}"
        )

    return (
        f"<task-notification>\n"
        f"Task ID: {task.id}\n"
        f"Agent: {task.name}\n"
        f"Status: {task.status}\n"
        f"Elapsed: {elapsed}\n"
        f"{tokens}\n"
        f"Result:\n{result}\n"
        f"</task-notification>"
    )


def inject_task_notifications(
    conversation: ConversationManager,
    completed_tasks: list[BackgroundTask],
) -> None:
    """
    将已完成任务的通知注入到对话中。
    
    主 Agent 在每轮迭代开始时调用此函数，
    这样 LLM 就能看到子 Agent 的执行结果并继续工作。
    """
    for task in completed_tasks:
        notification = format_task_notification(task)
        conversation.add_user_message(notification)

