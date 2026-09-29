"""
executors.py — Hook 动作执行器
=====================================

【这个模块做什么】
当 Hook 被触发时，需要执行对应的动作（Action）。
本模块实现了四种动作类型的执行器：

1. command — 执行 Shell 命令（如 echo、git commit）
2. prompt  — 向 LLM 注入提示消息（影响后续对话）
3. http    — 发送 HTTP 请求（通知外部服务）
4. agent   — 调用另一个 Agent（预留，未实现）

【执行流程】
每个执行器都遵循相同接口：
    async def execute_xxx(action: Action, ctx: HookContext) -> ActionResult

其中 ctx.expand() 用于替换模板变量（如 $TOOL_NAME、$FILE_PATH）。
"""
from __future__ import annotations

import asyncio
import logging
from urllib.request import Request, urlopen
from urllib.error import URLError

from mewcode.hooks.models import Action, ActionResult, HookContext

log = logging.getLogger(__name__)


async def execute_command(action: Action, ctx: HookContext) -> ActionResult:
    """
    执行 Shell 命令。
    
    通过 asyncio.create_subprocess_shell 创建子进程执行命令。
    支持超时控制，超时后会强制杀死进程。
    """
    command = ctx.expand(action.command)  # 替换模板变量
    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            stdout, _ = await asyncio.wait_for(
                proc.communicate(), timeout=action.timeout
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return ActionResult(
                output=f"Command timed out after {action.timeout}s: {command}",
                success=False,
            )
        output = stdout.decode(errors="replace").strip() if stdout else ""
        return ActionResult(output=output, success=proc.returncode == 0)
    except Exception as e:
        return ActionResult(output=f"Command execution error: {e}", success=False)


async def execute_prompt(action: Action, ctx: HookContext) -> ActionResult:
    """
    生成提示消息。
    
    不执行任何外部操作，只是将消息内容返回。
    返回的消息会被注入到 LLM 的对话中（通过 HookEngine._prompt_messages）。
    """
    message = ctx.expand(action.message)
    return ActionResult(output=message, success=True)


async def execute_http(action: Action, ctx: HookContext) -> ActionResult:
    """
    发送 HTTP 请求。
    
    用于通知外部服务（如 Webhook、Slack 通知等）。
    在线程池中执行以避免阻塞异步事件循环。
    """
    url = ctx.expand(action.url)
    body = ctx.expand(action.body) if action.body else None
    method = action.method or "POST"

    # 替换请求头中的模板变量
    headers = dict(action.headers)
    for k, v in headers.items():
        headers[k] = ctx.expand(v)
    if body and "Content-Type" not in headers:
        headers["Content-Type"] = "application/json"


    def _do_request() -> ActionResult:
        """在线程池中执行的同步 HTTP 请求"""
        try:
            data = body.encode() if body else None
            req = Request(url, data=data, headers=headers, method=method)
            with urlopen(req, timeout=30) as resp:
                resp_body = resp.read().decode(errors="replace")[:500]
                return ActionResult(
                    output=f"HTTP {resp.status}: {resp_body}",
                    success=200 <= resp.status < 300,
                )
        except URLError as e:
            return ActionResult(output=f"HTTP error: {e}", success=False)
        except Exception as e:
            return ActionResult(output=f"HTTP error: {e}", success=False)

    # 在线程池中执行，避免阻塞异步事件循环
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _do_request)


async def execute_agent(action: Action, ctx: HookContext) -> ActionResult:
    """
    调用另一个 Agent（预留接口，未实现）。
    
    未来将支持在 Hook 中触发子 Agent 执行复杂任务。
    """
    prompt = ctx.expand(action.prompt)
    log.info("Agent executor stub called with prompt: %s", prompt[:100])
    return ActionResult(
        output="agent executor not yet implemented",
        success=True,
    )


# 动作类型 → 执行函数的映射表
_EXECUTOR_MAP = {
    "command": execute_command,
    "prompt": execute_prompt,
    "http": execute_http,
    "agent": execute_agent,
}


async def execute_action(action: Action, ctx: HookContext) -> ActionResult:
    """
    根据动作类型分发到对应的执行器。
    这是所有 Hook 动作执行的统一入口。
    """
    executor = _EXECUTOR_MAP.get(action.type)
    if executor is None:
        return ActionResult(
            output=f"Unknown action type: {action.type}",
            success=False,
        )
    return await executor(action, ctx)
