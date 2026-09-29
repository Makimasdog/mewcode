"""
__init__.py — 工具注册表（ToolRegistry）
================================================

【这个模块做什么】
管理所有工具的注册、启用/禁用、延迟加载和 Schema 生成。

【核心概念】
ToolRegistry 是工具的「仓库」，Agent 通过它获取可用工具列表。

【延迟加载机制】
某些工具标记为 should_defer=True，不会立即暴露给 LLM。
LLM 需要通过 ToolSearch 工具「发现」这些工具后才能使用。
这减少了初始 token 消耗（工具描述会占用上下文空间）。

【对外接口】
- ToolRegistry: 工具注册表类
- create_default_registry(): 创建默认工具集
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mewcode.tools.base import Tool

if TYPE_CHECKING:
    from mewcode.cache import FileCache


class ToolRegistry:
    """
    工具注册表 — 管理所有工具的注册、启用/禁用、延迟加载。
    
    内部状态：
    - _tools: 所有已注册的工具（名称 → Tool 实例）
    - _disabled: 被禁用的工具名称集合
    - _discovered: 已被发现的延迟工具名称集合
    """
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}
        self._disabled: set[str] = set()
        self._discovered: set[str] = set()

    def register(self, tool: Tool) -> None:
        """注册一个工具到注册表"""
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        """按名称获取工具实例"""
        return self._tools.get(name)


    def is_enabled(self, name: str) -> bool:
        """检查工具是否已注册且未被禁用"""
        return name in self._tools and name not in self._disabled

    def enable(self, name: str) -> None:
        """启用一个被禁用的工具"""
        self._disabled.discard(name)


    def disable(self, name: str) -> None:
        """禁用一个工具（不会从注册表移除，只是不暴露给 LLM）"""
        if name in self._tools:
            self._disabled.add(name)

    def enable_all(self) -> None:
        """启用所有工具（清空禁用列表）"""
        self._disabled.clear()

    def mark_discovered(self, name: str) -> None:
        """
        标记一个延迟工具为「已发现」。
        
        当 LLM 通过 ToolSearch 找到并加载了某个延迟工具后，
        调用此方法标记它，使其在后续请求中可用。
        """
        self._discovered.add(name)

    def is_discovered(self, name: str) -> bool:
        """检查一个延迟工具是否已被发现"""
        return name in self._discovered


    def get_deferred_tool_names(self) -> list[str]:
        """
        获取所有待发现的延迟工具名称。
        
        用于 ToolSearch 工具展示可用工具列表。
        """
        return [
            name
            for name, tool in self._tools.items()
            if getattr(tool, "should_defer", False)
            and name not in self._discovered
            and name not in self._disabled
        ]

    def search_deferred(
        self, query: str, max_results: int, protocol: str = "anthropic"
    ) -> list[dict[str, Any]]:
        """
        按关键词搜索延迟工具。
        
        使用简单的评分机制：
        - 查询词完整匹配名称：+10 分
        - 查询词完整匹配描述：+5 分
        - 查询词中的单词匹配名称：+3 分/词
        - 查询词中的单词匹配描述：+1 分/词
        
        返回得分最高的 max_results 个工具的 Schema。
        """
        query_lower = query.lower()
        scored: list[tuple[int, str, Tool]] = []
        for name, tool in self._tools.items():
            if not getattr(tool, "should_defer", False):
                continue
            if name in self._disabled:
                continue
            score = 0
            name_lower = name.lower()
            desc_lower = (tool.description or "").lower()
            if query_lower in name_lower:
                score += 10
            if query_lower in desc_lower:
                score += 5
            for word in query_lower.split():
                if word in name_lower:
                    score += 3
                if word in desc_lower:
                    score += 1
            if score > 0:
                scored.append((score, name, tool))
        scored.sort(key=lambda x: x[0], reverse=True)
        results: list[dict[str, Any]] = []
        for _, _name, tool in scored[:max_results]:
            base = tool.get_schema()
            if protocol in ("openai", "openai-compat"):
                results.append({
                    "type": "function",
                    "name": base["name"],
                    "description": base["description"],
                    "parameters": base["input_schema"],
                })
            else:
                results.append(base)
        return results

    def find_deferred_by_names(
        self, names: list[str], protocol: str = "anthropic"
    ) -> list[dict[str, Any]]:
        """
        按精确名称列表查找延迟工具。
        
        用于 ToolSearch 的 "select:name1,name2" 语法。
        """
        results: list[dict[str, Any]] = []
        for name in names:
            tool = self._tools.get(name)
            if tool is None:
                continue
            if not getattr(tool, "should_defer", False):
                continue
            base = tool.get_schema()
            if protocol in ("openai", "openai-compat"):
                results.append({
                    "type": "function",
                    "name": base["name"],
                    "description": base["description"],
                    "parameters": base["input_schema"],
                })
            else:
                results.append(base)
        return results

    def list_tools(self) -> list[Tool]:
        """获取所有已注册的工具实例列表"""
        return list(self._tools.values())


    def get_all_schemas(self, protocol: str = "anthropic") -> list[dict[str, Any]]:
        """
        获取所有可用工具的 JSON Schema（给 LLM 的工具列表）。
        
        排除：
        - 被禁用的工具
        - 未发现的延迟工具（should_defer=True 且未 mark_discovered）
        
        protocol 参数用于适配不同 API 的 Schema 格式：
        - "anthropic": 原生格式 {name, description, input_schema}
        - "openai": {type: "function", name, description, parameters}
        """
        schemas: list[dict[str, Any]] = []
        for name, tool in self._tools.items():
            if name in self._disabled:
                continue
            if getattr(tool, "should_defer", False) and name not in self._discovered:
                continue
            base = tool.get_schema()
            if protocol in ("openai", "openai-compat"):
                schemas.append({
                    "type": "function",
                    "name": base["name"],
                    "description": base["description"],
                    "parameters": base["input_schema"],
                })
            else:
                schemas.append(base)
        return schemas


def create_default_registry(file_cache: FileCache | None = None, file_history: Any = None) -> ToolRegistry:
    """
    创建默认工具注册表。
    
    包含 6 个核心工具：
    - ReadFile: 读取文件
    - WriteFile: 写入文件
    - EditFile: 编辑文件（精确替换）
    - Bash: 执行命令
    - Glob: 文件模式匹配
    - Grep: 正则搜索
    
    这些工具是 Agent 的基础能力，始终可用。
    """
    from mewcode.tools.bash import Bash
    from mewcode.tools.edit_file import EditFile
    from mewcode.tools.file_state_cache import FileStateCache
    from mewcode.tools.glob import Glob
    from mewcode.tools.grep import Grep
    from mewcode.tools.read_file import ReadFile
    from mewcode.tools.write_file import WriteFile

    # FileStateCache 确保「先读后写」的安全约束
    file_state_cache = FileStateCache()

    registry = ToolRegistry()
    registry.register(ReadFile(file_cache=file_cache, file_state_cache=file_state_cache))
    registry.register(WriteFile(file_cache=file_cache, file_history=file_history, file_state_cache=file_state_cache))
    registry.register(EditFile(file_cache=file_cache, file_history=file_history, file_state_cache=file_state_cache))
    registry.register(Bash())
    registry.register(Glob())
    registry.register(Grep())
    return registry
