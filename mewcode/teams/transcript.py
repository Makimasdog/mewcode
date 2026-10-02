"""
transcript.py — 对话转录（团队成员的对话持久化）
=============================================================

【这个模块做什么】
将团队成员的对话历史序列化为 JSON 文件（转录），
支持后续加载恢复（用于会话恢复或事后审查）。

【存储结构】
~/.mewcode/teams/<team>/transcripts/
├── <agent_id_1>.json    ← 每个成员一个对话文件
├── <agent_id_2>.json
└── ...

JSON 格式：
[
  {
    "role": "user",
    "content": "请实现用户登录功能",
    "tool_uses": [...],     // 可选
    "tool_results": [...]   // 可选
  },
  {
    "role": "assistant",
    "content": "好的，我来实现...",
    "tool_uses": [{"tool_use_id": "...", "tool_name": "ReadFile", ...}],
    "tool_results": [...]
  }
]

【为什么需要它？】
- 会话恢复：进程崩溃后，可以恢复成员的对话上下文
- 事后审查：查看团队成员做了什么、说了什么
- 调试：分析 Agent 的决策过程

【核心函数】
- _serialize_conversation():   ConversationManager → list[dict]
- _deserialize_conversation(): list[dict] → ConversationManager
- save_transcript():           保存到文件
- load_transcript():           从文件加载

【对外接口】
- save_transcript(team_name, agent_id, conversation) → Path
- load_transcript(team_name, agent_id) → ConversationManager | None
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mewcode.conversation import ConversationManager, Message, ToolResultBlock, ToolUseBlock


def _serialize_conversation(conv: ConversationManager) -> list[dict[str, Any]]:
    """
    将对话历史序列化为可 JSON 化的列表。

    每条消息提取为字典：
    - role:         角色（user / assistant / system）
    - content:      文本内容
    - tool_uses:    工具调用列表（可选）
    - tool_results: 工具结果列表（可选）
    """
    messages: list[dict[str, Any]] = []
    for msg in conv.history:
        entry: dict[str, Any] = {"role": msg.role, "content": msg.content}
        if msg.tool_uses:
            entry["tool_uses"] = [
                {
                    "tool_use_id": tu.tool_use_id,
                    "tool_name": tu.tool_name,
                    "arguments": tu.arguments,
                }
                for tu in msg.tool_uses
            ]
        if msg.tool_results:
            entry["tool_results"] = [
                {
                    "tool_use_id": tr.tool_use_id,
                    "content": tr.content,
                    "is_error": tr.is_error,
                }
                for tr in msg.tool_results
            ]
        messages.append(entry)
    return messages


def _deserialize_conversation(data: list[dict[str, Any]]) -> ConversationManager:
    """
    从 JSON 数据反序列化为 ConversationManager。

    还原流程：
    1. 遍历每条消息数据
    2. 重建 ToolUseBlock 和 ToolResultBlock
    3. 组装 Message 并追加到 history
    4. 标记 env_injected 和 ltm_injected 为 True
       （避免恢复后重复注入环境和长期记忆）
    """
    conv = ConversationManager()
    for entry in data:
        tool_uses = [
            ToolUseBlock(
                tool_use_id=tu["tool_use_id"],
                tool_name=tu["tool_name"],
                arguments=tu["arguments"],
            )
            for tu in entry.get("tool_uses", [])
        ]
        tool_results = [
            ToolResultBlock(
                tool_use_id=tr["tool_use_id"],
                content=tr["content"],
                is_error=tr.get("is_error", False),
            )
            for tr in entry.get("tool_results", [])
        ]
        msg = Message(
            role=entry["role"],
            content=entry.get("content", ""),
            tool_uses=tool_uses,
            tool_results=tool_results,
        )
        conv.history.append(msg)
    # 标记已注入，避免恢复后重复注入
    conv.env_injected = True
    conv.ltm_injected = True
    return conv


def save_transcript(
    team_name: str,
    agent_id: str,
    conversation: ConversationManager,
) -> Path:
    """
    保存对话转录到文件。

    路径：~/.mewcode/teams/<team>/transcripts/<agent_id>.json
    返回：保存的文件路径
    """
    from mewcode.teams.models import resolve_team_dir

    transcript_dir = resolve_team_dir(team_name) / "transcripts"
    transcript_dir.mkdir(parents=True, exist_ok=True)
    path = transcript_dir / f"{agent_id}.json"
    data = _serialize_conversation(conversation)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_transcript(
    team_name: str,
    agent_id: str,
) -> ConversationManager | None:
    """
    加载对话转录。

    如果文件不存在 → 返回 None（首次启动的成员没有历史对话）
    如果文件存在 → 反序列化为 ConversationManager
    """
    from mewcode.teams.models import resolve_team_dir

    path = resolve_team_dir(team_name) / "transcripts" / f"{agent_id}.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return _deserialize_conversation(data)
