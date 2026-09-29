"""
synthetic_output.py — 结构化输出工具
================================================

【这个模块做什么】
让 Agent 以 JSON 格式返回结构化数据。

【使用场景】
- 非交互模式（单次执行）
- 协调者模式（coordinator mode）
- 需要结构化输出的 API 调用

【设计特点】
- 支持可选的 JSON Schema 验证
- 支持 dict、list、str 三种输出类型
- 自动格式化为可读的 JSON 字符串
"""
from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel

from mewcode.tools.base import Tool, ToolResult


class SyntheticOutputParams(BaseModel):
    """SyntheticOutput 参数模型"""
    output: dict[str, Any] | list[Any] | str  # 输出内容


class SyntheticOutputTool(Tool):
    """
    结构化输出工具 — 以 JSON 格式返回数据。
    
    特性:
    - 支持可选的 JSON Schema 验证
    - 自动格式化 JSON 输出
    - 用于非交互场景的最终响应
    """
    name = "SyntheticOutput"
    description = (
        "Return structured output in JSON format. "
        "Use this tool to return your final response as structured data "
        "in non-interactive or coordinator mode sessions."
    )
    params_model = SyntheticOutputParams
    category = "read"
    is_concurrency_safe = True
    is_system_tool = True


    def __init__(self, json_schema: dict[str, Any] | None = None) -> None:
        self._json_schema = json_schema  # 可选的输出 Schema 验证


    async def execute(self, params: BaseModel) -> ToolResult:
        p: SyntheticOutputParams = params  # type: ignore[assignment]

        # 如果设置了 Schema，验证输出格式
        if self._json_schema is not None:
            error = self._validate_schema(p.output)
            if error:
                return ToolResult(output=f"Output does not match required schema: {error}", is_error=True)

        # 字符串直接返回
        if isinstance(p.output, str):
            return ToolResult(output=p.output)

        # dict/list 格式化为 JSON
        return ToolResult(output=json.dumps(p.output, ensure_ascii=False, indent=2))


    def _validate_schema(self, data: Any) -> str | None:
        """
        验证输出是否符合指定的 JSON Schema。
        
        支持检查：
        - type: object/array/string
        - required: 必填字段列表
        
        返回: None 表示通过，否则返回错误信息。
        """
        schema = self._json_schema
        if schema is None:
            return None

        # 类型检查
        if "type" in schema:
            expected_type = schema["type"]
            if expected_type == "object" and not isinstance(data, dict):
                return f"Expected object, got {type(data).__name__}"
            if expected_type == "array" and not isinstance(data, list):
                return f"Expected array, got {type(data).__name__}"
            if expected_type == "string" and not isinstance(data, str):
                return f"Expected string, got {type(data).__name__}"

        # 必填字段检查
        if "required" in schema and isinstance(data, dict):
            missing = [k for k in schema["required"] if k not in data]
            if missing:
                return f"Missing required fields: {', '.join(missing)}"

        return None
