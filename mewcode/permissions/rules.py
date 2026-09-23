# 来源：公众号@小林coding
# 后端八股网站：xiaolincoding.com
# Agent网站：xiaolinnote.com
# 简历模版：jianli.xiaolinnote.com
# 说明：本项目所有规则语法形如 "ToolName(pattern)"，例如 "Bash(git *)"。

"""规则引擎（五层权限体系的第 3 层能力）。

RuleEngine 让用户可以自定义"针对某工具、某内容"的放行/拒绝规则，
并按"用户级 < 项目级 < 本地级"三档优先级加载。命中规则时，
以规则结论为准（规则的优先级高于默认的模式矩阵）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path
from typing import Any, Literal

import yaml

# 一条规则的效力：要么放行，要么拒绝（规则层没有"ask"）
Effect = Literal["allow", "deny"]

# 规则语法：开头是工具名(\w+)，括号里是匹配模式(.+)，如 "Bash(git *)"
_RULE_RE = re.compile(r"^(\w+)\((.+)\)$")

# 每个工具用于匹配规则内容的字段是哪个（用于从 params 里提取）
_CONTENT_FIELDS: dict[str, str] = {
    "Bash": "command",
    "ReadFile": "file_path",
    "WriteFile": "file_path",
    "EditFile": "file_path",
    "Glob": "pattern",
    "Grep": "pattern",
}


@dataclass(frozen=True)
class Rule:
    """一条权限规则。frozen=True 表示不可变（安全、可哈希）。

    - tool_name: 规则针对的工具名（如 "Bash"、"ReadFile"）
    - pattern:   用 fnmatch 通配的匹配模式（如 "git *"）
    - effect:    命中时的结论（"allow" 或 "deny"）
    """
    tool_name: str
    pattern: str
    effect: Effect


    def matches(self, tool_name: str, content: str) -> bool:
        """判断给定工具与内容是否命中本规则。

        工具名必须一致，且内容必须被 pattern 通配匹配。
        """
        if self.tool_name != tool_name:
            return False
        return fnmatch(content, self.pattern)


def parse_rule(raw: str, effect: Effect) -> Rule:
    """把字符串规则解析成 Rule 对象。

    :param raw: 形如 "Bash(git commit *)"
    :param effect: 该规则的效力（allow/deny）
    :raises ValueError: 语法不符合 "Name(pattern)" 时抛错
    """
    m = _RULE_RE.match(raw.strip())
    if not m:
        raise ValueError(f"无效的规则语法: {raw}")
    return Rule(tool_name=m.group(1), pattern=m.group(2), effect=effect)


def extract_content(tool_name: str, arguments: dict[str, Any]) -> str:
    """从工具参数字典里，按工具名取出"用来做规则匹配的内容字段"。

    :param tool_name: 工具名（Bash/ReadFile/WriteFile/...）
    :param arguments: 工具调用的参数字典
    :return: 对应的内容字符串；不认识的工具返回 ""
    """
    field = _CONTENT_FIELDS.get(tool_name)
    if field is None:
        return ""
    return str(arguments.get(field, ""))


def _load_rules_file(path: Path) -> list[Rule]:
    """读取一个 YAML 规则文件，返回其中的 Rule 列表。

    文件不存在、解析出错、或某条记录格式非法时，都安全地跳过（不抛异常）。
    """
    if not path.is_file():
        return []
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (yaml.YAMLError, OSError):
        return []
    if not isinstance(raw, list):  # 顶层必须是 YAML 列表
        return []
    rules: list[Rule] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        rule_str = entry.get("rule", "")
        effect = entry.get("effect", "")
        if effect not in ("allow", "deny"):
            continue  # effect 非法则跳过这条
        try:
            rules.append(parse_rule(rule_str, effect))
        except ValueError:
            continue  # 单条语法错误不影响其他规则
    return rules


class RuleEngine:
    """管理并加载三层规则源（用户级/项目级/本地级），并提供 evaluate 查询。

    优先级：user < project < local，即越靠后的层级越先被匹配到（更高优先）。
    """


    def __init__(
        self,
        user_rules_path: Path | None = None,
        project_rules_path: Path | None = None,
        local_rules_path: Path | None = None,
    ) -> None:
        """注入三个规则文件的路径（均可选，没有就不加载）。

        :param user_rules_path:    用户级规则文件
        :param project_rules_path: 项目级规则文件
        :param local_rules_path:   本地级规则文件（可临时追加）
        """
        self._user_path = user_rules_path
        self._project_path = project_rules_path
        self._local_path = local_rules_path

    def _load_tiers(self) -> list[list[Rule]]:
        """按优先级顺序加载各层规则：依次是 [user, project, local]。"""
        tiers: list[list[Rule]] = []
        for p in (self._user_path, self._project_path, self._local_path):
            tiers.append(_load_rules_file(p) if p else [])
        return tiers


    def evaluate(self, tool_name: str, content: str) -> Effect | None:
        """逐层匹配规则：返回最先命中的规则结论。

        - 每层内用 reversed() 从后往前遍历，实现"同一层里后面的规则覆盖前面的"（last-wins）。
        - 命中即返回该规则的 effect；全部未命中返回 None（由上层给默认决策）。
        """
        for rules in self._load_tiers():
            for rule in reversed(rules):
                if rule.matches(tool_name, content):
                    return rule.effect
        return None


    def append_local_rule(self, rule: Rule) -> None:
        """把一条规则追加写入本地规则文件（运行时动态新增自定义规则）。"""
        if self._local_path is None:
            return
        self._local_path.parent.mkdir(parents=True, exist_ok=True)  # 确保目录存在
        existing = _load_rules_file(self._local_path)  # 读回已有规则
        existing.append(rule)
        # 把规则序列化回 YAML（每条转成 {"rule": "...", "effect": "..."} 格式）
        entries = [{"rule": f"{r.tool_name}({r.pattern})", "effect": r.effect} for r in existing]
        self._local_path.write_text(yaml.dump(entries, allow_unicode=True), encoding="utf-8")