from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncIterator, Callable
from typing import Any, TYPE_CHECKING

from mewcode.runtime.models import AgentRun, RunEvent, RunStatus
from mewcode.runtime.store import RunStore

if TYPE_CHECKING:
    from mewcode.agent import Agent
    from mewcode.conversation import ConversationManager

log = logging.getLogger(__name__)

AgentFactory = Callable[[AgentRun], "Agent"]
ConversationFactory = Callable[[AgentRun], "ConversationManager | None"]
ConversationSaver = Callable[[AgentRun, "ConversationManager", int], None]


class AgentRuntime:
    """Application service for durable Agent runs.

    The runtime has no dependency on Textual or FastAPI. A CLI, HTTP server, or
    worker can submit the same run and consume the same persisted event stream.
    """

    def __init__(
        self,
        agent_factory: AgentFactory | None = None,
        conversation_factory: ConversationFactory | None = None,
        conversation_saver: ConversationSaver | None = None,
        store: RunStore | None = None,
    ) -> None:
        self.agent_factory = agent_factory
        self.conversation_factory = conversation_factory
        self.conversation_saver = conversation_saver
        self.store = store or RunStore()
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._agents: dict[str, Agent] = {}
        self._subscribers: dict[str, set[asyncio.Queue[RunEvent]]] = {}
        self._lock = asyncio.Lock()

    def submit(
        self,
        task: str,
        *,
        agent: Agent | None = None,
        session_id: str = "",
        max_attempts: int = 1,
        timeout_seconds: float | None = None,
        metadata: dict[str, Any] | None = None,
        run_id: str | None = None,
    ) -> AgentRun:
        """Persist and schedule a run. Must be called inside an event loop."""
        run = AgentRun(
            id=run_id or uuid.uuid4().hex[:12],
            task=task,
            session_id=session_id,
            max_attempts=max(1, max_attempts),
            timeout_seconds=timeout_seconds,
            metadata=dict(metadata or {}),
        )
        if agent is None and self.agent_factory is None:
            raise ValueError("AgentRuntime requires an agent or agent_factory")
        self.store.save(run)
        self._emit(run.id, "run_created", run.to_dict())
        self._tasks[run.id] = asyncio.create_task(self._execute(run, agent))
        return run

    async def _execute(self, run: AgentRun, initial_agent: Agent | None) -> None:
        try:
            while run.attempt < run.max_attempts:
                run.attempt += 1
                run.status = RunStatus.RUNNING
                run.started_at = run.started_at or time.time()
                run.error = ""
                self.store.save(run)
                self._emit(run.id, "run_started", {"attempt": run.attempt})

                agent = initial_agent if run.attempt == 1 and initial_agent is not None else None
                if agent is None:
                    if self.agent_factory is None:
                        raise RuntimeError("No agent factory configured for run")
                    agent = self.agent_factory(run)
                self._agents[run.id] = agent

                callback = lambda event: self._on_agent_event(run.id, event)
                conversation = (
                    self.conversation_factory(run)
                    if self.conversation_factory is not None
                    else None
                )
                history_before = len(conversation.history) if conversation is not None else 0
                coro = agent.run_to_completion(run.task, conversation, event_callback=callback)
                try:
                    if run.timeout_seconds and run.timeout_seconds > 0:
                        result = await asyncio.wait_for(coro, timeout=run.timeout_seconds)
                    else:
                        result = await coro
                except asyncio.TimeoutError:
                    run.error = f"run timed out after {run.timeout_seconds}s"
                    self._emit(run.id, "run_timeout", {"attempt": run.attempt})
                else:
                    run.result = result or ""
                    if conversation is not None and self.conversation_saver is not None:
                        self.conversation_saver(run, conversation, history_before)
                    run.status = RunStatus.COMPLETED
                    run.ended_at = time.time()
                    self.store.save(run)
                    self._emit(run.id, "run_completed", {"result": run.result})
                    return

                if run.attempt < run.max_attempts:
                    self._emit(
                        run.id,
                        "run_retrying",
                        {"attempt": run.attempt, "next_attempt": run.attempt + 1},
                    )
                    await asyncio.sleep(min(2 ** (run.attempt - 1), 8))
                    continue

                run.status = RunStatus.FAILED
                run.ended_at = time.time()
                self.store.save(run)
                self._emit(run.id, "run_failed", {"error": run.error})
                return
        except asyncio.CancelledError:
            run.status = RunStatus.CANCELLED
            run.error = "run cancelled"
            run.ended_at = time.time()
            self.store.save(run)
            self._emit(run.id, "run_cancelled", {})
            raise
        except Exception as exc:
            log.exception("Agent run %s failed", run.id)
            run.error = str(exc)
            if run.attempt < run.max_attempts:
                self._emit(run.id, "run_retrying", {"error": str(exc)})
                await asyncio.sleep(min(2 ** max(run.attempt - 1, 0), 8))
                await self._execute(run, None)
                return
            run.status = RunStatus.FAILED
            run.ended_at = time.time()
            self.store.save(run)
            self._emit(run.id, "run_failed", {"error": run.error})
        finally:
            self._tasks.pop(run.id, None)
            self._agents.pop(run.id, None)

    def _on_agent_event(self, run_id: str, event: dict[str, Any]) -> None:
        event_type = str(event.get("type", "agent_event"))
        self._emit(run_id, event_type, event)

    def _emit(self, run_id: str, event_type: str, payload: dict[str, Any]) -> RunEvent:
        event = self.store.append_event(run_id, event_type, payload)
        for queue in list(self._subscribers.get(run_id, set())):
            queue.put_nowait(event)
        return event

    def get(self, run_id: str) -> AgentRun | None:
        return self.store.load(run_id)

    def list_runs(self) -> list[AgentRun]:
        return self.store.list_runs()

    def cancel(self, run_id: str) -> bool:
        task = self._tasks.get(run_id)
        if task is None or task.done():
            return False
        task.cancel()
        return True

    def events(self, run_id: str, after: int = 0) -> list[RunEvent]:
        return self.store.events(run_id, after=after)

    async def subscribe(self, run_id: str, after: int = 0) -> AsyncIterator[RunEvent]:
        """Replay persisted events and then follow live events."""
        replayed = self.store.events(run_id, after=after)
        for event in replayed:
            yield event
        if replayed and replayed[-1].event_type in {
            "run_completed",
            "run_failed",
            "run_cancelled",
        }:
            return
        queue: asyncio.Queue[RunEvent] = asyncio.Queue()
        self._subscribers.setdefault(run_id, set()).add(queue)
        try:
            while True:
                event = await queue.get()
                yield event
                if event.event_type in {"run_completed", "run_failed", "run_cancelled"}:
                    break
        finally:
            self._subscribers.get(run_id, set()).discard(queue)

    async def recover(self) -> list[AgentRun]:
        """Re-schedule pending/running runs after a process restart.

        Exact conversation recovery is delegated to ``conversation_factory``;
        without an agent factory the run remains on disk for an operator to
        inspect instead of being silently discarded.
        """
        recovered: list[AgentRun] = []
        if self.agent_factory is None:
            return recovered
        for run in self.store.list_runs():
            if run.status not in {RunStatus.PENDING, RunStatus.RUNNING}:
                continue
            run.status = RunStatus.PENDING
            self.store.save(run)
            self._emit(run.id, "run_recovered", {})
            self._tasks[run.id] = asyncio.create_task(self._execute(run, None))
            recovered.append(run)
        return recovered
