"""
__main__.py — MewCode 启动入口（装配中心）
=============================================================

【这个模块做什么】
MewCode 的统一启动入口，负责「装配」所有子系统并选择运行模式：

  python -m mewcode              # 交互模式（TUI）
  python -m mewcode -p "提示词"  # 非交互模式（单次执行）

【两种运行模式】
┌─────────────────────────────────────────────────────────┐
│  交互模式 (默认)                                         │
│  → 启动 Textual TUI 应用 (MewCodeApp)                  │
│  → 用户通过终端界面与 Agent 交互                        │
│  → 支持多轮对话、命令补全、团队树等 UI 功能            │
├─────────────────────────────────────────────────────────┤
│  非交互模式 (-p)                                         │
│  → 直接构造 Agent 运行栈                               │
│  → 执行单次提示词并输出结果                             │
│  → 适合脚本调用和 CI/CD 集成                           │
└─────────────────────────────────────────────────────────┘

【装配流程】
1. 初始化日志 (.mewcode/debug.log)
2. 解析命令行参数 (--mode, -p)
3. 加载配置 (config.yaml 多层合并)
4. 加载 Hook 配置 (生命周期拦截器)
5. 根据模式选择:
   - 交互模式 → 创建 MewCodeApp (TUI)
   - 非交互模式 → 创建 Agent 运行栈 → 执行提示词

【设计思想：装配中心模式】
这个文件类似于一个「工厂车间」：
- 它不实现任何业务逻辑
- 它只负责把各个子系统（Agent、工具、权限、记忆等）组装在一起
- 所有子模块都通过显式导入和实例化来耦合，而非全局单例

这种设计的好处：
- 依赖关系清晰：看这个文件就知道系统有哪些组件
- 易于测试：可以单独测试每个子模块
- 易于扩展：新增组件只需在这里添加装配代码
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

from mewcode.config import ConfigError, load_config
from mewcode.hooks import HookConfigError, HookEngine, load_hooks
from mewcode.permissions import PermissionMode


def main() -> None:
    """
    MewCode 主入口函数。
    
    流程：
    1. 初始化日志系统
    2. 解析命令行参数
    3. 加载配置和 Hook
    4. 根据模式启动 TUI 或非交互执行
    """
    # ── 步骤 1: 初始化日志 ──────────────────────────────────────
    # 先确保 .mewcode/ 目录存在，否则写 debug.log 会因目录不存在而崩溃
    Path(".mewcode").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(message)s",
        filename=".mewcode/debug.log",
        filemode="w",  # 每次启动覆盖旧日志
    )

    # ── 步骤 2: 解析命令行参数 ──────────────────────────────────
    parser = argparse.ArgumentParser(prog="mewcode", description="MewCode AI coding assistant")
    parser.add_argument(
        "--mode",
        choices=[m.value for m in PermissionMode],
        default=None,
        help="Permission mode (overrides config.yaml)",
    )
    parser.add_argument(
        "-p",
        metavar="PROMPT",
        default=None,
        help="Run non-interactively: execute the prompt and print the result to stdout",
    )
    args = parser.parse_args()

    # ── 步骤 3: 加载配置 ────────────────────────────────────────
    # 配置来源: ~/.mewcode/config.yaml + .mewcode/config.yaml + .mewcode/config.local.yaml
    try:
        config = load_config()
    except ConfigError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    # 权限模式: 命令行参数优先，否则使用配置文件中的值
    mode_str = args.mode if args.mode else config.permission_mode
    permission_mode = PermissionMode(mode_str)

    # ── 步骤 4: 加载 Hook 配置 ──────────────────────────────────
    # Hook 是生命周期拦截器，可在 Agent 运行的关键时间点插入自定义逻辑
    try:
        hooks = load_hooks(config.raw_hooks)
    except HookConfigError as e:
        print(f"Hook config error: {e}", file=sys.stderr)
        sys.exit(1)

    hook_engine = HookEngine(hooks) if hooks else None

    # ── 步骤 5: 根据模式启动 ────────────────────────────────────
    if args.p is not None:
        for stream in (sys.stdout, sys.stderr):
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(errors="backslashreplace")
        # 非交互模式: 直接执行提示词并输出结果
        asyncio.run(_run_prompt(config, permission_mode, hook_engine, args.p))
        return

    # 交互模式: 启动 Textual TUI 应用
    from mewcode.app import MewCodeApp
    from mewcode.driver import NoAltScreenDriver

    app = MewCodeApp(
        providers=config.providers,
        permission_mode=permission_mode,
        mcp_servers=config.mcp_servers,
        hook_engine=hook_engine,
        enable_fork=config.enable_fork,
        enable_verification_agent=config.enable_verification_agent,
        worktree_config=config.worktree,
        teammate_mode=config.teammate_mode,
        enable_coordinator_mode=config.enable_coordinator_mode,
        driver_class=NoAltScreenDriver,
    )
    app.run()


async def _run_prompt(config, permission_mode, hook_engine, prompt: str) -> None:
    """
    非交互模式: 构造完整的 Agent 运行栈并执行单次提示词。
    
    这个函数是「装配中心」的核心：它把 MewCode 的所有子系统组装在一起。
    与交互模式 (MewCodeApp) 共享相同的装配逻辑，只是没有 UI 外壳。
    
    装配清单:
    ┌───────────────────────────────────────────────────────────────┐
    │  组件                  职责                                  │
    ├───────────────────────────────────────────────────────────────┤
    │  LLM Client           与 AI 模型通信                        │
    │  PermissionChecker    工具调用权限检查                        │
    │  ToolRegistry         工具注册表                              │
    │  Agent                Agent 主循环引擎                        │
    │  WorktreeManager      Git Worktree 管理                       │
    │  AgentLoader          子 Agent 定义加载                       │
    │  TaskManager          后台任务管理                            │
    │  TraceManager         执行追踪                                │
    │  TeamManager          团队协作管理                            │
    │  AgentTool            子 Agent 启动工具                       │
    │  DAG Tools            DAG 编排工具                            │
    │  Team Tools           团队创建/删除工具                       │
    └───────────────────────────────────────────────────────────────┘
    """
    # ── 延迟导入: 避免交互模式启动时加载不必要的模块 ────────────
    from mewcode.agent import Agent
    from mewcode.client import create_client, resolve_context_window
    from mewcode.conversation import ConversationManager
    from mewcode.memory.instructions import load_instructions
    from mewcode.permissions import (
        DangerousCommandDetector,
        PathSandbox,
        PermissionChecker,
        RuleEngine,
    )
    from mewcode.tools import create_default_registry
    from mewcode.agents.loader import AgentLoader
    from mewcode.agents.task_manager import TaskManager
    from mewcode.agents.trace import TraceManager
    from mewcode.tools.agent_tool import AgentTool
    from mewcode.tools.impl.tool_search import ToolSearchTool
    from mewcode.teams.manager import TeamManager
    from mewcode.teams.models import BackendType
    from mewcode.tools.team_create import TeamCreateTool
    from mewcode.tools.team_delete import TeamDeleteTool
    from mewcode.worktree import WorktreeManager
    from mewcode.config import WorktreeConfig

    # ── 1. LLM 客户端 ───────────────────────────────────────────
    provider = config.providers[0]
    client = create_client(provider)
    # 尽力从 provider 自动拉取模型的 context window（缓存在 provider 上）。
    # 不会抛异常或阻塞启动；失败则退化到映射表。
    await resolve_context_window(provider)
    work_dir = os.getcwd()
    home = Path.home()

    # ── 2. 权限检查器 ───────────────────────────────────────────
    # 多层权限检查: 危险命令检测 + 路径沙箱 + 规则引擎 + 权限模式
    checker = PermissionChecker(
        detector=DangerousCommandDetector(),
        sandbox=PathSandbox(work_dir),
        rule_engine=RuleEngine(
            user_rules_path=home / ".mewcode" / "permissions.yaml",
            project_rules_path=Path(work_dir) / ".mewcode" / "permissions.yaml",
            local_rules_path=Path(work_dir) / ".mewcode" / "permissions.local.yaml",
        ),
        mode=permission_mode,
    )

    # ── 3. 指令与工具注册表 ─────────────────────────────────────
    # 加载 MEWCODE.md 项目指令（会递归解析 @include 指令）
    instructions = load_instructions(work_dir)
    # 创建默认工具注册表（包含 ReadFile、WriteFile、Bash 等核心工具）
    registry = create_default_registry()
    # 注册 ToolSearchTool，让 Agent 能「发现」延迟加载的工具
    registry.register(ToolSearchTool(registry, protocol=provider.protocol))

    # ── 4. Agent 主引擎 ─────────────────────────────────────────
    # Agent 是「思考-行动-观察」循环的核心
    agent = Agent(
        client=client,
        registry=registry,
        protocol=provider.protocol,
        work_dir=work_dir,
        permission_checker=checker,
        context_window=provider.get_context_window(),
        instructions_content=instructions,
        hook_engine=hook_engine,
    )

    # ── 5. 辅助管理器 ───────────────────────────────────────────
    # WorktreeManager: Git Worktree 隔离工作区管理
    wt_cfg = config.worktree or WorktreeConfig()
    wt_manager = WorktreeManager(
        repo_root=work_dir,
        symlink_directories=wt_cfg.symlink_directories,
    )
    # TraceManager: 子 Agent 执行追踪
    trace_manager = TraceManager()
    # TaskManager: 后台任务管理（支持异步执行和完成通知）
    task_manager = TaskManager()
    # AgentLoader: 加载子 Agent 定义（.mewcode/agents/*.md）
    agent_loader = AgentLoader(work_dir, enable_verification=config.enable_verification_agent)
    agent_loader.load_all()
    # TeamManager: 多 Agent 团队协作管理
    team_manager = TeamManager(worktree_manager=wt_manager, trace_manager=trace_manager)

    # ── 6. 编排工具注册 ─────────────────────────────────────────
    # AgentTool: 让 Agent 能启动子 Agent
    agent_tool = AgentTool(
        agent_loader=agent_loader,
        task_manager=task_manager,
        trace_manager=trace_manager,
        parent_agent=agent,
        enable_fork=config.enable_fork,
        provider_config=provider,
        worktree_manager=wt_manager,
        team_manager=team_manager,
    )
    registry.register(agent_tool)
    # DAG 工具: 有向无环图方式编排多个子 Agent
    from mewcode.tools.dag_tools import DAGCreateTool, DAGStatusTool
    dag_tool = DAGCreateTool(agent_tool, work_dir=work_dir)
    registry.register(dag_tool)
    registry.register(DAGStatusTool(dag_tool.scheduler))
    # 团队工具: 创建/删除多 Agent 协作团队
    registry.register(TeamCreateTool(
        team_manager=team_manager,
        parent_agent=agent,
        teammate_mode="in-process",  # 非交互模式使用进程内执行
        is_interactive=False,
        enable_coordinator_mode=config.enable_coordinator_mode,
    ))
    registry.register(TeamDeleteTool(team_manager=team_manager, parent_agent=agent))

    # ── 7. 通知回调 ─────────────────────────────────────────────
    # 通知收集函数: 从任务管理器和团队邮箱收集通知
    def drain_notifications() -> list[str]:
        """收集所有待处理的通知（任务完成 + 团队消息）"""
        notes: list[str] = []
        for t in task_manager.poll_completed():
            notes.append(
                f"<task-notification>\n<task_id>{t.id}</task_id>\n"
                f"<status>{t.status}</status>\n<result>{t.result}</result>\n"
                f"</task-notification>"
            )
        notes.extend(team_manager.drain_lead_mailbox())
        return notes

    def drain_mailbox_only() -> list[str]:
        """仅收集团队邮箱消息"""
        return team_manager.drain_lead_mailbox()

    # 将通知回调注入 Agent（每轮对话结束后调用）
    agent.notification_fn = drain_mailbox_only

    # ── 8. 执行提示词 ───────────────────────────────────────────
    conv = ConversationManager()
    last_result = await agent.run_to_completion(prompt, conv)
    print(last_result, flush=True)

    # ── 9. 团队通知轮询（如果有团队在运行） ───────────────────
    # 非交互模式下，如果有团队成员在后台运行，
    # 需要轮询收集它们的通知并喂回 Agent 处理
    if not team_manager._teams:
        return

    # 最多轮询 90 次 × 2 秒 = 180 秒
    import sys
    for i in range(90):
        await asyncio.sleep(2)
        running = {k: not t.done() for k, t in task_manager._async_tasks.items()}
        completed_ids = [t.id for t in task_manager._tasks.values() if t.status != "running"]
        print(f"[poll {i}] running={running} completed={completed_ids} teams={list(team_manager._teams.keys())} queue_size={task_manager._notify_queue.qsize()}", file=sys.stderr, flush=True)
        notes = drain_notifications()
        if not notes:
            has_running = any(v for v in running.values())
            if not has_running:
                print(f"[poll {i}] no running tasks, breaking", file=sys.stderr, flush=True)
                break
            continue
        # 将通知注入对话并让 Agent 继续处理
        for note in notes:
            conv.add_system_reminder(note)
        last_result = await agent.run_to_completion(
            "Teammate notifications received. Process them and continue.", conv
        )
        print(last_result, flush=True)


if __name__ == "__main__":
    main()

