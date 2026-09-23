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
    """Build a service-ready runtime from the same configuration as the CLI.

    The factory intentionally creates a fresh Agent for each retry/run while
    the conversation map keeps multi-turn sessions alive in the process. The
    session saver writes newly produced messages to the existing JSONL format,
    so the TUI and HTTP runtime share the same recovery primitives.
    """
    root = str(Path(work_dir or os.getcwd()).resolve())
    provider = config.providers[0]
    session_manager = SessionManager(root)
    conversations: dict[str, ConversationManager] = {}
    sessions: dict[str, Session] = {}
    cursors: dict[str, int] = {}
    instructions = load_instructions(root)

    def get_conversation(run: AgentRun) -> ConversationManager:
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
        session_id = run.session_id or run.id
        session = sessions.get(session_id)
        if session is None:
            return
        start = min(cursors.get(session_id, history_before), len(conversation.history))
        for message in conversation.history[start:]:
            session.append(message)
        cursors[session_id] = len(conversation.history)

    def factory(run: AgentRun) -> Agent:
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
