"""
events.py — Hook 生命周期事件定义
=====================================

【这个模块做什么】
定义了 Agent 运行过程中可以触发 Hook 的所有事件类型。
Hook 通过监听这些事件，在特定时机执行自定义逻辑。

【事件层级】
事件分为 5 个层级，从外到内：

    系统级 (startup/shutdown)
    └── 会话级 (session_start/session_end)
        └── 轮次级 (turn_start/turn_end)
            ├── 消息级 (pre_send/post_receive)
            └── 工具级 (pre_tool_use/post_tool_use)

【常用事件】
- pre_tool_use: 工具执行前触发，可以拦截工具执行（reject）
- post_tool_use: 工具执行后触发，可以记录日志
- pre_send: 发送给 LLM 前触发，可以注入额外提示
- post_receive: 收到 LLM 响应后触发，可以记录日志
"""

from __future__ import annotations

from enum import StrEnum


class LifecycleEvent(StrEnum):
    """
    Agent 生命周期事件枚举。
    
    每个事件代表 Agent 运行过程中的一个特定时间点，
    Hook 可以监听这些事件并执行自定义逻辑。
    """
    # ===== 会话（Session）级别 =====
    # 会话开始/结束时触发，每个对话会话只触发一次
    SESSION_START = "session_start"
    SESSION_END = "session_end"


    # ===== 轮次（Turn）级别 =====
    # 每一轮「LLM 调用 + 工具执行」循环开始/结束时触发
    TURN_START = "turn_start"
    TURN_END = "turn_end"


    # ===== 工具（Tool）级别 =====
    # 工具执行前/后触发，pre_tool_use 可以拦截工具执行
    PRE_TOOL_USE = "pre_tool_use"
    POST_TOOL_USE = "post_tool_use"

    # ===== 消息（Message）级别 =====
    # 发送给 LLM 前 / 收到 LLM 响应后触发
    PRE_SEND = "pre_send"
    POST_RECEIVE = "post_receive"

    # ===== 系统（System）级别 =====
    # 程序启动/关闭、错误、压缩、权限请求、文件变更、命令执行等
    STARTUP = "startup"
    SHUTDOWN = "shutdown"
    ERROR = "error"
    COMPACT = "compact"
    PERMISSION_REQUEST = "permission_request"
    FILE_CHANGE = "file_change"
    COMMAND_EXECUTE = "command_execute"

