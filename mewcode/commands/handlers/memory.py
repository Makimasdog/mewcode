from __future__ import annotations

from mewcode.commands.registry import Command, CommandContext, CommandType


async def handle_memory(ctx: CommandContext) -> None:
    mm = ctx.memory_manager
    if mm is None:
        ctx.ui.add_system_message("记忆管理器未初始化")
        return


    parts = ctx.args.split(None, 1)
    sub = parts[0] if parts else ""

    if sub == "":
        display = mm.get_display_text()
        ctx.ui.add_system_message(display)

    elif sub == "list":
        display = mm.get_display_text()
        ctx.ui.add_system_message(display)

    elif sub == "clear":
        mm.clear()
        ctx.ui.add_system_message("所有自动记忆已清空。")

    elif sub == "edit":
        ctx.ui.add_system_message(
            f"编辑记忆文件：\n"
            f"  用户级: {mm.user_path}\n"
            f"  项目级: {mm.project_path}"
        )

    elif sub == "import":
        count = mm.import_legacy()
        ctx.ui.add_system_message(f"已导入 {count} 条记忆。")

    elif sub == "search":
        query = parts[1].strip() if len(parts) > 1 else ""
        if not query:
            ctx.ui.add_system_message("用法: /memory search <关键词>")
            return
        items = mm.search(query)
        if not items:
            ctx.ui.add_system_message("没有找到匹配的记忆。")
            return
        lines = [
            f"[{item.id}] ({item.scope}/{item.type}) {item.content}"
            for item in items
        ]
        ctx.ui.add_system_message("\n".join(lines))

    elif sub == "show":
        memory_id = parts[1].strip() if len(parts) > 1 else ""
        item = mm.get(memory_id) if memory_id else None
        if item is None:
            ctx.ui.add_system_message("找不到该记忆。")
            return
        ctx.ui.add_system_message(
            f"[{item.id}]\n"
            f"作用域: {item.scope}\n"
            f"类型: {item.type}\n"
            f"状态: {item.status}\n"
            f"置信度: {item.confidence:.2f}\n"
            f"内容: {item.content}"
        )

    elif sub in {"approve", "reject", "archive"}:
        memory_id = parts[1].strip() if len(parts) > 1 else ""
        status = {
            "approve": "active",
            "reject": "rejected",
            "archive": "archived",
        }[sub]
        if not memory_id or not mm.set_status(memory_id, status):
            ctx.ui.add_system_message("找不到该记忆。")
            return
        ctx.ui.add_system_message("记忆状态已更新。")

    elif sub == "forget":
        memory_id = parts[1].strip() if len(parts) > 1 else ""
        if not memory_id or not mm.delete(memory_id):
            ctx.ui.add_system_message("找不到该记忆。")
            return
        ctx.ui.add_system_message("记忆已删除。")

    else:
        ctx.ui.add_system_message(
            "用法: /memory [list | clear | edit | import | search <关键词> | "
            "show <id> | approve <id> | reject <id> | archive <id> | forget <id>]"
        )


MEMORY_COMMAND = Command(
    name="memory",
    description="记忆管理",
    usage="/memory [list | clear | edit | import | search <关键词> | show <id>]",
    type=CommandType.LOCAL,
    handler=handle_memory,
)

