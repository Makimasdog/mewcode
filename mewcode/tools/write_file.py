"""
write_file.py — 文件写入工具
================================================

【这个模块做什么】
将内容写入文件，支持创建新文件或覆盖现有文件。

【安全约束】
- 必须先 ReadFile 读取现有文件才能覆盖（通过 FileStateCache 检查）
- 自动创建父目录
- 写入后更新 FileStateCache 状态

【工作流程】
1. 检查文件历史追踪（file_history.track_edit）
2. 检查先读后写约束（FileStateCache.check）
3. 创建父目录 + 写入文件
4. 更新缓存（FileCache.invalidate + FileStateCache.update）
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from mewcode.tools.base import Tool, ToolResult

if TYPE_CHECKING:
    from mewcode.cache import FileCache
    from mewcode.tools.file_state_cache import FileStateCache


class Params(BaseModel):
    """WriteFile 参数模型"""
    file_path: str = Field(description="Path to the file to write")
    content: str = Field(description="Content to write to the file")


class WriteFile(Tool):
    """
    文件写入工具 — 将内容写入文件。
    
    特性:
    - 覆盖现有文件前必须先读取（安全约束）
    - 自动创建父目录
    - 支持文件历史追踪
    """
    name = "WriteFile"
    description = (
        "Write content to a file, creating parent directories if needed. Overwrites existing files.\n"
        "You MUST read existing files with ReadFile before overwriting them. This tool will fail otherwise."
    )
    params_model = Params
    category = "write"


    def __init__(self, file_cache: FileCache | None = None, file_history: Any = None, file_state_cache: FileStateCache | None = None) -> None:
        self._cache = file_cache              # 文件内容缓存
        self.file_history = file_history      # 文件历史追踪（用于回滚）
        self._state_cache = file_state_cache  # 先读后写状态缓存


    async def execute(self, params: Params) -> ToolResult:
        # 1. 追踪编辑行为（用于文件历史/回滚）
        if self.file_history is not None:
            self.file_history.track_edit(params.file_path)

        path = Path(params.file_path)

        # 2. 检查先读后写约束（文件存在时）
        if self._state_cache and path.exists():
            resolved = str(path.resolve())
            ok, err_msg = self._state_cache.check(resolved)
            if not ok:
                return ToolResult(output=err_msg, is_error=True)

        # 3. 创建父目录 + 写入文件
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(params.content, encoding="utf-8")
            # 4. 更新缓存
            if self._cache:
                self._cache.invalidate(str(path.resolve()))
            if self._state_cache:
                self._state_cache.update(str(path.resolve()))
        except Exception as e:
            return ToolResult(output=f"Error writing file: {e}", is_error=True)
        return ToolResult(output=f"Successfully wrote to {params.file_path}")
