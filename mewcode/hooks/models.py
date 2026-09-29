"""
models.py — Hook 系统核心数据模型
=====================================

【这个模块做什么】
定义了 Hook 系统的基础数据结构：
- Action：Hook 触发时要执行的动作（命令/提示/HTTP/Agent）
- ActionResult：动作执行结果
- Hook：一个完整的 Hook 定义（事件 + 条件 + 动作）
- HookContext：Hook 执行时的上下文信息
- ToolRejectedError：工具被 Hook 拦截时抛出的异常

【Hook 配置示例】
在 config.yaml 中：
    hooks:
      - event: pre_tool_use
        if: 'tool == "Bash"'
        reject: true
        action:
          type: command
          command: "echo 'Bash is not allowed!'"
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from mewcode.hooks.conditions import ConditionGroup


@dataclass
class Action:
    """
    Hook 触发时要执行的动作。
    
    支持四种类型：
    - command: 执行 Shell 命令
    - prompt: 向 LLM 注入提示消息
    - http: 发送 HTTP 请求
    - agent: 调用另一个 Agent（预留）
    """
    type: str               # 动作类型："command"/"prompt"/"http"/"agent"
    command: str = ""       # Shell 命令（type=command 时使用）
    message: str = ""       # 提示消息内容（type=prompt 时使用）
    url: str = ""           # HTTP URL（type=http 时使用）
    method: str = "POST"    # HTTP 方法
    body: str = ""          # HTTP 请求体
    headers: dict[str, str] = field(default_factory=dict)  # HTTP 请求头
    prompt: str = ""        # Agent 提示词（type=agent 时使用）
    timeout: int = 30       # 执行超时时间（秒）


@dataclass
class ActionResult:
    """动作执行结果"""
    output: str = ""        # 输出内容
    success: bool = True    # 是否成功


@dataclass
class Hook:
    """
    一个完整的 Hook 定义。
    
    Hook = 事件 + 条件 + 动作
    例如：「当工具调用前(pre_tool_use)，如果是 Bash 工具(tool=="Bash")，则拒绝(reject=true)」
    """
    id: str                         # Hook 唯一标识符
    event: str                      # 触发事件（如 "pre_tool_use"）
    action: Action                  # 要执行的动作
    condition: ConditionGroup | None = None  # 触发条件（可选）
    reject: bool = False            # 是否拒绝工具执行（仅 pre_tool_use）
    once: bool = False              # 是否只执行一次
    async_exec: bool = False        # 是否异步执行（不阻塞主流程）
    executed: bool = False          # 是否已经执行过


    def should_run(self) -> bool:
        """检查 Hook 是否应该执行（考虑 once 限制）"""
        if self.once and self.executed:
            return False
        return True


    def mark_executed(self) -> None:
        """标记 Hook 已执行"""
        self.executed = True


@dataclass
class HookContext:
    """
    Hook 执行时的上下文信息。
    
    包含当前事件的相关信息，如工具名称、参数、文件路径等。
    用于条件评估和模板变量替换。
    """
    event_name: str = ""            # 当前事件名称
    tool_name: str = ""             # 工具名称
    tool_args: dict[str, Any] = field(default_factory=dict)  # 工具参数
    file_path: str = ""             # 文件路径
    message: str = ""               # 消息内容
    error: str = ""                 # 错误信息

    def get_field(self, name: str) -> str:
        """
        按名称获取上下文字段值。
        支持："tool"、"event"、"args.xxx" 格式。
        用于条件评估。
        """
        if name == "tool":
            return self.tool_name
        if name == "event":
            return self.event_name
        if name.startswith("args."):
            key = name[5:]
            value = self.tool_args.get(key, "")
            return str(value) if value else ""
        return ""

    def expand(self, template: str) -> str:
        """
        模板变量替换。
        将 $EVENT、$TOOL_NAME、$FILE_PATH 等变量替换为实际值。
        用于命令、URL、消息等字符串的动态生成。
        """
        result = template
        result = result.replace("$EVENT", self.event_name)
        result = result.replace("$TOOL_NAME", self.tool_name)
        result = result.replace("$FILE_PATH", self.file_path)
        result = result.replace("$MESSAGE", self.message)
        result = result.replace("$ERROR", self.error)
        for key, value in self.tool_args.items():
            result = result.replace(f"$TOOL_ARGS.{key}", str(value))
        return result


class ToolRejectedError(Exception):
    """
    工具被 Hook 拦截时抛出的异常。
    
    当 pre_tool_use Hook 设置了 reject=true 时，
    工具执行会被拒绝，并抛出此异常。
    """
    def __init__(self, tool: str, reason: str, hook_id: str) -> None:
        self.tool = tool            # 被拒绝的工具名称
        self.reason = reason        # 拒绝原因
        self.hook_id = hook_id      # 拦截的 Hook ID
        super().__init__(f"Tool '{tool}' rejected by hook '{hook_id}': {reason}")
