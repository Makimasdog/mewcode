"""
models.py — 团队数据模型（团队系统的基石数据结构）
=============================================================

【这个模块做什么】
定义多 Agent 团队系统中的核心数据结构：
- BackendType:   终端后端类型枚举（tmux / iTerm2 / 进程内）
- TeammateInfo:  团队成员信息（名称、Agent ID、模型、工作目录等）
- AgentTeam:     团队定义（名称、领导者、成员列表、持久化）
- 辅助函数:      名称清理、目录解析、唯一名称生成

【数据结构关系】
AgentTeam
├── lead_agent_id: str          ← 领导者 Agent 的 ID
├── members: list[TeammateInfo] ← 成员列表
│   └── TeammateInfo
│       ├── name / agent_id     ← 身份标识
│       ├── model               ← 使用的 LLM 模型
│       ├── worktree_path       ← 独立工作目录（Git Worktree）
│       ├── backend_type        ← 终端后端（tmux/iterm2/in-process）
│       └── progress            ← 实时进度（运行时附加，不持久化）
└── config_path                 ← 团队配置 JSON 的存储路径

【持久化策略】
团队配置保存为 JSON 文件：~/.mewcode/teams/<slug>/team.json
注意：progress 字段是运行时状态（含 threading.Lock），不参与序列化。

【对外接口】
- AgentTeam.save() / .load()    持久化团队配置
- resolve_team_dir(name)        获取团队目录路径
- unique_team_name(name)        生成不重复的团队名称
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

from mewcode.teams.progress import TeammateProgress


class BackendType(str, Enum):
    """
    终端后端类型。

    决定团队成员的 Agent 运行在哪里：
    - TMUX:       在 tmux 分窗格中启动独立进程（可实时查看）
    - ITERM2:     在 iTerm2 分窗格中启动独立进程（macOS 专属）
    - IN_PROCESS: 在当前进程内以 asyncio.Task 运行（默认，进度可追踪）
    """
    TMUX = "tmux"
    ITERM2 = "iterm2"
    IN_PROCESS = "in-process"


@dataclass
class TeammateInfo:
    """
    团队成员信息。

    描述一个 Worker Agent 的完整配置：
    - name / agent_id:  身份标识（name 是人类可读名，agent_id 是系统生成的唯一 ID）
    - agent_type:       Agent 类型（对应 agents/ 目录下的配置名）
    - model:            使用的 LLM 模型名称
    - worktree_path:    独立工作目录（每个成员在独立的 Git Worktree 中工作）
    - backend_type:     终端后端（tmux/iterm2/in-process）
    - is_active:        是否正在工作（None=未知, True=工作中, False=空闲/完成）
    - progress:         实时进度追踪器（运行时附加，不参与序列化）
    """
    name: str
    agent_id: str
    agent_type: str
    model: str
    worktree_path: str
    backend_type: str  # BackendType value
    is_active: bool | None = None
    progress: Optional[TeammateProgress] = None

    def to_dict(self) -> dict:
        """序列化为字典（排除 progress，因为它含 threading.Lock 不可序列化）"""
        return {
            "name": self.name,
            "agent_id": self.agent_id,
            "agent_type": self.agent_type,
            "model": self.model,
            "worktree_path": self.worktree_path,
            "backend_type": self.backend_type,
            "is_active": self.is_active,
        }

    @classmethod
    def from_dict(cls, data: dict) -> TeammateInfo:
        """从字典反序列化（忽略未知字段，增强兼容性）"""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


def _sanitize_name(name: str) -> str:
    """
    将团队名称转为安全的目录名（slug 化）。

    规则：
    1. 转小写
    2. 非字母数字字符替换为 '-'
    3. 连续 '-' 合并为一个
    4. 去除首尾 '-'
    5. 空结果默认为 'team'
    """
    slug = re.sub(r"[^a-zA-Z0-9_-]", "-", name.strip().lower())
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug or "team"


@dataclass
class AgentTeam:
    """
    Agent 团队定义。

    一个团队包含：
    - name:           团队名称（slug 化后的目录名）
    - lead_agent_id:  领导者 Agent 的 ID（协调者模式下的 Manager）
    - members:        成员列表（Worker Agent）
    - config_path:    团队配置 JSON 的路径（用于持久化）
    - description:    团队描述（可选）

    设计亮点：
    - 支持 JSON 持久化（save/load），重启后可恢复团队状态
    - 成员查询支持 name 或 agent_id 匹配（灵活性）
    - is_active 三态设计（None/True/False）区分未知/工作中/空闲
    """
    name: str
    lead_agent_id: str
    members: list[TeammateInfo] = field(default_factory=list)
    config_path: str = ""
    description: str = ""

    def get_member(self, name: str) -> TeammateInfo | None:
        """按名称或 agent_id 查找成员"""
        for m in self.members:
            if m.name == name or m.agent_id == name:
                return m
        return None


    def add_member(self, member: TeammateInfo) -> None:
        """添加成员到团队"""
        self.members.append(member)

    def remove_member(self, name: str) -> bool:
        """按名称或 agent_id 移除成员，返回是否成功"""
        for i, m in enumerate(self.members):
            if m.name == name or m.agent_id == name:
                self.members.pop(i)
                return True
        return False


    def set_member_active(self, name: str, is_active: bool | None) -> bool:
        """设置成员的活动状态"""
        member = self.get_member(name)
        if member is None:
            return False
        member.is_active = is_active
        return True

    def all_idle(self) -> bool:
        """检查所有成员是否都空闲（用于判断团队是否可以清理）"""
        return all(m.is_active is False for m in self.members)


    def active_members(self) -> list[TeammateInfo]:
        """获取所有活跃（非空闲）的成员列表"""
        return [m for m in self.members if m.is_active is not False]

    def to_dict(self) -> dict:
        """序列化为字典"""
        return {
            "name": self.name,
            "lead_agent_id": self.lead_agent_id,
            "members": [m.to_dict() for m in self.members],
            "config_path": self.config_path,
            "description": self.description,
        }


    @classmethod
    def from_dict(cls, data: dict) -> AgentTeam:
        """从字典反序列化（递归解析成员列表）"""
        members = [TeammateInfo.from_dict(m) for m in data.get("members", [])]
        return cls(
            name=data["name"],
            lead_agent_id=data["lead_agent_id"],
            members=members,
            config_path=data.get("config_path", ""),
            description=data.get("description", ""),
        )

    def save(self) -> None:
        """将团队配置序列化为 JSON 并保存到 config_path"""
        path = Path(self.config_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def load(cls, config_path: str) -> AgentTeam:
        """从 JSON 文件加载团队配置（用于重启后恢复团队）"""
        data = json.loads(Path(config_path).read_text(encoding="utf-8"))
        team = cls.from_dict(data)
        team.config_path = config_path
        return team


def resolve_team_dir(team_name: str) -> Path:
    """
    获取团队的存储目录。

    路径格式：~/.mewcode/teams/<slug>/
    例如：~/.mewcode/teams/my-team/
    """
    slug = _sanitize_name(team_name)
    return Path.home() / ".mewcode" / "teams" / slug


def unique_team_name(team_name: str) -> str:
    """
    生成唯一的团队名称（避免目录冲突）。

    如果名称已存在，自动追加数字后缀：
    my-team → my-team-2 → my-team-3 → ...
    """
    slug = _sanitize_name(team_name)
    base_dir = Path.home() / ".mewcode" / "teams"
    if not (base_dir / slug).exists():
        return slug
    counter = 2
    while (base_dir / f"{slug}-{counter}").exists():
        counter += 1
    return f"{slug}-{counter}"
