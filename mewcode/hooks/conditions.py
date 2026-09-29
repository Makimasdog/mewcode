"""
conditions.py — Hook 条件表达式解析与求值
=============================================

【这个模块做什么】
Hook 可以有条件：只有满足条件时才执行。
本模块负责解析和求值这些条件表达式。

【条件语法】
条件表达式写在 config.yaml 的 `if` 字段中：
    if: 'tool == "Bash"'               # 工具名等于 Bash
    if: 'tool =~ /^rm/'                # 工具名匹配正则
    if: 'tool ~= "*.py"'               # 工具名匹配 glob
    if: 'tool == "Bash" && args.command =~ "rm"'  # 组合条件

【支持的运算符】
- ==  精确匹配
- !=  不等于
- =~  正则匹配（用 /pattern/ 包裹）
- ~=  Glob 通配符匹配

【逻辑组合】
- &&  AND（所有条件都满足）
- ||  OR（任一条件满足）
- 不允许混用 && 和 ||（需要拆分到不同的 Hook）
"""
from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mewcode.hooks.models import HookContext


@dataclass
class Condition:
    """
    单个条件表达式。
    
    例如：tool == "Bash"、args.command =~ "^rm"
    由字段名、运算符和值组成。
    """
    field: str        # 要检查的字段（如 "tool"、"event"、"args.command"）
    operator: str     # 运算符：==、!=、=~、~=
    value: str        # 要比较的值


    def evaluate(self, ctx: HookContext) -> bool:
        """
        根据上下文求值条件。
        从 ctx 中获取字段值，然后用运算符与期望值比较。
        """
        field_value = ctx.get_field(self.field)
        if self.operator == "==":
            return field_value == self.value
        if self.operator == "!=":
            return field_value != self.value
        if self.operator == "=~":
            # 正则匹配：支持 /pattern/ 格式
            pattern = self.value
            if pattern.startswith("/") and pattern.endswith("/"):
                pattern = pattern[1:-1]
            try:
                return bool(re.search(pattern, field_value))
            except re.error:
                return False
        if self.operator == "~=":
            # Glob 通配符匹配（如 "*.py"）
            return fnmatch.fnmatch(field_value, self.value)
        return False


@dataclass
class ConditionGroup:
    """
    条件组：多个条件的逻辑组合。
    
    支持 AND（所有条件都满足）或 OR（任一条件满足）。
    """
    conditions: list[Condition] = field(default_factory=list)
    logic: str = "and"  # "and" 或 "or"


    def evaluate(self, ctx: HookContext) -> bool:
        """
        求值条件组。
        空条件组默认返回 True（无条件执行）。
        """
        if not self.conditions:
            return True
        if self.logic == "and":
            return all(c.evaluate(ctx) for c in self.conditions)
        return any(c.evaluate(ctx) for c in self.conditions)


class ConditionParseError(Exception):
    """条件表达式解析失败时抛出的异常"""
    pass


# 支持的运算符（按长度排序，确保先匹配长运算符）
_OPERATORS = ("==", "!=", "=~", "~=")


def _parse_single(expr: str) -> Condition:
    """
    解析单个条件表达式。
    例如：'tool == "Bash"' → Condition(field="tool", operator="==", value="Bash")
    """
    expr = expr.strip()
    for op in _OPERATORS:
        idx = expr.find(op)
        if idx == -1:
            continue
        field_part = expr[:idx].strip()
        value_part = expr[idx + len(op):].strip()
        # 去除值的引号
        if value_part.startswith('"') and value_part.endswith('"'):
            value_part = value_part[1:-1]
        return Condition(field=field_part, operator=op, value=value_part)
    raise ConditionParseError(f"No valid operator found in condition: '{expr}'")


def parse_condition(expr: str) -> ConditionGroup | None:
    """
    解析条件表达式字符串为 ConditionGroup。
    
    支持：
    - 单条件：'tool == "Bash"'
    - AND 组合：'tool == "Bash" && args.command =~ "rm"'
    - OR 组合：'tool == "Bash" || tool == "WriteFile"'
    
    注意：不允许混用 && 和 ||，需要拆分到不同的 Hook。
    """
    if not expr or not expr.strip():
        return None

    expr = expr.strip()
    has_and = "&&" in expr
    has_or = "||" in expr

    # 不允许混用 AND 和 OR
    if has_and and has_or:
        raise ConditionParseError(
            "Cannot mix '&&' and '||' in a single condition expression. "
            "Split into separate hooks instead."
        )

    if has_and:
        parts = expr.split("&&")
        logic = "and"
    elif has_or:
        parts = expr.split("||")
        logic = "or"
    else:
        parts = [expr]
        logic = "and"

    conditions = [_parse_single(p) for p in parts]
    return ConditionGroup(conditions=conditions, logic=logic)
