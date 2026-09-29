"""
edit_file.py — 文件编辑工具（精确替换）
================================================

【这个模块做什么】
在文件中查找并替换精确匹配的字符串。

【与 WriteFile 的区别】
- WriteFile: 覆盖整个文件内容
- EditFile: 只替换文件中唯一匹配的字符串（更精确、更安全）

【安全约束】
- old_string 必须在文件中唯一出现（防止误替换）
- 必须先 ReadFile 读取文件才能编辑

【工作流程】
1. 检查文件存在
2. 检查先读后写约束
3. 读取文件内容
4. 验证 old_string 唯一性
5. 执行替换并写入
6. 更新缓存
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
    """EditFile 参数模型"""
    file_path: str = Field(description="Path to the file to edit")
    old_string: str = Field(description="The exact string to find and replace (must be unique in file)")
    new_string: str = Field(description="The replacement string")


class EditFile(Tool):
    """
    文件编辑工具 — 精确替换文件中的字符串。
    
    特性:
    - old_string 必须唯一（防止误替换）
    - 必须先读取文件才能编辑
    - 支持文件历史追踪
    """
    name = "EditFile"
    description = (
        "Replace an exact string in a file. The old_string must appear exactly once in the file.\n"
        "You MUST read the file with ReadFile before editing. This tool will fail otherwise."
    )
    params_model = Params
    category = "write"


    def __init__(self, file_cache: FileCache | None = None, file_history: Any = None, file_state_cache: FileStateCache | None = None) -> None:
        self._cache = file_cache              # 文件内容缓存
        self.file_history = file_history      # 文件历史追踪
        self._state_cache = file_state_cache  # 先读后写状态缓存


    async def execute(self, params: Params) -> ToolResult:
        # 1. 追踪编辑行为
        if self.file_history is not None:
            self.file_history.track_edit(params.file_path)

        path = Path(params.file_path)
        if not path.exists():
            return ToolResult(output=f"Error: file not found: {params.file_path}", is_error=True)

        # 2. 检查先读后写约束
        if self._state_cache:
            resolved = str(path.resolve())
            ok, err_msg = self._state_cache.check(resolved)
            if not ok:
                return ToolResult(output=err_msg, is_error=True)

        # 3. 读取文件内容
        try:
            content = path.read_text(encoding="utf-8")
        except Exception as e:
            return ToolResult(output=f"Error reading file: {e}", is_error=True)

        # 4. 验证 old_string 唯一性
        count = content.count(params.old_string)
        if count == 0:
            return ToolResult(output="Error: old_string not found in file", is_error=True)
        if count > 1:
            return ToolResult(
                output=f"Error: old_string found {count} times, must be unique",
                is_error=True,
            )

        # 5. 执行替换并写入
        new_content = content.replace(params.old_string, params.new_string, 1)
        try:
            path.write_text(new_content, encoding="utf-8")
            # 6. 更新缓存
            if self._cache:
                self._cache.invalidate(str(path.resolve()))
            if self._state_cache:
                self._state_cache.update(str(path.resolve()))
        except Exception as e:
            return ToolResult(output=f"Error writing file: {e}", is_error=True)

        return ToolResult(output=f"Successfully edited {params.file_path}")
