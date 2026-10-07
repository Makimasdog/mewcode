"""
agent.py — MewCode 的核心引擎（Agent 主循环）
=============================================

【这个文件做了什么】
这是整个 MewCode 项目最核心的文件，实现了 AI Agent 的「思考-行动-观察」循环。
简单来说，Agent 的工作方式如下：

    1. 把用户的对话历史 + 系统提示词 发送给 LLM（大语言模型）
    2. LLM 返回两种内容：
       - 文本回复（直接给用户看的）
       - 工具调用请求（比如要执行 Bash 命令、读写文件等）
    3. 如果有工具调用 → 执行工具 → 把结果追加到对话历史 → 回到步骤 1
    4. 如果没有工具调用 → 说明 LLM 认为任务完成 → 退出循环

这个循环叫做 "Agent Loop"（智能体循环），是所有 AI Agent 系统的核心模式。

【文件结构总览】
- 事件类型定义（StreamText, ToolUseEvent 等）：Agent 循环中产生的各种事件
- StreamCollector：收集 LLM 流式响应的收集器
- partition_tool_calls + StreamingExecutor：工具调用的批量/并行执行
- Agent 类：核心主循环，串联 LLM 调用、工具执行、权限检查、上下文压缩等

【关键概念】
- Conversation（对话）：存储所有消息的列表，包括用户消息、助手消息、工具结果
- Tool（工具）：Agent 可以调用的能力，如 Bash、ReadFile、WriteFile 等
- Context Window（上下文窗口）：LLM 一次能处理的最大 token 数，超出后需要压缩
- Permission（权限）：某些危险操作（如删除文件）需要用户确认
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, AsyncIterator, Callable

from pydantic import ValidationError

# --- LLM 客户端：负责与 Anthropic/OpenAI 等模型 API 通信 ---
from mewcode.client import LLMClient
# --- 上下文管理：处理对话压缩、token 预算、内容替换等 ---
from mewcode.context import (
    CompactBoundary,
    CompactCircuitBreaker,
    CompactEvent,
    ContentReplacementRecord,
    ContentReplacementState,
    RecoveryState,
    append_replacement_records,
    apply_tool_result_budget,
    auto_compact,
    create_replacement_state,
    ensure_session_dir,
    load_replacement_records,
    reconstruct_replacement_state,
)
# --- 对话管理：维护消息历史，包括文本消息和工具调用/结果 ---
from mewcode.conversation import ConversationManager, ToolResultBlock, ToolUseBlock
from mewcode.conversation import ThinkingBlock as ConvThinkingBlock
# --- 记忆系统：自动从对话中提取和持久化用户偏好/项目知识 ---
from mewcode.memory.auto_memory import MemoryManager
# --- 权限系统：控制哪些工具可以直接执行、哪些需要用户确认 ---
from mewcode.permissions import (
    Decision,
    PermissionChecker,
    PermissionMode,
)
# --- Hook 引擎：在特定时机（如工具执行前后）运行自定义脚本 ---
from mewcode.hooks import HookContext, HookEngine, ToolRejectedError
from mewcode.hooks.engine import HookNotification
# --- Prompt 构建：生成发送给 LLM 的系统提示词 ---
from mewcode.prompts import build_environment_context, build_plan_mode_reminder, build_system_prompt
# --- 工具注册表：管理所有可用工具的注册、查询和 schema 生成 ---
from mewcode.tools import ToolRegistry
# --- 工具基础类型：定义了工具执行过程中的各种流式事件 ---
from mewcode.tools.base import (
    MAX_OUTPUT_CHARS,
    StreamEnd,
    StreamEvent,
    TextDelta,
    ThinkingComplete,
    ThinkingDelta,
    ToolCallComplete,
    ToolCallDelta,
    ToolCallStart,
    ToolResult,
)

log = logging.getLogger(__name__)

# ==================== 全局常量 ====================
# 每隔多少轮对话自动提取记忆（用户偏好、项目知识等）
MEMORY_EXTRACTION_INTERVAL = 5
# 当 LLM 输出达到 token 上限时，第一次自动提升到此值（64000 tokens）
MAX_TOKENS_CEILING = 64000
# 提升后仍然超限，最多再恢复几次（防止无限循环）
MAX_OUTPUT_TOKENS_RECOVERIES = 3
MAX_IDENTICAL_TOOL_ATTEMPTS = 2


def _tool_error_category(output: str) -> str:
    """Classify common tool failures for the runtime UI and Agent feedback."""
    value = output.lower()
    if "permission denied" in value or "permission" in value and "denied" in value:
        return "permission"
    if "validation error" in value or "invalid parameter" in value:
        return "validation"
    if any(token in value for token in ("timeout", "timed out", "rate limit", "429", "connection", "network")):
        return "transient"
    return "execution"


# ---------------------------------------------------------------------------
# AgentEvent 事件类型
# ---------------------------------------------------------------------------
# 【什么是 AgentEvent？】
# Agent 在运行过程中会产生各种事件，UI 层通过监听这些事件来展示进度。
# 这是一种「事件驱动」的设计模式——Agent 核心循环不直接操作 UI，
# 而是通过 yield 事件来通知 UI 层发生了什么。
#
# 例如：
#   - LLM 正在生成文字 → yield StreamText
#   - LLM 要调用工具 → yield ToolUseEvent
#   - 工具执行完毕 → yield ToolResultEvent
#   - 一轮结束 → yield TurnComplete
# ---------------------------------------------------------------------------

# --- 文本流式事件：LLM 正在生成文字，一小段一小段地输出 ---
@dataclass
class StreamText:
    text: str


# --- 思考过程事件：部分 LLM（如 Claude）支持「扩展思考」，展示推理过程 ---
@dataclass
class ThinkingText:
    text: str


# --- 重试事件：当 LLM 输出被截断或出错，Agent 会自动重试 ---
@dataclass
class RetryEvent:
    reason: str
    wait: float = 0.0


# --- 工具调用事件：LLM 请求调用某个工具（如 Bash、ReadFile）---
@dataclass
class ToolUseEvent:
    tool_name: str      # 工具名称，如 "Bash", "ReadFile"
    tool_id: str        # 唯一标识符，用于将工具结果与请求匹配
    arguments: dict[str, Any]  # 工具参数，如 {"command": "ls -la"}


# --- 工具结果事件：工具执行完毕，返回结果 ---
@dataclass
class ToolResultEvent:
    tool_id: str
    tool_name: str
    output: str         # 工具输出内容
    is_error: bool      # 是否执行出错
    elapsed: float      # 执行耗时（秒）


# --- 轮次完成事件：一次「LLM调用 + 工具执行」算一轮 ---
@dataclass
class TurnComplete:
    turn: int


# --- 循环完成事件：整个 Agent 循环结束 ---
@dataclass
class LoopComplete:
    total_turns: int


# --- Token 用量事件：累计消耗的输入/输出 token 数 ---
@dataclass
class UsageEvent:
    input_tokens: int
    output_tokens: int


# --- 错误事件：发生了不可恢复的错误 ---
@dataclass
class ErrorEvent:
    message: str


# --- 上下文压缩通知：对话太长，自动压缩后的通知 ---
@dataclass
class CompactNotification:
    before_tokens: int  # 压缩前的 token 数
    message: str
    # 结构化 boundary（摘要 + 原文保留尾部），UI/session 层用它持久化 compact_boundary 记录。
    # 失败路径下为 None。
    boundary: "CompactBoundary | None" = None


# --- Hook 事件：生命周期钩子执行后的通知 ---
@dataclass
class HookEvent:
    hook_id: str
    event: str
    output: str
    success: bool


# --- 权限响应枚举：用户对权限请求的三种可能回应 ---
class PermissionResponse(Enum):
    ALLOW = "allow"           # 允许这一次
    DENY = "deny"             # 拒绝这一次
    ALLOW_ALWAYS = "allow_always"  # 永远允许此类操作


# --- 权限请求事件：当 Agent 要执行危险操作时，向 UI 发送请求 ---
@dataclass
class PermissionRequest:
    tool_name: str            # 要调用的工具名
    description: str          # 操作描述（如命令内容、文件路径）
    future: asyncio.Future[PermissionResponse]  # 异步等待用户的决定


# AgentEvent 是所有事件的联合类型（Type Union）
# 在 Python 中用 | 语法表示「这些类型中的任意一种」
AgentEvent = (
    StreamText
    | ThinkingText
    | RetryEvent
    | ToolUseEvent
    | ToolResultEvent
    | TurnComplete
    | LoopComplete
    | UsageEvent
    | ErrorEvent
    | PermissionRequest
    | CompactNotification
    | HookEvent
)


# ---------------------------------------------------------------------------
# LLM 响应收集器
# ---------------------------------------------------------------------------
# 【什么是 StreamCollector？】
# LLM 的响应是「流式」的——不是一次性返回所有内容，而是像打字机一样
# 一小段一小段地发送。StreamCollector 负赉把这些碎片收集起来，拼成完整的响应。
#
# 同时，它会把流式事件「转发」给 UI 层，让用户能实时看到 LLM 的输出。
# ---------------------------------------------------------------------------

@dataclass
class ThinkingBlock:
    thinking: str
    signature: str  # 用于验证思考过程的完整性


# LLM 响应的完整结构，包含文本、工具调用、思考过程和 token 用量
@dataclass
class LLMResponse:
    text: str = ""                                    # LLM 的文本回复
    tool_calls: list[ToolCallComplete] = field(default_factory=list)  # 工具调用请求列表
    thinking_blocks: list[ThinkingBlock] = field(default_factory=list)  # 思考过程块
    stop_reason: str = ""                             # 停止原因（如 "end_turn", "max_tokens"）
    input_tokens: int = 0                             # 输入消耗的 token 数
    output_tokens: int = 0                            # 输出消耗的 token 数
    cache_read: int = 0                               # 从缓存读取的 token 数（省钱！）
    cache_creation: int = 0                           # 创建缓存的 token 数


class StreamCollector:
    """流式响应收集器：把 LLM 的流式输出收集成完整的 LLMResponse，同时转发事件给 UI"""
    def __init__(self) -> None:
        self.response = LLMResponse()

    async def consume(
        self, stream: AsyncIterator[StreamEvent]
    ) -> AsyncIterator[AgentEvent]:
        """
        消费 LLM 流式事件，做两件事：
        1. 将内容累积到 self.response（给 Agent 用）
        2. yield 事件给调用方（给 UI 展示用）
        """
        async for event in stream:
            if isinstance(event, TextDelta):
                # 文本片段：拼接到完整文本，同时转发给 UI
                self.response.text += event.text
                yield StreamText(text=event.text)
            elif isinstance(event, ThinkingDelta):
                # 思考过程片段：只转发给 UI 展示
                yield ThinkingText(text=event.text)
            elif isinstance(event, ThinkingComplete):
                # 思考过程完成：保存完整的思考块
                self.response.thinking_blocks.append(
                    ThinkingBlock(thinking=event.thinking, signature=event.signature)
                )
            elif isinstance(event, ToolCallStart):
                # 工具调用开始（流式传输的中间状态，这里不需要处理）
                pass
            elif isinstance(event, ToolCallDelta):
                # 工具调用参数增量（流式传输中，参数一点点发过来）
                pass
            elif isinstance(event, ToolCallComplete):
                # 工具调用完成：参数已完整收集，记录并通知 UI
                self.response.tool_calls.append(event)
                yield ToolUseEvent(
                    tool_name=event.tool_name,
                    tool_id=event.tool_id,
                    arguments=event.arguments,
                )
            elif isinstance(event, StreamEnd):
                # 流结束：记录停止原因和 token 用量
                self.response.stop_reason = event.stop_reason
                self.response.input_tokens = event.input_tokens
                self.response.output_tokens = event.output_tokens
                self.response.cache_read = event.cache_read
                self.response.cache_creation = event.cache_creation


# ---------------------------------------------------------------------------
# tool 批量执行
# ---------------------------------------------------------------------------
# 【为什么需要批量执行？】
# LLM 可能一次返回多个工具调用请求。例如：
#   LLM: “我要同时读取 3 个文件” → [ReadFile(a.py), ReadFile(b.py), ReadFile(c.py)]
#
# 这 3 个读取操作互不依赖，可以「并行」执行以提高效率。
# 但有些操作（如 Bash 命令）必须「串行」执行，因为它们可能修改状态。
#
# partition_tool_calls 函数就是把工具调用列表分成多个「批次」：
# - 安全的工具（只读操作）→ 合并到一个并行批次
# - 不安全的工具（写操作）→ 单独成一个串行批次
# ---------------------------------------------------------------------------

@dataclass
class ToolBatch:
    concurrent: bool              # 是否可以并行执行
    calls: list[ToolCallComplete] # 这一批包含的工具调用


def partition_tool_calls(
    tool_calls: list[ToolCallComplete],
    registry: ToolRegistry,
) -> list[ToolBatch]:
    """
    将工具调用列表切分为多个批次。
    规则：相邻的「并发安全」工具合并为一个批次，其他工具单独成批次。
    """
    batches: list[ToolBatch] = []
    for tc in tool_calls:
        tool = registry.get(tc.tool_name)
        # 判断这个工具是否标记为「并发安全」（通常是只读操作，如 ReadFile、Grep）
        safe = tool is not None and tool.is_concurrency_safe and registry.is_enabled(tc.tool_name)

        # 如果当前工具安全，且上一个批次也是并行的，就合并进去
        if safe and batches and batches[-1].concurrent:
            batches[-1].calls.append(tc)
        else:
            # 否则新建一个批次
            batches.append(ToolBatch(concurrent=safe, calls=[tc]))
    return batches


# ---------------------------------------------------------------------------
# streaming 执行器 — 异步工具执行器
# ---------------------------------------------------------------------------
# 【StreamingExecutor 的作用】
# 当多个工具需要并行执行时，StreamingExecutor 负责：
# 1. 把每个工具执行任务包装成 asyncio.Task（异步任务）
# 2. 等待所有任务完成
# 3. 按提交顺序收集结果
# ---------------------------------------------------------------------------

@dataclass
class _ToolExecResult:
    """单个工具执行的结果包装类"""
    tool_id: str
    tool_name: str
    result: ToolResult   # 工具执行结果
    elapsed: float       # 执行耗时
    is_unknown: bool     # 是否是不认识的工具（连续调用未知工具会触发安全终止）


class StreamingExecutor:
    """异步工具执行器：管理多个工具的并行执行和结果收集"""
    def __init__(self) -> None:
        self._tasks: list[tuple[int, asyncio.Task[_ToolExecResult]]] = []  # (序号, 任务)
        self._order = 0  # 提交序号，用于保持结果顺序

    def submit(
        self,
        coro: Any,
    ) -> None:
        """提交一个异步工具执行任务"""
        task = asyncio.create_task(coro)
        self._tasks.append((self._order, task))
        self._order += 1

    async def collect_results(self) -> list[_ToolExecResult]:
        """等待所有任务完成，按提交顺序返回结果"""
        if not self._tasks:
            return []
        # 按提交序号排序，保证结果顺序与提交顺序一致
        tasks = [t for _, t in sorted(self._tasks, key=lambda x: x[0])]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        out: list[_ToolExecResult] = []
        for r in results:
            if isinstance(r, Exception):
                out.append(_ToolExecResult(
                    tool_id="",
                    tool_name="",
                    result=ToolResult(output=f"Tool execution error: {r}", is_error=True),
                    elapsed=0.0,
                    is_unknown=False,
                ))
            else:
                out.append(r)
        return out


# ---------------------------------------------------------------------------
# Agent 主循环
# ---------------------------------------------------------------------------
# 【Agent 类是整个文件的核心】
# 它把 LLM 客户端、工具注册表、权限检查、上下文管理等组件串联起来，
# 实现完整的「思考-行动-观察」循环。
#
# 初始化时需要注入以下依赖：
# - client: LLM 客户端，负责与模型 API 通信
# - registry: 工具注册表，管理所有可用工具
# - permission_checker: 权限检查器，控制危险操作
# - memory_manager: 记忆管理器，自动提取和持久化记忆
# - hook_engine: Hook 引擎，在特定时机运行自定义脚本
# ---------------------------------------------------------------------------

class Agent:
    """
    AI Agent 核心引擎。

    工作流程：
    1. 构建系统提示词 + 对话历史
    2. 发送给 LLM 获取响应
    3. 如果 LLM 返回工具调用 → 执行工具 → 把结果加入对话 → 回到 2
    4. 如果 LLM 返回纯文本 → 任务完成，退出循环
    """
    def __init__(
        self,
        client: LLMClient,              # LLM 客户端，与模型 API 通信
        registry: ToolRegistry,         # 工具注册表，管理所有可用工具
        protocol: str,                  # 协议类型："anthropic" 或 "openai"
        work_dir: str = ".",            # 工作目录，Agent 在此目录下执行操作
        max_iterations: int = 50,       # 最大循环次数，防止无限循环
        permission_checker: PermissionChecker | None = None,  # 权限检查器
        context_window: int = 200_000,  # 上下文窗口大小（token 数）
        instructions_content: str = "", # 用户自定义指令（会加入系统提示词）
        memory_manager: MemoryManager | None = None,  # 记忆管理器
        hook_engine: HookEngine | None = None,        # Hook 引擎
    ) -> None:
        # --- 核心依赖 ---
        self.client = client
        self.registry = registry
        self.protocol = protocol
        self.work_dir = work_dir
        self.max_iterations = max_iterations

        # --- 权限系统 ---
        self.permission_checker = permission_checker
        self.permission_mode: PermissionMode = (
            permission_checker.mode if permission_checker else PermissionMode.DEFAULT
        )

        # --- 上下文管理 ---
        self.context_window = context_window
        self.session_dir = ensure_session_dir(work_dir)  # 会话文件存储目录
        self.compact_breaker = CompactCircuitBreaker()   # 压缩操作的熔断器（防止频繁压缩）
        self.replacement_state: ContentReplacementState = create_replacement_state()
        # 恢复状态：保存最近的文件读取内容，用于压缩后恢复上下文
        self.recovery_state: RecoveryState = RecoveryState()

        # --- Token 用量统计 ---
        self.total_input_tokens = 0
        self.total_output_tokens = 0

        # --- 记忆与 Hook ---
        self.instructions_content = instructions_content
        self.memory_manager = memory_manager
        self.hook_engine = hook_engine

        # --- 内部状态 ---
        self._loop_count = 0           # 循环计数器，用于触发定期记忆提取
        self._extracting = False       # 是否正在提取记忆（防止重复提取）
        self.session_id: str = ""      # 当前会话 ID

        # --- 技能系统 ---
        self.active_skills: dict[str, str] = {}  # 当前激活的技能 {名称: 内容}
        self._skill_catalog: str = ""            # 可用技能目录（告诉 LLM 有哪些技能）

        # --- 子 Agent / 团队协作 ---
        self._agent_catalog: str = ""            # 可用子 Agent 目录
        self._agent_catalog_list: list[tuple[str, str]] = []
        self.agent_id: str = uuid.uuid4().hex[:12]  # 唯一 Agent ID
        self.parent_id: str | None = None           # 父 Agent ID（用于追踪调用链）
        self.trace_id: str | None = None            # 追踪 ID
        self.coordinator_mode: bool = False         # 是否启用协调者模式
        self.team_name: str = ""                    # 所属团队名称
        self._team_manager: Any = None              # 团队管理器
        self.notification_fn: Callable[[], list[str]] | None = None  # 通知回调
        self.file_history: Any = None               # 文件历史记录器
        self.cancel_event = asyncio.Event()

    def cancel(self) -> None:
        """Request cooperative cancellation before the runtime cancels its task."""
        self.cancel_event.set()

    def _raise_if_cancelled(self) -> None:
        if self.cancel_event.is_set():
            raise asyncio.CancelledError

    @property
    def _transcript_path(self) -> str:
        if self.session_id:
            return str(Path(self.work_dir) / ".mewcode" / "sessions" / f"{self.session_id}.jsonl")
        return ""

    @property
    def plan_mode(self) -> bool:
        return self.permission_mode == PermissionMode.PLAN

    _plan_path_cache: Path | None = None

    def _get_plan_path(self) -> Path:
        if self._plan_path_cache is not None:
            return self._plan_path_cache
        import random
        import datetime
        _ADJECTIVES = ["bold", "bright", "calm", "cool", "deep", "fair", "fast", "fine",
                       "glad", "keen", "kind", "lean", "mild", "neat", "pure", "safe",
                       "slim", "soft", "tall", "warm", "wise", "grand", "swift", "vivid"]
        _NOUNS = ["sketch", "draft", "spark", "bloom", "trail", "ridge", "creek", "grove",
                  "cliff", "cloud", "field", "forge", "frost", "haven", "pearl", "stone",
                  "storm", "river", "tower", "delta", "flame", "orbit", "pulse", "shore"]
        plans_dir = Path(self.work_dir) / ".mewcode" / "plans"
        plans_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.datetime.now().strftime("%m%d-%H%M")
        slug = f"{random.choice(_ADJECTIVES)}-{random.choice(_NOUNS)}-{ts}"
        self._plan_path_cache = plans_dir / f"{slug}.md"
        return self._plan_path_cache

    def set_permission_mode(self, mode: PermissionMode) -> None:
        self.permission_mode = mode
        if self.permission_checker:
            self.permission_checker.mode = mode

    def activate_skill(self, name: str, prompt_body: str) -> None:
        self.active_skills[name] = prompt_body

    def clear_active_skills(self) -> None:
        self.active_skills.clear()

    def set_skill_catalog(self, catalog: str) -> None:
        self._skill_catalog = catalog

    def set_agent_catalog(self, catalog: str, catalog_list: list[tuple[str, str]] | None = None) -> None:
        self._agent_catalog = catalog
        if catalog_list is not None:
            self._agent_catalog_list = catalog_list

    def _build_hook_context(self, event: str, **kwargs: str | dict) -> HookContext:
        return HookContext(
            event_name=event,
            tool_name=str(kwargs.get("tool_name", "")),
            tool_args=kwargs.get("tool_args", {}),
            file_path=str(kwargs.get("file_path", "")),
            message=str(kwargs.get("message", "")),
            error=str(kwargs.get("error", "")),
        )

    def _infer_file_path(self, args: dict) -> str:
        return str(args.get("file_path", args.get("path", "")))

    def _drain_hook_events(self) -> list[HookEvent]:
        if not self.hook_engine:
            return []
        return [
            HookEvent(
                hook_id=n.hook_id,
                event=n.event,
                output=n.output,
                success=n.success,
            )
            for n in self.hook_engine.drain_notifications()
        ]

    async def run(self, conversation: ConversationManager) -> AsyncIterator[AgentEvent]:
        """
        Agent 主循环——这是整个 Agent 最核心的方法。

        参数:
            conversation: 对话管理器，存储所有消息历史

        返回:
            异步迭代器，yield 各种 AgentEvent 事件给 UI 层

        工作流程：
        ┌─────────────────────────────────────────────┐
        │  1. 初始化：注入环境信息、记忆、触发 Hook      │
        │  2. 循环开始：                                  │
        │     a. 检查是否超过最大迭代次数               │
        │     b. 自动压缩上下文（如果接近 token 上限）    │
        │     c. 构建系统提示词                         │
        │     d. 调用 LLM，收集流式响应                 │
        │     e. 如果 LLM 返回工具调用：              │
        │        - 检查权限                            │
        │        - 执行工具                            │
        │        - 把结果加入对话历史                    │
        │        - 回到 2                              │
        │     f. 如果 LLM 返回纯文本：任务完成，退出    │
        └─────────────────────────────────────────────┘
        """
        self._current_conversation = conversation

        # ===== 阶段 1：初始化 =====
        # 注入环境信息（工作目录、可用技能等）到对话中
        env_context = build_environment_context(
            self.work_dir, self.active_skills, self._skill_catalog, self._agent_catalog
        )
        conversation.inject_environment(env_context)

        # 注入长期记忆（用户指令 + 已提取的记忆内容）
        memory_content = self.memory_manager.load() if self.memory_manager else ""
        conversation.inject_long_term_memory(self.instructions_content, memory_content)

        # 触发 session_start Hook（如果配置了的话）
        if self.hook_engine:
            ctx = self._build_hook_context("session_start")
            await self.hook_engine.run_hooks("session_start", ctx)
            for he in self._drain_hook_events():
                yield he

        # ===== 阶段 2：主循环 =====
        iteration = 0                    # 当前迭代次数
        consecutive_unknown = 0          # 连续未知工具调用次数（用于安全终止）
        max_tokens_escalated = False     # 是否已经提升过输出 token 上限
        output_recoveries = 0            # 输出超限恢复次数

        while True:
            self._raise_if_cancelled()
            iteration += 1

            # 安全检查：防止无限循环
            if iteration > self.max_iterations:
                yield ErrorEvent(
                    message=f"Agent reached maximum iterations ({self.max_iterations})"
                )
                break

            # 触发 turn_start Hook
            if self.hook_engine:                                    # ① 没配 Hook 引擎就整体跳过（零开销）
                ctx = self._build_hook_context("turn_start")        # ② 构造上下文：event_name="turn_start"，其余字段为空
                await self.hook_engine.run_hooks("turn_start", ctx) # ③ 匹配并执行所有监听此事件的 Hook
                for he in self._drain_hook_events():                # ④ 把执行结果从通知队列取出
                    yield he                                        # ⑤ 转成 HookEvent 推给 UI 展示

            # 消费团队邮箱中的新消息（多 Agent 协作时）
            self._consume_mailbox(conversation)
            # 添加外部通知到对话中
            if self.notification_fn:
                for note in self.notification_fn():
                    conversation.add_system_reminder(note)

            # ===== 步骤 2a：自动压缩上下文 =====
            # 当对话太长、接近 context_window 上限时，自动触发压缩
            # 压缩策略：用 LLM 生成摘要替换早期对话，保留最近的内容
            compact_result = await auto_compact(
                conversation,
                self.client,
                self.context_window,
                self.session_dir,
                protocol=self.protocol,
                breaker=self.compact_breaker,
                recovery=self.recovery_state,
                tool_schemas=self.registry.get_all_schemas(self.protocol),
                transcript_path=self._transcript_path,
            )
            if isinstance(compact_result, CompactEvent):
                # 压缩成功：通知 UI，并重新注入环境信息和记忆
                yield CompactNotification(
                    before_tokens=compact_result.before_tokens,
                    message=f"上下文已压缩（压缩前 {compact_result.before_tokens:,} tokens）",
                    boundary=compact_result.boundary,
                )
                # 压缩会重置对话历史，所以需要重新注入环境信息和记忆
                conversation.inject_environment(env_context)
                mem = self.memory_manager.load() if self.memory_manager else ""
                conversation.inject_long_term_memory(
                    self.instructions_content, mem
                )
            elif isinstance(compact_result, str):
                # 压缩失败，返回错误信息
                yield ErrorEvent(message=compact_result)

            # 触发 pre_send Hook（发送消息前的最后处理机会）
            if self.hook_engine:
                ctx = self._build_hook_context("pre_send")
                await self.hook_engine.run_hooks("pre_send", ctx)
                for he in self._drain_hook_events():
                    yield he

            # ===== 步骤 2b：构建系统提示词 =====
            hook_prompts = (
                self.hook_engine.get_prompt_messages() if self.hook_engine else None
            )
            system = build_system_prompt(
                hook_prompts=hook_prompts,
                coordinator_mode=self.coordinator_mode,
                agent_catalog=self._agent_catalog_list or None,
            )

            # Plan 模式：添加计划文件路径提示
            if self.plan_mode:
                plan_path = str(self._get_plan_path())
                if self.permission_checker:
                    self.permission_checker.plan_file_path = plan_path
                plan_exists = self._get_plan_path().exists()
                plan_reminder = build_plan_mode_reminder(
                    plan_path, plan_exists, iteration
                )
                conversation.add_system_reminder(plan_reminder)

            # 添加 Hook 产生的系统提醒
            if self.hook_engine:
                for note in self.hook_engine.drain_notifications():
                    conversation.add_system_reminder(
                        f"Hook [{note.hook_id}] {note.event}: {note.output}"
                    )

            # 添加「延迟加载工具」的提示（这些工具需要通过 ToolSearch 主动加载）
            deferred_names = self.registry.get_deferred_tool_names()
            if deferred_names:
                conversation.add_system_reminder(
                    "The following deferred tools are available via ToolSearch. "
                    "Their schemas are NOT loaded - use ToolSearch with "
                    'query "select:<name>[,<name>...]" to load tool schemas before calling them:\n'
                    + "\n".join(deferred_names)
                )

            # 获取所有可用工具的 schema（告诉 LLM 有哪些工具可以调用）
            tools = self.registry.get_all_schemas(self.protocol)

            # ===== 步骤 2c：应用工具结果预算 =====
            # 为了节省 token，过长的工具结果会被截断/替换
            # 这里生成最终发送给 LLM 的对话副本
            api_conv, _new_records = apply_tool_result_budget(
                conversation, self.session_dir, self.replacement_state
            )
            if _new_records:
                append_replacement_records(self.session_dir, _new_records)

            # ===== 步骤 2d：调用 LLM，收集流式响应 =====
            collector = StreamCollector()
            # 发起流式请求，LLM 会一小段一小段地返回内容
            llm_stream = self.client.stream(api_conv, system=system, tools=tools)
            # 消费流式事件，同时转发给 UI 层
            async for event in collector.consume(llm_stream):
                yield event

            # 收集完整的响应
            response = collector.response

            # 触发 post_receive Hook（收到响应后的处理）
            if self.hook_engine:
                ctx = self._build_hook_context("post_receive", message=response.text)
                await self.hook_engine.run_hooks("post_receive", ctx)
                for he in self._drain_hook_events():
                    yield he

            # 累计 token 用量并通知 UI
            self.total_input_tokens += response.input_tokens
            self.total_output_tokens += response.output_tokens
            yield UsageEvent(
                input_tokens=self.total_input_tokens,
                output_tokens=self.total_output_tokens,
            )

            # 转换思考块格式（用于对话历史）
            conv_thinking = [
                ConvThinkingBlock(thinking=tb.thinking, signature=tb.signature)
                for tb in response.thinking_blocks
            ]

            # ===== 步骤 2e：处理输出截断情况 =====
            # 如果 LLM 输出被 max_tokens 截断，尝试恢复
            if response.stop_reason == "max_tokens":
                if not max_tokens_escalated:
                    # 第一次截断：提升输出上限，让 LLM 继续
                    self.client.set_max_output_tokens(MAX_TOKENS_CEILING)
                    max_tokens_escalated = True
                    if response.text:
                        conversation.add_assistant_message(
                            response.text, thinking_blocks=conv_thinking
                        )
                        # 告诉 LLM 从截断处继续，不要道歉或重复
                        conversation.add_user_message(
                            "Output token limit hit. Resume directly from where you stopped. "
                            "Do not apologize or repeat previous content. Pick up mid-thought if needed."
                        )
                    yield RetryEvent(reason="max_tokens escalation")
                    continue
                elif output_recoveries < MAX_OUTPUT_TOKENS_RECOVERIES:
                    # 后续截断：有限次数地尝试恢复
                    output_recoveries += 1
                    conversation.add_assistant_message(
                        response.text, thinking_blocks=conv_thinking
                    )
                    conversation.add_user_message(
                        "Output token limit hit. Resume directly from where you stopped. "
                        "Break remaining work into smaller pieces."
                    )
                    yield RetryEvent(
                        reason=f"max_tokens recovery {output_recoveries}/{MAX_OUTPUT_TOKENS_RECOVERIES}"
                    )
                    continue
            else:
                output_recoveries = 0  # 正常结束，重置恢复计数

            # ===== 步骤 2f：检查是否有工具调用 =====
            # 如果没有工具调用，说明 LLM 认为任务完成，退出循环
            if not response.tool_calls:
                conversation.add_assistant_message(
                    response.text, thinking_blocks=conv_thinking
                )
                self._loop_count += 1
                # 定期自动提取记忆（每 MEMORY_EXTRACTION_INTERVAL 轮一次）
                if (
                    self._loop_count % MEMORY_EXTRACTION_INTERVAL == 0
                    and self.memory_manager
                ):
                    asyncio.ensure_future(self._extract_memories(conversation))
                # 触发 turn_end 和 session_end Hook
                if self.hook_engine:
                    ctx = self._build_hook_context("turn_end")
                    await self.hook_engine.run_hooks("turn_end", ctx)
                    ctx = self._build_hook_context("session_end")
                    await self.hook_engine.run_hooks("session_end", ctx)
                    for he in self._drain_hook_events():
                        yield he
                # 创建文件历史快照（用于 Rewind 功能）
                if self.file_history is not None:
                    summary = response.text[:60] + "..." if len(response.text) > 60 else response.text
                    self.file_history.make_snapshot(len(conversation.history), summary)
                yield LoopComplete(total_turns=iteration)
                break

            # ===== 步骤 2g：有工具调用，开始执行 =====
            # 先把 LLM 的回复（包含工具调用请求）加入对话历史
            tool_uses = [
                ToolUseBlock(
                    tool_use_id=tc.tool_id,
                    tool_name=tc.tool_name,
                    arguments=tc.arguments,
                )
                for tc in response.tool_calls
            ]
            conversation.add_assistant_message(
                response.text, tool_uses, thinking_blocks=conv_thinking
            )
            # 记录当前 token 用量「锚点」，用于下一轮压缩估算
            conversation.record_usage_anchor(
                response.input_tokens,
                response.output_tokens,
                response.cache_read,
                response.cache_creation,
            )

            # 将工具调用分批执行（并发安全的工具可以并行）
            tool_results: list[ToolResultBlock] = []
            batches = partition_tool_calls(response.tool_calls, self.registry)

            for batch in batches:
                self._raise_if_cancelled()
                if batch.concurrent and len(batch.calls) > 1:
                    # 并行执行多个工具（如同时读取多个文件）
                    batch_results = await self._execute_batch_parallel(batch.calls)
                    for br in batch_results:
                        if br.is_unknown:
                            consecutive_unknown += 1
                        else:
                            consecutive_unknown = 0
                        # 处理工具输出：过长则持久化到文件，截断显示
                        content = self._maybe_persist_or_truncate(
                            br.tool_id, br.result.output
                        )
                        tool_results.append(
                            ToolResultBlock(
                                tool_use_id=br.tool_id,
                                content=content,
                                is_error=br.result.is_error,
                            )
                        )
                        yield ToolResultEvent(
                            tool_id=br.tool_id,
                            tool_name=br.tool_name,
                            output=br.result.output,
                            is_error=br.result.is_error,
                            elapsed=br.elapsed,
                        )
                else:
                    # 串行执行工具（单个工具或需要串行的工具）
                    for tc in batch.calls:
                        result: ToolResult | None = None
                        elapsed = 0.0
                        is_unknown = False

                        # 触发 pre_tool_use Hook（工具执行前，可以拦截）
                        if self.hook_engine:
                            file_path = self._infer_file_path(tc.arguments)
                            hook_ctx = self._build_hook_context(
                                "pre_tool_use",
                                tool_name=tc.tool_name,
                                tool_args=tc.arguments,
                                file_path=file_path,
                            )
                            rejection = await self.hook_engine.run_pre_tool_hooks(hook_ctx)
                            for he in self._drain_hook_events():
                                yield he
                            # Hook 可以拦截工具执行，返回拒绝原因
                            if rejection is not None:
                                result = ToolResult(
                                    output=f"Hook rejected: {rejection.reason}",
                                    is_error=True,
                                )
                                content = self._maybe_persist_or_truncate(
                                    tc.tool_id, result.output
                                )
                                tool_results.append(
                                    ToolResultBlock(
                                        tool_use_id=tc.tool_id,
                                        content=content,
                                        is_error=True,
                                    )
                                )
                                yield ToolResultEvent(
                                    tool_id=tc.tool_id,
                                    tool_name=tc.tool_name,
                                    output=result.output,
                                    is_error=True,
                                    elapsed=0.0,
                                )
                                continue  # 跳过这个工具，执行下一个

                        # 执行工具（包含权限检查）
                        async for item in self._execute_tool(tc):
                            if isinstance(item, PermissionRequest):
                                # 需要用户确认，转发权限请求给 UI
                                yield item
                            else:
                                result, elapsed, is_unknown = item

                        if result is None:
                            result = ToolResult(output="Error: no result from tool", is_error=True)

                        # 跟踪连续未知工具调用次数（安全机制）
                        if is_unknown:
                            consecutive_unknown += 1
                        else:
                            consecutive_unknown = 0

                        # 触发 post_tool_use Hook（工具执行后）
                        if self.hook_engine:
                            file_path = self._infer_file_path(tc.arguments)
                            hook_ctx = self._build_hook_context(
                                "post_tool_use",
                                tool_name=tc.tool_name,
                                tool_args=tc.arguments,
                                file_path=file_path,
                            )
                            await self.hook_engine.run_hooks("post_tool_use", hook_ctx)
                            for he in self._drain_hook_events():
                                yield he

                        # 处理工具输出并收集结果
                        content = self._maybe_persist_or_truncate(
                            tc.tool_id, result.output
                        )
                        tool_results.append(
                            ToolResultBlock(
                                tool_use_id=tc.tool_id,
                                content=content,
                                is_error=result.is_error,
                            )
                        )
                        yield ToolResultEvent(
                            tool_id=tc.tool_id,
                            tool_name=tc.tool_name,
                            output=result.output,
                            is_error=result.is_error,
                            elapsed=elapsed,
                        )

            # 安全检查：连续 3 次调用未知工具，终止 Agent
            if consecutive_unknown >= 3:
                yield ErrorEvent(
                    message="Agent terminated: too many consecutive unknown tool calls"
                )
                break

            # 检查是否调用了退出计划模式工具
            exit_plan_called = any(
                tc.tool_name == "ExitPlanMode" for tc in response.tool_calls
            )
            # 把所有工具结果加入对话历史，下一轮迭代会发给 LLM
            conversation.add_tool_results_message(tool_results)
            if exit_plan_called:
                yield TurnComplete(turn=iteration)
                yield LoopComplete(total_turns=iteration)
                break

            # 触发 turn_end Hook
            if self.hook_engine:
                ctx = self._build_hook_context("turn_end")
                await self.hook_engine.run_hooks("turn_end", ctx)
                for he in self._drain_hook_events():
                    yield he
            yield TurnComplete(turn=iteration)

    def _consume_mailbox(self, conversation: ConversationManager) -> None:
        if not self.team_name or not self._team_manager:
            return
        try:
            mailbox = self._team_manager.get_mailbox(self.team_name)
            if mailbox is None:
                return
            messages = mailbox.consume(self.agent_id)
            for msg in messages:
                prefix = f"[Message from {msg.from_agent}]"
                if msg.message_type != "text":
                    prefix = f"[{msg.message_type} from {msg.from_agent}]"
                content = f"{prefix} {msg.content}"
                conversation.add_user_message(content)
        except Exception as e:
            log.debug("Mailbox consumption failed: %s", e)

    def _build_permission_description(self, tc: ToolCallComplete) -> str:
        if tc.tool_name == "Bash":
            return tc.arguments.get("command", tc.tool_name)
        if tc.tool_name in ("ReadFile", "WriteFile", "EditFile"):
            return tc.arguments.get("file_path", tc.tool_name)
        return str(tc.arguments)

    async def _execute_single_tool_direct(
        self, tc: ToolCallComplete
    ) -> _ToolExecResult:
        """
        直接执行单个工具（无权限检查）。
        用于并行批次执行，这些工具已经被标记为「并发安全」。
        """
        tool = self.registry.get(tc.tool_name)
        start = time.monotonic()

        # 检查工具是否存在
        if tool is None:
            return _ToolExecResult(
                tool_id=tc.tool_id,
                tool_name=tc.tool_name,
                result=ToolResult(output=f"Error: unknown tool '{tc.tool_name}'", is_error=True),
                elapsed=time.monotonic() - start,
                is_unknown=True,
            )

        # 检查工具是否已启用
        if not self.registry.is_enabled(tc.tool_name):
            return _ToolExecResult(
                tool_id=tc.tool_id,
                tool_name=tc.tool_name,
                result=ToolResult(output=f"Error: tool '{tc.tool_name}' is disabled", is_error=True),
                elapsed=time.monotonic() - start,
                is_unknown=False,
            )

        # 验证参数并执行
        try:
            params = tool.params_model.model_validate(tc.arguments)  # Pydantic 参数验证
            result = await tool.execute(params)
        except ValidationError as e:
            result = ToolResult(output=f"Parameter validation error: {e}", is_error=True)
        except Exception as e:
            result = ToolResult(output=f"Tool execution error: {e}", is_error=True)

        # 为压缩恢复保存快照（如果是 ReadFile）
        self._snapshot_for_recovery(tc, result)

        return _ToolExecResult(
            tool_id=tc.tool_id,
            tool_name=tc.tool_name,
            result=result,
            elapsed=time.monotonic() - start,
            is_unknown=False,
        )


    async def _execute_batch_parallel(
        self, calls: list[ToolCallComplete]
    ) -> list[_ToolExecResult]:
        """并行执行多个工具，使用 asyncio.gather 并发执行"""
        tasks = [self._execute_single_tool_direct(tc) for tc in calls]
        return list(await asyncio.gather(*tasks))

    async def _execute_tool(
        self, tc: ToolCallComplete
    ) -> AsyncIterator[tuple[ToolResult, float, bool]]:
        """
        执行单个工具（带权限检查）。

        这是一个异步生成器，可能会 yield 两种东西：
        1. PermissionRequest：需要用户确认，等待用户决定
        2. (ToolResult, elapsed, is_unknown)：工具执行结果

        工作流程：
        1. 检查工具是否存在、是否启用
        2. 权限检查（可能 yield PermissionRequest 等待用户决定）
        3. 验证参数并执行工具
        4. 返回结果
        """
        tool = self.registry.get(tc.tool_name)
        start = time.monotonic()
        is_unknown = False

        # 检查工具是否存在
        if tool is None:
            result = ToolResult(
                output=f"Error: unknown tool '{tc.tool_name}'", is_error=True
            )
            is_unknown = True
            elapsed = time.monotonic() - start
            yield result, elapsed, is_unknown
            return

        # 检查工具是否已启用
        if not self.registry.is_enabled(tc.tool_name):
            result = ToolResult(
                output=f"Error: tool '{tc.tool_name}' is disabled in current mode",
                is_error=True,
            )
            elapsed = time.monotonic() - start
            yield result, elapsed, is_unknown
            return

        # ===== 权限检查 =====
        # 权限系统有三种决策：
        # - allow: 直接允许（安全操作或已配置规则）
        # - deny: 直接拒绝（危险操作被禁止）
        # - ask: 询问用户（需要用户确认）
        if self.permission_checker:
            decision = self.permission_checker.check(tool, tc.arguments)

            if decision.effect == "deny":
                # 操作被禁止
                result = ToolResult(
                    output=f"Permission denied: {decision.reason}",
                    is_error=True,
                )
                elapsed = time.monotonic() - start
                yield result, elapsed, is_unknown
                return

            if decision.effect == "ask":
                # 需要询问用户，创建异步 Future 等待用户决定
                loop = asyncio.get_running_loop()
                future: asyncio.Future[PermissionResponse] = loop.create_future()
                desc = self._build_permission_description(tc)
                # yield 权限请求事件给 UI 层，UI 会展示对话框让用户选择
                yield PermissionRequest(
                    tool_name=tc.tool_name,
                    description=desc,
                    future=future,
                )
                # 异步等待用户在 UI 中做出决定
                response = await future

                if response == PermissionResponse.DENY:
                    # 用户拒绝
                    result = ToolResult(
                        output="Permission denied: 用户拒绝了此操作",
                        is_error=True,
                    )
                    elapsed = time.monotonic() - start
                    yield result, elapsed, is_unknown
                    return

                if response == PermissionResponse.ALLOW_ALWAYS:
                    # 用户选择「永远允许」：添加本地规则，以后不再询问
                    from mewcode.permissions.rules import Rule, extract_content
                    content = extract_content(tc.tool_name, tc.arguments)
                    pattern = f"{content[:60]}*" if len(content) > 60 else f"{content}*"
                    rule = Rule(tool_name=tc.tool_name, pattern=pattern, effect="allow")
                    self.permission_checker.rule_engine.append_local_rule(rule)

        # ===== 执行工具 =====
        try:
            params = tool.params_model.model_validate(tc.arguments)  # Pydantic 参数验证
            result = await tool.execute(params)
        except ValidationError as e:
            # 参数格式错误
            result = ToolResult(
                output=f"Parameter validation error: {e}", is_error=True
            )
        except Exception as e:
            result = ToolResult(
                output=f"Tool execution error: {e}", is_error=True
            )

        self._snapshot_for_recovery(tc, result)

        elapsed = time.monotonic() - start
        yield result, elapsed, is_unknown

    def _snapshot_for_recovery(
        self, tc: ToolCallComplete, result: ToolResult
    ) -> None:
        """
        为上下文压缩恢复保存快照。

        当对话被压缩时，早期工具结果会被丢弃。但如果之前读取了文件，
        压缩后需要重新附加这些文件内容，否则 LLM 会「忘记」文件内容。

        这里保存 ReadFile 工具读取的文件内容，压缩后可以恢复。
        """
        if result.is_error or tc.tool_name != "ReadFile":
            return  # 只处理成功的 ReadFile 调用
        path = tc.arguments.get("file_path") if isinstance(tc.arguments, dict) else None
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                content = fh.read()
        except OSError:
            return
        # 记录文件路径和内容，用于压缩后恢复
        self.recovery_state.record_file_read(path, content)

    async def _extract_memories(
        self, conversation: ConversationManager
    ) -> None:
        """
        自动提取记忆。

        每隔一定轮数，自动分析对话历史，提取用户偏好、项目知识等，
        保存到长期记忆中。这样下次对话时，Agent 还能记得这些信息。
        """
        if self._extracting or not self.memory_manager:
            return  # 防止重复提取
        self._extracting = True
        try:
            await self.memory_manager.extract(
                self.client, conversation, self.protocol
            )
        except Exception as e:
            log.debug("Memory extraction failed: %s", e)  # 记忆提取失败不影响主流程
        finally:
            self._extracting = False

    async def manual_compact(
        self, conversation: ConversationManager
    ) -> CompactNotification | ErrorEvent:
        """
        手动触发上下文压缩。

        用户可以通过 /compact 命令手动触发，或者系统自动触发。
        压缩会用 LLM 生成对话摘要，替换早期对话内容。
        """
        # auto_compact 会用摘要替换 conversation.history，所有 tool-result 内容
        # （原始或已替换的）都将被丢弃。这里跳过 apply_tool_result_budget —
        # 它在主循环中的唯一目的是为 LLM 调用生成 api_conv，而本路径不需要
        # 发起看到替换结果的 LLM 调用（auto_compact 内部的摘要调用操作的是原始对话）。
        result = await auto_compact(
            conversation,
            self.client,
            self.context_window,
            self.session_dir,
            protocol=self.protocol,
            manual=True,
            breaker=self.compact_breaker,
            recovery=self.recovery_state,
            tool_schemas=self.registry.get_all_schemas(self.protocol),
            transcript_path=self._transcript_path,
        )
        if isinstance(result, CompactEvent):
            env_context = build_environment_context(
            self.work_dir, self.active_skills, self._skill_catalog, self._agent_catalog
        )
            conversation.inject_environment(env_context)
            memory_content = self.memory_manager.load() if self.memory_manager else ""
            conversation.inject_long_term_memory(
                self.instructions_content, memory_content
            )
            return CompactNotification(
                before_tokens=result.before_tokens,
                message=f"上下文已压缩（压缩前 {result.before_tokens:,} tokens）",
                boundary=result.boundary,
            )
        return ErrorEvent(message=result or "压缩失败：对话历史为空或未达到压缩条件")

    async def run_to_completion(
        self, task: str, conversation: ConversationManager | None = None,
        event_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> str:
        """
        简化版 Agent 循环，用于非交互模式（如子 Agent、批处理）。

        与 run() 的区别：
        - 不产生事件流，直接返回最终文本结果
        - 不处理权限请求（自动拒绝需要用户确认的操作）
        - 适用于子 Agent 执行独立任务

        参数:
            task: 要执行的任务描述
            conversation: 可选的对话管理器，不提供则创建新的
            event_callback: 可选的事件回调，用于通知外部进度

        返回:
            LLM 最后一条文本回复
        """
        # 如果没有提供对话，创建一个新的
        if conversation is None:
            conversation = ConversationManager()

            env_context = build_environment_context(
                self.work_dir, self.active_skills, self._skill_catalog, self._agent_catalog
            )
            conversation.inject_environment(env_context)

            if self.instructions_content:
                memory_content = self.memory_manager.load() if self.memory_manager else ""
                conversation.inject_long_term_memory(
                    self.instructions_content, memory_content
                )

        # 添加用户任务到对话
        if task:
            conversation.add_user_message(task)

        # 构建系统提示词
        hook_prompts = (
            self.hook_engine.get_prompt_messages() if self.hook_engine else None
        )
        system = build_system_prompt(
            hook_prompts=hook_prompts,
            coordinator_mode=self.coordinator_mode,
        )

        tools = self.registry.get_all_schemas(self.protocol)

        log.info(
            "[run_to_completion] agent=%s tools=%d names=%s coordinator=%s",
            self.agent_id,
            len(tools),
            [t["name"] for t in tools][:10],
            self.coordinator_mode,
        )

        last_text = ""  # 记录最后一条文本，作为返回值
        last_tool_signature = ""
        identical_tool_attempts = 0

        # 主循环（与 run() 类似，但简化了事件处理）
        for iteration in range(1, self.max_iterations + 1):
            self._raise_if_cancelled()
            llm_started = time.monotonic()
            if event_callback:
                event_callback({"type": "agent_phase", "phase": "thinking", "iteration": iteration})
            if self.hook_engine:
                ctx = self._build_hook_context("turn_start")
                await self.hook_engine.run_hooks("turn_start", ctx)

            # 消费团队邮箱消息
            self._consume_mailbox(conversation)
            if self.notification_fn:
                for note in self.notification_fn():
                    conversation.add_system_reminder(note)

            compact_result = await auto_compact(
                conversation,
                self.client,
                self.context_window,
                self.session_dir,
                protocol=self.protocol,
                breaker=self.compact_breaker,
                recovery=self.recovery_state,
                tool_schemas=self.registry.get_all_schemas(self.protocol),
                transcript_path=self._transcript_path,
            )
            if isinstance(compact_result, CompactEvent):
                conversation.inject_environment(env_context)

            deferred_names = self.registry.get_deferred_tool_names()
            if deferred_names:
                conversation.add_system_reminder(
                    "The following deferred tools are available via ToolSearch. "
                    "Their schemas are NOT loaded - use ToolSearch with "
                    'query "select:<name>[,<name>...]" to load tool schemas before calling them:\n'
                    + "\n".join(deferred_names)
                )

            api_conv, _new_records = apply_tool_result_budget(
                conversation, self.session_dir, self.replacement_state
            )
            if _new_records:
                append_replacement_records(self.session_dir, _new_records)

            collector = StreamCollector()
            llm_stream = self.client.stream(api_conv, system=system, tools=tools)
            async for _event in collector.consume(llm_stream):
                pass
            llm_duration_ms = round((time.monotonic() - llm_started) * 1000)

            response = collector.response
            self.total_input_tokens += response.input_tokens
            self.total_output_tokens += response.output_tokens

            if event_callback:
                event_callback({
                    "type": "usage",
                    "iteration": iteration,
                    "phase": "thinking",
                    "usage": {
                        "inputTokens": self.total_input_tokens,
                        "outputTokens": self.total_output_tokens,
                    },
                    "duration_ms": llm_duration_ms,
                })

            if response.text:
                last_text = response.text
                if event_callback:
                    event_callback({
                        "type": "stream_text",
                        "text": response.text,
                    })

            log.info(
                "[run_to_completion] agent=%s iter=%d tool_calls=%d text_len=%d stop=%s",
                self.agent_id, iteration, len(response.tool_calls),
                len(response.text), response.stop_reason,
            )

            if not response.tool_calls:
                if event_callback:
                    event_callback({"type": "agent_phase", "phase": "completed", "iteration": iteration})
                conversation.add_assistant_message(response.text)
                if self.file_history is not None:
                    summary = response.text[:60] + "..." if len(response.text) > 60 else response.text
                    self.file_history.make_snapshot(len(conversation.history), summary)
                break

            tool_uses = [
                ToolUseBlock(
                    tool_use_id=tc.tool_id,
                    tool_name=tc.tool_name,
                    arguments=tc.arguments,
                )
                for tc in response.tool_calls
            ]
            conversation.add_assistant_message(response.text, tool_uses)
            # assistant 回复已在历史中，锚定实际用量；下一轮迭代只需对
            # 下方追加的 tool results 做字符估算。
            conversation.record_usage_anchor(
                response.input_tokens,
                response.output_tokens,
                response.cache_read,
                response.cache_creation,
            )

            tool_results: list[ToolResultBlock] = []
            for tc in response.tool_calls:
                signature = json.dumps(
                    [tc.tool_name, tc.arguments], sort_keys=True, ensure_ascii=False,
                    separators=(",", ":"), default=str,
                )
                if signature == last_tool_signature:
                    identical_tool_attempts += 1
                else:
                    last_tool_signature = signature
                    identical_tool_attempts = 1
                if event_callback:
                    event_callback({"type": "agent_phase", "phase": "tool_call", "iteration": iteration})
                if event_callback:
                    event_callback({
                        "type": "tool_use",
                        "toolName": tc.tool_name,
                        "tool_id": tc.tool_id,
                        "args": tc.arguments,
                        "iteration": iteration,
                        "phase": "tool_call",
                        "attempt": identical_tool_attempts,
                    })
                tool_started = time.monotonic()
                if identical_tool_attempts > MAX_IDENTICAL_TOOL_ATTEMPTS:
                    result = ToolResult(
                        output=("Repeated tool call blocked: this exact tool and argument set "
                                f"has already been repeated {MAX_IDENTICAL_TOOL_ATTEMPTS} times. "
                                "Change the arguments or choose another approach."),
                        is_error=True,
                    )
                else:
                    result = await self._execute_tool_noninteractive(tc)
                duration_ms = round((time.monotonic() - tool_started) * 1000)
                attempt = identical_tool_attempts
                if event_callback:
                    event_callback({
                        "type": "tool_result", "toolName": tc.tool_name,
                        "tool_id": tc.tool_id,
                        "output": result.output, "is_error": result.is_error,
                        "iteration": iteration, "phase": "tool_result",
                        "duration_ms": duration_ms,
                        "error_category": _tool_error_category(result.output) if result.is_error else "",
                        "attempt": attempt,
                    })
                if not result.is_error:
                    last_tool_signature = ""
                    identical_tool_attempts = 0
                content = self._maybe_persist_or_truncate(tc.tool_id, result.output)
                tool_results.append(
                    ToolResultBlock(
                        tool_use_id=tc.tool_id,
                        content=content,
                        is_error=result.is_error,
                    )
                )

            conversation.add_tool_results_message(tool_results)
            if event_callback:
                event_callback({"type": "agent_phase", "phase": "thinking", "iteration": iteration + 1})

            if self.hook_engine:
                ctx = self._build_hook_context("turn_end")
                await self.hook_engine.run_hooks("turn_end", ctx)

        else:
            raise RuntimeError(
                f"Agent exceeded {self.max_iterations} iterations without a final answer"
            )
        return last_text

    async def _execute_tool_noninteractive(
        self, tc: ToolCallComplete
    ) -> ToolResult:
        """
        非交互模式下的工具执行。

        与 _execute_tool 的区别：
        - 不产生事件流，直接返回结果
        - 不能向用户询问权限（自动拒绝需要确认的操作）
        - 用于子 Agent 和批处理场景
        """
        tool = self.registry.get(tc.tool_name)

        # 检查工具是否存在
        if tool is None:
            return ToolResult(
                output=f"Error: unknown tool '{tc.tool_name}'", is_error=True
            )

        # 检查工具是否已启用
        if not self.registry.is_enabled(tc.tool_name):
            return ToolResult(
                output=f"Error: tool '{tc.tool_name}' is disabled",
                is_error=True,
            )

        # 触发 pre_tool_use Hook（可以拦截工具执行）
        if self.hook_engine:
            file_path = self._infer_file_path(tc.arguments)
            hook_ctx = self._build_hook_context(
                "pre_tool_use",
                tool_name=tc.tool_name,
                tool_args=tc.arguments,
                file_path=file_path,
            )
            rejection = await self.hook_engine.run_pre_tool_hooks(hook_ctx)
            if rejection is not None:
                return ToolResult(
                    output=f"Hook rejected: {rejection.reason}",
                    is_error=True,
                )

        # 权限检查（非交互模式下，需要确认的操作会被拒绝）
        if self.permission_checker:
            decision = self.permission_checker.check(tool, tc.arguments)
            if decision.effect == "deny":
                return ToolResult(
                    output=f"Permission denied: {decision.reason}",
                    is_error=True,
                )
            if decision.effect == "ask":
                if self.permission_mode == PermissionMode.DONT_ASK:
                    pass  # DONT_ASK 模式：自动批准
                else:
                    # 非交互模式无法弹出对话框，直接拒绝
                    return ToolResult(
                        output="Permission denied: non-interactive agent cannot prompt user",
                        is_error=True,
                    )

        # 验证参数并执行
        try:
            params = tool.params_model.model_validate(tc.arguments)
            result = await tool.execute(params)
        except ValidationError as e:
            result = ToolResult(
                output=f"Parameter validation error: {e}", is_error=True
            )
        except Exception as e:
            result = ToolResult(
                output=f"Tool execution error: {e}", is_error=True
            )

        # 触发 post_tool_use Hook
        if self.hook_engine:
            file_path = self._infer_file_path(tc.arguments)
            hook_ctx = self._build_hook_context(
                "post_tool_use",
                tool_name=tc.tool_name,
                tool_args=tc.arguments,
                file_path=file_path,
            )
            await self.hook_engine.run_hooks("post_tool_use", hook_ctx)

        return result

    def _maybe_persist_or_truncate(self, tool_use_id: str, text: str) -> str:
        """
        处理工具输出：根据长度决定如何截断或持久化。

        策略：
        - 超过 SINGLE_RESULT_CHAR_LIMIT：保存到文件，只返回预览
        - 超过 MAX_OUTPUT_CHARS：截断，添加省略号
        - 否则：原样返回
        """
        from mewcode.context.manager import (
            SINGLE_RESULT_CHAR_LIMIT,
            make_persisted_preview,
            persist_tool_result,
        )

        if len(text) > SINGLE_RESULT_CHAR_LIMIT:
            # 超长输出：保存到文件，返回预览 + 文件路径
            fp = persist_tool_result(tool_use_id, text, self.session_dir)
            return make_persisted_preview(text, fp)
        if len(text) > MAX_OUTPUT_CHARS:
            # 中等长度：截断
            return text[:MAX_OUTPUT_CHARS] + "\n… (output truncated)"
        # 短输出：原样返回
        return text
