from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Iterable

from mewcode.runtime.models import AgentRun, RunEvent


class RunStore:
    """Small append-only event store for local Agent Runtime deployments.

    A JSON snapshot makes status queries cheap while the per-run JSONL file
    preserves the execution timeline for replay and debugging.
    """

    def __init__(self, root: str | Path = ".mewcode/runs") -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def _snapshot_path(self, run_id: str) -> Path:
        return self.root / f"{run_id}.json"

    def _events_path(self, run_id: str) -> Path:
        return self.root / f"{run_id}.events.jsonl"

    def save(self, run: AgentRun) -> None:
        payload = json.dumps(run.to_dict(), ensure_ascii=False, indent=2)
        path = self._snapshot_path(run.id)
        tmp = path.with_suffix(".json.tmp")
        with self._lock:
            tmp.write_text(payload, encoding="utf-8")
            tmp.replace(path)

    def load(self, run_id: str) -> AgentRun | None:
        path = self._snapshot_path(run_id)
        try:
            return AgentRun.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return None

    def list_runs(self) -> list[AgentRun]:
        result: list[AgentRun] = []
        for path in self.root.glob("*.json"):
            if path.name.endswith(".tmp"):
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
        path = self._events_path(run_id)
        with self._lock:
            sequence = 1
            if path.exists():
                try:
                    last = next(reversed(path.read_text(encoding="utf-8").splitlines()))
                    sequence = RunEvent.from_dict(json.loads(last)).sequence + 1
                except (OSError, StopIteration, json.JSONDecodeError, KeyError, ValueError):
                    sequence = sum(1 for _ in self._read_events_unlocked(run_id)) + 1
            event = RunEvent(
                run_id=run_id,
                sequence=sequence,
                event_type=event_type,
                payload=dict(payload or {}),
            )
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")
                fh.flush()
            return event

    def _read_events_unlocked(self, run_id: str) -> Iterable[RunEvent]:
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
                    continue
        except OSError:
            return []
        return events

    def events(self, run_id: str, after: int = 0) -> list[RunEvent]:
        with self._lock:
            return [e for e in self._read_events_unlocked(run_id) if e.sequence > after]
