# 来源：公众号@小林coding
# 后端八股网站：xiaolincoding.com
# Agent网站：xiaolinnote.com
# 简历模版：jianli.xiaolinnote.com

"""权限模式（Permission Mode）核心定义。

这是五层权限体系里"第 4 层权限模式兜底"用到的数据与逻辑：
- 用枚举 PermissionMode 表示几种运行模式（default / plan / bypass 等）;
- 用一张"模式 × 工具类别"的矩阵 _MODE_MATRIX 描述每种模式下，
  各工具类别默认是放行(allow)/拒绝(deny)/询问(ask)。
一句话：本文件回答"在某个模式下，这类工具默认该怎么处理"。
"""
from __future__ import annotations

from enum import Enum
from typing import Literal

from mewcode.tools.base import ToolCategory

# 一次权限裁决的三种可能结果
# Literal 表示这个类型只能是这三个字符串之一。
DecisionEffect = Literal["allow", "deny", "ask"]


class PermissionMode(str, Enum):
    """权限模式的枚举：str 继承让枚举值能直接用字符串比较/展示。

    每种模式代表一种"对工具调用的信任程度"：
    - DEFAULT    默认：读放行，写和命令要问用户
    - ACCEPT_EDITS 接受编辑：读写都放行，命令仍要问
    - PLAN       规划模式：只读，禁止写盘和执行命令
    - BYPASS     完全绕过：读写命令全放行
    - CUSTOM     自定义：默认都要问
    - DONT_ASK   不问：读写命令全部放行（完全自动）
    """
    DEFAULT = "default"
    ACCEPT_EDITS = "acceptEdits"
    PLAN = "plan"
    BYPASS = "bypassPermissions"
    CUSTOM = "custom"
    DONT_ASK = "dontAsk"


# 模式决策矩阵：给每种模式，按工具类别(读取/写入/命令)给出默认决策。
# - read   只读工具（如 ReadFile）
# - write  写入工具（如 WriteFile / EditFile）
# - command 命令工具（如 Bash）
_MODE_MATRIX: dict[PermissionMode, dict[ToolCategory, DecisionEffect]] = {
    PermissionMode.DEFAULT: {"read": "allow", "write": "ask", "command": "ask"},
    PermissionMode.ACCEPT_EDITS: {"read": "allow", "write": "allow", "command": "ask"},
    PermissionMode.PLAN: {"read": "allow", "write": "deny", "command": "deny"},
    PermissionMode.BYPASS: {"read": "allow", "write": "allow", "command": "allow"},
    PermissionMode.CUSTOM: {"read": "ask", "write": "ask", "command": "ask"},
    PermissionMode.DONT_ASK: {"read": "allow", "write": "allow", "command": "allow"},
}


def mode_decide(mode: PermissionMode, category: ToolCategory) -> DecisionEffect:
    """查矩阵：mode 模式下，category 类别工具默认返回什么决策。"""
    return _MODE_MATRIX[mode][category]