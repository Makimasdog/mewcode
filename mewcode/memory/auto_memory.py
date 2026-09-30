from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any

from mewcode.conversation import ConversationManager, Message
from mewcode.memory.migration import import_legacy_memory
from mewcode.memory.store import MemoryItem, MemoryStore

USER_MEMORIES_RELPATH = ".mewcode/memories.md"
PROJECT_MEMORIES_RELPATH = ".mewcode/memories.md"

MEMORY_EXTRACTION_PROMPT = """\
你是一个记忆提取助手。分析下面的对话，提取值得长期记忆的信息，更新 memories.md。

分类规则：
- **用户偏好**：用户的编码习惯和风格要求（如缩进、命名规范、语言偏好）
- **纠正反馈**：用户明确指出的错误和正确做法
- **项目知识**：当前项目的具体技术信息（技术栈、目录结构、部署方式）
- **参考资料**：外部链接和文档地址

规则：
1. 已有相同含义的条目不要重复添加
2. 没有值得记忆的内容，该分类下留空（不要写任何条目，不要写占位符）
3. 每条记忆用一行 `- ` 开头，必须是具体内容，不要用 `...` 占位
4. 输出完整的 memories.md 内容，包含所有四个分类标题

输出格式（严格遵守，没有内容的分类下不写任何条目）：
### 用户偏好
- 用户偏好简洁代码风格

### 纠正反馈

### 项目知识
- 项目使用 PostgreSQL 15

### 参考资料

不要输出任何其他内容，不要调用任何工具。"""

_USER_LEVEL_HEADERS = {"用户偏好", "纠正反馈"}
_PROJECT_LEVEL_HEADERS = {"项目知识", "参考资料"}


