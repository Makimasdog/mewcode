# 来源：公众号@小林coding
# 后端八股网站：xiaolincoding.com
# Agent网站：xiaolinnote.com
# 简历模版：jianli.xiaolinnote.com

from __future__ import annotations

from mewcode.commands.registry import Command, CommandContext, CommandType


async def handle_do(ctx: CommandContext) -> None:
    ctx.ui.set_plan_mode(False)
    ctx.ui.add_system_message("已切换到执行模式 — 允许写入和命令执行")
    if ctx.args:
        ctx.ui.send_user_message(ctx.args)


DO_COMMAND = Command(
    name="do",
    aliases=[],
    description="切换到执行模式（退出 Plan 模式）",
    usage="/do [任务描述]",
    type=CommandType.LOCAL_UI,
    handler=handle_do,
)
