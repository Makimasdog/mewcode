"""
hooks 模块 — Agent 生命周期 Hook 系统
========================================

【什么是 Hook】
Hook（钩子）是一种拦截机制，允许在 Agent 运行的特定时机执行自定义逻辑。
类似于 Web 框架中的中间件，Hook 可以在事件发生前/后执行操作。

【Hook 能做什么】
- 拦截工具执行：在工具执行前检查条件，拒绝危险操作
- 注入提示消息：在特定时机向 LLM 注入额外提示
- 发送通知：当特定事件发生时通知外部服务（如 Webhook）
- 记录日志：记录工具调用、错误等信息

【模块结构】
    events.py      — 定义可监听的生命周期事件（如 pre_tool_use、session_start）
    conditions.py  — 条件表达式解析与求值（如 tool == "Bash"）
    models.py      — 核心数据模型（Action、Hook、HookContext）
    executors.py   — 动作执行器（command、prompt、http、agent）
    loader.py      — 从 config.yaml 加载 Hook 配置
    engine.py      — Hook 执行引擎（查找匹配、执行动作、收集结果）

【使用示例】
在 config.yaml 中配置：
    hooks:
      - event: pre_tool_use
        if: 'tool == "Bash"'
        reject: true
        action:
          type: command
          command: "echo 'Bash is not allowed!'"

【工作流程】
    Agent 触发事件
    ↓
    HookEngine.run_hooks(event, ctx)
    ↓
    find_matching_hooks()  # 查找匹配的 Hook
    ↓
    检查条件 → 执行动作 → 收集结果
    ↓
    返回结果/通知给 Agent
"""


from mewcode.hooks.conditions import (
    Condition,           # 单个条件表达式
    ConditionGroup,      # 条件组（AND/OR 组合）
    ConditionParseError, # 条件解析错误
    parse_condition,     # 解析条件字符串
)
from mewcode.hooks.engine import HookEngine  # Hook 执行引擎
from mewcode.hooks.events import LifecycleEvent  # 生命周期事件枚举
from mewcode.hooks.loader import HookConfigError, load_hooks  # 配置加载
from mewcode.hooks.models import (
    Action,              # 要执行的动作
    ActionResult,        # 动作执行结果
    Hook,                # 完整的 Hook 定义
    HookContext,         # Hook 执行上下文
    ToolRejectedError,   # 工具被拒绝时抛出的异常
)


__all__ = [
    "Action",
    "ActionResult",
    "Condition",
    "ConditionGroup",
    "ConditionParseError",
    "Hook",
    "HookConfigError",
    "HookContext",
    "HookEngine",
    "LifecycleEvent",
    "ToolRejectedError",
    "load_hooks",
    "parse_condition",
]