class MemoryManager:
    def __init__(self, project_root: str, storage_mode: str | None = None) -> None:
        self._user_path = Path.home() / USER_MEMORIES_RELPATH
        self._project_path = Path(project_root) / PROJECT_MEMORIES_RELPATH
        self._last_extraction_msg_count = 0
        # ``dual`` is the safe rollout mode: old Markdown remains readable and
        # writable while structured records are built alongside it. Set
        # MEWCODE_MEMORY_MODE=legacy to preserve the pre-upgrade behavior.
        self.storage_mode = storage_mode or os.environ.get("MEWCODE_MEMORY_MODE", "dual")
        if self.storage_mode not in {"legacy", "dual", "structured"}:
            self.storage_mode = "dual"
        self._user_store: MemoryStore | None = None
        self._project_store: MemoryStore | None = None


    @property
    def user_path(self) -> Path:
        return self._user_path


    @property
    def project_path(self) -> Path:
        return self._project_path

    @property
    def user_mem_dir(self) -> Path:
        """User-level memory directory (~/.mewcode/memory/).

        This is where .md memory files with frontmatter (type user/feedback)
        live. Distinct from ``user_path`` which points at the flat
        ``memories.md`` file.
        """
        return Path.home() / ".mewcode" / "memory"

    @property
    def project_mem_dir(self) -> Path:
        """Project-level memory directory (<project>/.mewcode/memory/).

        This is where .md memory files with frontmatter (type
        project/reference) live. Distinct from ``project_path`` which
        points at the flat ``memories.md`` file.
        """
        return self._project_path.parent / "memory"

    @property
    def user_db_path(self) -> Path:
        return Path.home() / ".mewcode" / "memory.db"

    @property
    def project_db_path(self) -> Path:
        return self._project_path.parent / "memory.db"

    @property
    def user_store(self) -> MemoryStore | None:
        if self.storage_mode == "legacy":
            return None
        if self._user_store is None:
            try:
                self._user_store = MemoryStore(self.user_db_path)
            except (OSError, ValueError, sqlite3.DatabaseError):
                self._user_store = None
        return self._user_store

    @property
    def project_store(self) -> MemoryStore | None:
        if self.storage_mode == "legacy":
            return None
        if self._project_store is None:
            try:
                self._project_store = MemoryStore(self.project_db_path)
            except (OSError, ValueError, sqlite3.DatabaseError):
                self._project_store = None
        return self._project_store

    @staticmethod
    def _render_structured(items: list[MemoryItem]) -> str:
        headers = {
            "user": {"user": "### 用户偏好", "feedback": "### 纠正反馈"},
            "project": {"project": "### 项目知识", "reference": "### 参考资料"},
        }
        order = (("user", "user"), ("user", "feedback"), ("project", "project"), ("project", "reference"))
        grouped: dict[tuple[str, str], list[str]] = {}
        for item in items:
            if item.status != "active":
                continue
            grouped.setdefault((item.scope, item.type), []).append(item.content)
        parts: list[str] = []
        for key in order:
            values = grouped.get(key, [])
            if values:
                parts.append(headers[key[0]][key[1]] + "\n" + "\n".join(f"- {v}" for v in values))
        return "\n\n".join(parts)

    def _structured_items(self) -> list[MemoryItem]:
        result: list[MemoryItem] = []
        for store in (self.user_store, self.project_store):
            if store is not None:
                try:
                    result.extend(store.list(statuses=("active",)))
                except (OSError, ValueError, sqlite3.DatabaseError):
                    continue
        return result

    def load(self) -> str:
        sections: list[str] = []

        if self._user_path.exists():
            content = self._user_path.read_text(encoding="utf-8").strip()
            if content:
                sections.append(content)

        if self._project_path.exists():
            content = self._project_path.read_text(encoding="utf-8").strip()
            if content:
                sections.append(content)

        legacy = "\n\n".join(sections)
        if self.storage_mode == "legacy":
            return legacy

        # Structured records are rendered in the same four-heading format.
        # Deduplication by content prevents dual-write records from appearing
        # twice while retaining manually edited Markdown during migration.
        structured = self._render_structured(self._structured_items())
        if not structured:
            return legacy
        legacy_lower = legacy.casefold()
        extra_lines = [
            line for line in structured.splitlines()
            if not (line.startswith("- ") and line[2:].strip().casefold() in legacy_lower)
        ]
        if not extra_lines:
            return legacy
        extras = "\n".join(extra_lines)
        return "\n\n".join(part for part in (legacy, extras) if part)

    async def extract(
        self,
        client: Any,
        conversation: ConversationManager,
        protocol: str,
    ) -> None:
        from mewcode.tools.base import StreamEnd, TextDelta

        current_memories = self.load()

        recent = conversation.history[self._last_extraction_msg_count :]
        if not recent:
            return

        conv_lines: list[str] = []
        for msg in recent:
            if msg.role == "user" and msg.content:
                conv_lines.append(f"用户: {msg.content}")
            elif msg.role == "assistant" and msg.content:
                conv_lines.append(f"助手: {msg.content}")

        if not conv_lines:
            return

        prompt = (
            f"{MEMORY_EXTRACTION_PROMPT}\n\n"
            f"## 当前 memories.md\n"
            f"{current_memories if current_memories else '(空)'}\n\n"
            f"## 最近对话\n"
            f"{chr(10).join(conv_lines)}\n\n"
            f"请输出更新后的完整 memories.md 内容。"
        )

        extract_conv = ConversationManager()
        extract_conv.history = [Message(role="user", content=prompt)]

        collected = ""
        try:
            async for event in client.stream(
                extract_conv, system="你是一个记忆提取助手。"
            ):
                if isinstance(event, TextDelta):
                    collected += event.text
                elif isinstance(event, StreamEnd):
                    pass
        except Exception:
            return

        self._last_extraction_msg_count = len(conversation.history)

        collected = collected.strip()
        if not collected:
            return

        self._write_memories(collected)

    def _write_memories(self, content: str) -> None:
        user_sections: list[str] = []
        project_sections: list[str] = []

        current_header = ""
        current_lines: list[str] = []

        for line in content.split("\n"):
            if line.startswith("### "):
                if current_header:
                    self._assign_section(
                        current_header, current_lines, user_sections, project_sections
                    )
                current_header = line
                current_lines = []
            else:
                current_lines.append(line)

        if current_header:
            self._assign_section(
                current_header, current_lines, user_sections, project_sections
            )

        if user_sections:
            self._user_path.parent.mkdir(parents=True, exist_ok=True)
            self._user_path.write_text(
                "\n".join(user_sections).strip() + "\n", encoding="utf-8"
            )

        if project_sections:
            self._project_path.parent.mkdir(parents=True, exist_ok=True)
            self._project_path.write_text(
                "\n".join(project_sections).strip() + "\n", encoding="utf-8"
            )

        if self.storage_mode != "legacy":
            # Importing is idempotent and leaves the source Markdown intact.
            # It also lets old extraction prompts feed the new structured store
            # before JSON candidate extraction is enabled in a later phase.
            try:
                if self.user_store is not None:
                    import_legacy_memory(
                        self.user_store,
                        user_flat=self._user_path,
                        project_flat=Path("__nonexistent_project_memories__.md"),
                        user_dir=self.user_mem_dir,
                    )
                if self.project_store is not None:
                    import_legacy_memory(
                        self.project_store,
                        user_flat=Path("__nonexistent_user_memories__.md"),
                        project_flat=self._project_path,
                        project_dir=self.project_mem_dir,
                    )
            except (OSError, ValueError, sqlite3.DatabaseError):
                # Markdown remains the authoritative fallback if SQLite cannot
                # be opened or written.
                pass

    @staticmethod
    def _is_placeholder(line: str) -> bool:
        stripped = line.strip().lstrip("- ").strip()
        return stripped in {"", "...", "…", "无", "暂无", "N/A"}


    @staticmethod
    def _assign_section(
        header: str,
        lines: list[str],
        user_sections: list[str],
        project_sections: list[str],
    ) -> None:
        real_lines = [l for l in lines if l.strip().startswith("- ") and not MemoryManager._is_placeholder(l)]
        if not real_lines:
            return

        section_text = header + "\n" + "\n".join(real_lines)

        for keyword in _USER_LEVEL_HEADERS:
            if keyword in header:
                user_sections.append(section_text)
                return

        for keyword in _PROJECT_LEVEL_HEADERS:
            if keyword in header:
                project_sections.append(section_text)
                return


    def clear(self) -> None:
        if self._user_path.exists():
            self._user_path.write_text("", encoding="utf-8")
        if self._project_path.exists():
            self._project_path.write_text("", encoding="utf-8")
        if self.storage_mode != "legacy":
            for store in (self.user_store, self.project_store):
                if store is not None:
                    try:
                        store.clear()
                    except (OSError, ValueError, sqlite3.DatabaseError):
                        pass

    def import_legacy(self) -> int:
        """Import all supported Markdown memories without deleting them."""
        if self.storage_mode == "legacy":
            return 0
        count = 0
        if self.user_store is not None:
            count += import_legacy_memory(
                self.user_store,
                user_flat=self._user_path,
                project_flat=Path("__nonexistent_project_memories__.md"),
                user_dir=self.user_mem_dir,
            )
        if self.project_store is not None:
            count += import_legacy_memory(
                self.project_store,
                user_flat=Path("__nonexistent_user_memories__.md"),
                project_flat=self._project_path,
                project_dir=self.project_mem_dir,
            )
        return count

    def search(self, query: str, limit: int = 20) -> list[MemoryItem]:
        if self.storage_mode == "legacy":
            return []
        result: list[MemoryItem] = []
        for store in (self.user_store, self.project_store):
            if store is not None:
                try:
                    result.extend(store.search(query, limit=limit))
                except (OSError, ValueError, sqlite3.DatabaseError):
                    continue
        result.sort(key=lambda item: item.updated_at, reverse=True)
        return result[:limit]

    def get(self, memory_id: str) -> MemoryItem | None:
        if self.storage_mode == "legacy":
            return None
        for store in (self.user_store, self.project_store):
            if store is not None:
                item = store.get(memory_id)
                if item is not None:
                    return item
        return None

    def set_status(self, memory_id: str, status: str) -> bool:
        if self.storage_mode == "legacy":
            return False
        for store in (self.user_store, self.project_store):
            if store is not None and store.set_status(memory_id, status):
                return True
        return False

    def delete(self, memory_id: str) -> bool:
        if self.storage_mode == "legacy":
            return False
        for store in (self.user_store, self.project_store):
            if store is not None and store.delete(memory_id):
                return True
        return False

    def get_display_text(self) -> str:
        parts: list[str] = []

        if self._user_path.exists():
            content = self._user_path.read_text(encoding="utf-8").strip()
            if content:
                parts.append(f"[用户级] {self._user_path}\n{content}")

        if self._project_path.exists():
            content = self._project_path.read_text(encoding="utf-8").strip()
            if content:
                parts.append(f"[项目级] {self._project_path}\n{content}")

        if self.storage_mode != "legacy":
            try:
                self.import_legacy()
            except (OSError, ValueError, sqlite3.DatabaseError):
                pass
            structured = self._render_structured(self._structured_items())
            if structured and not parts:
                parts.append(f"[结构化记忆] 用户数据库: {self.user_db_path}\n{structured}")

        if not parts:
            return "当前没有任何自动记忆。"

        return "\n\n".join(parts)
