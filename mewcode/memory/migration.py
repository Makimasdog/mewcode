from __future__ import annotations

from pathlib import Path

from mewcode.memory.recall import parse_frontmatter
from mewcode.memory.store import MemoryItem, MemoryStore, make_memory_id


HEADER_TO_TYPE = {
    "用户偏好": ("user", "user"),
    "纠正反馈": ("user", "feedback"),
    "项目知识": ("project", "project"),
    "参考资料": ("project", "reference"),
}


def _items_from_flat_file(path: Path) -> list[MemoryItem]:
    if not path.exists():
        return []
    items: list[MemoryItem] = []
    current_type: tuple[str, str] | None = None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("### "):
            current_type = HEADER_TO_TYPE.get(line[4:].strip())
            continue
        if current_type and line.strip().startswith("- "):
            content = line.strip()[2:].strip()
            if not content or content in {"...", "…", "无", "暂无", "N/A"}:
                continue
            scope, type_ = current_type
            items.append(
                MemoryItem(
                    id=make_memory_id(scope, type_, content),
                    scope=scope,
                    type=type_,
                    content=content,
                )
            )
    return items


def _items_from_memory_dir(path: Path, scope: str) -> list[MemoryItem]:
    if not path.is_dir():
        return []
    result: list[MemoryItem] = []
    for file_path in sorted(path.rglob("*.md")):
        if file_path.name == "MEMORY.md":
            continue
        text = file_path.read_text(encoding="utf-8", errors="replace")
        fm = parse_frontmatter(text)
        type_ = fm.get("type", "")
        if type_ not in {"user", "feedback", "project", "reference"}:
            continue
        body = text
        if text.startswith("---"):
            end = text.find("\n---", 3)
            if end >= 0:
                body = text[end + 4 :]
        content = body.strip()
        if not content:
            continue
        result.append(
            MemoryItem(
                id=make_memory_id(scope, type_, content),
                scope=scope,
                type=type_,
                content=content,
                summary=fm.get("description", ""),
                tags=(fm.get("name", ""),) if fm.get("name") else (),
            )
        )
    return result


def import_legacy_memory(
    store: MemoryStore,
    *,
    user_flat: Path,
    project_flat: Path,
    user_dir: Path | None = None,
    project_dir: Path | None = None,
) -> int:
    """Import legacy files idempotently; never deletes or modifies source files."""
    items = _items_from_flat_file(user_flat)
    items.extend(_items_from_flat_file(project_flat))
    if user_dir is not None:
        items.extend(_items_from_memory_dir(user_dir, "user"))
    if project_dir is not None:
        items.extend(_items_from_memory_dir(project_dir, "project"))
    count = 0
    for item in items:
        before = store.get(item.id)
        store.upsert(item)
        if before is None:
            count += 1
    return count
