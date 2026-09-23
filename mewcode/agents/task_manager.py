# 来源：公众号@小林coding
# 后端八股网站：xiaolincoding.com
# Agent网站：xiaolinnote.com
# 简历模版：jianli.xiaolinnote.com
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable

from mewcode.runtime.models import AgentRun, RunStatus
from mewcode.runtime.store import RunStore

if TYPE_CHECKING:
    from mewcode.agent import Agent

log = logging.getLogger(__name__)


@dataclass
class ProgressInfo:
    tool_call_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    last_activity: str = ""


@dataclass
class BackgroundTask:
    id: str
    name: str
    agent: Agent
    task: str
    status: str = "running"
    result: str = ""
    start_time: float = field(default_factory=time.monotonic)
    end_time: float | None = None
    cancel: Callable[[], None] | None = None
    progress: ProgressInfo = field(default_factory=ProgressInfo)
    run_id: str = ""
    attempt: int = 0
    max_attempts: int = 1
    timeout_seconds: float | None = None


class TaskManager:


    def __init__(self, store: RunStore | None = None) -> None:
        self._tasks: dict[str, BackgroundTask] = {}
        self._notify_queue: asyncio.Queue[str] = asyncio.Queue()
        self._async_tasks: dict[str, asyncio.Task[None]] = {}
        self.store = store or RunStore()


    def launch(
        self,
        agent: Agent,
        task: str,
        name: str = "",
        fork_conversation: Any = None,
        *,
        max_attempts: int = 1,
        timeout_seconds: float | None = None,
    ) -> str:
        task_id = uuid.uuid4().hex[:8]
        bg = BackgroundTask(
            id=task_id,
            name=name or task_id,
            agent=agent,
            task=task,
            run_id=task_id,
            max_attempts=max(1, max_attempts),
            timeout_seconds=timeout_seconds,
        )
        self._tasks[task_id] = bg

        run = AgentRun(
            id=task_id,
            task=task,
            status=RunStatus.RUNNING,
            max_attempts=bg.max_attempts,
            timeout_seconds=timeout_seconds,
            metadata={"name": bg.name},
        )
        self.store.save(run)
        self.store.append_event(task_id, "run_created", run.to_dict())

        async_task = asyncio.create_task(
            self._run_background(task_id, fork_conversation)
        )
        self._async_tasks[task_id] = async_task

        bg.cancel = async_task.cancel
        return task_id


    async def _run_background(
        self, task_id: str, fork_conversation: Any = None
    ) -> None:
        bg = self._tasks.get(task_id)
        if bg is None:
            return

        run = self.store.load(task_id)
        if run is None:
            run = AgentRun(id=task_id, task=bg.task, status=RunStatus.RUNNING)

        try:
            while bg.attempt < bg.max_attempts:
                bg.attempt += 1
                run.attempt = bg.attempt
                run.status = RunStatus.RUNNING
                self.store.save(run)
                self.store.append_event(task_id, "run_started", {"attempt": bg.attempt})
                try:
                    if fork_conversation is not None:
                        coro = bg.agent.run_to_completion("", fork_conversation)
                    else:
                        coro = bg.agent.run_to_completion(bg.task)
                    if bg.timeout_seconds and bg.timeout_seconds > 0:
                        result = await asyncio.wait_for(coro, timeout=bg.timeout_seconds)
                    else:
                        result = await coro
                except asyncio.TimeoutError:
                    run.error = f"run timed out after {bg.timeout_seconds}s"
                    self.store.append_event(task_id, "run_timeout", {"attempt": bg.attempt})
                    if bg.attempt >= bg.max_attempts:
                        raise RuntimeError(run.error)
                    continue
                except Exception as exc:
                    run.error = str(exc)
                    self.store.append_event(task_id, "run_error", {"error": str(exc), "attempt": bg.attempt})
                    if bg.attempt >= bg.max_attempts:
                        raise
                    await asyncio.sleep(min(2 ** (bg.attempt - 1), 8))
                    continue

                bg.result = result
                bg.status = "completed"
                run.result = result or ""
                run.status = RunStatus.COMPLETED
                run.ended_at = time.time()
                self.store.save(run)
                self.store.append_event(task_id, "run_completed", {"result": bg.result})
                break

            if bg.agent.team_name and bg.agent._team_manager:
                mailbox = bg.agent._team_manager.get_mailbox(bg.agent.team_name)
                if mailbox:
                    from mewcode.teams.mailbox import create_message
                    msg = create_message(
                        from_agent=bg.name,
                        to_agent="lead",
                        content=f"[idle] {bg.name}: completed initial task",
                        summary=f"{bg.name} idle",
                    )
                    mailbox.write("lead", msg)

                    for _ in range(60):
                        await asyncio.sleep(1)
                        msgs = mailbox.consume(bg.agent.agent_id)
                        if not msgs:
                            continue
                        prompt = "\n\n".join(
                            f"[Message from {m.from_agent}] {m.content}" for m in msgs
                        )
                        result = await bg.agent.run_to_completion(prompt)
                        bg.result = result
                        msg = create_message(
                            from_agent=bg.name,
                            to_agent="lead",
                            content=f"[idle] {bg.name}: completed follow-up",
                            summary=f"{bg.name} idle",
                        )
                        mailbox.write("lead", msg)

        except asyncio.CancelledError:
            bg.status = "cancelled"
            bg.result = "Task was cancelled"
            run.status = RunStatus.CANCELLED
            run.error = bg.result
            run.ended_at = time.time()
            self.store.save(run)
            self.store.append_event(task_id, "run_cancelled", {})
        except Exception as e:
            log.error("Background task %s failed: %s", task_id, e)
            bg.status = "failed"
            bg.result = f"Error: {e}"
            run.status = RunStatus.FAILED
            run.error = bg.result
            run.ended_at = time.time()
            self.store.save(run)
            self.store.append_event(task_id, "run_failed", {"error": bg.result})
        finally:
            bg.end_time = time.monotonic()
            bg.progress.input_tokens = bg.agent.total_input_tokens
            bg.progress.output_tokens = bg.agent.total_output_tokens
            run.attempt = bg.attempt
            run.result = bg.result
            run.ended_at = time.time()
            self.store.save(run)
            self._async_tasks.pop(task_id, None)
            await self._notify_queue.put(task_id)


    def adopt_running(
        self,
        agent: Agent,
        task_description: str,
        partial_result: str = "",
        name: str = "",
    ) -> str:
        task_id = uuid.uuid4().hex[:8]
        bg = BackgroundTask(
            id=task_id,
            name=name or task_id,
            agent=agent,
            task=task_description,
            result=partial_result,
            run_id=task_id,
        )
        self._tasks[task_id] = bg

        run = AgentRun(
            id=task_id,
            task=task_description,
            status=RunStatus.RUNNING,
            result=partial_result,
            metadata={"adopted": True, "name": bg.name},
        )
        self.store.save(run)
        self.store.append_event(task_id, "run_adopted", {"partial_result": partial_result})

        async_task = asyncio.create_task(self._continue_background(task_id))
        self._async_tasks[task_id] = async_task
        bg.cancel = async_task.cancel
        return task_id


    async def _continue_background(self, task_id: str) -> None:
        bg = self._tasks.get(task_id)
        if bg is None:
            return

        run: AgentRun | None = None
        try:
            run = self.store.load(task_id)
            if run is None:
                run = AgentRun(id=task_id, task=bg.task, status=RunStatus.RUNNING)
            run.attempt += 1
            run.status = RunStatus.RUNNING
            self.store.save(run)
            self.store.append_event(task_id, "run_started", {"attempt": run.attempt})
            result = await bg.agent.run_to_completion(bg.task)
            bg.result = (bg.result + "\n" + result).strip() if bg.result else result
            bg.status = "completed"
            run.result = bg.result
            run.status = RunStatus.COMPLETED
            run.ended_at = time.time()
            self.store.save(run)
            self.store.append_event(task_id, "run_completed", {"result": bg.result})
        except asyncio.CancelledError:
            bg.status = "cancelled"
            if run is not None:
                run.status = RunStatus.CANCELLED
                run.ended_at = time.time()
                self.store.save(run)
                self.store.append_event(task_id, "run_cancelled", {})
        except Exception as e:
            log.error("Background task %s failed: %s", task_id, e)
            bg.status = "failed"
            bg.result = f"Error: {e}"
            if run is not None:
                run.status = RunStatus.FAILED
                run.error = bg.result
                run.ended_at = time.time()
                self.store.save(run)
                self.store.append_event(task_id, "run_failed", {"error": bg.result})
        finally:
            bg.end_time = time.monotonic()
            bg.progress.input_tokens = bg.agent.total_input_tokens
            bg.progress.output_tokens = bg.agent.total_output_tokens
            self._async_tasks.pop(task_id, None)
            await self._notify_queue.put(task_id)

    def get(self, task_id: str) -> BackgroundTask | None:
        return self._tasks.get(task_id)

    def get_run(self, task_id: str) -> AgentRun | None:
        """Return the durable run snapshot behind a background task."""
        return self.store.load(task_id)

    def run_events(self, task_id: str, after: int = 0):
        return self.store.events(task_id, after=after)

    def recover(self, agent_factory: Callable[[AgentRun], Agent]) -> list[str]:
        """Recover pending/running tasks after process restart.

        Recovery is explicit because recreating an Agent requires application
        context (provider, permissions and possibly a resumed conversation).
        """
        recovered: list[str] = []
        for run in self.store.list_runs():
            if run.status not in {RunStatus.PENDING, RunStatus.RUNNING}:
                continue
            agent = agent_factory(run)
            bg = BackgroundTask(
                id=run.id,
                name=str(run.metadata.get("name", run.id)),
                agent=agent,
                task=run.task,
                run_id=run.id,
                max_attempts=run.max_attempts,
                timeout_seconds=run.timeout_seconds,
                attempt=run.attempt,
            )
            self._tasks[run.id] = bg
            task = asyncio.create_task(self._run_background(run.id))
            self._async_tasks[run.id] = task
            bg.cancel = task.cancel
            recovered.append(run.id)
        return recovered

    def list_tasks(self) -> list[BackgroundTask]:
        return list(self._tasks.values())

    def cancel(self, task_id: str) -> bool:
        bg = self._tasks.get(task_id)
        if bg is None or bg.status != "running":
            return False
        async_task = self._async_tasks.get(task_id)
        if async_task and not async_task.done():
            async_task.cancel()
            return True
        return False

    def poll_completed(self) -> list[BackgroundTask]:
        completed: list[BackgroundTask] = []
        while not self._notify_queue.empty():
            try:
                task_id = self._notify_queue.get_nowait()
                bg = self._tasks.get(task_id)
                if bg is not None:
                    completed.append(bg)
            except asyncio.QueueEmpty:
                break
        return completed
