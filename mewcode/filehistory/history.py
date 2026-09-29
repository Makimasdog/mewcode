"""
history.py — 文件编辑历史与回滚系统
=====================================

【这个模块做什么】
记录 Agent 对文件的所有编辑操作，支持「回滚」到任意历史快照。
类似于 Git 的版本控制，但更轻量，专为 Agent 会话设计。

【核心概念】
- Backup（备份）：文件在某次编辑前的完整副本
- Snapshot（快照）：某一时刻所有已跟踪文件的备份集合
- Rewind（回滚）：将文件恢复到某个快照的状态

【工作流程】
    Agent 编辑文件前
    ↓
    track_edit(path)  →  保存编辑前的文件副本
    ↓
    每轮对话结束时
    ↓
    make_snapshot()  →  创建快照（记录所有文件的当前版本）
    ↓
    用户执行 /rewind 命令
    ↓
    rewind(index)  →  将文件恢复到指定快照的状态

【存储结构】
    .mewcode/file-history/{session_id}/
    ├── a1b2c3d4@v1   # SHA256前16位@版本号
    ├── a1b2c3d4@v2
    └── e5f6g7h8@v1
"""

from __future__ import annotations

import hashlib
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

# 最多保留的快照数量（超出后丢弃最早的）
MAX_SNAPSHOTS = 100


@dataclass
class Backup:
    """
    单个文件的备份记录。
    
    存储文件在某次编辑前的完整副本，用于回滚时恢复。
    """
    backup_path: str   # 备份文件的磁盘路径
    version: int       # 版本号（每次编辑 +1）
    timestamp: float   # 备份时间戳


@dataclass
class Snapshot:
    """
    文件快照：某一时刻所有已跟踪文件的备份集合。
    
    每个快照对应一轮对话，包含该轮对话开始前所有文件的版本信息。
    用户可通过 /rewind 命令回滚到任意快照。
    """
    message_index: int                              # 对应的对话消息索引
    user_text: str                                  # 用户的原始消息（便于识别）
    backups: dict[str, Backup] = field(default_factory=dict)  # 文件路径 → 备份记录
    timestamp: float = 0.0                          # 快照创建时间


class FileHistory:
    """
    文件编辑历史管理器。
    
    负责：
    1. 在文件被编辑前保存备份（track_edit）
    2. 在对话轮次结束时创建快照（make_snapshot）
    3. 支持回滚到任意快照（rewind）
    
    线程安全：所有公开方法都通过 threading.Lock 保护。
    """

    def __init__(self, base_dir: str, session_id: str) -> None:
        """
        初始化文件历史管理器。
        
        参数:
            base_dir: 项目根目录
            session_id: 会话 ID（每个会话独立的历史空间）
        """
        # 备份存储目录：.mewcode/file-history/{session_id}/
        self._session_dir = Path(base_dir) / ".mewcode" / "file-history" / session_id
        self._session_dir.mkdir(parents=True, exist_ok=True)
        self._tracked: dict[str, int] = {}   # 文件绝对路径 → 当前版本号
        self._snapshots: list[Snapshot] = []  # 快照列表（按时间顺序）
        self._lock = threading.Lock()         # 线程安全锁

    def _backup_name(self, file_path: str, version: int) -> str:
        """
        生成备份文件名。
        
        格式：{SHA256前16位}@v{版本号}
        例如：a1b2c3d4e5f6g7h8@v3
        
        用 SHA256 哈希避免路径中的特殊字符导致文件名非法。
        """
        h = hashlib.sha256(file_path.encode()).hexdigest()[:16]
        return f"{h}@v{version}"

    def track_edit(self, path: str) -> None:
        """
        跟踪文件编辑：在编辑前保存当前文件内容的备份。
        
        每次调用都会递增版本号并保存新备份。
        如果文件不存在（新建文件），则跳过备份。
        
        参数:
            path: 要编辑的文件路径
        """
        with self._lock:
            abs_path = str(Path(path).resolve())
            ver = self._tracked.get(abs_path, 0)
            new_ver = ver + 1

            # 保存编辑前的文件内容作为备份
            try:
                data = Path(abs_path).read_bytes()
                bp = self._session_dir / self._backup_name(abs_path, new_ver)
                bp.write_bytes(data)
            except FileNotFoundError:
                pass  # 新文件无需备份

            self._tracked[abs_path] = new_ver

    def make_snapshot(self, msg_index: int, user_text: str) -> None:
        """
        创建当前状态的快照。
        
        在每轮对话结束时调用，记录所有已跟踪文件的当前版本。
        快照数量超过 MAX_SNAPSHOTS 时，丢弃最早的快照。
        
        参数:
            msg_index: 当前对话消息的索引
            user_text: 用户的原始消息文本
        """
        with self._lock:
            backups: dict[str, Backup] = {}
            for path, ver in self._tracked.items():
                bp = self._session_dir / self._backup_name(path, ver)
                # 确保备份文件存在
                if not bp.exists():
                    try:
                        data = Path(path).read_bytes()
                        bp.write_bytes(data)
                    except (FileNotFoundError, OSError):
                        pass
                backups[path] = Backup(
                    backup_path=str(bp), version=ver, timestamp=time.time(),
                )

            self._snapshots.append(Snapshot(
                message_index=msg_index,
                user_text=user_text,
                backups=backups,
                timestamp=time.time(),
            ))
            # 超出上限时丢弃最早的快照
            if len(self._snapshots) > MAX_SNAPSHOTS:
                self._snapshots = self._snapshots[-MAX_SNAPSHOTS:]

    def get_snapshots(self) -> list[Snapshot]:
        """获取所有快照的副本"""
        with self._lock:
            return list(self._snapshots)

    def has_snapshots(self) -> bool:
        """检查是否有可回滚的快照"""
        with self._lock:
            return len(self._snapshots) > 0

    def rewind(self, snapshot_index: int) -> list[str]:
        """
        回滚到指定快照，将文件恢复到该快照的状态。
        
        流程：
        1. 读取目标快照中每个文件的备份内容
        2. 与当前文件内容比较，不同则覆盖
        3. 如果备份不存在（说明当时文件不存在），则删除当前文件
        4. 丢弃目标快照之后的所有快照（不可「重做」）
        
        参数:
            snapshot_index: 目标快照的索引
            
        返回:
            被修改的文件路径列表
        """
        with self._lock:
            if snapshot_index < 0 or snapshot_index >= len(self._snapshots):
                return []

            target = self._snapshots[snapshot_index]
            changed: list[str] = []

            for file_path, backup in target.backups.items():
                bp = Path(backup.backup_path)
                try:
                    backup_data = bp.read_bytes()
                except FileNotFoundError:
                    # 备份不存在 = 当时文件不存在，删除当前文件
                    fp = Path(file_path)
                    if fp.exists():
                        fp.unlink()
                        changed.append(file_path)
                    continue

                fp = Path(file_path)
                try:
                    current_data = fp.read_bytes()
                except FileNotFoundError:
                    current_data = b""

                # 只有内容不同时才覆盖（避免不必要的写入）
                if current_data != backup_data:
                    fp.parent.mkdir(parents=True, exist_ok=True)
                    fp.write_bytes(backup_data)
                    changed.append(file_path)

            # 丢弃目标快照之后的所有快照（不可重做）
            self._snapshots = self._snapshots[: snapshot_index + 1]
            # 更新跟踪状态为目标快照的版本
            for file_path, backup in target.backups.items():
                self._tracked[file_path] = backup.version

            return changed
