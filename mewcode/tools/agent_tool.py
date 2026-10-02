"""
agent_tool.py — 子 Agent 启动工具（核心编排器）
================================================

【这个模块做什么】
启动子 Agent 来处理任务，支持三种执行路径：
1. 普通子 Agent: 在父 Agent 进程内运行
2. Worktree 隔离: 在独立 Git worktree 中执行
3. 团队成员: 作为长期运行的队友在独立终端执行

【三种路径对比】
- 普通子 Agent: 一次性任务，阻塞等待结果
- Worktree 隔离: 独立工作区，不污染主目录
- 团队成员: 长期运行，通过 SendMessage 通信

【设计亮点】
- 通过参数组合决定执行路径（team_name、isolation、subagent_type）
- 统一的权限检查、任务追踪、追踪树管理
- 支持 Fork 模式（继承父对话上下文）
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from mewcode.tools.base import Tool, ToolResult

if TYPE_CHECKING:
    from mewcode.agent import Agent
    from mewcode.agents.loader import AgentLoader
    from mewcode.agents.task_manager import TaskManager
    from mewcode.agents.trace import TraceManager
    from mewcode.client import LLMClient

log = logging.getLogger(__name__)


class AgentToolParams(BaseModel):
    """
    Agent 工具的入参模型。
    
    通过参数组合决定启动哪种类型的子 Agent：
    - 仅带 prompt: fork 当前对话（需开启 enable_fork）
    - 带 subagent_type: 启动预设类型的子 Agent（Explore/Plan/...）
    - 带 team_name: 以团队成员身份启动（团队协作场景）
    """

    prompt: str  # 派发给子 Agent 的任务说明
    description: str  # 描述字段（供调度/展示使用）
    subagent_type: str | None = None  # 预设 Agent 类型，省略则 fork 父对话
    model: str | None = None  # 覆盖模型（如 haiku/sonnet/opus），否则继承父 Agent
    run_in_background: bool = False  # 是否后台运行（不阻塞，返回 Task ID）
    force_foreground: bool = False  # DAG 等调用方强制等待真实结果
    name: str | None = None  # 自定义子 Agent 名称
    isolation: str | None = None  # 隔离方式（如 "worktree"），来自 Agent 定义
    team_name: str | None = Field(
        default=None,
        description=(
            "REQUIRED when creating team members. Spawns the agent as a long-running "
            "teammate under this team (created via TeamCreate). Unlike regular sub-agents, "
            "team members run in their own terminal, persist after the lead returns, and "
            "communicate with each other via SendMessage. Without team_name the agent "
            "runs as a one-shot sub-agent that blocks and returns inline."
        ),
    )


# 权限模式映射：配置字符串 → PermissionMode 枚举名
PERMISSION_MODE_MAP = {
    "default": "DEFAULT",
    "acceptEdits": "ACCEPT_EDITS",
    "dontAsk": "DONT_ASK",
}


# 团队成员的强制约束（附加到系统提示词末尾）
# 成员只能通过 SendMessage 与外界通信，文件访问限定在隔离 worktree 内
TEAMMATE_ADDENDUM = (
    "\n\nIMPORTANT: You are running as an agent in a team.\n"
    "Just writing a response in text is not visible to others\n"
    "on your team - you MUST use the SendMessage tool.\n"
    "The user interacts primarily with the team lead.\n"
    "Your work is coordinated through the task system\n"
    "and teammate messaging.\n\n"
    "You are working in an isolated Git worktree. "
    "All file paths you use MUST be relative to your current working directory. "
    "Do NOT use absolute paths from the original project — they are outside your sandbox and will be rejected."
)


class AgentTool(Tool):
    """
    子 Agent 启动工具 — 核心编排器。
    
    根据参数选择三种执行路径：
    1. 指定 team_name → 团队成员模式
    2. isolation="worktree" → Git worktree 隔离执行
    3. 其他 → 常规子 Agent（预设类型或 fork 父对话）
    """
    name = "Agent"
    description = (
        "Launch a sub-agent to handle a task in an isolated context. "
        "Use subagent_type to select a predefined agent type (e.g. Explore, Plan, general-purpose), "
        "or leave it empty to fork the current conversation. "
        "Use team_name to spawn a teammate in an existing team."
    )
    params_model = AgentToolParams
    category = "command"
    is_concurrency_safe = False


    def __init__(
        self,
        agent_loader: AgentLoader,
        task_manager: TaskManager,
        trace_manager: TraceManager,
        parent_agent: Agent,
        enable_fork: bool = False,
        provider_config: Any = None,
        worktree_manager: Any = None,
        team_manager: Any = None,
    ) -> None:
        self._agent_loader = agent_loader      # Agent 定义加载器
        self._task_manager = task_manager        # 任务管理器（后台任务）
        self._trace_manager = trace_manager      # 追踪管理器（追踪树）
        self._parent_agent = parent_agent        # 父 Agent（继承配置）
        self._enable_fork = enable_fork          # 是否允许 Fork 模式
        self._provider_config = provider_config  # LLM 提供商配置
        self._worktree_manager = worktree_manager  # Worktree 管理器
        self._team_manager = team_manager        # 团队管理器

    async def execute(self, params: BaseModel) -> ToolResult:
        """
        Agent 工具主入口。
        
        按参数分流到三种执行路径：
        1. team_name 存在 → _execute_as_teammate()
        2. isolation="worktree" → _execute_with_worktree()
        3. 其他 → 常规子 Agent 执行
        """
        p: AgentToolParams = params  # type: ignore[assignment]

        # 路径 1：指定了团队 → 以团队成员身份启动
        if p.team_name:
            return await self._execute_as_teammate(p)

        # 解析子 Agent 是否要求 worktree 隔离（以定义中的 isolation 为准）
        isolation = ""
        if p.subagent_type:
            defn = self._agent_loader.get(p.subagent_type)
            if defn and defn.isolation:
                isolation = defn.isolation

        # 路径 2：隔离在独立 Git worktree 中执行，不污染主工作区
        if isolation == "worktree":
            return await self._execute_with_worktree(p)

        # 路径 3：常规子 Agent（预设类型或 fork 父对话）
        from mewcode.agents.fork import ForkError, build_forked_messages
        from mewcode.agents.parser import AgentDef
        from mewcode.agents.tool_filter import resolve_agent_tools
        from mewcode.agent import Agent as AgentClass
        from mewcode.conversation import ConversationManager
        from mewcode.permissions import (
            DangerousCommandDetector,
            PathSandbox,
            PermissionChecker,
            PermissionMode,
            RuleEngine,
        )

        definition: AgentDef | None = None
        conversation: ConversationManager

        # 3a. 有 subagent_type：从加载器取预设定义；无则尝试 fork 父对话
        if p.subagent_type:
            definition = self._agent_loader.get(p.subagent_type)
            if definition is None:
                return ToolResult(
                    output=f"Unknown agent type: '{p.subagent_type}'. "
                    f"Available types: {', '.join(t for t, _ in self._agent_loader.list_agents())}",
                    is_error=True,
                )
            conversation = ConversationManager()  # 预设类型：全新的空对话
        else:
            # fork 模式必须先被显式开启
            if not self._enable_fork:
                return ToolResult(
                    output="Fork mode is not enabled. "
                    "Set 'enable_fork: true' in config.yaml to use fork, "
                    "or specify a subagent_type parameter.",
                    is_error=True,
                )
            try:
                parent_conv = getattr(self._parent_agent, '_current_conversation', None)
                if parent_conv is None:
                    return ToolResult(
                        output="Cannot fork: no active conversation in parent agent.",
                        is_error=True,
                    )
                # fork 时基于父对话的当前消息构造新会话，继承已有上下文
                conversation = build_forked_messages(parent_conv, p.prompt)
            except ForkError as e:
                return ToolResult(output=str(e), is_error=True)

            # fork 出的子 Agent 使用一个内置定义
            definition = AgentDef(
                agent_type="fork",
                when_to_use="Forked from parent agent",
                system_prompt="",
                disallowed_tools=[],
                model="inherit",  # 模型默认继承父 Agent
                max_turns=self._parent_agent.max_iterations,
                permission_mode="dontAsk",
                source="builtin",
            )

        # 选择 LLM 客户端：优先按入参/定义的模型覆盖，否则复用父客户端
        client = self._select_llm(p, definition)

        # 判定是否后台运行：入参指定、定义要求、或处于 fork 模式
        is_background = not p.force_foreground and (p.run_in_background or definition.background)
        # Fork mode normally runs asynchronously, but DAG nodes explicitly
        # request a foreground result so that dependency scheduling cannot
        # mistake a task handle for completed work.
        if self._enable_fork and not p.force_foreground:
            is_background = True

        # 过滤工具：优先用完整注册表（coordinator 模式可能已缩减注册表）
        _base_registry = getattr(self._parent_agent, '_full_registry', None) or self._parent_agent.registry
        filtered_registry = resolve_agent_tools(
            _base_registry, definition, is_background
        )

        # 为子 agent 创建权限检查器
        pm_str = definition.permission_mode
        pm_enum = getattr(
            PermissionMode,
            PERMISSION_MODE_MAP.get(pm_str, "DEFAULT"),
            PermissionMode.DEFAULT,
        )
        # Non-interactive parent runs cannot answer permission prompts. Pass
        # through explicit dontAsk mode to synchronous DAG children.
        if self._parent_agent.permission_mode == PermissionMode.DONT_ASK:
            pm_enum = PermissionMode.DONT_ASK
        checker = PermissionChecker(
            detector=DangerousCommandDetector(),
            sandbox=PathSandbox(self._parent_agent.work_dir),
            rule_engine=RuleEngine(),
            mode=pm_enum,
        )

        # 创建子 agent
        sub_agent = AgentClass(
            client=client,
            registry=filtered_registry,
            protocol=self._parent_agent.protocol,
            work_dir=self._parent_agent.work_dir,
            max_iterations=definition.max_turns,
            permission_checker=checker,
            context_window=self._parent_agent.context_window,
            instructions_content=definition.system_prompt,
            hook_engine=self._parent_agent.hook_engine,
        )
        sub_agent.parent_id = self._parent_agent.agent_id  # 记录父 Agent 关系
        sub_agent.trace_id = self._parent_agent.trace_id or self._parent_agent.agent_id

        # fork 子 agent 继承父 agent 的替换状态，确保共享的 tool_use_id 做出一致的
        # 决策——这样父子共享的 prompt cache 前缀才能保持字节级一致
        if p.subagent_type is None:
            from mewcode.context import clone_replacement_state
            sub_agent.replacement_state = clone_replacement_state(
                self._parent_agent.replacement_state
            )

        # 注册追踪节点，建立父→子的调用链
        trace_node = self._trace_manager.create(
            agent_type=definition.agent_type,
            parent_id=self._parent_agent.agent_id,
            trace_id=sub_agent.trace_id,
        )
        sub_agent.agent_id = trace_node.agent_id

        agent_name = p.name or p.subagent_type or f"agent-{trace_node.agent_id}"
        is_fork = p.subagent_type is None

        # 分支：后台启动 or 前台同步执行
        if is_background:
            if is_fork:
                sub_agent._fork_conversation = conversation
            task_id = self._task_manager.launch(
                agent=sub_agent,
                task="" if is_fork else p.prompt,
                name=agent_name,
                fork_conversation=conversation if is_fork else None,
            )
            # 后台启动后立即返回 Task ID，明确告知"不要睡/轮询"
            return ToolResult(
                output=f"Sub-agent launched in background.\n"
                f"Task ID: {task_id}\n"
                f"Agent: {agent_name}\n"
                f"Type: {definition.agent_type}\n"
                f"The system will notify automatically when it completes.\n"
                f"Do NOT wait, sleep, or poll. Report the task ID to the user and move on.",
            )

        # 前台同步执行
        try:
            if is_fork:
                result_text = await sub_agent.run_to_completion("", conversation)
            else:
                result_text = await sub_agent.run_to_completion(p.prompt)
        except Exception as e:
            self._trace_manager.complete(trace_node.agent_id, "failed")
            return ToolResult(
                output=f"Sub-agent failed: {e}", is_error=True
            )

        self._trace_manager.update(
            trace_node.agent_id,
            input_tokens=sub_agent.total_input_tokens,
            output_tokens=sub_agent.total_output_tokens,
        )
        self._trace_manager.complete(trace_node.agent_id, "completed")

        return ToolResult(output=result_text or "(sub-agent returned no output)")

    async def _execute_as_teammate(self, p: AgentToolParams) -> ToolResult:
        """以团队成员身份启动代理：持久运行、独立 worktree、经 SendMessage 协作。"""
        if self._team_manager is None:
            return ToolResult(output="TeamManager not configured.", is_error=True)
        if self._worktree_manager is None:
            return ToolResult(output="WorktreeManager not configured for team spawn.", is_error=True)

        from mewcode.agents.fork import ForkError, build_forked_messages
        from mewcode.agents.parser import AgentDef
        from mewcode.agents.tool_filter import build_teammate_tools
        from mewcode.agent import Agent as AgentClass
        from mewcode.conversation import ConversationManager
        from mewcode.permissions import (
            DangerousCommandDetector,
            PathSandbox,
            PermissionChecker,
            PermissionMode,
            RuleEngine,
        )
        from mewcode.teams.models import BackendType, TeammateInfo
        from mewcode.teams.registry import AgentNameRegistry

        team = self._team_manager.get_team(p.team_name)
        if team is None:
            return ToolResult(output=f"Team '{p.team_name}' not found. Create it first with TeamCreate.", is_error=True)

        # 生成唯一队友名：重名时追加 -2、-3...
        base_name = p.name or p.subagent_type or "worker"
        existing_names = {m.name for m in team.members}
        teammate_name = base_name
        if teammate_name in existing_names:
            counter = 2
            while f"{base_name}-{counter}" in existing_names:
                counter += 1
            teammate_name = f"{base_name}-{counter}"

        # 1. 加载 agent 定义（预设类型或 fork 父对话）
        definition: AgentDef
        conversation: ConversationManager | None = None
        is_fork = False

        if p.subagent_type:
            defn = self._agent_loader.get(p.subagent_type)
            if defn is None:
                return ToolResult(
                    output=f"Unknown agent type: '{p.subagent_type}'. "
                    f"Available: {', '.join(t for t, _ in self._agent_loader.list_agents())}",
                    is_error=True,
                )
            definition = defn
        else:
            if self._enable_fork:
                try:
                    parent_conv = getattr(self._parent_agent, '_current_conversation', None)
                    if parent_conv is None:
                        return ToolResult(output="Cannot fork: no active conversation.", is_error=True)
                    conversation = build_forked_messages(parent_conv, p.prompt)
                    is_fork = True
                except ForkError as e:
                    return ToolResult(output=str(e), is_error=True)

            definition = AgentDef(
                agent_type="teammate",
                when_to_use="Team member",
                system_prompt="",
                disallowed_tools=[],
                model="inherit",
                max_turns=self._parent_agent.max_iterations,
                permission_mode="dontAsk",
                source="builtin",
            )

        # 2. 创建 worktree
        wt_name = f"team-{p.team_name}/{teammate_name}"
        try:
            wt = await self._worktree_manager.create(wt_name, "HEAD")
        except Exception as e:
            return ToolResult(output=f"Failed to create worktree for teammate: {e}", is_error=True)

        # 3. 选择 LLM
        client = self._select_llm(p, definition)

        # 4. 检测后端类型
        backend = self._team_manager.detect_backend()

        # 5. 构建队友的工具集
        trace_node = self._trace_manager.create(
            agent_type=definition.agent_type,
            parent_id=self._parent_agent.agent_id,
            trace_id=self._parent_agent.trace_id or self._parent_agent.agent_id,
        )
        agent_id = trace_node.agent_id

        _has_full = getattr(self._parent_agent, '_full_registry', None) is not None
        full_registry = getattr(self._parent_agent, '_full_registry', None) or self._parent_agent.registry
        _full_tools = [t.name for t in full_registry.list_tools()]
        log.info(
            "[teammate] has_full_registry=%s full_tools=%d names=%s backend=%s def_tools=%s def_disallowed=%s",
            _has_full, len(_full_tools), _full_tools,
            backend.value,
            getattr(definition, 'tools', []),
            getattr(definition, 'disallowed_tools', []),
        )
        teammate_registry = build_teammate_tools(
            parent_registry=full_registry,
            team_manager=self._team_manager,
            team_name=p.team_name,
            agent_id=agent_id,
            agent_name=teammate_name,
            backend_type=backend.value,
            definition=definition,
        )
        _tm_tools = [t.name for t in teammate_registry.list_tools()]
        log.info("[teammate] result_tools=%d names=%s", len(_tm_tools), _tm_tools)

        # 6. 创建子 agent 并附加队友专属指令
        instructions = (definition.system_prompt or "") + TEAMMATE_ADDENDUM

        checker = PermissionChecker(
            detector=DangerousCommandDetector(),
            sandbox=PathSandbox(wt.path),
            rule_engine=RuleEngine(),
            mode=PermissionMode.DONT_ASK,
        )

        sub_agent = AgentClass(
            client=client,
            registry=teammate_registry,
            protocol=self._parent_agent.protocol,
            work_dir=wt.path,
            max_iterations=definition.max_turns,
            permission_checker=checker,
            context_window=self._parent_agent.context_window,
            instructions_content=instructions,
            hook_engine=self._parent_agent.hook_engine,
        )
        sub_agent.parent_id = self._parent_agent.agent_id
        sub_agent.trace_id = self._parent_agent.trace_id or self._parent_agent.agent_id
        sub_agent.agent_id = agent_id
        sub_agent.team_name = p.team_name
        sub_agent._team_manager = self._team_manager

        # 7. 注册名称和成员信息
        AgentNameRegistry.instance().register(teammate_name, agent_id)

        member = TeammateInfo(
            name=teammate_name,
            agent_id=agent_id,
            agent_type=definition.agent_type,
            model=p.model or definition.model,
            worktree_path=wt.path,
            backend_type=backend.value,
            is_active=True,
        )
        self._team_manager.register_member(p.team_name, member)

        # 8. 按后端类型启动队友
        if backend in (BackendType.TMUX, BackendType.ITERM2):
            return self._spawn_pane_teammate(
                p, team, member, backend, wt, agent_id, teammate_name
            )

        # 进程内模式：直接用 task_manager 执行并通知结果
        task_id = self._task_manager.launch(
            agent=sub_agent,
            task="" if is_fork else p.prompt,
            name=teammate_name,
            fork_conversation=conversation if is_fork else None,
        )

        return ToolResult(
            output=(
                f"Teammate '{teammate_name}' spawned in team '{p.team_name}'.\n"
                f"Agent ID: {agent_id}\n"
                f"Backend: {backend.value}\n"
                f"Worktree: {wt.path}\n"
                f"Task ID: {task_id}\n"
                f"The system will notify when it completes."
            )
        )


    def _spawn_pane_teammate(
        self, p: Any, team: Any, member: Any, backend: Any, wt: Any,
        agent_id: str, teammate_name: str,
    ) -> ToolResult:
        """在独立终端（tmux pane / iterm2 pane）中启动团队队友，与主进程解耦。"""
        from mewcode.teams.models import BackendType

        mailbox = self._team_manager.get_mailbox(p.team_name)
        mailbox_dir = str(mailbox._base_dir) if mailbox else ""

        try:
            if backend == BackendType.TMUX:
                from mewcode.teams.spawn_tmux import spawn_tmux_teammate
                pane_info = spawn_tmux_teammate(
                    team_name=p.team_name,
                    teammate_name=teammate_name,
                    worktree_path=wt.path,
                    prompt=p.prompt,
                    agent_type=p.subagent_type or "",
                    model=p.model or "",
                    mailbox_dir=mailbox_dir,
                )
                self._team_manager.register_pane_id(agent_id, pane_info.pane_id)
            elif backend == BackendType.ITERM2:
                from mewcode.teams.spawn_iterm2 import spawn_iterm2_teammate
                pane_info = spawn_iterm2_teammate(
                    team_name=p.team_name,
                    teammate_name=teammate_name,
                    worktree_path=wt.path,
                    prompt=p.prompt,
                    agent_type=p.subagent_type or "",
                    model=p.model or "",
                    mailbox_dir=mailbox_dir,
                )
        except Exception as e:
            log.warning("Pane spawn failed, falling back to in-process: %s", e)
            return ToolResult(
                output=f"Pane spawn failed ({e}), teammate not started. Retry or set teammate_mode to in-process.",
                is_error=True,
            )

        return ToolResult(
            output=(
                f"Teammate '{teammate_name}' spawned in team '{p.team_name}'.\n"
                f"Agent ID: {agent_id}\n"
                f"Backend: {backend.value} (pane)\n"
                f"Worktree: {wt.path}\n"
                f"The teammate is running in an independent process."
            )
        )


    def _select_llm(
        self,
        params: AgentToolParams,
        definition: AgentDef,
    ) -> LLMClient:
        """选择子 Agent 的 LLM 客户端：优先按入参/定义覆盖模型，否则复用父客户端。"""
        from mewcode.agents.parser import AgentDef

        # 模型覆盖优先级：入参显式指定 > 定义中的 model（非 "inherit"）
        model_override = params.model or (
            definition.model if definition.model != "inherit" else None
        )

        if model_override and model_override != "inherit":
            client = self._create_client_for_model(model_override)
            if client is not None:
                return client

        return self._parent_agent.client


    async def _execute_with_worktree(self, p: AgentToolParams) -> ToolResult:
        """在独立 Git worktree 中隔离执行子任务，避免污染主工作区。"""
        if self._worktree_manager is None:
            return ToolResult(
                output="Worktree isolation is not available: WorktreeManager not configured.",
                is_error=True,
            )

        from mewcode.agents.parser import AgentDef
        from mewcode.agents.tool_filter import resolve_agent_tools
        from mewcode.agent import Agent as AgentClass
        from mewcode.conversation import ConversationManager
        from mewcode.permissions import (
            DangerousCommandDetector,
            PathSandbox,
            PermissionChecker,
            PermissionMode,
            RuleEngine,
        )
        from mewcode.worktree.integration import (
            build_worktree_notice,
            generate_worktree_name,
        )

        definition: AgentDef | None = None
        if p.subagent_type:
            definition = self._agent_loader.get(p.subagent_type)
            if definition is None:
                return ToolResult(
                    output=f"Unknown agent type: '{p.subagent_type}'. "
                    f"Available types: {', '.join(t for t, _ in self._agent_loader.list_agents())}",
                    is_error=True,
                )
        else:
            definition = AgentDef(
                agent_type="worktree-agent",
                when_to_use="Isolated worktree agent",
                system_prompt="",
                disallowed_tools=[],
                model="inherit",
                max_turns=self._parent_agent.max_iterations,
                permission_mode="dontAsk",
                source="builtin",
            )

        wt_name = generate_worktree_name()
        try:
            wt = await self._worktree_manager.create(wt_name, "HEAD")
        except Exception as e:
            return ToolResult(
                output=f"Failed to create worktree: {e}",
                is_error=True,
            )

        notice = build_worktree_notice(self._parent_agent.work_dir, wt.path)
        task = notice + "\n\n" + p.prompt

        client = self._select_llm(p, definition)

        _base_registry = getattr(self._parent_agent, '_full_registry', None) or self._parent_agent.registry
        filtered_registry = resolve_agent_tools(
            _base_registry, definition, False
        )

        pm_str = definition.permission_mode
        pm_enum = getattr(
            PermissionMode,
            PERMISSION_MODE_MAP.get(pm_str, "DEFAULT"),
            PermissionMode.DEFAULT,
        )
        checker = PermissionChecker(
            detector=DangerousCommandDetector(),
            sandbox=PathSandbox(wt.path),
            rule_engine=RuleEngine(),
            mode=pm_enum,
        )

        sub_agent = AgentClass(
            client=client,
            registry=filtered_registry,
            protocol=self._parent_agent.protocol,
            work_dir=wt.path,
            max_iterations=definition.max_turns,
            permission_checker=checker,
            context_window=self._parent_agent.context_window,
            instructions_content=definition.system_prompt,
            hook_engine=self._parent_agent.hook_engine,
        )
        sub_agent.parent_id = self._parent_agent.agent_id
        sub_agent.trace_id = self._parent_agent.trace_id or self._parent_agent.agent_id

        trace_node = self._trace_manager.create(
            agent_type=definition.agent_type,
            parent_id=self._parent_agent.agent_id,
            trace_id=sub_agent.trace_id,
        )
        sub_agent.agent_id = trace_node.agent_id

        try:
            result_text = await sub_agent.run_to_completion(task)
        except Exception as e:
            self._trace_manager.complete(trace_node.agent_id, "failed")
            return ToolResult(
                output=f"Sub-agent in worktree failed: {e}",
                is_error=True,
            )

        self._trace_manager.update(
            trace_node.agent_id,
            input_tokens=sub_agent.total_input_tokens,
            output_tokens=sub_agent.total_output_tokens,
        )
        self._trace_manager.complete(trace_node.agent_id, "completed")

        cleanup = await self._worktree_manager.auto_cleanup(wt_name, wt.head_commit)
        if cleanup.kept:
            result_text = (result_text or "") + (
                f"\n[Worktree preserved at {cleanup.path}, branch {cleanup.branch}]"
            )

        return ToolResult(output=result_text or "(sub-agent returned no output)")


    def _create_client_for_model(self, model_alias: str) -> LLMClient | None:
        if self._provider_config is None:
            return None

        from mewcode.client import create_client
        from mewcode.config import ProviderConfig

        model_map = {
            "haiku": "claude-haiku-4-5-20251001",
            "sonnet": "claude-sonnet-4-6-20250514",
            "opus": "claude-opus-4-6-20250514",
        }
        model_id = model_map.get(model_alias, model_alias)

        config = ProviderConfig(
            name=f"sub-{model_alias}",
            protocol=self._provider_config.protocol,
            base_url=self._provider_config.base_url,
            model=model_id,
            api_key=self._provider_config.api_key,
            context_window=self._provider_config.context_window,
        )
        try:
            return create_client(config)
        except Exception:
            return None
