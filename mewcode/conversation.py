
"""
conversation.py — 对话管理器（Agent 的记忆中枢）
=============================================================

【这个模块做什么】
管理 Agent 与 LLM 之间的对话历史，包括：
- 消息数据结构（Message、ToolUseBlock、ToolResultBlock、ThinkingBlock）
- Token 用量估算（基于字符数 + API 真实锚点）
- 上下文注入（环境信息、长期记忆、指令）
- 对话历史替换（压缩后重建）

【核心概念：用量锚点机制】
直接对全部消息做字符估算是不准的，因为不同 API 的 token 化方式不同。
解决方案：每次 API 响应后，用真实的 token 数「锚定」当前位置，
后续只对新增的消息做字符估算。这样既利用了 API 的精确数据，
又避免了全量重新计算的开销。

  无锚点时:  全量字符估算  → 粗略但可用
  有锚点时:  真实用量 + 仅估算新增部分  → 精确

【消息结构】
对话历史是一个 Message 列表，每条消息可以是：
- user: 用户输入 / 系统提醒 / 工具结果
- assistant: LLM 回复（可包含工具调用和思维块）

【对外接口】
- ConversationManager: 对话管理器核心类
- Message / ToolUseBlock / ToolResultBlock / ThinkingBlock: 消息数据结构
- estimate_tokens(): 粗略 token 估算函数
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# 消息块数据结构
# 消息块是 Message 的组成部分，类似于乐高积木的「零件」
# ---------------------------------------------------------------------------

@dataclass
class ToolUseBlock:
    """
    工具调用块 — 表示 LLM 发起的一次工具调用。
    
    当 LLM 决定使用工具时，会在回复中生成一个 ToolUseBlock，
    Agent 引擎执行工具后，将结果作为 ToolResultBlock 回传。
    """
    tool_use_id: str          # 工具调用唯一 ID（用于匹配结果）
    tool_name: str            # 工具名称（如 "ReadFile"、"Bash"）
    arguments: dict[str, Any] # 工具参数（LLM 生成的 JSON）


@dataclass
class ToolResultBlock:
    """
    工具结果块 — 工具执行后的返回结果。
    
    通过 tool_use_id 与对应的 ToolUseBlock 配对。
    """
    tool_use_id: str    # 对应的工具调用 ID
    content: str        # 结果内容（给 LLM 看）
    is_error: bool = False  # 是否为错误结果


@dataclass
class ThinkingBlock:
    """
    思维块 — LLM 的内部推理过程（extended thinking）。
    
    通常不显示给用户，但会保留在对话历史中。
    signature 用于 API 验证（防止思维内容被篡改）。
    """
    thinking: str       # 思维内容
    signature: str      # API 签名


@dataclass
class Message:
    """
    消息 — 对话历史的基本单元。
    
    一条消息可以是：
    - 用户输入: role="user", content="..."
    - 助手回复: role="assistant", content="...", tool_uses=[...]
    - 工具结果: role="user", tool_results=[...]
    - 系统提醒: role="user", content="<system-reminder>..."
    """
    role: str  # "user" | "assistant"
    content: str
    tool_uses: list[ToolUseBlock] = field(default_factory=list)       # 工具调用列表
    tool_results: list[ToolResultBlock] = field(default_factory=list) # 工具结果列表
    thinking_blocks: list[ThinkingBlock] = field(default_factory=list) # 思维块列表


# ---------------------------------------------------------------------------
# Token 估算
# ---------------------------------------------------------------------------

# 字符/token 比率（粗略估算用）
# 与 context.manager 中的恢复状态启发值保持一致，全代码库统一使用同一比率。
_CHARS_PER_TOKEN = 3.5


def _message_chars(m: Message) -> int:
    """
    计算单条消息的字符数（用于 token 估算）。
    
    统计范围：消息正文 + thinking + 工具调用参数 + 工具结果内容。
    """
    n = len(m.content)
    for tb in m.thinking_blocks:
        n += len(tb.thinking)
    for tu in m.tool_uses:
        n += len(tu.tool_name) + len(json.dumps(tu.arguments, ensure_ascii=False))
    for tr in m.tool_results:
        n += len(tr.content)
    return n


def estimate_tokens(messages: list[Message]) -> int:
    """
    基于字符数对消息列表做粗略 token 估算。
    
    刻意做得粗略——它只覆盖那些尚未锚定到真实 API 用量数值的消息，
    这部分的精确度本就无关紧要。
    """
    total = sum(_message_chars(m) for m in messages)
    return int(total / _CHARS_PER_TOKEN)


# ---------------------------------------------------------------------------
# 对话管理器
# ---------------------------------------------------------------------------

@dataclass
class ConversationManager:
    """
    对话管理器 — Agent 的记忆中枢。
    
    职责：
    1. 管理对话历史（消息列表）
    2. 估算当前 token 用量（锚点机制）
    3. 注入上下文（环境信息、长期记忆、指令）
    4. 支持历史替换（压缩后重建）
    
    核心设计：用量锚点机制
    ┌─────────────────────────────────────────────────┐
    │  API 响应后:  record_usage_anchor()  钉下锚点  │
    │  查询用量时:  baseline + 仅估算新增消息        │
    │  压缩后:      replace_history()  重置锚点      │
    └─────────────────────────────────────────────────┘
    """
    history: list[Message] = field(default_factory=list)  # 对话历史
    env_injected: bool = field(default=False, init=False)  # 环境信息是否已注入
    ltm_injected: bool = field(default=False, init=False)  # 长期记忆是否已注入
    # API 报告的每轮真实 prompt 大小，保留用于向后兼容。
    # 现在与 baseline_tokens 一致（input + cache_read + cache_creation + output）。
    last_input_tokens: int = field(default=0, init=False)
    # 真实用量锚点。baseline_tokens 是上一轮 API 计费的完整 prompt+output 大小；
    # anchor_count 是记录该数值时的消息数量。两者配合让 current_tokens() 在
    # anchor_count 以内信任 API 数据，只对之后追加的消息做字符估算。
    # baseline_tokens == 0 表示"尚无锚点"（冷启动），此时退化为纯字符估算。
    baseline_tokens: int = field(default=0, init=False)
    anchor_count: int = field(default=0, init=False)

    def record_usage_anchor(
        self,
        input_tokens: int,
        output_tokens: int = 0,
        cache_read: int = 0,
        cache_creation: int = 0,
    ) -> None:
        """
        钉下真实用量锚点。
        
        每次 API 响应后调用，将真实的 token 用量记录为基准。
        baseline = input + cache_read + cache_creation + output
        
        为什么加上 output？因为 assistant 的回复此刻已成为历史的一部分，
        下次请求时它会作为 prompt 的一部分发送。
        """
        self.baseline_tokens = (
            input_tokens + cache_read + cache_creation + output_tokens
        )
        self.anchor_count = len(self.history)
        # 保持旧字段同步，兼容仍在使用它的读取方。
        self.last_input_tokens = self.baseline_tokens

    def current_tokens(self) -> int:
        """
        估算当前对话的 token 用量。
        
        策略：
        - 有锚点: baseline（真实用量）+ 仅估算锚点之后新增的消息
        - 无锚点: 对整个历史做字符估算（冷启动或压缩后）
        
        这是上下文窗口管理的核心——Agent 需要知道何时该压缩对话。
        """
        if self.baseline_tokens <= 0:
            return estimate_tokens(self.history)
        tail = self.history[self.anchor_count:]
        return self.baseline_tokens + estimate_tokens(tail)

    # -----------------------------------------------------------------------
    # 消息添加方法
    # -----------------------------------------------------------------------

    def add_user_message(self, content: str) -> None:
        """添加用户消息"""
        self.history.append(Message(role="user", content=content))

    def add_assistant_message(
        self,
        content: str,
        tool_uses: list[ToolUseBlock] | None = None,
        thinking_blocks: list[ThinkingBlock] | None = None,
    ) -> None:
        """添加助手回复（可包含工具调用和思维块）"""
        self.history.append(
            Message(
                role="assistant",
                content=content,
                tool_uses=tool_uses or [],
                thinking_blocks=thinking_blocks or [],
            )
        )

    def add_system_reminder(self, content: str) -> None:
        """
        添加系统提醒（以 user 消息形式注入，用 <system-reminder> 标签包裹）。
        
        用于向 Agent 注入运行时信息（如记忆召回结果、团队消息等）。
        """
        self.history.append(
            Message(
                role="user",
                content=f"<system-reminder>\n{content}\n</system-reminder>",
            )
        )

    def add_tool_results_message(self, tool_results: list[ToolResultBlock]) -> None:
        """
        添加工具结果消息。
        
        工具执行完成后，将所有结果打包为一条 user 消息发送给 LLM。
        """
        self.history.append(
            Message(role="user", content="", tool_results=tool_results)
        )


    # -----------------------------------------------------------------------
    # 上下文注入方法
    # 在对话开始时，将环境信息和长期记忆注入到历史头部
    # -----------------------------------------------------------------------

    def inject_environment(self, context: str) -> None:
        """
        注入环境上下文到历史头部。
        
        环境信息包括：操作系统、工作目录、Shell 类型等。
        只注入一次（env_injected 标记防止重复）。
        """
        if not self.env_injected:
            self.history.insert(0, Message(role="user", content=context))
            self.env_injected = True

    def inject_long_term_memory(
        self, instructions: str, memories: str
    ) -> None:
        """
        注入长期记忆和项目指令到历史头部。
        
        注入内容包括：
        - MEWCODE.md 项目指令（覆盖默认行为）
        - 自动提取的记忆（用户偏好、项目知识等）
        - 当前日期
        
        注入位置：环境信息之后（如果已注入），否则历史头部。
        只注入一次（ltm_injected 标记防止重复）。
        """
        if self.ltm_injected:
            return
        sections: list[str] = []
        if instructions:
            sections.append(
                "# mewcodeMd\n"
                "Codebase and user instructions are shown below. "
                "Be sure to adhere to these instructions. "
                "IMPORTANT: These instructions OVERRIDE any default behavior "
                "and you MUST follow them exactly as written.\n\n" + instructions
            )
        if memories:
            sections.append("# autoMemory\n" + memories)
        if not sections:
            return
        from datetime import date

        sections.append(f"# currentDate\nToday's date is {date.today().isoformat()}.")
        body = "\n\n".join(sections)
        wrapped = (
            "<system-reminder>\n"
            "As you answer the user's questions, you can use the following context:\n"
            + body
            + "\n\n      IMPORTANT: this context may or may not be relevant to your tasks."
            " You should not respond to this context unless it is highly relevant to your task.\n"
            "</system-reminder>"
        )
        pos = 1 if self.env_injected else 0
        self.history.insert(pos, Message(role="user", content=wrapped))
        self.ltm_injected = True

    def replace_history(self, new_messages: list[Message]) -> None:
        """
        替换整个对话历史（压缩后调用）。
        
        压缩（compact）会将长对话摘要为短消息，
        此时旧的用量锚点已失效，需要重置。
        重置后 current_tokens() 退化为纯字符估算，
        直到下次 API 响应建立新锚点。
        """
        self.history = new_messages
        self.env_injected = False
        self.ltm_injected = False
        # 旧的用量锚点描述的是压缩前的对话记录，这里清除它，
        # 使 current_tokens() 退化为字符估算，直到下次 API 响应
        # 基于摘要后的历史重新建立锚点。
        self.baseline_tokens = 0
        self.anchor_count = 0
        self.last_input_tokens = 0


    def get_messages(self) -> list[Message]:
        """获取对话历史的副本（浅拷贝）"""
        return list(self.history)
