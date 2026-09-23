from __future__ import annotations

import enum
import time
import uuid
from dataclasses import dataclass, field
from typing import Any


class RunStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class AgentRun:
    """Durable description and latest state of one Agent execution.

    The task text and session id are deliberately persisted so a process restart
    can reconstruct the run with an application-provided agent factory.
    """

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    task: str = ""
    session_id: str = ""
    status: RunStatus = RunStatus.PENDING
    attempt: int = 0
    max_attempts: int = 1
    timeout_seconds: float | None = None
    result: str = ""
    error: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    ended_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
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
    run_id: str
    sequence: int
    event_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "sequence": self.sequence,
            "event_type": self.event_type,
            "payload": self.payload,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RunEvent:
        return cls(
            run_id=str(data["run_id"]),
            sequence=int(data["sequence"]),
            event_type=str(data["event_type"]),
            payload=dict(data.get("payload") or {}),
            timestamp=float(data.get("timestamp", time.time())),
        )
