# 来源：公众号@小林coding
# 后端八股网站：xiaolincoding.com
# Agent网站：xiaolinnote.com
# 简历模版：jianli.xiaolinnote.com

"""LoadSkill 工具：让 Agent 能按名称"加载并激活"一个技能。

技能（skill）是一套预定义的 SOP（标准操作流程）+ 可选的专业工具集。
当 Agent 决定使用某个技能时，就调用本工具把它"挂载"进来，之后就能按
技能规定的步骤做事，并调用技能附带的专用工具。
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from mewcode.tools.base import Tool, ToolResult

if TYPE_CHECKING:
    # 仅在类型检查时导入，避免循环导入和启动时的额外开销
    from mewcode.agent import Agent
    from mewcode.skills.directory import register_skill_tools
    from mewcode.skills.loader import SkillLoader


class LoadSkillParams(BaseModel):
    # 本工具唯一需要的入参：要加载的技能名
    name: str = Field(description="The name of the skill to load")


class LoadSkill(Tool):
    # 工具在注册表 / 给 LLM 的 schema 中显示的名字
    name = "LoadSkill"
    # 对 LLM 的描述：让模型知道何时该用这个工具
    description = (
        "Load and activate a skill by name. "
        "The skill's SOP will be pinned to the environment context "
        "and any specialized tools will be registered."
    )
    params_model = LoadSkillParams  # 绑定入参模型
    category = "read"  # 归类为只读类工具（本质上不修改文件）
    is_concurrency_safe = False  # 加载技能会改全局状态，不能并发安全地重复执行
    is_system_tool = True  # 系统级工具，通常不面向用户直接调用


    def __init__(self) -> None:
        # 两个外部依赖通过 setter 注入，而非构造时传入：
        # 这样本工具可以被先创建、后由 Agent 初始化时再关联起来。
        self._loader: SkillLoader | None = None  # 用来查找/解析技能定义
        self._agent: Agent | None = None  # 执行加载动作的目标 Agent


    def set_loader(self, loader: SkillLoader) -> None:
        """注入技能加载器（由 Agent 初始化时调用）。"""
        self._loader = loader

    def set_agent(self, agent: Agent) -> None:
        """注入目标 Agent 实例（由 Agent 初始化时调用）。"""
        self._agent = agent


    async def execute(self, params: BaseModel) -> ToolResult:
        """执行入口：找到技能 → 激活 → 注册专用工具 → 返回结果。"""
        assert isinstance(params, LoadSkillParams)

        # 防御性检查：两个依赖必须已注入，否则说明初始化没完成
        if self._loader is None or self._agent is None:
            return ToolResult(
                output="Error: LoadSkill not properly initialized",
                is_error=True,
            )

        # 1. 按名称查技能；查不到则把可用技能列表告诉模型，方便它纠正
        skill = self._loader.get(params.name)
        if skill is None:
            available = ", ".join(n for n, _ in self._loader.get_catalog())
            return ToolResult(
                output=f"Error: unknown skill '{params.name}'. Available skills: {available}",
                is_error=True,
            )

        # 2. 把技能的 SOP 正文钉进 Agent 的环境上下文，让后续每轮它都带着这份指令
        self._agent.activate_skill(skill.name, skill.prompt_body)

        # 3. 若是"目录型技能"（带专用工具的文件夹技能），注册其附带的专业工具
        tool_count = 0
        if skill.is_directory and skill.source_path is not None:
            from mewcode.skills.directory import register_skill_tools
            skill_dir = skill.source_path.parent
            tool_count = register_skill_tools(skill_dir, self._agent.registry)

        # 4. 汇总结果：提示 SOP 已生效 + 注册了几个专用工具
        parts = [f"Skill '{skill.name}' activated. SOP pinned to environment context."]
        if tool_count > 0:
            parts.append(f"{tool_count} specialized tool(s) registered.")
        return ToolResult(output=" ".join(parts))