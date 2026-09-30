"""
loader.py — 子 Agent 加载器
=============================

【这个模块做什么】
AgentLoader 负责从多个来源加载子 Agent 定义：

1. 项目级（.mewcode/agents/）—— 优先级最高
2. 用户级（~/.mewcode/agents/）—— 个人全局 Agent
3. 内置（mewcode/agents/builtins/）—— 随代码发布
4. 插件（预留，未实现）

【优先级规则】
同名 Agent，高优先级来源会覆盖低优先级来源。
例如：项目级定义了 "code-reviewer"，内置也有 "code-reviewer"，
则使用项目级版本。

【热重载】
对于文件来源的 Agent，每次 get() 时会检查文件是否更新，
自动重新加载。这样修改 Agent 定义文件后无需重启即可生效。
"""
from __future__ import annotations

import importlib.resources
import logging
from pathlib import Path

from mewcode.agents.parser import AgentDef, AgentParseError, parse_agent_file

log = logging.getLogger(__name__)

# Agent 定义文件的搜索目录
PROJECT_AGENTS_DIR = ".mewcode/agents"  # 项目级
USER_AGENTS_DIR = "~/.mewcode/agents"   # 用户级


class AgentLoader:
    """
    子 Agent 加载器。
    
    从多个目录加载 Agent 定义文件（.md），按优先级合并，
    并提供热重载能力。
    """

    def __init__(
        self,
        work_dir: str,                    # 项目工作目录
        enable_verification: bool = False, # 是否启用验证 Agent
    ) -> None:
        self._work_dir = work_dir
        self._enable_verification = enable_verification
        self._agents: dict[str, AgentDef] = {}  # 已加载的 Agent {名称: 定义}


    def _scan_directory(self, path: Path, source: str) -> list[AgentDef]:
        """
        扫描目录中的所有 .md 文件，解析为 AgentDef 列表。
        解析失败的文件会被跳过并记录警告。
        """
        results: list[AgentDef] = []
        if not path.is_dir():
            return results

        for entry in sorted(path.iterdir()):
            if not entry.is_file() or entry.suffix != ".md":
                continue
            try:
                agent_def = parse_agent_file(entry)
                agent_def.source = source
                agent_def.file_path = entry
                results.append(agent_def)
            except AgentParseError as e:
                log.warning("Skipping agent file %s: %s", entry, e)
        return results


    def _load_builtins(self) -> list[AgentDef]:
        """
        加载内置 Agent 定义。
        内置 Agent 打包在 mewcode/agents/builtins/ 目录中，
        通过 importlib.resources 访问（支持打包为 zip/wheel 的情况）。
        """
        results: list[AgentDef] = []
        try:
            builtins_pkg = importlib.resources.files("mewcode.agents.builtins")
        except (ModuleNotFoundError, TypeError):
            log.warning("Could not load built-in agents package")
            return results

        for item in builtins_pkg.iterdir():
            if not item.name.endswith(".md"):
                continue
            try:
                raw = item.read_text(encoding="utf-8")
                from mewcode.agents.parser import parse_frontmatter, _validate_agent_meta

                meta, body = parse_frontmatter(raw)
                _validate_agent_meta(meta, item.name)

                agent_def = AgentDef(
                    agent_type=meta["name"],
                    when_to_use=meta["description"],
                    system_prompt=body,
                    tools=meta.get("tools", []),
                    disallowed_tools=meta.get("disallowedTools", []),
                    model=str(meta.get("model", "inherit")),
                    max_turns=meta.get("maxTurns", 50),
                    permission_mode=str(meta.get("permissionMode", "default")),
                    background=bool(meta.get("background", False)),
                    file_path=None,
                    source="builtin",
                )

                # 验证 Agent 是特殊的内置 Agent，需要显式启用
                if (
                    agent_def.agent_type == "Verification"
                    and not self._enable_verification
                ):
                    continue

                results.append(agent_def)
            except (AgentParseError, Exception) as e:
                log.warning("Skipping built-in agent %s: %s", item.name, e)

        return results

    def load_all(self) -> dict[str, AgentDef]:
        """
        从所有来源加载 Agent 定义，按优先级合并。
        同名 Agent 高优先级覆盖低优先级。
        """
        seen: dict[str, AgentDef] = {}

        # 优先级 1：项目级（最高）
        project_path = Path(self._work_dir) / PROJECT_AGENTS_DIR
        for agent_def in self._scan_directory(project_path, "project"):
            if agent_def.agent_type not in seen:
                seen[agent_def.agent_type] = agent_def

        # 优先级 2：用户级
        user_path = Path(USER_AGENTS_DIR).expanduser()
        for agent_def in self._scan_directory(user_path, "user"):
            if agent_def.agent_type not in seen:
                seen[agent_def.agent_type] = agent_def

        # 优先级 3：内置
        for agent_def in self._load_builtins():
            if agent_def.agent_type not in seen:
                seen[agent_def.agent_type] = agent_def

        # 优先级 4：插件（保留，未实现）

        self._agents = seen
        return seen


    def get(self, agent_type: str) -> AgentDef | None:
        """
        获取指定类型的 Agent 定义。
        支持热重载：如果源文件已更新，自动重新解析。
        """
        cached = self._agents.get(agent_type) #先查缓存，None 直接返回	不存在的 Agent 不做无用 IO
        if cached is None:
            return None

        # 从文件热重载：每次都无条件重新解析
        if cached.file_path is not None and cached.file_path.exists():
            try:
                reloaded = parse_agent_file(cached.file_path) #parse_agent_file() 重新读盘解析 核心动作：拿到文件当前内容
                reloaded.source = cached.source     #修补信息丢失（见下）
                self._agents[agent_type] = reloaded
                return reloaded
            except AgentParseError as e:
                log.warning(
                    "Hot reload failed for %s, using cached: %s",
                    agent_type,
                    e,
                )
        return cached


    def list_agents(self) -> list[tuple[str, str]]:
        """返回所有已加载 Agent 的 (名称, 描述) 列表"""
        return [
            (ad.agent_type, ad.when_to_use) for ad in self._agents.values()
        ]

    def register_plugin_source(self, path: Path) -> None:
        """注册插件来源（预留接口，未实现）"""
        pass
