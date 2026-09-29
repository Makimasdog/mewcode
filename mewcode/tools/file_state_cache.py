"""
file_state_cache.py — 先读后写安全机制
================================================

【这个模块做什么】
确保 Agent 在编辑文件之前必须先读取文件内容。

【为什么需要这个】
防止 Agent 意外覆盖未查看的文件，或基于过期内容编辑。
这是一个安全约束，强制 Agent 先「看」再「改」。

【工作原理】
1. ReadFile 读取文件后，调用 record() 记录文件路径、内容和修改时间
2. EditFile/WriteFile 写入前，调用 check() 验证：
   - Gate 1: 文件是否已被读取过？
   - Gate 2: 文件是否被外部修改过？（mtime 变化）
3. 写入成功后，调用 update() 更新缓存

【存储结构】
_cache: { 绝对路径: (文件内容, mtime_ns) }
"""

from __future__ import annotations

from pathlib import Path


class FileStateCache:
    """
    文件状态缓存 — 追踪文件的读取状态，强制先读后写。
    
    存储结构: { 绝对路径: (内容, mtime_ns) }
    
    工作流程:
    1. ReadFile 调用 record() 记录文件状态
    2. EditFile/WriteFile 调用 check() 验证安全性
    3. 写入成功后调用 update() 更新缓存
    """

    def __init__(self) -> None:
        self._cache: dict[str, tuple[str, int]] = {}

    def record(self, path: str, content: str, mtime_ns: int) -> None:
        """
        记录文件的读取状态。
        
        由 ReadFile 在成功读取文件后调用。
        """
        self._cache[path] = (content, mtime_ns)

    def check(self, path: str) -> tuple[bool, str]:
        """
        检查文件是否可以安全编辑。
        
        返回 (ok, error_message):
        - ok=True: 可以编辑
        - ok=False: 不能编辑，error_message 说明原因
        
        检查逻辑:
        1. 文件是否已被读取过？（存在于缓存中）
        2. 文件是否被外部修改过？（mtime 是否变化）
        """
        entry = self._cache.get(path)
        if entry is None:
            return False, "Error: file has not been read yet. Read it first before editing."

        _, cached_mtime_ns = entry
        try:
            current_mtime_ns = Path(path).stat().st_mtime_ns
        except OSError:
            # 文件可能已被删除，允许写入继续
            # (WriteFile 会创建新文件，EditFile 会自行报错)
            return True, ""

        if current_mtime_ns != cached_mtime_ns:
            return False, "Error: file has been modified since last read. Read it again before editing."

        return True, ""

    def update(self, path: str) -> None:
        """
        写入成功后更新缓存。
        
        重新读取文件内容并更新 mtime，确保下次 check() 基于最新状态。
        """
        try:
            p = Path(path)
            content = p.read_text(encoding="utf-8")
            mtime_ns = p.stat().st_mtime_ns
            self._cache[path] = (content, mtime_ns)
        except OSError:
            # 如果无法读回，移除过期条目
            self._cache.pop(path, None)
