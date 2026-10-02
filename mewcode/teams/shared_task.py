"""
shared_task.py — 共享任务存储（团队协作的任务看板）
=============================================================

【这个模块做什么】
实现 SharedTaskStore：一个基于 JSON 文件的共享任务看板，
让团队中的所有 Agent 都能看到和管理共同的任务列表。

【为什么需要它？】
多 Agent 协作时，需要一种机制来：
- 分配任务给不同成员
- 追踪任务状态（待办/进行中/完成/阻塞）
- 表达任务间的依赖关系（A 完成后才能开始 B）

【任务状态流转】
pending → in_progress → completed
                ↓
             blocked（等待其他任务完成）

【任务依赖】
- blocks:      本任务完成后才能解除阻塞的任务列表
- blocked_by:  本任务需要等待其完成的任务列表

例如：
  任务 1（设计数据库）blocks 任务 2（实现 API）
  → 任务 2 的 blocked_by 包含任务 1

【存储结构】
~/.mewcode/teams/<team>/tasks.json
{
  "next_id": 4,
  "tasks": [
    {"id": "1", "title": "设计数据库", "status": "completed", ...},
    {"id": "2", "title": "实现 API", "status": "in_progress", "blocked_by": ["1"], ...}
  ]
}

【并发安全】
每次读写操作都会重新加载文件（_load），确保获取最新状态。
这比内存缓存更安全（多进程场景下文件是唯一真实来源）。

【对外接口】
- SharedTask       任务数据类
- SharedTaskStore  任务存储类（CRUD + 持久化）
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class SharedTask:
    """
    共享任务。

    字段说明：
    - id:          任务 ID（自增数字的字符串形式）
    - title:       任务标题
    - description: 任务详细描述
    - status:      状态（pending / in_progress / completed / blocked）
    - assignee:    负责人（Agent ID 或名称）
    - blocks:      本任务阻塞的其他任务 ID 列表
    - blocked_by:  阻塞本任务的其他任务 ID 列表
    - created_by:  创建者（Agent ID 或名称）
    """
    id: str
    title: str
    description: str = ""
    status: str = "pending"  # pending | in_progress | completed | blocked
    assignee: str = ""
    blocks: list[str] = field(default_factory=list)
    blocked_by: list[str] = field(default_factory=list)
    created_by: str = ""


    def to_dict(self) -> dict[str, Any]:
        """序列化为字典"""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SharedTask:
        """从字典反序列化（忽略未知字段）"""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class SharedTaskStore:
    """
    基于 JSON 文件的共享任务存储。

    设计特点：
    - 每次操作前重新加载文件（确保多进程场景下数据一致性）
    - 自增 ID 持久化（next_id 存在 JSON 中，重启后不重复）
    - 支持按状态和负责人过滤查询
    - 依赖关系通过 blocks/blocked_by 列表维护（不自动传播）
    """


    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._next_id = 1
        self._tasks: dict[str, SharedTask] = {}
        self._load()

    def _load(self) -> None:
        """从 JSON 文件加载任务数据（每次操作前调用，确保数据最新）"""
        if not self._path.exists():
            return
        data = json.loads(self._path.read_text(encoding="utf-8"))
        self._next_id = data.get("next_id", 1)
        for t in data.get("tasks", []):
            task = SharedTask.from_dict(t)
            self._tasks[task.id] = task

    def _save(self) -> None:
        """将任务数据保存到 JSON 文件"""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "next_id": self._next_id,
            "tasks": [t.to_dict() for t in self._tasks.values()],
        }
        self._path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def create(
        self,
        title: str,
        description: str = "",
        assignee: str = "",
        blocks: list[str] | None = None,
        blocked_by: list[str] | None = None,
        created_by: str = "",
    ) -> SharedTask:
        """
        创建新任务。

        流程：分配 ID → 创建任务 → 保存到文件 → 返回任务
        """
        task_id = str(self._next_id)
        self._next_id += 1
        task = SharedTask(
            id=task_id,
            title=title,
            description=description,
            assignee=assignee,
            blocks=blocks or [],
            blocked_by=blocked_by or [],
            created_by=created_by,
        )
        self._tasks[task_id] = task
        self._save()
        return task

    def get(self, task_id: str) -> SharedTask | None:
        """按 ID 获取任务（先重新加载文件）"""
        self._load()
        return self._tasks.get(task_id)


    def list_tasks(
        self,
        status: str | None = None,
        assignee: str | None = None,
    ) -> list[SharedTask]:
        """
        列出任务（支持过滤）。

        参数：
        - status:   按状态过滤（如 "pending"、"in_progress"）
        - assignee: 按负责人过滤
        """
        self._load()
        result = list(self._tasks.values())
        if status:
            result = [t for t in result if t.status == status]
        if assignee:
            result = [t for t in result if t.assignee == assignee]
        return result


    def update(
        self,
        task_id: str,
        status: str | None = None,
        assignee: str | None = None,
        description: str | None = None,
        add_blocks: list[str] | None = None,
        add_blocked_by: list[str] | None = None,
    ) -> SharedTask | None:
        """
        更新任务（部分更新，只修改传入的字段）。

        参数：
        - task_id:       要更新的任务 ID
        - status:        新状态
        - assignee:      新负责人
        - description:   新描述
        - add_blocks:    追加阻塞关系（本任务阻塞这些任务）
        - add_blocked_by: 追加阻塞关系（这些任务阻塞本任务）
        """
        self._load()
        task = self._tasks.get(task_id)
        if task is None:
            return None
        if status is not None:
            task.status = status
        if assignee is not None:
            task.assignee = assignee
        if description is not None:
            task.description = description
        # 追加依赖关系（去重）
        if add_blocks:
            for bid in add_blocks:
                if bid not in task.blocks:
                    task.blocks.append(bid)
        if add_blocked_by:
            for bid in add_blocked_by:
                if bid not in task.blocked_by:
                    task.blocked_by.append(bid)
        self._save()
        return task

    def init_empty(self) -> None:
        """初始化为空任务存储（团队创建时调用）"""
        self._tasks.clear()
        self._next_id = 1
        self._save()
