"""
service.py — Agent 运行时核心服务
=============================================================

【这个模块做什么】
提供 Agent 运行的完整生命周期管理：
- 提交运行: submit() 创建并启动 Agent 执行
- 执行控制: 支持重试、超时、取消
- 事件订阅: subscribe() 实时推送运行事件
- 进程恢复: recover() 重启后恢复未完成的运行

【核心设计】
1. 依赖注入: 通过工厂函数注入 Agent 创建逻辑，解耦运行时与具体实现
2. 事件驱动: 所有状态变化都产生事件，支持 SSE 实时推送
3. 持久化优先: 每次状态变化都写入磁盘，确保进程崩溃后可恢复

【事件类型】
run_created → run_started → run_completed/run_failed/run_cancelled
              run_timeout → run_retrying
              run_recovered (进程恢复后)

【调用关系】
- 被谁调用: http.py (HTTP API)、bootstrap.py (CLI)
- 调用了谁: store.py (持久化)、agent.py (Agent 执行)
"""
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

# 工厂类型别名
AgentFactory = Callable[[AgentRun], "Agent"]
ConversationFactory = Callable[[AgentRun], "ConversationManager | None"]
ConversationSaver = Callable[[AgentRun, "ConversationManager", int], None]


class AgentRuntime:
    """
    Agent 运行时服务 — 管理 Agent 执行的完整生命周期。
    
    设计亮点：
    - 与 Textual/FastAPI 解耦: CLI、HTTP、Worker 都可以提交相同的运行
    - 事件流持久化: 支持 SSE 实时推送，也支持事后回放
    - 进程恢复: 重启后自动恢复未完成的运行
    """

    def __init__(
        self,
        agent_factory: AgentFactory | None = None,
        conversation_factory: ConversationFactory | None = None,
        conversation_saver: ConversationSaver | None = None,
        store: RunStore | None = None,
    ) -> None:
        """
        初始化运行时。
        
        agent_factory: 创建 Agent 实例的工厂（重试时会重新创建）
        conversation_factory: 创建/恢复对话上下文的工厂
        conversation_saver: 保存对话历史的回调
        store: 持久化存储
        """
        self.agent_factory = agent_factory
        self.conversation_factory = conversation_factory
        self.conversation_saver = conversation_saver
        self.store = store or RunStore()
        self._tasks: dict[str, asyncio.Task[None]] = {}  # 运行 ID → asyncio 任务
        self._agents: dict[str, Agent] = {}  # 运行 ID → Agent 实例
        self._subscribers: dict[str, set[asyncio.Queue[RunEvent]]] = {}  # 事件订阅者
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
        """
        提交运行请求。
        
        流程：
        1. 创建 AgentRun 记录
        2. 持久化到磁盘
        3. 发射 run_created 事件
        4. 创建 asyncio 任务启动执行
        """
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
        """
        执行运行的核心逻辑。
        
        重试策略：
        - 失败后等待指数退避（2^attempt 秒，最多 8 秒）
        - 重试时通过 agent_factory 创建新的 Agent 实例
        
        超时控制：
        - 使用 asyncio.wait_for 包装执行
        - 超时后发射 run_timeout 事件并尝试重试
        """
        try:
            while run.attempt < run.max_attempts:
                run.attempt += 1
                run.status = RunStatus.RUNNING
                run.started_at = run.started_at or time.time()
                run.error = ""
                self.store.save(run)
                self._emit(run.id, "run_started", {"attempt": run.attempt})

                # 首次使用传入的 agent，重试时通过工厂创建新实例
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
                    # 执行成功
                    run.result = result or ""
                    if conversation is not None and self.conversation_saver is not None:
                        self.conversation_saver(run, conversation, history_before)
                    run.status = RunStatus.COMPLETED
                    run.ended_at = time.time()
                    self.store.save(run)
                    self._emit(run.id, "run_completed", {"result": run.result})
                    return

                # 失败后重试
                if run.attempt < run.max_attempts:
                    self._emit(
                        run.id,
                        "run_retrying",
                        {"attempt": run.attempt, "next_attempt": run.attempt + 1},
                    )
                    await asyncio.sleep(min(2 ** (run.attempt - 1), 8))  # 指数退避
                    continue

                # 达到最大重试次数
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
                await self._execute(run, None)  # 递归重试
                return
            run.status = RunStatus.FAILED
            run.ended_at = time.time()
            self.store.save(run)
            self._emit(run.id, "run_failed", {"error": run.error})
        finally:
            self._tasks.pop(run.id, None)
            self._agents.pop(run.id, None)

    def _on_agent_event(self, run_id: str, event: dict[str, Any]) -> None:
        """处理 Agent 执行过程中的事件（转发到事件流）"""
        event_type = str(event.get("type", "agent_event"))
        self._emit(run_id, event_type, event)

    def _emit(self, run_id: str, event_type: str, payload: dict[str, Any]) -> RunEvent:
        """
        发射事件。
        
        流程：
        1. 持久化到事件日志
        2. 推送到所有订阅者的队列
        """
        event = self.store.append_event(run_id, event_type, payload)
        for queue in list(self._subscribers.get(run_id, set())):
            queue.put_nowait(event)
        return event

    def get(self, run_id: str) -> AgentRun | None:
        """获取运行快照"""
        return self.store.load(run_id)

    def list_runs(self) -> list[AgentRun]:
        """列出所有运行"""
        return self.store.list_runs()

    def cancel(self, run_id: str) -> bool:
        """取消运行（通过取消 asyncio 任务）"""
        task = self._tasks.get(run_id)
        if task is None or task.done():
            return False
        task.cancel()
        return True

    def events(self, run_id: str, after: int = 0) -> list[RunEvent]:
        """获取事件（支持分页）"""
        return self.store.events(run_id, after=after)

    async def subscribe(self, run_id: str, after: int = 0) -> AsyncIterator[RunEvent]:
        """
        订阅运行事件流。
        
        流程：
        1. 先回放已持久化的事件
        2. 然后实时跟随新事件
        3. 运行结束时自动退出
        """
        replayed = self.store.events(run_id, after=after)
        for event in replayed:
            yield event
        if replayed and replayed[-1].event_type in {
            "run_completed",
            "run_failed",
            "run_cancelled",
        }:
            return  # 运行已结束，不需要实时跟随
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
        """
        进程恢复：重新调度未完成的运行。
        
        场景：进程崩溃重启后，磁盘上可能还有 PENDING/RUNNING 状态的运行。
        这个方法将它们重新加入执行队列。
        
        注意：对话上下文的精确恢复由 conversation_factory 负责。
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
