"""
glob.py — 文件模式匹配工具
================================================

【这个模块做什么】
使用 glob 模式匹配查找文件，返回相对路径列表。

【使用场景】
- 查找所有 Python 文件: **/*.py
- 查找配置文件: **/*.json
- 查找特定目录下的文件: src/**/*.ts

【设计特点】
- 自动跳过无关目录（SKIP_DIRS: .git, node_modules 等）
- 返回相对路径（便于 LLM 理解）
- 并发安全: is_concurrency_safe = True
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from mewcode.tools.base import SKIP_DIRS, Tool, ToolResult


class Params(BaseModel):
    """Glob 参数模型"""
    pattern: str = Field(description="Glob pattern to match (e.g. '**/*.py')")
    path: str = Field(default=".", description="Base directory to search from")


class Glob(Tool):
    """
    文件模式匹配工具 — 查找匹配 glob 模式的文件。
    
    特性:
    - 支持标准 glob 语法（**、*、?）
    - 自动跳过 .git、node_modules 等无关目录
    - 返回排序后的相对路径列表
    - 并发安全
    """
    name = "Glob"
    description = "Find files matching a glob pattern, returning relative paths."
    params_model = Params
    category = "read"
    is_concurrency_safe = True


    async def execute(self, params: Params) -> ToolResult:
        base = Path(params.path)
        if not base.exists():
            return ToolResult(output=f"Error: path not found: {params.path}", is_error=True)

        try:
            # 匹配文件，过滤掉 SKIP_DIRS 中的目录
            matches = sorted(
                str(p.relative_to(base))
                for p in base.glob(params.pattern)
                if p.is_file() and not any(part in SKIP_DIRS for part in p.parts)
            )
        except Exception as e:
            return ToolResult(output=f"Error: {e}", is_error=True)

        if not matches:
            return ToolResult(output="No files matched the pattern.")
        return ToolResult(output="\n".join(matches))

