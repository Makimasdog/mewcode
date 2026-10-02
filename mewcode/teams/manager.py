"""
manager.py — 团队管理器（多 Agent 协作的指挥中心）
=============================================================

【这个模块做什么】
TeamManager 是多 Agent 团队协作的核心管理器，负责：
- 团队生命周期: 创建、查询、删除团队
- 成员管理: 注册成员、设置空闲状态
- 资源管理: 邮箱、任务存储、进程句柄、终端面板
- 清理工作: 关闭终端面板、清理 Git Worktree、删除追踪

【核心概念】
一个「团队」由以下部分组成：
┌─────────────────────────────────────────────────────────────┐
│  AgentTeam          团队定义（名称、领导者、成员列表）        │
│  SharedTaskStore    共享任务存储（团队成员可见的任务）        │
│  Mailbox            邮箱系统（成员间消息传递）                │
│  TeammateProgress   成员进度追踪（工具调用、Token 用量）      │
│  AgentNameRegistry  名称注册表（name → agent_id 映射）       │
└─────────────────────────────────────────────────────────────┘

【三种执行后端】
团队成员可以在不同的后端运行：
- in-process: 同进程异步任务（默认，最轻量）
- tmux: 独立 tmux 分窗（可视化，可交互）
- iterm2: 独立 iTerm2 分屏（macOS 专属）

【设计亮点】
1. 延迟加载: get_team/get_task_store/get_mailbox 都支持从磁盘恢复
2. 安全删除: 删除团队前检查活跃成员，防止误删
3. 完整清理: 删除时清理邮箱、Worktree、追踪、终端面板
4. 通知聚合: drain_lead_mailbox 收集所有团队给领导者的消息

【调用关系】
- 被谁调用: team_create.py / team_delete.py (工具层)
- 调用了谁: mailbox / models / progress / registry / shared_task / spawn_*
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from mewcode.teams.backend_detect import BackendDetectionError, detect_backend
from mewcode.teams.mailbox import Mailbox, create_message
from mewcode.teams.models import (
    AgentTeam,
    BackendType,
    TeammateInfo,
    resolve_team_dir,
    unique_team_name,
)
from mewcode.teams.progress import TeammateProgress
from mewcode.teams.registry import AgentNameRegistry
from mewcode.teams.shared_task import SharedTaskStore
from mewcode.teams.spawn_inprocess import InProcessTeammateHandle

if TYPE_CHECKING:
    from mewcode.agent import Agent

log = logging.getLogger(__name__)


class TeamError(Exception):
    """团队操作异常（如删除有活跃成员的团队）"""
    pass


class TeamManager:
    """
    团队管理器 — 多 Agent 协作的指挥中心。
    
    内部状态：
    - _teams: 团队名称 → AgentTeam 对象
    - _task_stores: 团队名称 → 共享任务存储
    - _mailboxes: 团队名称 → 邮箱
    - _inprocess_handles: agent_id → 进程内任务句柄
    - _pane_ids: agent_id → tmux/iterm2 面板 ID
    - _teammate_team_map: agent_id → 所属团队名称
    """

    def __init__(self, worktree_manager: Any = None, trace_manager: Any = None) -> None:
        self._teams: dict[str, AgentTeam] = {}
        self._task_stores: dict[str, SharedTaskStore] = {}
        self._mailboxes: dict[str, Mailbox] = {}
        self._inprocess_handles: dict[str, InProcessTeammateHandle] = {}
        self._pane_ids: dict[str, str] = {}  # agent_id -> pane_id (tmux/iterm2)
        self._detected_backend: BackendType | None = None
        self._worktree_manager = worktree_manager
        self._trace_manager = trace_manager
        self._teammate_team_map: dict[str, str] = {}  # agent_id -> team_name

    def detect_backend(
        self,
        teammate_mode: str = "",
        is_interactive: bool = True,
    ) -> BackendType:
        """
        检测可用的执行后端。
        
        检测结果会被缓存，避免重复检测。
        优先级: in-process > tmux > iterm2
        """
        if self._detected_backend is None:
            self._detected_backend = detect_backend(teammate_mode, is_interactive)
        return self._detected_backend


    def create_team(
        self,
        name: str,
        lead_agent_id: str,
        description: str = "",
        teammate_mode: str = "",
        is_interactive: bool = True,
    ) -> AgentTeam:
        """
        创建新团队。
        
        流程：
        1. 检测执行后端
        2. 生成唯一团队名称（slug）
        3. 创建团队目录 (~/.mewcode/teams/<slug>/)
        4. 初始化任务存储和邮箱
        5. 保存团队配置
        
        目录结构：
        ~/.mewcode/teams/<slug>/
        ├── config.json      # 团队配置
        ├── tasks.json       # 共享任务
        └── mailbox/         # 邮箱目录
        """
        backend = self.detect_backend(teammate_mode, is_interactive)
        slug = unique_team_name(name)
        team_dir = resolve_team_dir(slug)
        team_dir.mkdir(parents=True, exist_ok=True)

        config_path = str(team_dir / "config.json")
        team = AgentTeam(
            name=slug,
            lead_agent_id=lead_agent_id,
            config_path=config_path,
            description=description,
        )
        team.save()

        task_store = SharedTaskStore(team_dir / "tasks.json")
        task_store.init_empty()

        mailbox_dir = team_dir / "mailbox"
        mailbox_dir.mkdir(parents=True, exist_ok=True)
        mailbox = Mailbox(mailbox_dir)

        self._teams[slug] = team
        self._task_stores[slug] = task_store
        self._mailboxes[slug] = mailbox

        log.info("Created team '%s' at %s (backend=%s)", slug, team_dir, backend.value)
        return team


    def get_team(self, name: str) -> AgentTeam | None:
        """
        获取团队（支持从磁盘恢复）。
        
        先查内存缓存，未命中则尝试从磁盘加载。
        """
        if name in self._teams:
            return self._teams[name]
        team_dir = resolve_team_dir(name)
        config_path = team_dir / "config.json"
        if config_path.exists():
            team = AgentTeam.load(str(config_path))
            self._teams[name] = team
            return team
        return None

    def get_task_store(self, team_name: str) -> SharedTaskStore | None:
        """获取任务存储（支持从磁盘恢复）"""
        if team_name in self._task_stores:
            return self._task_stores[team_name]
        team_dir = resolve_team_dir(team_name)
        tasks_path = team_dir / "tasks.json"
        if tasks_path.exists():
            store = SharedTaskStore(tasks_path)
            self._task_stores[team_name] = store
            return store
        return None

    def get_mailbox(self, team_name: str) -> Mailbox | None:
        """获取邮箱（支持从磁盘恢复）"""
        if team_name in self._mailboxes:
            return self._mailboxes[team_name]
        team_dir = resolve_team_dir(team_name)
        mailbox_dir = team_dir / "mailbox"
        if mailbox_dir.exists():
            mailbox = Mailbox(mailbox_dir)
            self._mailboxes[team_name] = mailbox
            return mailbox
        return None

    def register_member(
        self,
        team_name: str,
        member: TeammateInfo,
    ) -> None:
        """
        注册团队成员。
        
        流程：
        1. 添加成员到团队
        2. 保存团队配置
        3. 注册到名称注册表（name → agent_id）
        4. 记录 agent_id → team_name 映射
        """
        team = self.get_team(team_name)
        if team is None:
            raise TeamError(f"Team '{team_name}' not found")
        team.add_member(member)
        team.save()

        AgentNameRegistry.instance().register(member.name, member.agent_id)
        self._teammate_team_map[member.agent_id] = team_name
        log.info("Registered member '%s' (agent=%s) in team '%s'", member.name, member.agent_id, team_name)

    def set_member_idle(self, team_name: str, member_name: str) -> None:
        """
        设置成员为空闲状态。
        
        同时向团队领导者发送通知消息。
        """
        team = self.get_team(team_name)
        if team is None:
            return
        team.set_member_active(member_name, False)
        team.save()

        # 向领导者发送空闲通知
        mailbox = self.get_mailbox(team_name)
        if mailbox:
            msg = create_message(
                from_agent=member_name,
                to_agent=team.lead_agent_id,
                content=f"Teammate '{member_name}' is now idle (run_to_completion finished).",
                summary=f"{member_name} idle",
                message_type="text",
            )
            mailbox.write(team.lead_agent_id, msg)

    def register_inprocess_handle(self, agent_id: str, handle: InProcessTeammateHandle) -> None:
        """注册进程内任务句柄（用于取消和状态查询）"""
        self._inprocess_handles[agent_id] = handle

    def register_pane_id(self, agent_id: str, pane_id: str) -> None:
        """注册终端面板 ID（tmux/iterm2）"""
        self._pane_ids[agent_id] = pane_id


    def get_pane_id(self, agent_id: str) -> str | None:
        """获取终端面板 ID"""
        return self._pane_ids.get(agent_id)

    def delete_team(self, team_name: str) -> None:
        """
        删除团队（完整清理流程）。
        
        安全检查：
        - 有活跃成员时拒绝删除
        
        清理内容：
        1. 注销名称注册表
        2. 取消进程内任务
        3. 关闭终端面板
        4. 清理 Git Worktree
        5. 移除追踪记录
        6. 清理邮箱
        7. 删除团队目录
        """
        team = self.get_team(team_name)
        if team is None:
            raise TeamError(f"Team '{team_name}' not found")

        # 安全检查：拒绝删除有活跃成员的团队
        active = [m for m in team.members if m.is_active is not False]
        if active:
            names = ", ".join(m.name for m in active)
            raise TeamError(f"Cannot delete team: active members: {names}")

        # 逐成员清理资源
        for member in list(team.members):
            AgentNameRegistry.instance().unregister(member.name)

            # 取消进程内任务
            handle = self._inprocess_handles.pop(member.agent_id, None)
            if handle and not handle.done:
                handle.cancel()

            # 关闭终端面板
            pane_id = self._pane_ids.pop(member.agent_id, None)
            if pane_id:
                self._kill_pane(pane_id, member.backend_type)

            # 清理 Git Worktree
            if member.worktree_path:
                self._cleanup_worktree(member.worktree_path)

            # 移除追踪记录
            if self._trace_manager:
                self._trace_manager.remove(member.agent_id)

        # 清理邮箱
        mailbox = self.get_mailbox(team_name)
        if mailbox:
            mailbox.cleanup_all()

        # 删除团队目录
        team_dir = resolve_team_dir(team_name)
        self._remove_dir(team_dir)

        # 清理内存缓存
        self._teams.pop(team_name, None)
        self._task_stores.pop(team_name, None)
        self._mailboxes.pop(team_name, None)

        log.info("Deleted team '%s'", team_name)

    def get_team_for_teammate(self, agent_id: str) -> str | None:
        """
        查找成员所属的团队。
        
        先查映射表，未命中则遍历所有团队。
        """
        if agent_id in self._teammate_team_map:
            return self._teammate_team_map[agent_id]
        for name, team in self._teams.items():
            for m in team.members:
                if m.agent_id == agent_id:
                    return name
        return None


    def drain_lead_mailbox(self) -> list[str]:
        """
        收集所有团队给领导者的消息。
        
        返回格式：
        <team-notification team="team-name">
        from=agent1: message content
        from=agent2: message content
        </team-notification>
        
        这些消息会被注入到领导者的对话中，让领导者感知团队动态。
        """
        notes: list[str] = []
        for team_name in list(self._teams.keys()):
            team = self.get_team(team_name)
            if team is None:
                continue
            mailbox = self.get_mailbox(team_name)
            if mailbox is None:
                continue
            msgs = mailbox.consume(team.lead_agent_id)
            if not msgs:
                continue
            parts = [f'<team-notification team="{team_name}">']
            for m in msgs:
                parts.append(f"from={m.from_agent}: {m.content}")
            parts.append("</team-notification>")
            notes.append("\n".join(parts))
        return notes

    def get_all_teammate_progress(self) -> list[TeammateProgress]:
        """收集所有成员的进度信息"""
        results: list[TeammateProgress] = []
        for team in self._teams.values():
            for member in team.members:
                if hasattr(member, "progress") and member.progress is not None:
                    results.append(member.progress)
        return results

    def on_teammate_completed(self, agent_id: str) -> None:
        """
        成员完成回调。
        
        当成员执行完毕时调用，将其标记为空闲并发送通知。
        """
        team_name = self.get_team_for_teammate(agent_id)
        if team_name is None:
            return
        team = self.get_team(team_name)
        if team is None:
            return
        member = next((m for m in team.members if m.agent_id == agent_id), None)
        if member:
            self.set_member_idle(team_name, member.name)


    def _kill_pane(self, pane_id: str, backend_type: str) -> None:
        """关闭终端面板（tmux）"""
        try:
            if backend_type == BackendType.TMUX.value:
                from mewcode.teams.spawn_tmux import kill_pane
                kill_pane(pane_id)
        except Exception as e:
            log.warning("Failed to kill pane %s: %s", pane_id, e)

    def _cleanup_worktree(self, worktree_path: str) -> None:
        """
        清理 Git Worktree。
        
        先尝试 git worktree remove，失败则强制删除目录。
        """
        import subprocess
        try:
            subprocess.run(
                ["git", "worktree", "remove", worktree_path, "--force"],
                capture_output=True, timeout=10,
            )
        except Exception as e:
            log.warning("git worktree remove failed for %s: %s", worktree_path, e)
            import shutil
            try:
                if Path(worktree_path).exists():
                    shutil.rmtree(worktree_path, ignore_errors=True)
            except Exception:
                pass

    def _remove_dir(self, path: Path) -> None:
        """安全删除目录"""
        import shutil
        try:
            if path.exists():
                shutil.rmtree(path, ignore_errors=True)
        except Exception as e:
            log.warning("Failed to remove directory %s: %s", path, e)
