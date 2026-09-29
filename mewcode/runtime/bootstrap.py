"""
bootstrap.py — 运行时装配工厂
=============================================================

【这个模块做什么】
从配置文件构建完整的 AgentRuntime 实例：
- 创建 Agent 工厂（每次重试创建新实例）
- 创建对话工厂（支持会话恢复）
- 创建对话保存器（写入 JSONL）
- 组装权限检查、工具注册表等组件

【设计亮点】
1. 闭包工厂: 通过闭包捕获外部状态，实现依赖注入
2. 会话复用: 同一 session_id 的运行共享对话上下文
3. 与 CLI 共享配置: 复用 config.yaml，保证行为一致

【调用关系】
- 被谁调用: server.py (HTTP 服务)、CLI
- 调用了谁: 各子系统模块（config、agent、permissions、tools 等）
"""
from __future__ import annotations

import os
from pathlib import Path

from mewcode.agent import Agent
from mewcode.client import create_client
from mewcode.config import AppConfig
from mewcode.conversation import ConversationManager
from mewcode.memory.instructions import load_instructions
from mewcode.memory.session import Session, SessionManager
from mewcode.permissions import (
    DangerousCommandDetector,
    PathSandbox,
    PermissionChecker,
    PermissionMode,
    RuleEngine,
)
from mewcode.prompts import build_environment_context
from mewcode.runtime.models import AgentRun
from mewcode.runtime.service import AgentRuntime
from mewcode.runtime.store import RunStore
from mewcode.tools import create_default_registry
from mewcode.tools.impl.tool_search import ToolSearchTool


def build_runtime(config: AppConfig, work_dir: str | None = None) -> AgentRuntime:
    """
    构建服务就绪的 AgentRuntime。
    
    工厂意图：
    - 每次重试/运行创建新的 Agent 实例
    - 会话映射保持多轮对话的连续性
    - 会话保存器将新消息写入 JSONL，TUI 和 HTTP 运行时共享相同的恢复原语
    
    返回的 AgentRuntime 可直接用于 HTTP 服务或 CLI。
    """
    root = str(Path(work_dir or os.getcwd()).resolve())
    provider = config.providers[0]
    session_manager = SessionManager(root)
    
    # 闭包状态：会话映射（同一 session_id 共享对话）
    conversations: dict[str, ConversationManager] = {}
    sessions: dict[str, Session] = {}
    cursors: dict[str, int] = {}  # 会话写入游标
    instructions = load_instructions(root)

    def get_conversation(run: AgentRun) -> ConversationManager:
        """
        获取或创建对话上下文。
        
        流程：
        1. 检查内存缓存（同一 session_id 复用）
        2. 尝试从磁盘恢复会话
        3. 创建新会话并注入环境上下文
        """
        session_id = run.session_id or run.id
        existing = conversations.get(session_id)
        if existing is not None:
            cursors.setdefault(session_id, len(existing.history))
            return existing

        conv = ConversationManager()
        resumed = session_manager.resume(session_id)
        if resumed is not None:
            conv.history = list(resumed.messages)
            sessions[session_id] = resumed.session
        else:
            sessions[session_id] = session_manager.create(session_id=session_id)
        conversations[session_id] = conv
        cursors[session_id] = len(conv.history)
        conv.inject_environment(build_environment_context(root))
        conv.inject_long_term_memory(instructions, "")
        return conv

    def save_conversation(
        run: AgentRun,
        conversation: ConversationManager,
        history_before: int,
    ) -> None:
        """
        保存对话历史到 JSONL。
        
        只写入新增的消息（从 cursor 位置开始）。
        """
        session_id = run.session_id or run.id
        session = sessions.get(session_id)
        if session is None:
            return
        start = min(cursors.get(session_id, history_before), len(conversation.history))
        for message in conversation.history[start:]:
            session.append(message)
        cursors[session_id] = len(conversation.history)

    def factory(run: AgentRun) -> Agent:
        """
        Agent 工厂 — 创建新的 Agent 实例。
        
        每次重试都会创建新的 Agent，确保状态干净。
        组装组件：LLM 客户端、权限检查器、工具注册表。
        """
        client = create_client(provider)
        checker = PermissionChecker(
            detector=DangerousCommandDetector(),
            sandbox=PathSandbox(root),
            rule_engine=RuleEngine(
                user_rules_path=Path.home() / ".mewcode" / "permissions.yaml",
                project_rules_path=Path(root) / ".mewcode" / "permissions.yaml",
                local_rules_path=Path(root) / ".mewcode" / "permissions.local.yaml",
            ),
            mode=PermissionMode(config.permission_mode),
        )
        registry = create_default_registry()
        registry.register(ToolSearchTool(registry, protocol=provider.protocol))
        agent = Agent(
            client=client,
            registry=registry,
            protocol=provider.protocol,
            work_dir=root,
            permission_checker=checker,
            context_window=provider.get_context_window(),
            instructions_content=instructions,
        )
        agent.session_id = run.session_id or run.id
        return agent

    return AgentRuntime(
        agent_factory=factory,
        conversation_factory=get_conversation,
        conversation_saver=save_conversation,
        store=RunStore(Path(root) / ".mewcode" / "runs"),
    )
