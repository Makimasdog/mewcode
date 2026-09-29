"""
store.py — Agent 运行持久化存储
=============================================================

【这个模块做什么】
提供 Agent 运行的本地持久化存储：
- 快照存储: JSON 文件保存运行状态（用于快速查询）
- 事件日志: JSONL 文件追加写入事件（用于回放和调试）

【存储结构】
.mewcode/runs/
├── {run_id}.json          # 运行快照（最新状态）
└── {run_id}.events.jsonl  # 事件日志（完整时间线）

【设计亮点】
- 原子写入: 先写临时文件再 rename，避免写入中断导致数据损坏
- 双文件策略: 快照 + 事件日志分离，查询和回放互不影响
- 线程安全: 使用 RLock 保护并发写入
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Iterable

from mewcode.runtime.models import AgentRun, RunEvent


class RunStore:
    """
    Agent 运行存储 — 本地文件存储实现。
    
    存储策略：
    - 快照 (JSON): 保存运行的最新状态，查询快速
    - 事件 (JSONL): 追加写入完整事件流，支持回放
    
    原子写入流程：
    1. 写入临时文件 .json.tmp
    2. 原子替换为最终文件 .json
    """

    def __init__(self, root: str | Path = ".mewcode/runs") -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)  # 自动创建存储目录
        self._lock = threading.RLock()  # 线程锁（保护并发写入）

    def _snapshot_path(self, run_id: str) -> Path:
        """获取快照文件路径"""
        return self.root / f"{run_id}.json"

    def _events_path(self, run_id: str) -> Path:
        """获取事件日志路径"""
        return self.root / f"{run_id}.events.jsonl"

    def save(self, run: AgentRun) -> None:
        """
        保存运行快照（原子写入）。
        
        流程：先写 .tmp 文件，再 rename 为最终文件。
        这样即使写入中断，也不会损坏现有快照。
        """
        payload = json.dumps(run.to_dict(), ensure_ascii=False, indent=2)
        path = self._snapshot_path(run.id)
        tmp = path.with_suffix(".json.tmp")  # 临时文件
        with self._lock:
            tmp.write_text(payload, encoding="utf-8")
            tmp.replace(path)  # 原子替换

    def load(self, run_id: str) -> AgentRun | None:
        """加载运行快照（找不到或损坏返回 None）"""
        path = self._snapshot_path(run_id)
        try:
            return AgentRun.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return None

    def list_runs(self) -> list[AgentRun]:
        """列出所有运行（按创建时间倒序）"""
        result: list[AgentRun] = []
        for path in self.root.glob("*.json"):
            if path.name.endswith(".tmp"):  # 跳过临时文件
                continue
            run = self.load(path.stem)
            if run is not None:
                result.append(run)
        result.sort(key=lambda r: r.created_at, reverse=True)
        return result

    def append_event(
        self,
        run_id: str,
        event_type: str,
        payload: dict | None = None,
    ) -> RunEvent:
        """
        追加事件到日志（JSONL 格式）。
        
        自动计算序号：读取最后一行的序号 + 1。
        如果日志为空或损坏，回退到计数行数。
        """
        path = self._events_path(run_id)
        with self._lock:
            sequence = 1
            if path.exists():
                try:
                    # 快速路径：读取最后一行获取序号
                    last = next(reversed(path.read_text(encoding="utf-8").splitlines()))
                    sequence = RunEvent.from_dict(json.loads(last)).sequence + 1
                except (OSError, StopIteration, json.JSONDecodeError, KeyError, ValueError):
                    # 慢速路径：日志损坏时回退到计数
                    sequence = sum(1 for _ in self._read_events_unlocked(run_id)) + 1
            event = RunEvent(
                run_id=run_id,
                sequence=sequence,
                event_type=event_type,
                payload=dict(payload or {}),
            )
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")
                fh.flush()  # 立即刷盘，确保事件不丢失
            return event

    def _read_events_unlocked(self, run_id: str) -> Iterable[RunEvent]:
        """读取所有事件（内部方法，不获取锁）"""
        path = self._events_path(run_id)
        if not path.exists():
            return []
        events: list[RunEvent] = []
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    events.append(RunEvent.from_dict(json.loads(line)))
                except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                    continue  # 跳过损坏的行
        except OSError:
            return []
        return events

    def events(self, run_id: str, after: int = 0) -> list[RunEvent]:
        """
        读取事件（支持分页）。
        
        after: 只返回序号大于 after 的事件（用于增量拉取）
        """
        with self._lock:
            return [e for e in self._read_events_unlocked(run_id) if e.sequence > after]
