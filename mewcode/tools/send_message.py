"""
send_message.py — 团队消息发送工具
================================================

【这个模块做什么】
在团队成员之间发送消息，支持点对点和广播。

【消息类型】
- text: 普通文本消息（必须包含 summary）
- shutdown_request: 关闭请求
- shutdown_response: 关闭响应

【使用场景】
- 子 Agent 向父 Agent 报告结果
- 团队成员之间协作通信
- 广播消息给所有成员（to="*"）

【设计特点】
- 通过 AgentNameRegistry 解析目标名称
- 支持唤醒接收方的终端 pane
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from mewcode.tools.base import Tool, ToolResult

if TYPE_CHECKING:
    from mewcode.teams.manager import TeamManager

log = logging.getLogger(__name__)


class SendMessageParams(BaseModel):
    """SendMessage 参数模型"""
    to: str           # 接收者（名称或 agent_id，"*" 表示广播）
    message: str      # 消息内容
    summary: str = "" # 消息摘要（text 类型必填）
    message_type: str = "text"  # 消息类型
    metadata: dict[str, Any] | None = None  # 元数据


# 有效的消息类型
VALID_MESSAGE_TYPES = {"text", "shutdown_request", "shutdown_response"}


class SendMessageTool(Tool):
    """
    团队消息发送工具 — 在团队成员之间发送消息。
    
    特性:
    - 支持点对点发送（指定名称或 agent_id）
    - 支持广播（to="*"）
    - 三种消息类型：text、shutdown_request、shutdown_response
    - 自动唤醒接收方的终端 pane
    """
    name = "SendMessage"
    description = (
        "Send a message to a teammate by name or agent ID. "
        "Use to='*' to broadcast to all teammates. "
        "For text messages, include a short summary (5-10 words). "
        "Supports structured types: shutdown_request, shutdown_response."
    )
    params_model = SendMessageParams
    category = "command"
    is_concurrency_safe = True


    def __init__(
        self,
        team_manager: TeamManager,
        team_name: str,
        from_agent_id: str,
        from_agent_name: str = "",
    ) -> None:
        self._team_manager = team_manager
        self._team_name = team_name
        self._from_agent_id = from_agent_id
        self._from_agent_name = from_agent_name


    async def execute(self, params: BaseModel) -> ToolResult:
        p: SendMessageParams = params  # type: ignore[assignment]

        # 验证消息类型
        if p.message_type not in VALID_MESSAGE_TYPES:
            return ToolResult(
                output=f"Invalid message_type '{p.message_type}'. Must be one of: {', '.join(sorted(VALID_MESSAGE_TYPES))}",
                is_error=True,
            )

        # text 类型必须包含 summary
        if p.message_type == "text" and not p.summary:
            return ToolResult(
                output="Text messages require a 'summary' field (5-10 words).",
                is_error=True,
            )

        from mewcode.teams.mailbox import create_message
        from mewcode.teams.registry import AgentNameRegistry

        team = self._team_manager.get_team(self._team_name)
        if team is None:
            return ToolResult(output=f"Team '{self._team_name}' not found", is_error=True)

        mailbox = self._team_manager.get_mailbox(self._team_name)
        if mailbox is None:
            return ToolResult(output=f"Mailbox not found for team '{self._team_name}'", is_error=True)

        # 创建消息
        msg = create_message(
            from_agent=self._from_agent_name or self._from_agent_id,
            to_agent=p.to,
            content=p.message,
            summary=p.summary,
            message_type=p.message_type,
            metadata=p.metadata,
        )

        registry = AgentNameRegistry.instance()

        # 广播模式：发送给所有成员（排除自己）
        if p.to == "*":
            member_ids = [
                m.agent_id for m in team.members
                if m.agent_id != self._from_agent_id
            ]
            if team.lead_agent_id != self._from_agent_id:
                member_ids.append(team.lead_agent_id)
            mailbox.broadcast(member_ids, msg, exclude=self._from_agent_id)
            self._wake_pane_members(team, member_ids)
            return ToolResult(output=f"Message broadcast to {len(member_ids)} teammates.")

        # 点对点模式：解析目标名称
        target_id = registry.resolve(p.to)
        if target_id is None:
            return ToolResult(
                output=f"Cannot resolve recipient '{p.to}'. Check the name or agent ID.",
                is_error=True,
            )

        mailbox.write(target_id, msg)
        self._wake_pane(target_id)

        return ToolResult(output=f"Message sent to '{p.to}'.")


    def _wake_pane(self, agent_id: str) -> None:
        """唤醒指定 Agent 的终端 pane（发送空键触发刷新）"""
        pane_id = self._team_manager.get_pane_id(agent_id)
        if pane_id is None:
            return
        try:
            from mewcode.teams.spawn_tmux import send_keys_to_pane
            send_keys_to_pane(pane_id, "")
        except Exception:
            pass

    def _wake_pane_members(self, team: Any, agent_ids: list[str]) -> None:
        """唤醒多个成员的终端 pane"""
        for aid in agent_ids:
            self._wake_pane(aid)
