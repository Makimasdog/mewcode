"""
filehistory 模块 — 文件编辑历史与回滚系统
============================================

【这个模块做什么】
记录 Agent 对文件的所有编辑操作，支持「回滚」到任意历史状态。
类似于轻量级的 Git，专为 Agent 会话设计。

【核心组件】
- FileHistory: 文件历史管理器，负责跟踪编辑、创建快照、执行回滚
- Snapshot: 文件快照，记录某一时刻所有已跟踪文件的版本

【工作流程】
    Agent 编辑文件前 → track_edit() 保存备份
    每轮对话结束 → make_snapshot() 创建快照
    用户执行 /rewind → rewind() 恢复到指定快照

【与 rewind 命令的关系】
commands/handlers/rewind.py 调用本模块的 FileHistory 实现回滚功能。
"""

from mewcode.filehistory.history import FileHistory, Snapshot

__all__ = ["FileHistory", "Snapshot"]
