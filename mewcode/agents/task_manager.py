"""
task_manager.py — 后台任务管理器
=====================================

【这个模块做什么】
当主 Agent 委托子任务给子 Agent 时，这些任务可能在后台运行。
TaskManager 负责：
1. 启动后台任务（launch）
2. 跟踪任务状态（running/completed/failed/cancelled）
3. 支持重试和超时控制
4. 支持进程重启后恢复未完成的任务（recover）
5. 通知主 Agent 任务完成（通过 notify_queue）

【为什么需要后台任务？】
主 Agent 可以同时启动多个子 Agent 并行工作。
例如：一个 Agent 写代码，另一个写测试，第三个做审查。
后台任务机制让这些并行执行成为可能。

【持久化】
任务状态通过 RunStore 持久化到磁盘（.mewcode/runs/）。
即使进程崩溃或重启，未完成的任务可以被恢复继续执行。
"""
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
    """任务进度信息（用于 UI 展示）"""
    tool_call_count: int = 0    # 工具调用次数
    input_tokens: int = 0       # 输入 token 消耗
    output_tokens: int = 0      # 输出 token 消耗
    last_activity: str = ""     # 最近活动描述


@dataclass
class BackgroundTask:
    """
    后台任务的完整状态。

    每个后台任务包含：
    - 任务基本信息（id, name, task）
    - 关联的 Agent 实例
    - 执行状态和结果
    - 重试配置（max_attempts, timeout_seconds）
    """
    id: str                     # 任务唯一 ID
    name: str                   # 任务名称（用于展示）
    agent: Agent                # 执行任务的 Agent 实例
    task: str                   # 任务描述
    status: str = "running"     # 状态：running/completed/failed/cancelled
    result: str = ""            # 执行结果
    start_time: float = field(default_factory=time.monotonic)  # 启动时间
    end_time: float | None = None  # 结束时间
    cancel: Callable[[], None] | None = None  # 取消函数
    progress: ProgressInfo = field(default_factory=ProgressInfo)  # 进度信息
    run_id: str = ""            # 持久化运行 ID
    attempt: int = 0            # 当前重试次数
    max_attempts: int = 1       # 最大重试次数
    timeout_seconds: float | None = None  # 超时时间（秒）
    event_callback: Callable[[dict[str, Any]], None] | None = None


class TaskManager:
    """
    后台任务管理器。

    管理后台 Agent 任务的完整生命周期：
    启动 → 运行 → 完成/失败/取消
    支持重试、超时、持久化和进程重启后恢复。
    """

    def __init__(self, store: RunStore | None = None) -> None:
        self._tasks: dict[str, BackgroundTask] = {}          # {task_id: 任务}
        self._notify_queue: asyncio.Queue[str] = asyncio.Queue()  # 完成通知队列
        self._async_tasks: dict[str, asyncio.Task[None]] = {}     # {task_id: asyncio任务}
        self.store = store or RunStore()  # 持久化存储


    def launch(
        self,
        agent: Agent,
        task: str,
        name: str = "",
        fork_conversation: Any = None,
        *,
        max_attempts: int = 1,
        timeout_seconds: float | None = None,
        event_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> str:
        """
        启动一个后台任务。

        参数:
            agent: 执行任务的 Agent 实例
            task: 任务描述
            name: 任务名称（用于展示）
            fork_conversation: Fork 的对话副本（可选）
            max_attempts: 最大重试次数
            timeout_seconds: 超时时间（秒）

        返回:
            task_id: 任务唯一标识符
        """
        task_id = uuid.uuid4().hex[:8]
        bg = BackgroundTask(
            id=task_id,
            name=name or task_id,
            agent=agent,
            task=task,
            run_id=task_id,
            max_attempts=max(1, max_attempts),
            timeout_seconds=timeout_seconds,
            event_callback=event_callback,
        )
        self._tasks[task_id] = bg

        # 持久化运行状态
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

        # 创建异步任务在后台执行
        async_task = asyncio.create_task(
            self._run_background(task_id, fork_conversation)
        )
        self._async_tasks[task_id] = async_task

        bg.cancel = async_task.cancel  # 绑定取消函数
        return task_id


    async def _run_background(
        self, task_id: str, fork_conversation: Any = None
    ) -> None:
        """
        后台执行任务的核心逻辑。

        包含：
        - 重试机制：失败后自动重试，最多 max_attempts 次
        - 超时控制：超过 timeout_seconds 自动终止
        - 指数退避：重试间隔逐渐增加（1s, 2s, 4s, 8s...）
        - 团队通知：完成后通过邮箱通知主 Agent
        """
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
                        coro = bg.agent.run_to_completion(
                            "", fork_conversation, event_callback=bg.event_callback
                        )
                    else:
                        coro = bg.agent.run_to_completion(
                            bg.task, event_callback=bg.event_callback
                        )
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
                if bg.event_callback:
                    bg.event_callback({"type": "agent_status", "status": "completed"})
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
            if bg.event_callback:
                bg.event_callback({"type": "agent_status", "status": "cancelled"})
            bg.result = "Task was cancelled"
            run.status = RunStatus.CANCELLED
            run.error = bg.result
            run.ended_at = time.time()
            self.store.save(run)
            self.store.append_event(task_id, "run_cancelled", {})
        except Exception as e:
            log.error("Background task %s failed: %s", task_id, e)
            bg.status = "failed"
            if bg.event_callback:
                bg.event_callback({"type": "agent_status", "status": "failed", "error": str(e)})
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
        """
        接管一个已经在运行的任务。
        用于进程重启后恢复任务，或从外部系统导入任务。
        """
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
        """继续执行被接管的后台任务"""
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
        """获取指定任务的详细信息"""
        return self._tasks.get(task_id)

    def get_run(self, task_id: str) -> AgentRun | None:
        """获取任务的持久化运行快照"""
        return self.store.load(task_id)

    def run_events(self, task_id: str, after: int = 0):
        """获取任务的事件列表（用于 SSE 流式传输）"""
        return self.store.events(task_id, after=after)

    def recover(self, agent_factory: Callable[[AgentRun], Agent]) -> list[str]:
        """
        进程重启后恢复未完成的任务。

        从持久化存储中加载 PENDING/RUNNING 状态的任务，
        用 agent_factory 重新创建 Agent 实例，然后继续执行。

        参数:
            agent_factory: 从 AgentRun 创建 Agent 实例的工厂函数

        返回:
            已恢复的任务 ID 列表
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
        """返回所有任务列表"""
        return list(self._tasks.values())

    def cancel(self, task_id: str) -> bool:
        """取消指定任务，返回是否成功取消"""
        bg = self._tasks.get(task_id)
        if bg is None or bg.status != "running":
            return False
        async_task = self._async_tasks.get(task_id)
        if async_task and not async_task.done():
            async_task.cancel()
            return True
        return False

    def poll_completed(self) -> list[BackgroundTask]:
        """
        轮询已完成的任务。
        从通知队列中取出所有已完成的任务 ID，返回对应的任务对象。
        主 Agent 在每轮迭代开始时调用此方法，获取子 Agent 的结果。
        """
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
