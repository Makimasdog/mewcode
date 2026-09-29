"""
ask_user.py — 用户问答工具
================================================

【这个模块做什么】
Agent 向用户提问，阻塞等待用户回答。

【使用场景】
- 需要用户确认操作
- 需要用户提供额外信息
- 需要用户做选择

【问题类型】
- text: 文本输入
- radio: 单选
- select: 下拉选择
- checkbox: 多选

【设计特点】
- 通过 asyncio Future 实现阻塞等待
- 超时时间 5 分钟
- 标记为系统工具（is_system_tool=True）
- 延迟加载（should_defer=True）
"""
from __future__ import annotations

import asyncio
from typing import Any

from pydantic import BaseModel, Field

from mewcode.tools.base import Tool, ToolResult


class QuestionItem(BaseModel):
    """单个问题的定义"""
    type: str = Field(description="Question type: text, radio, select, checkbox")
    name: str = Field(description="Question identifier")
    message: str = Field(description="Question text to display")
    options: list[str] = Field(
        default_factory=list,
        description="Options for radio/select/checkbox types",
    )


class AskUserParams(BaseModel):
    """AskUser 参数模型"""
    questions: list[QuestionItem] = Field(
        description="List of questions to ask the user"
    )


class AskUserEvent:
    """
    用户问答事件 — 封装问题和响应 Future。
    
    TUI 层接收此事件，展示问题给用户，
    然后通过 future.set_result() 回传答案。
    """


    def __init__(
        self,
        questions: list[dict[str, Any]],
        future: asyncio.Future[dict[str, str]],
    ) -> None:
        self.questions = questions
        self.future = future


class AskUserTool(Tool):
    """
    用户问答工具 — Agent 向用户提问并等待回答。
    
    特性:
    - 支持多种问题类型（text/radio/select/checkbox）
    - 阻塞等待用户回答（超时 5 分钟）
    - 标记为系统工具（不显示给用户）
    - 延迟加载（需通过 ToolSearch 发现）
    """
    name = "AskUserQuestion"
    description = (
        "Ask the user one or more questions when you need information "
        "that cannot be determined from code or context alone. Supports "
        "text input, radio (single select), select, and checkbox (multi select) "
        "question types."
    )
    params_model = AskUserParams
    category: str = "read"
    is_system_tool = True    # 系统工具（不显示给用户）
    should_defer = True      # 延迟加载


    def __init__(self) -> None:
        self._pending_event: AskUserEvent | None = None

    async def execute(self, params: AskUserParams) -> ToolResult:
        """
        执行提问：创建 Future，等待 TUI 层回传答案。
        
        流程:
        1. 创建 asyncio Future
        2. 创建 AskUserEvent 并保存
        3. 等待 Future 完成（超时 5 分钟）
        4. 返回用户的答案
        """
        questions_data = [q.model_dump() for q in params.questions]

        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, str]] = loop.create_future()

        self._pending_event = AskUserEvent(questions=questions_data, future=future)

        try:
            answers = await asyncio.wait_for(future, timeout=300)
        except asyncio.TimeoutError:
            return ToolResult(
                output="User did not respond within 5 minutes", is_error=True
            )
        finally:
            self._pending_event = None

        lines = []
        for q in params.questions:
            answer = answers.get(q.name, "(no answer)")
            lines.append(f"{q.name}: {answer}")

        return ToolResult(output="\n".join(lines))
