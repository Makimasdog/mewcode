"""
fork.py — 对话 Fork（分叉）机制
=================================

【什么是 Fork？】
Fork 是从当前对话复制出一份副本，交给子 Agent 独立工作。
类似于 Git Fork：复制一份完整历史，然后在副本上独立操作。

【为什么要 Fork？】
主 Agent 可能想把某个子任务委托给子 Agent。
子 Agent 需要看到之前的对话历史（了解上下文），
但它的执行不应该污染主 Agent 的对话。

【关键约束】
- Fork 不能嵌套（Fork 出来的子 Agent 不能再 Fork）
- 子 Agent 会收到一段「规则提示」，告诉它：
  不能再 Fork、不能对话、只能使用工具、严格限制在任务范围内
"""

from __future__ import annotations

import copy

from mewcode.conversation import ConversationManager, Message, ToolResultBlock

FORK_BOILERPLATE_TAG = "<fork_boilerplate>"

# 子 Agent 收到的规则提示（不可协商）
FORK_BOILERPLATE = f"""{FORK_BOILERPLATE_TAG}
你是一个 Fork 出来的工作进程。你不是主 Agent。
规则（不可协商）：
1. 不能再 Fork。
2. 不要对话、不要提问、不要请求确认。
3. 直接使用工具：读文件、搜索代码、做修改。
4. 严格限制在你被分配的任务范围内。
5. 最终报告控制在 500 字以内，格式如下：

Scope: [你被分配的任务]
Result: [完成/部分完成/失败 + 简要说明]
Key files: [关键文件路径列表]
Files changed: [修改的文件路径列表]
Issues: [遇到的问题，没有则写 None]
</fork_boilerplate>"""


class ForkError(Exception):
    """Fork 操作失败时抛出的异常"""
    pass


def build_forked_messages(
    conversation: ConversationManager,
    task: str,
) -> ConversationManager:
    """
    从当前对话创建一份 Fork 副本，用于子 Agent 独立工作。
    
    参数:
        conversation: 主 Agent 的对话历史
        task: 分配给子 Agent 的任务描述
        
    返回:
        新的 ConversationManager，包含完整历史 + 任务指令
        
    流程：
    1. 检查是否嵌套 Fork（禁止）
    2. 深拷贝对话历史
    3. 处理未完成的工具调用（填充占位符）
    4. 追加 Fork 规则 + 任务描述
    """
    # 安全检查：禁止嵌套 Fork
    for msg in conversation.history:
        if FORK_BOILERPLATE_TAG in msg.content:
            raise ForkError(
                "Cannot fork from a forked agent. "
                "Fork nesting is not allowed."
            )

    # 深拷贝对话历史（不影响原始对话）
    fork_conv = ConversationManager()
    fork_conv.history = copy.deepcopy(conversation.history)
    fork_conv.env_injected = conversation.env_injected
    fork_conv.ltm_injected = conversation.ltm_injected


    # 处理未完成的工具调用：
    # 如果最后一条助手消息包含工具调用但没有对应结果，
    # 需要填充占位符，否则 LLM API 会报错
    if fork_conv.history:
        last = fork_conv.history[-1]
        if last.role == "assistant" and last.tool_uses:
            existing_result_ids = set()
            if len(fork_conv.history) >= 2:
                candidate = fork_conv.history[-1]
                if candidate.tool_results:
                    existing_result_ids = {
                        tr.tool_use_id for tr in candidate.tool_results
                    }

            # 找出没有结果的工具调用
            pending = [
                tu
                for tu in last.tool_uses
                if tu.tool_use_id not in existing_result_ids
            ]
            if pending:
                # 为未完成的工具调用填充 "interrupted" 占位符
                placeholders = [
                    ToolResultBlock(
                        tool_use_id=tu.tool_use_id,
                        content="interrupted",
                        is_error=False,
                    )
                    for tu in pending
                ]
                fork_conv.history.append(
                    Message(
                        role="user",
                        content="",
                        tool_results=placeholders,
                    )
                )

    # 追加 Fork 规则 + 任务描述作为最后一条用户消息
    fork_conv.add_user_message(f"{FORK_BOILERPLATE}\n\n你的任务：\n{task}")
    return fork_conv

