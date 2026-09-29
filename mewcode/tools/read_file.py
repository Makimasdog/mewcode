"""
read_file.py — 文件读取工具
================================================

【这个模块做什么】
读取文件内容并返回带行号的文本。

【设计亮点】
1. 支持 FileCache: 缓存已读取的文件内容，避免重复 IO
2. 支持 FileStateCache: 读取后记录状态，强制「先读后写」
3. 支持分页读取: offset + limit 参数避免大文件一次性加载
4. 并发安全: is_concurrency_safe = True
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from mewcode.tools.base import Tool, ToolResult

if TYPE_CHECKING:
    from mewcode.cache import FileCache
    from mewcode.tools.file_state_cache import FileStateCache


class Params(BaseModel):
    """ReadFile 参数模型"""
    file_path: str = Field(description="Absolute or relative path to the file to read")
    offset: int = Field(default=0, description="Line offset to start reading from (0-based)")
    limit: int = Field(default=2000, description="Maximum number of lines to read")


class ReadFile(Tool):
    """
    文件读取工具 — 读取文件并返回带行号的内容。
    
    特性:
    - 可选 FileCache 缓存，避免重复 IO
    - 可选 FileStateCache，记录读取状态
    - 支持分页读取（offset + limit）
    - 并发安全，可与其他只读工具并行执行
    """
    name = "ReadFile"
    description = "Read a file and return its contents with line numbers."
    params_model = Params
    category = "read"
    is_concurrency_safe = True


    def __init__(self, file_cache: FileCache | None = None, file_state_cache: FileStateCache | None = None) -> None:
        self._cache = file_cache          # 文件内容缓存（可选）
        self._state_cache = file_state_cache  # 先读后写状态缓存（可选）


    async def execute(self, params: Params) -> ToolResult:
        path = Path(params.file_path)
        if not path.exists():
            return ToolResult(output=f"Error: file not found: {params.file_path}", is_error=True)
        if not path.is_file():
            return ToolResult(output=f"Error: not a file: {params.file_path}", is_error=True)

        resolved = str(path.resolve())

        # 尝试从缓存读取，否则从文件系统读取
        try:
            text = self._cache.get(resolved) if self._cache else None
            if text is None:
                text = path.read_text(encoding="utf-8")
                if self._cache:
                    self._cache.put(resolved, text)
        except Exception as e:
            return ToolResult(output=f"Error reading file: {e}", is_error=True)

        # 记录文件状态到 FileStateCache（用于先读后写检查）
        if self._state_cache:
            try:
                mtime_ns = path.stat().st_mtime_ns
                self._state_cache.record(resolved, text, mtime_ns)
            except OSError:
                pass

        # 分页截取并添加行号
        lines = text.splitlines()
        selected = lines[params.offset : params.offset + params.limit]
        numbered = [f"{i + params.offset + 1}\t{line}" for i, line in enumerate(selected)]
        return ToolResult(output="\n".join(numbered))
