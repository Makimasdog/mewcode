# 来源：公众号@小林coding
# 后端八股网站：xiaolincoding.com
# Agent网站：xiaolinnote.com
# 简历模版：jianli.xiaolinnote.com
"""
__main__.py — MewCode 程序入口
=====================================

【这个文件做什么】
这是 MewCode 的启动入口，执行 `python -m mewcode` 时会调用 main()。
它负责：
1. 初始化日志
2. 解析命令行参数
3. 加载配置和 Hook
4. 根据运行模式启动：
   - 交互模式：启动 Textual TUI 应用（MewCodeApp）
   - 非交互模式（-p）：直接执行提示词并输出结果

【两种运行模式】
    # 交互模式（默认）：启动 TUI 界面
    python -m mewcode

    # 非交互模式：执行单次提示词
    python -m mewcode -p "解释这个项目的作用"

【启动流程】
    main()
    ├── 创建 .mewcode/ 目录 + 初始化日志
    ├── 解析命令行参数（--mode, -p）
    ├── 加载配置（config.yaml）
    ├── 加载 Hook（hooks 配置）
    └── 分支：
        ├── -p 模式 → _run_prompt()  → 构建完整 Agent 栈 → 执行 → 输出
        └── 默认模式 → MewCodeApp()  → 启动 TUI 界面
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
    
    流程：初始化 → 解析参数 → 加载配置 → 加载 Hook → 启动应用
    """
    # 先确保 .mewcode/ 目录存在，否则下面写 debug.log 会因目录不存在而崩溃
    Path(".mewcode").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(message)s",
        filename=".mewcode/debug.log",
        filemode="w",
    )

    # 解析命令行参数
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

    # 加载配置文件（config.yaml）
    try:
        config = load_config()
    except ConfigError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    # 确定权限模式：命令行参数优先，否则用配置文件中的设置
    mode_str = args.mode if args.mode else config.permission_mode
    permission_mode = PermissionMode(mode_str)

    # 加载 Hook 配置（从 config.yaml 的 hooks 字段）
    try:
        hooks = load_hooks(config.raw_hooks)
    except HookConfigError as e:
        print(f"Hook config error: {e}", file=sys.stderr)
        sys.exit(1)

    hook_engine = HookEngine(hooks) if hooks else None

    # 非交互模式：执行单次提示词并输出结果
    if args.p is not None:
        asyncio.run(_run_prompt(config, permission_mode, hook_engine, args.p))
        return

    # 交互模式：启动 Textual TUI 应用
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
    非交互模式：构建完整的 Agent 运行栈，执行单次提示词并输出结果。
    
    这个函数手动组装 Agent 需要的所有组件（LLM客户端、权限检查、
    工具注册表、子 Agent、团队管理等），不经过 TUI 界面。
    
    用于脚本化调用、CI/CD 集成、管道处理等场景。
    """
    # === 导入所有需要的组件 ===
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

    # === 1. 创建 LLM 客户端 ===
    provider = config.providers[0]
    client = create_client(provider)
    # 第 2 层：尽力从 provider 自动拉取模型的 context window（缓存在 provider 上）。
    # 不会抛异常或阻塞启动；失败则退化到映射表。
    await resolve_context_window(provider)
    work_dir = os.getcwd()
    home = Path.home()

    # === 2. 创建权限检查器 ===
    # 包含：危险命令检测 + 路径沙箱 + 规则引擎
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

    # === 3. 创建工具注册表并注册基础工具 ===
    instructions = load_instructions(work_dir)
    registry = create_default_registry()
    registry.register(ToolSearchTool(registry, protocol=provider.protocol))

    # === 4. 创建主 Agent ===
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

    # === 5. 创建辅助管理器 ===
    wt_cfg = config.worktree or WorktreeConfig()
    wt_manager = WorktreeManager(
        repo_root=work_dir,
        symlink_directories=wt_cfg.symlink_directories,
    )
    trace_manager = TraceManager()      # Agent 追踪树
    task_manager = TaskManager()        # 后台任务管理
    agent_loader = AgentLoader(work_dir, enable_verification=config.enable_verification_agent)
    agent_loader.load_all()             # 加载所有 Agent 定义
    team_manager = TeamManager(worktree_manager=wt_manager, trace_manager=trace_manager)

    # === 6. 注册高级工具（子 Agent、团队管理） ===
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
    registry.register(TeamCreateTool(
        team_manager=team_manager,
        parent_agent=agent,
        teammate_mode="in-process",
        is_interactive=False,
        enable_coordinator_mode=config.enable_coordinator_mode,
    ))
    registry.register(TeamDeleteTool(team_manager=team_manager, parent_agent=agent))

    # === 7. 设置通知机制 ===
    def drain_notifications() -> list[str]:
        """收集任务完成通知和团队邮箱消息"""
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
        """只收集团队邮箱消息（初始阶段使用）"""
        return team_manager.drain_lead_mailbox()

    agent.notification_fn = drain_mailbox_only

    # === 8. 执行提示词 ===
    conv = ConversationManager()
    last_result = await agent.run_to_completion(prompt, conv)
    print(last_result, flush=True)

    # === 9. 团队模式：轮询等待团队任务完成 ===
    # 如果没有创建团队，直接返回
    if not team_manager._teams:
        return

    # 有团队在运行：每 2 秒轮询一次，最多等待 180 秒（90 * 2s）
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
        # 将团队通知注入对话，让 Agent 处理
        for note in notes:
            conv.add_system_reminder(note)
        last_result = await agent.run_to_completion(
            "Teammate notifications received. Process them and continue.", conv
        )
        print(last_result, flush=True)


if __name__ == "__main__":
    main()

