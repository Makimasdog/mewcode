"""
load_skill.py — 技能加载工具
================================================

【这个模块做什么】
加载并激活技能（Skill），将技能的 SOP 钉入环境上下文。

【技能类型】
- 文件型技能: 只包含提示词（SOP）
- 目录型技能: 包含提示词 + 专用工具

【工作流程】
1. 按名称查找技能
2. 激活技能（SOP 钉入环境上下文）
3. 如果是目录型技能，注册其专用工具
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from mewcode.tools.base import Tool, ToolResult

if TYPE_CHECKING:
    from mewcode.agent import Agent
    from mewcode.skills.directory import register_skill_tools
    from mewcode.skills.loader import SkillLoader


class LoadSkillParams(BaseModel):
    """LoadSkill 参数模型"""
    name: str = Field(description="The name of the skill to load")


class LoadSkill(Tool):
    """
    技能加载工具 — 加载并激活技能。
    
    特性:
    - 将技能的 SOP 钉入环境上下文
    - 目录型技能会注册专用工具
    - 标记为系统工具（is_system_tool=True）
    """
    name = "LoadSkill"
    description = (
        "Load and activate a skill by name. "
        "The skill's SOP will be pinned to the environment context "
        "and any specialized tools will be registered."
    )
    params_model = LoadSkillParams
    category = "read"
    is_concurrency_safe = False
    is_system_tool = True


    def __init__(self) -> None:
        self._loader: SkillLoader | None = None
        self._agent: Agent | None = None


    def set_loader(self, loader: SkillLoader) -> None:
        """注入技能加载器（延迟注入）"""
        self._loader = loader

    def set_agent(self, agent: Agent) -> None:
        """注入 Agent 实例（延迟注入）"""
        self._agent = agent


    async def execute(self, params: BaseModel) -> ToolResult:
        assert isinstance(params, LoadSkillParams)

        if self._loader is None or self._agent is None:
            return ToolResult(
                output="Error: LoadSkill not properly initialized",
                is_error=True,
            )

        # 1. 查找技能
        skill = self._loader.get(params.name)
        if skill is None:
            available = ", ".join(n for n, _ in self._loader.get_catalog())
            return ToolResult(
                output=f"Error: unknown skill '{params.name}'. Available skills: {available}",
                is_error=True,
            )

        # 2. 激活技能（SOP 钉入环境上下文）
        self._agent.activate_skill(skill.name, skill.prompt_body)

        # 3. 如果是目录型技能，注册其专用工具
        tool_count = 0
        if skill.is_directory and skill.source_path is not None:
            from mewcode.skills.directory import register_skill_tools
            skill_dir = skill.source_path.parent
            tool_count = register_skill_tools(skill_dir, self._agent.registry)

        parts = [f"Skill '{skill.name}' activated. SOP pinned to environment context."]
        if tool_count > 0:
            parts.append(f"{tool_count} specialized tool(s) registered.")
        return ToolResult(output=" ".join(parts))
