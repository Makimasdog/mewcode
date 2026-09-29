"""
parser.py — 子 Agent 定义文件解析器
=====================================

【这个模块做什么】
MewCode 支持通过 Markdown 文件定义子 Agent（类似技能文件）。
每个文件用 YAML frontmatter 定义元数据，正文作为系统提示词。

例如一个 Agent 定义文件（.md）：
    ---
    name: code-reviewer
    description: 代码审查专家
    tools: [ReadFile, Grep, Glob]
    model: inherit
    maxTurns: 20
    ---
    你是一个代码审查专家，负责检查代码质量和安全性...

本模块负责：
1. 解析这种文件格式（YAML frontmatter + Markdown 正文）
2. 验证必填字段和合法值
3. 生成 AgentDef 数据结构
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

# 合法的模型名称：inherit 表示继承父 Agent 的模型
VALID_MODELS = {"inherit", "sonnet", "opus", "haiku", ""}
# 合法的权限模式
VALID_PERMISSION_MODES = {"default", "acceptEdits", "dontAsk", ""}


class AgentParseError(Exception):
    """Agent 定义文件解析失败时抛出的异常"""
    pass


VALID_ISOLATION_MODES = {"", "worktree"}  # 隔离模式：空=不隔离，worktree=Git Worktree 隔离


@dataclass
class AgentDef:
    """
    子 Agent 的定义结构。
    
    一个 AgentDef 描述了一个子 Agent 的所有配置：
    - 它叫什么、什么时候该用它
    - 它的系统提示词（告诉 LLM 如何行动）
    - 它能用哪些工具、不能用哪些工具
    - 用什么模型、最多运行多少轮
    """
    agent_type: str           # Agent 类型名称（如 "code-reviewer"）
    when_to_use: str          # 描述什么时候应该使用这个 Agent（给主 Agent 看的）
    system_prompt: str = ""   # 系统提示词（Markdown 正文部分）
    tools: list[str] = field(default_factory=list)            # 允许使用的工具列表
    disallowed_tools: list[str] = field(default_factory=list) # 禁止使用的工具列表
    model: str = "inherit"    # 使用的模型（"inherit"=继承父 Agent）
    max_turns: int = 50       # 最大循环轮数
    permission_mode: str = "default"  # 权限模式
    background: bool = False  # 是否在后台运行
    isolation: str = ""       # 隔离模式（"worktree"=在 Git Worktree 中运行）
    file_path: Path | None = None  # 源文件路径（用于热重载）
    source: str = "builtin"   # 来源："builtin"/"project"/"user"/"plugin"


def parse_frontmatter(raw: str) -> tuple[dict, str]:
    """
    解析 Markdown 文件中的 YAML frontmatter。
    
    Frontmatter 格式：
        ---
        name: xxx
        description: xxx
        ---
        正文内容...
    
    返回: (元数据字典, 正文字符串)
    """
    stripped = raw.lstrip()
    if not stripped.startswith("---"):
        raise AgentParseError("Missing YAML frontmatter (must start with ---)")

    end = stripped.find("---", 3)
    if end == -1:
        raise AgentParseError("Unclosed YAML frontmatter (missing closing ---)")

    yaml_block = stripped[3:end]
    body = stripped[end + 3 :].lstrip("\n")

    try:
        meta = yaml.safe_load(yaml_block)
    except yaml.YAMLError as e:
        raise AgentParseError(f"Invalid YAML in frontmatter: {e}") from e

    if not isinstance(meta, dict):
        raise AgentParseError("Frontmatter must be a YAML mapping")

    return meta, body


def _validate_agent_meta(meta: dict, source: str = "") -> None:
    """
    验证 Agent 元数据的合法性。
    检查必填字段（name, description）和可选字段的合法值。
    """
    ctx = f" in {source}" if source else ""

    # 必填字段检查
    if "name" not in meta:
        raise AgentParseError(f"Missing required field 'name'{ctx}")
    if "description" not in meta:
        raise AgentParseError(f"Missing required field 'description'{ctx}")

    # 模型名称合法性检查
    model = str(meta.get("model", "inherit"))
    if model not in VALID_MODELS:
        raise AgentParseError(
            f"Invalid model '{model}'{ctx}: must be one of {VALID_MODELS - {''}}"
        )

    # 权限模式合法性检查
    pm = str(meta.get("permissionMode", "default"))
    if pm not in VALID_PERMISSION_MODES:
        raise AgentParseError(
            f"Invalid permissionMode '{pm}'{ctx}: "
            f"must be one of {VALID_PERMISSION_MODES - {''}}"
        )

    # maxTurns 必须是正整数
    max_turns = meta.get("maxTurns")
    if max_turns is not None:
        if not isinstance(max_turns, int) or max_turns <= 0:
            raise AgentParseError(
                f"Invalid maxTurns '{max_turns}'{ctx}: must be a positive integer"
            )

    # 隔离模式合法性检查
    isolation = str(meta.get("isolation", ""))
    if isolation not in VALID_ISOLATION_MODES:
        raise AgentParseError(
            f"Invalid isolation '{isolation}'{ctx}: "
            f"must be one of {VALID_ISOLATION_MODES - {''}}"
        )


def parse_agent_file(path: Path) -> AgentDef:
    """
    解析一个 Agent 定义文件（.md），返回 AgentDef 对象。
    
    流程：读取文件 → 解析 frontmatter → 验证元数据 → 构造 AgentDef
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as e:
        raise AgentParseError(f"Cannot read agent file {path}: {e}") from e

    meta, body = parse_frontmatter(raw)
    _validate_agent_meta(meta, str(path))

    return AgentDef(
        agent_type=meta["name"],
        when_to_use=meta["description"],
        system_prompt=body,             # Markdown 正文作为系统提示词
        tools=meta.get("tools", []),
        disallowed_tools=meta.get("disallowedTools", []),
        model=str(meta.get("model", "inherit")),
        max_turns=meta.get("maxTurns", 50),
        permission_mode=str(meta.get("permissionMode", "default")),
        background=bool(meta.get("background", False)),
        isolation=str(meta.get("isolation", "")),
        file_path=path,
        source="builtin",
    )
