"""
teams — 多 Agent 团队协作系统
=============================================================

【这个模块做什么】
让多个 Agent 组成团队，由一个领导者（Manager）协调多个工作者（Worker）
并行完成复杂任务。每个 Worker 在独立的终端窗格或进程内任务中运行。

【模块结构】
teams/
├── models.py           数据模型（AgentTeam, TeammateInfo, BackendType）
├── manager.py          团队管理器（创建/删除团队、成员管理）
├── coordinator.py      协调者模式（Manager-Worker 架构开关）
├── mailbox.py          邮箱系统（Agent 间异步消息传递）
├── registry.py         名称注册表（名字 ↔ Agent ID 映射）
├── shared_task.py      共享任务存储（团队任务看板）
├── progress.py         进度追踪（实时状态 + 趣味动词）
├── backend_detect.py   后端检测（自动选择终端方案）
├── spawn_inprocess.py  进程内执行后端（默认）
├── spawn_tmux.py       tmux 分窗格后端
├── spawn_iterm2.py     iTerm2 分窗格后端
└── transcript.py       对话转录（会话持久化）

【核心设计】
1. 文件系统驱动：所有状态（邮箱、任务、转录）都通过 JSON 文件持久化
2. 三种执行后端：in-process（默认）、tmux、iTerm2
3. 协调者模式：Agent 只思考不执行，将工作委派给 Worker
4. 邮箱通信：跨进程的异步消息传递

【使用场景】
- 大型项目开发：多个 Worker 分别负责前端、后端、测试
- 并行任务：同时处理多个独立子任务
- 代码审查：一个 Worker 写代码，另一个审查

【配置示例】
# config.yaml
enable_coordinator_mode: true
teammate_mode: "in-process"  # 或 "tmux" / "iterm2"
"""

from mewcode.teams.mailbox import Mailbox, MailboxMessage, create_message
from mewcode.teams.models import (
    AgentTeam,
    BackendType,
    TeammateInfo,
    resolve_team_dir,
    unique_team_name,
)
from mewcode.teams.progress import TeammateProgress, ToolActivity
from mewcode.teams.registry import AgentNameRegistry
from mewcode.teams.shared_task import SharedTask, SharedTaskStore


__all__ = [
    "AgentTeam",
    "AgentNameRegistry",
    "BackendType",
    "Mailbox",
    "MailboxMessage",
    "SharedTask",
    "SharedTaskStore",
    "TeammateInfo",
    "TeammateProgress",
    "ToolActivity",
    "create_message",
    "resolve_team_dir",
    "unique_team_name",
]
