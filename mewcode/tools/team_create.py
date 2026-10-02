"""
team_create.py — 团队创建工具
================================================

【这个模块做什么】
创建 Agent 团队，用于协调多个 Agent 并行工作。

【团队工作流】
1. 创建团队 (TeamCreate)
2. 生成队友 (Agent + team_name)
3. 队友独立工作，通过 SendMessage 通信
4. 队友完成后向 lead 报告
5. lead 收集并综合结果

【协调者模式】
启用后，lead 的工具集会被裁剪为「调度专用」，
专注于任务分配而非直接执行。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel

from mewcode.tools.base import Tool, ToolResult

if TYPE_CHECKING:
    from mewcode.agent import Agent
    from mewcode.teams.manager import TeamManager


class TeamCreateParams(BaseModel):
    """TeamCreate 参数模型"""
    team_name: str         # 团队名称
    description: str = ""  # 团队描述


class TeamCreateTool(Tool):
    """
    团队创建工具 — 创建 Agent 团队。
    
    特性:
    - 自动检测后端（TMUX/iTerm2/进程内）
    - 支持协调者模式（工具集裁剪）
    - 团队创建后可通过 Agent 工具生成队友
    """
    name = "TeamCreate"
    description = (
        "Create a new team for coordinating multiple agents.\n\n"
        "## When to Use\n\n"
        "Use this tool proactively whenever:\n"
        "- The user explicitly asks to use a team, swarm, or group of agents\n"
        "- The user mentions wanting agents to work together, coordinate, or collaborate\n"
        "- A task requires sequential or parallel collaboration between multiple agents\n\n"
        "When in doubt about whether a task warrants a team, prefer spawning a team.\n\n"
        "When coordinator mode is enabled, TeamCreate also activates the coordinator. "
        "A workflow using ordinary one-shot sub-agents can create the team without spawning teammates; "
        "those sub-agents share the main work directory and do not receive team messages.\n\n"
        "For a paper search and reproduction request, create a paper-study team to activate "
        "the coordinator, then use the PaperSearch/PaperProtocol/PaperStudy/Verification "
        "one-shot worker pipeline without team_name.\n\n"
        "## Team Workflow\n\n"
        "1. **Create a team** with TeamCreate\n"
        "2. **Spawn teammates** using the Agent tool with team_name and name parameters "
        "— this is REQUIRED to create long-running team members\n"
        "3. Teammates work independently and communicate via **SendMessage**\n"
        "4. When a teammate finishes, it sends its result to \"lead\" via SendMessage, then goes idle\n"
        "5. The lead collects and synthesizes all teammate results\n\n"
        "## CRITICAL: Spawning Teammates\n\n"
        "To add a member to a team, you MUST pass both team_name and name to the Agent tool:\n"
        "```\nAgent({\n"
        '  "team_name": "<team name from step 1>",\n'
        '  "name": "<member name, e.g. reviewer>",\n'
        '  "prompt": "...",\n'
        '  "description": "..."\n'
        "})\n```\n"
        "Without team_name, the agent runs as a one-shot sub-agent and will NOT be a team member. "
        "With run_in_background=true it returns a task ID and later completion notification.\n\n"
        "## Teammate Idle State\n\n"
        "Teammates go idle after every turn — this is completely normal. "
        "Sending a message to an idle teammate wakes them up.\n\n"
        "## Communication\n\n"
        "- Use SendMessage to talk to teammates by name\n"
        "- Messages from teammates arrive as system reminders at the start of each turn\n"
        "- Messages are delivered automatically — you do NOT need to manually check your inbox"
    )
    params_model = TeamCreateParams
    category = "command"
    is_concurrency_safe = False


    def __init__(
        self,
        team_manager: TeamManager,
        parent_agent: Agent,
        teammate_mode: str = "",
        is_interactive: bool = True,
        enable_coordinator_mode: bool = False,
    ) -> None:
        self._team_manager = team_manager
        self._parent_agent = parent_agent
        self._teammate_mode = teammate_mode
        self._is_interactive = is_interactive
        self._enable_coordinator_mode = enable_coordinator_mode


    async def execute(self, params: BaseModel) -> ToolResult:
        p: TeamCreateParams = params  # type: ignore[assignment]

        # 1. 检测后端（TMUX/iTerm2/进程内）
        from mewcode.teams.backend_detect import BackendDetectionError

        try:
            backend = self._team_manager.detect_backend(
                self._teammate_mode, self._is_interactive
            )
        except BackendDetectionError as e:
            return ToolResult(output=str(e), is_error=True)

        # 2. 创建团队
        try:
            team = self._team_manager.create_team(
                name=p.team_name,
                lead_agent_id=self._parent_agent.agent_id,
                description=p.description,
                teammate_mode=self._teammate_mode,
                is_interactive=self._is_interactive,
            )
        except Exception as e:
            return ToolResult(output=f"Failed to create team: {e}", is_error=True)

        # 3. 可选：启用协调者模式
        coordinator_note = ""
        from mewcode.teams.coordinator import is_coordinator_mode
        if is_coordinator_mode(self._enable_coordinator_mode):
            from mewcode.agents.tool_filter import apply_coordinator_filter
            self._parent_agent.coordinator_mode = True
            self._parent_agent._team_manager = self._team_manager
            self._parent_agent._full_registry = self._parent_agent.registry
            self._parent_agent.registry = apply_coordinator_filter(self._parent_agent.registry)
            coordinator_note = "\nCoordinator Mode activated: tools narrowed to dispatch-only."

        return ToolResult(
            output=(
                f"Team '{team.name}' created successfully.\n"
                f"Backend: {backend.value}\n"
                f"Config: {team.config_path}\n"
                f"Use Agent tool with team_name='{team.name}' to spawn teammates."
                f"{coordinator_note}"
            )
        )
