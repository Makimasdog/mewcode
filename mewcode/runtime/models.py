"""
models.py — Agent 运行时数据模型
=============================================================

【这个模块做什么】
定义 Agent 运行的核心数据结构：
- RunStatus: 运行状态枚举
- AgentRun: 单次 Agent 执行的完整描述
- RunEvent: 运行过程中的事件记录

【为什么需要这个】
Agent 运行可能持续数分钟甚至数小时，需要：
1. 持久化运行状态（进程重启后可恢复）
2. 记录事件流（用于调试和回放）
3. 支持重试和超时机制

【状态机】
PENDING → RUNNING → COMPLETED
                  → FAILED
                  → WAITING_APPROVAL → RUNNING
         → CANCELLED
"""
from __future__ import annotations

import enum
import time
import uuid
from dataclasses import dataclass, field
from typing import Any


class RunStatus(str, enum.Enum):
    """
    Agent 运行状态枚举。
    
    状态流转：
    PENDING → RUNNING → COMPLETED/FAILED
                      → WAITING_APPROVAL → RUNNING
    任何状态 → CANCELLED
    """
    PENDING = "pending"                  # 待执行
    RUNNING = "running"                  # 执行中
    WAITING_APPROVAL = "waiting_approval"  # 等待用户审批
    COMPLETED = "completed"              # 已完成
    FAILED = "failed"                    # 失败
    CANCELLED = "cancelled"              # 已取消


@dataclass
class AgentRun:
    """
    Agent 运行记录 — 单次 Agent 执行的完整描述。
    
    设计亮点：
    - task 和 session_id 被持久化，进程重启后可重建运行
    - 支持重试机制（attempt/max_attempts）
    - 支持超时控制（timeout_seconds）
    - 支持元数据扩展（metadata）
    """

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])  # 运行 ID
    task: str = ""                    # 任务描述（给 Agent 的提示词）
    session_id: str = ""              # 会话 ID（用于恢复对话上下文）
    status: RunStatus = RunStatus.PENDING  # 当前状态
    attempt: int = 0                  # 当前重试次数
    max_attempts: int = 1             # 最大重试次数
    timeout_seconds: float | None = None  # 超时时间（秒）
    result: str = ""                  # 执行结果
    error: str = ""                   # 错误信息
    metadata: dict[str, Any] = field(default_factory=dict)  # 扩展元数据
    created_at: float = field(default_factory=time.time)    # 创建时间
    started_at: float | None = None   # 开始时间
    ended_at: float | None = None     # 结束时间

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典（用于 JSON 持久化）"""
        return {
            "id": self.id,
            "task": self.task,
            "session_id": self.session_id,
            "status": self.status.value,
            "attempt": self.attempt,
            "max_attempts": self.max_attempts,
            "timeout_seconds": self.timeout_seconds,
            "result": self.result,
            "error": self.error,
            "metadata": self.metadata,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentRun:
        """从字典反序列化（用于恢复持久化的运行记录）"""
        raw_status = data.get("status", RunStatus.PENDING.value)
        try:
            status = RunStatus(raw_status)
        except ValueError:
            status = RunStatus.FAILED
        return cls(
            id=str(data.get("id") or uuid.uuid4().hex[:12]),
            task=str(data.get("task", "")),
            session_id=str(data.get("session_id", "")),
            status=status,
            attempt=int(data.get("attempt", 0)),
            max_attempts=max(1, int(data.get("max_attempts", 1))),
            timeout_seconds=data.get("timeout_seconds"),
            result=str(data.get("result", "")),
            error=str(data.get("error", "")),
            metadata=dict(data.get("metadata") or {}),
            created_at=float(data.get("created_at", time.time())),
            started_at=data.get("started_at"),
            ended_at=data.get("ended_at"),
        )


@dataclass(frozen=True)
class RunEvent:
    """
    运行事件 — 运行过程中的事件记录。
    
    事件流用于：
    - 实时 SSE 推送给客户端
    - 调试和回放
    - 审计日志
    
    frozen=True: 事件一旦创建不可修改（保证事件流的完整性）
    """
    run_id: str           # 所属运行 ID
    sequence: int         # 事件序号（单调递增，用于排序和去重）
    event_type: str       # 事件类型（如 run_created, run_started, run_completed）
    payload: dict[str, Any] = field(default_factory=dict)  # 事件数据
    timestamp: float = field(default_factory=time.time)    # 事件时间

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典"""
        return {
            "run_id": self.run_id,
            "sequence": self.sequence,
            "event_type": self.event_type,
            "payload": self.payload,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RunEvent:
        """从字典反序列化"""
        return cls(
            run_id=str(data["run_id"]),
            sequence=int(data["sequence"]),
            event_type=str(data["event_type"]),
            payload=dict(data.get("payload") or {}),
            timestamp=float(data.get("timestamp", time.time())),
        )
