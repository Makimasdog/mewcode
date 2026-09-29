"""
base.py — 工具系统基础设施
=====================================

【这个模块做什么】
定义整个工具系统的基石：
- Tool: 所有工具的抽象基类（定义接口规范）
- ToolResult: 工具执行结果
- StreamEvent: LLM 流式响应事件类型

【核心设计】
每个工具都是一个 Tool 子类，必须实现：
1. name/description: 工具名称和描述（给 LLM 看）
2. params_model: Pydantic 参数模型（自动验证 LLM 的输入）
3. execute(): 实际执行逻辑

【工具分类】
- category="read": 只读工具，可安全并行执行
- category="write": 写入工具，需注意并发安全
- category="command": 命令工具，可能产生副作用

【延迟加载机制】
should_defer=True 的工具不会立即暴露给 LLM，
需要通过 ToolSearch 工具搜索并「发现」后才能使用。
这减少了初始 token 消耗。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel

# 工具扫描时跳过的目录（避免扫描无关文件）
SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", ".tox", ".mypy_cache"}

# 工具输出最大字符数（超出会被截断）
MAX_OUTPUT_CHARS = 10000

# 工具分类：read=只读、write=写入、command=命令
ToolCategory = Literal["read", "write", "command"]


@dataclass
class ToolResult:
    """
    工具执行结果。
    
    工具不通过异常表达失败，而是通过 is_error=True 返回错误信息。
    这确保了对话循环不会因工具错误而中断。
    """
    output: str           # 输出内容（给 LLM 看）
    is_error: bool = False  # 是否为错误结果


class Tool(ABC):
    """
    所有工具的抽象基类。
    
    每个工具必须定义：
    - name: 工具名称（如 "ReadFile"、"Bash"）
    - description: 工具描述（给 LLM 看，决定何时使用）
    - params_model: Pydantic 参数模型（自动验证 LLM 输入）
    - execute(): 实际执行逻辑
    """
    name: str
    description: str
    params_model: type[BaseModel]
    category: ToolCategory = "read"       # 工具分类
    is_concurrency_safe: bool = False     # 是否可安全并行执行
    is_system_tool: bool = False          # 是否为系统工具（不显示给用户）
    should_defer: bool = False            # 是否延迟加载（需通过 ToolSearch 发现）

    @property
    def is_read_only(self) -> bool:
        """是否为只读工具（可安全并行）"""
        return self.category == "read"


    def get_schema(self) -> dict[str, Any]:
        """
        生成工具的 JSON Schema（给 LLM 的工具列表）。
        
        LLM 通过这个 schema 了解工具的参数格式。
        """
        schema = self.params_model.model_json_schema()
        schema.pop("title", None)
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": schema,
        }

    @abstractmethod
    async def execute(self, params: BaseModel) -> ToolResult: 
        """
        执行工具逻辑。
        
        参数: params - Pydantic 验证后的参数对象
        返回: ToolResult - 执行结果
        """
        ...


# ---------------------------------------------------------------------------
# 流式事件类型
# LLM 流式响应时，通过以下事件类型逐步输出内容
# ---------------------------------------------------------------------------

@dataclass
class TextDelta:
    """文本增量事件（LLM 输出的可见文本）"""
    text: str


@dataclass
class ToolCallStart:
    """工具调用开始事件"""
    tool_name: str
    tool_id: str


@dataclass
class ToolCallDelta:
    """工具调用参数增量事件（流式输出参数 JSON）"""
    text: str


@dataclass
class ToolCallComplete:
    """工具调用完成事件（参数收集完毕）"""
    tool_id: str
    tool_name: str
    arguments: dict[str, Any]


@dataclass
class ThinkingDelta:
    """思考过程增量事件（LLM 的内部推理，通常不显示给用户）"""
    text: str


@dataclass
class ThinkingComplete:
    """思考过程完成事件"""
    thinking: str
    signature: str


@dataclass
class StreamEnd:
    """
    流式响应结束事件。
    
    包含 token 使用统计和缓存命中信息。
    """
    stop_reason: str         # 停止原因（如 "end_turn"、"tool_use"）
    input_tokens: int = 0    # 输入 token 数
    output_tokens: int = 0   # 输出 token 数
    # API 返回的 prompt cache 用量。Anthropic 把缓存前缀 token 分为
    # "read"（cache 命中，按 10% 计费）和 "creation"（cache 写入）。
    # input_tokens 已排除这两部分，因此实际 prompt 大小 =
    # input + cache_read + cache_creation。OpenAI 系列只暴露
    # cache_read（通过 *_tokens_details.cached_tokens），没有 creation
    # 计数，所以 cache_creation 在那边始终为 0。
    cache_read: int = 0
    cache_creation: int = 0


# 流式事件联合类型（用于类型提示）
StreamEvent = TextDelta | ThinkingDelta | ThinkingComplete | ToolCallStart | ToolCallDelta | ToolCallComplete | StreamEnd
