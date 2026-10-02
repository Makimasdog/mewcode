"""
mailbox.py — 邮箱系统（团队成员间的异步消息传递）
=============================================================

【这个模块做什么】
实现基于文件系统的异步邮箱（Mailbox），让团队中的 Agent 可以互相发消息。

【为什么用文件系统？】
团队成员可能运行在不同的终端窗格（tmux/iTerm2）甚至不同进程中，
没有共享内存，所以用文件作为消息载体——简单、可靠、跨进程。

【存储结构】
~/.mewcode/teams/<team>/mailbox/
├── <agent_id_1>/            ← 每个成员一个目录
│   ├── 1727000000.123456_abc123.json  ← 每条消息一个文件
│   └── 1727000001.654321_def456.json
└── <agent_id_2>/
    └── ...

文件名格式：{timestamp}_{message_id}.json
- 按时间戳排序 → 消息自然有序
- 唯一 ID → 避免冲突

【消息类型】
- text:               普通文本消息（任务结果、状态更新等）
- shutdown_request:   关闭请求（领导者要求成员停止）
- shutdown_response:  关闭响应（成员确认停止）

【核心操作】
- write():     写一条消息到目标 Agent 的邮箱
- read():      读取邮箱中的所有消息（不删除）
- consume():   读取并删除（消息一旦被消费就消失）
- broadcast(): 群发消息给所有成员（可排除某人）

【对外接口】
- Mailbox                邮箱类
- MailboxMessage         消息数据类
- create_message()       便捷工厂函数（自动生成 ID 和时间戳）
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class MailboxMessage:
    """
    邮箱消息。

    字段说明：
    - id:             消息唯一 ID（12 位十六进制）
    - from_agent:     发送者 Agent ID
    - to_agent:       接收者 Agent ID
    - content:        消息正文
    - summary:        消息摘要（用于 UI 显示，避免展示完整内容）
    - message_type:   消息类型（text / shutdown_request / shutdown_response）
    - timestamp:      发送时间（Unix 时间戳，用于排序）
    - metadata:       扩展元数据（预留字段，未来可携带更多信息）
    """
    id: str
    from_agent: str
    to_agent: str
    content: str
    summary: str = ""
    message_type: str = "text"  # text | shutdown_request | shutdown_response
    timestamp: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


    def to_dict(self) -> dict[str, Any]:
        """序列化为字典"""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MailboxMessage:
        """从字典反序列化（忽略未知字段）"""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class Mailbox:
    """
    基于文件系统的异步邮箱。

    设计思路：
    - 每个 Agent 有自己的收件目录
    - 消息以 JSON 文件形式存储（一个消息一个文件）
    - 文件名以时间戳开头 → 自然按时间排序
    - consume() 读取后删除 → 实现「已读即清除」语义
    - 文件操作天然跨进程安全（不同 Agent 写不同文件）
    """
    def __init__(self, base_dir: str | Path) -> None:
        self._base_dir = Path(base_dir)

    def _agent_dir(self, agent_id: str) -> Path:
        """获取指定 Agent 的收件目录"""
        return self._base_dir / agent_id


    def write(self, agent_id: str, message: MailboxMessage) -> None:
        """
        写入一条消息到指定 Agent 的收件箱。

        文件名格式：{timestamp:.6f}_{id}.json
        - 时间戳精度到微秒 → 避免同名
        - 按文件名排序 = 按时间排序
        """
        d = self._agent_dir(agent_id)
        d.mkdir(parents=True, exist_ok=True)
        filename = f"{message.timestamp:.6f}_{message.id}.json"
        (d / filename).write_text(
            json.dumps(message.to_dict(), ensure_ascii=False),
            encoding="utf-8",
        )

    def read(self, agent_id: str) -> list[MailboxMessage]:
        """读取邮箱中的所有消息（不删除，按时间排序）"""
        d = self._agent_dir(agent_id)
        if not d.exists():
            return []
        messages: list[MailboxMessage] = []
        for f in sorted(d.iterdir()):
            if f.suffix != ".json":
                continue
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                messages.append(MailboxMessage.from_dict(data))
            except (json.JSONDecodeError, KeyError):
                continue  # 跳过损坏的消息文件
        return messages

    def consume(self, agent_id: str) -> list[MailboxMessage]:
        """
        消费邮箱：读取所有消息并删除文件。

        「已读即清除」语义：
        - 读取成功后立即删除消息文件
        - 保证每条消息只被消费一次
        - 损坏的文件也会被删除（避免反复出错）
        """
        d = self._agent_dir(agent_id)
        if not d.exists():
            return []
        messages: list[MailboxMessage] = []
        for f in sorted(d.iterdir()):
            if f.suffix != ".json":
                continue
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                messages.append(MailboxMessage.from_dict(data))
                f.unlink()  # 读一条删一条
            except (json.JSONDecodeError, KeyError):
                continue
        return messages

    def broadcast(
        self,
        team_members: list[str],
        message: MailboxMessage,
        exclude: str = "",
    ) -> None:
        """
        群发消息给所有团队成员。

        参数：
        - team_members:  成员 Agent ID 列表
        - message:       要发送的消息
        - exclude:       排除的 Agent ID（通常是发送者自己）
        """
        for agent_id in team_members:
            if agent_id == exclude:
                continue
            self.write(agent_id, message)


    def cleanup(self, agent_id: str) -> None:
        """清理指定 Agent 的邮箱（删除所有消息和目录）"""
        d = self._agent_dir(agent_id)
        if d.exists():
            for f in d.iterdir():
                f.unlink(missing_ok=True)
            d.rmdir()

    def cleanup_all(self) -> None:
        """清理所有邮箱（团队解散时调用）"""
        if not self._base_dir.exists():
            return
        for d in self._base_dir.iterdir():
            if d.is_dir():
                for f in d.iterdir():
                    f.unlink(missing_ok=True)
                d.rmdir()


def create_message(
    from_agent: str,
    to_agent: str,
    content: str,
    summary: str = "",
    message_type: str = "text",
    metadata: dict[str, Any] | None = None,
) -> MailboxMessage:
    """
    创建邮箱消息的便捷工厂函数。

    自动生成：
    - id:        12 位 UUID 十六进制
    - timestamp: 当前 Unix 时间戳

    使用示例：
        msg = create_message(
            from_agent="lead-001",
            to_agent="worker-002",
            content="请实现用户登录功能",
            summary="分配任务：用户登录",
        )
    """
    return MailboxMessage(
        id=uuid.uuid4().hex[:12],
        from_agent=from_agent,
        to_agent=to_agent,
        content=content,
        summary=summary,
        message_type=message_type,
        timestamp=time.time(),
        metadata=metadata or {},
    )
