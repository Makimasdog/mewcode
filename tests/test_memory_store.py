from __future__ import annotations

from pathlib import Path

from mewcode.memory.auto_memory import MemoryManager
from mewcode.memory.migration import import_legacy_memory
from mewcode.memory.store import MemoryItem, MemoryStore


def test_store_upsert_search_status_and_delete(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    item = MemoryItem(
        id="",
        scope="user",
        type="user",
        content="用户偏好使用中文回答",
        tags=("language",),
    )
    created = store.upsert(item)
    duplicate = store.upsert(item)
    assert created.id == duplicate.id
    assert len(store.list()) == 1
    assert store.search("中文")[0].content == item.content
    assert store.set_status(created.id, "archived") is True
    assert store.search("中文") == []
    assert store.delete(created.id) is True
    assert store.get(created.id) is None


def test_markdown_import_is_idempotent(tmp_path: Path) -> None:
    user_flat = tmp_path / "home" / ".mewcode" / "memories.md"
    project_flat = tmp_path / "project" / ".mewcode" / "memories.md"
    user_flat.parent.mkdir(parents=True)
    project_flat.parent.mkdir(parents=True)
    user_flat.write_text("### 用户偏好\n- 使用中文\n", encoding="utf-8")
    project_flat.write_text("### 项目知识\n- 使用 SQLite\n", encoding="utf-8")

    store = MemoryStore(tmp_path / "memory.db")
    kwargs = {
        "user_flat": user_flat,
        "project_flat": project_flat,
    }
    assert import_legacy_memory(store, **kwargs) == 2
    assert import_legacy_memory(store, **kwargs) == 0
    assert len(store.list(statuses=("active",))) == 2


def test_memory_manager_dual_mode_keeps_legacy_and_structured(
    tmp_path: Path, monkeypatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    project = tmp_path / "project"
    manager = MemoryManager(str(project), storage_mode="dual")

    manager._write_memories("### 用户偏好\n- 使用中文\n### 项目知识\n- 使用 SQLite\n")

    assert manager.user_path.exists()
    assert manager.project_path.exists()
    assert "使用中文" in manager.load()
    assert "使用 SQLite" in manager.load()
    assert manager.search("SQLite")[0].content == "使用 SQLite"
