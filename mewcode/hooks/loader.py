"""
loader.py — Hook 配置加载器
=====================================

【这个模块做什么】
从 config.yaml 中的 hooks 配置加载 Hook 定义。
负责验证配置的正确性，并将原始字典转换为 Hook 对象。

【配置示例】
    hooks:
      - event: pre_tool_use
        id: no-bash
        if: 'tool == "Bash"'
        reject: true
        action:
          type: command
          command: "echo 'Bash is not allowed!'"
          timeout: 10

【验证规则】
- event 必须是合法的生命周期事件
- action.type 必须是 command/prompt/http/agent 之一
- 每种 action type 有必填字段（command 需要 command，http 需要 url 等）
- reject 只能用于 pre_tool_use 事件
- async 不能用于 pre_tool_use 事件（因为需要等待结果决定是否拦截）
"""

from __future__ import annotations

from mewcode.hooks.conditions import ConditionParseError, parse_condition
from mewcode.hooks.events import LifecycleEvent
from mewcode.hooks.models import Action, Hook

# 合法的事件名称集合
_VALID_EVENTS = {e.value for e in LifecycleEvent}
# 合法的动作类型集合
_VALID_ACTION_TYPES = {"command", "prompt", "http", "agent"}

# 每种动作类型的必填字段
_REQUIRED_FIELDS: dict[str, list[str]] = {
    "command": ["command"],
    "prompt": ["message"],
    "http": ["url"],
    "agent": ["prompt"],
}


class HookConfigError(Exception):
    """Hook 配置错误时抛出的异常"""
    pass


def _identify(entry: dict, index: int) -> str:
    """生成 Hook 的标识字符串，用于错误消息"""
    hook_id = entry.get("id", "")
    return f"hook '{hook_id}'" if hook_id else f"hook #{index + 1}"


def load_hooks(raw_hooks: list[dict] | None) -> list[Hook]:
    """
    从原始配置字典列表加载 Hook 对象。
    
    流程：
    1. 遍历每个配置项
    2. 验证必填字段和合法值
    3. 解析条件表达式
    4. 构造 Hook 对象
    
    参数:
        raw_hooks: config.yaml 中的 hooks 配置列表
        
    返回:
        解析后的 Hook 对象列表
    """
    if not raw_hooks:
        return []

    hooks: list[Hook] = []
    for i, entry in enumerate(raw_hooks):
        label = _identify(entry, i)

        # 验证基本结构
        if not isinstance(entry, dict):
            raise HookConfigError(f"{label}: must be a mapping")

        # 验证事件名称
        event = entry.get("event")
        if not event:
            raise HookConfigError(f"{label}: missing 'event' field")
        if event not in _VALID_EVENTS:
            raise HookConfigError(
                f"{label}: invalid event '{event}', "
                f"must be one of: {', '.join(sorted(_VALID_EVENTS))}"
            )

        # 验证动作配置
        raw_action = entry.get("action")
        if not isinstance(raw_action, dict):
            raise HookConfigError(f"{label}: missing or invalid 'action' field")

        action_type = raw_action.get("type")
        if action_type not in _VALID_ACTION_TYPES:
            raise HookConfigError(
                f"{label}: invalid action type '{action_type}', "
                f"must be one of: {', '.join(sorted(_VALID_ACTION_TYPES))}"
            )

        # 验证动作类型的必填字段
        required = _REQUIRED_FIELDS[action_type]
        for field_name in required:
            if not raw_action.get(field_name):
                raise HookConfigError(
                    f"{label}: action type '{action_type}' requires "
                    f"'{field_name}' field"
                )

        # reject 只能用于 pre_tool_use（因为只有它能拦截工具执行）
        reject = bool(entry.get("reject", False))
        if reject and event != "pre_tool_use":
            raise HookConfigError(
                f"{label}: 'reject' can only be used with 'pre_tool_use' event"
            )

        # async 不能用于 pre_tool_use（因为需要等待结果决定是否拦截）
        async_exec = bool(entry.get("async", False))
        if async_exec and event == "pre_tool_use":
            raise HookConfigError(
                f"{label}: 'async' cannot be used with 'pre_tool_use' event"
            )

        # 解析条件表达式（如 'tool == "Bash"'）
        condition = None
        raw_if = entry.get("if")
        if raw_if:
            try:
                condition = parse_condition(str(raw_if))
            except ConditionParseError as e:
                raise HookConfigError(f"{label}: condition error: {e}") from e

        hook_id = entry.get("id", f"{event}_{i}")

        # 验证超时时间
        timeout = raw_action.get("timeout", 30)
        if not isinstance(timeout, int) or timeout <= 0:
            raise HookConfigError(f"{label}: timeout must be a positive integer")

        # 构造 Action 对象
        action = Action(
            type=action_type,
            command=raw_action.get("command", ""),
            message=raw_action.get("message", ""),
            url=raw_action.get("url", ""),
            method=raw_action.get("method", "POST"),
            body=raw_action.get("body", ""),
            headers=raw_action.get("headers", {}),
            prompt=raw_action.get("prompt", ""),
            timeout=timeout,
        )

        # 构造 Hook 对象
        hooks.append(
            Hook(
                id=hook_id,
                event=event,
                action=action,
                condition=condition,
                reject=reject,
                once=bool(entry.get("once", False)),
                async_exec=async_exec,
            )
        )

    return hooks

