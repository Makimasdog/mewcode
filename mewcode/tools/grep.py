"""
grep.py — 正则搜索工具
================================================

【这个模块做什么】
使用正则表达式搜索文件内容，返回匹配的行（类似 grep 命令）。

【使用场景】
- 搜索函数定义: def my_function
- 搜索导入语句: import requests
- 搜索错误信息: Error:.*timeout

【设计特点】
- 支持完整正则语法
- 可选 include 参数过滤文件类型（如 "*.py"）
- 自动跳过无关目录（SKIP_DIRS）
- 返回格式: 文件:行号:内容
- 并发安全: is_concurrency_safe = True
"""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel, Field

from mewcode.tools.base import SKIP_DIRS, Tool, ToolResult


class Params(BaseModel):
    """Grep 参数模型"""
    pattern: str = Field(description="Regex pattern to search for")
    path: str = Field(default=".", description="Base directory to search from")
    include: str = Field(default="", description="Glob filter for filenames (e.g. '*.py')")


class Grep(Tool):
    """
    正则搜索工具 — 使用正则表达式搜索文件内容。
    
    特性:
    - 支持完整正则语法
    - 可选 include 参数过滤文件类型
    - 自动跳过 .git、node_modules 等无关目录
    - 返回格式: 文件:行号:内容
    - 并发安全
    """
    name = "Grep"
    description = "Search file contents using a regex pattern, returning file:line:content matches."
    params_model = Params
    category = "read"
    is_concurrency_safe = True


    async def execute(self, params: Params) -> ToolResult:
        base = Path(params.path)
        if not base.exists():
            return ToolResult(output=f"Error: path not found: {params.path}", is_error=True)

        # 编译正则表达式
        try:
            regex = re.compile(params.pattern)
        except re.error as e:
            return ToolResult(output=f"Error: invalid regex: {e}", is_error=True)

        # 构建 glob 模式（默认搜索所有文件）
        glob_pattern = params.include if params.include else "**/*"
        if not glob_pattern.startswith("**/"):
            glob_pattern = "**/" + glob_pattern

        results: list[str] = []
        for file_path in sorted(base.glob(glob_pattern)):
            if not file_path.is_file():
                continue
            if any(part in SKIP_DIRS for part in file_path.parts):
                continue
            try:
                text = file_path.read_text(encoding="utf-8", errors="ignore")
            except (OSError, UnicodeDecodeError):
                continue
            # 逐行搜索，记录匹配
            for line_num, line in enumerate(text.splitlines(), 1):
                if regex.search(line):
                    rel = file_path.relative_to(base)
                    results.append(f"{rel}:{line_num}:{line}")

        if not results:
            return ToolResult(output="No matches found.")
        return ToolResult(output="\n".join(results))

