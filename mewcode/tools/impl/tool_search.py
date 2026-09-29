"""
tool_search.py — 延迟工具搜索与加载
================================================

【这个模块做什么】
搜索并加载延迟加载的工具（should_defer=True）。

【为什么需要这个】
某些工具不常用，如果全部暴露给 LLM 会浪费 token。
通过延迟加载机制，只有当 LLM 需要时才「发现」这些工具。

【使用方式】
1. 按关键词搜索: query="task management"
2. 按名称精确加载: query="select:TaskCreate,TaskList"

【工作流程】
1. LLM 调用 ToolSearch 搜索工具
2. 在延迟工具列表中匹配
3. 匹配成功后标记为「已发现」
4. 后续请求中该工具可用
"""
from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel

from mewcode.tools.base import Tool, ToolResult

if __import__("typing").TYPE_CHECKING:
    from mewcode.tools import ToolRegistry


class ToolSearchParams(BaseModel):
    """ToolSearch 参数模型"""
    query: str           # 搜索关键词或 "select:name1,name2" 语法
    max_results: int = 5  # 最大返回数量


class ToolSearchTool(Tool):
    """
    延迟工具搜索工具 — 搜索并加载延迟加载的工具。
    
    特性:
    - 支持关键词搜索（按名称和描述匹配）
    - 支持精确名称加载（select: 语法）
    - 加载后标记工具为「已发现」
    - 自身永远不延迟加载（should_defer=False）
    """
    name = "ToolSearch"
    description = (
        "Search for and load additional tools that are not immediately available. "
        "Use query 'select:<name>[,<name>...]' to load specific tools by name, "
        "or provide keywords to search by relevance."
    )
    params_model = ToolSearchParams
    category = "read"
    should_defer = False  # ToolSearch 自身永远不延迟加载


    def __init__(
        self,
        registry: ToolRegistry,
        protocol: str = "anthropic",
    ) -> None:
        self._registry = registry
        self._protocol = protocol


    def get_schema(self) -> dict[str, Any]:
        """生成工具的 JSON Schema"""
        schema = self.params_model.model_json_schema()
        schema.pop("title", None)
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": schema,
        }


    async def execute(self, params: BaseModel) -> ToolResult:
        """
        执行搜索：支持两种模式。
        
        1. 关键词搜索: 按名称和描述匹配
        2. 精确加载: "select:name1,name2" 语法
        """
        assert isinstance(params, ToolSearchParams)
        query = params.query
        max_results = params.max_results

        # 精确加载模式
        if query.startswith("select:"):
            names = [n.strip() for n in query[7:].split(",")]
            schemas = self._registry.find_deferred_by_names(names, self._protocol)
        else:
            # 关键词搜索模式
            schemas = self._registry.search_deferred(
                query, max_results, self._protocol
            )

        if not schemas:
            deferred_names = self._registry.get_deferred_tool_names()
            return ToolResult(
                output=(
                    f'No matching deferred tools for "{query}". '
                    f'Available: {", ".join(deferred_names)}'
                )
            )

        # 标记找到的工具为「已发现」
        for s in schemas:
            if "name" in s:
                self._registry.mark_discovered(s["name"])

        return ToolResult(
            output=(
                f"Found {len(schemas)} tool(s). Their full schemas are now loaded:\n\n"
                f"{json.dumps(schemas, indent=2, ensure_ascii=False)}"
            )
        )
