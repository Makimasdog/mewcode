"""
registry.py — 名称注册表（Agent 的「电话簿」）
=============================================================

【这个模块做什么】
AgentNameRegistry 是一个全局单例，维护「名称 → Agent ID」的映射关系。

【为什么需要它？】
在团队中，人类更习惯用名字（如 "alice"、"backend-dev"）来称呼 Agent，
但系统内部用 agent_id（如 "a1b2c3d4"）来标识。
注册表就是两者之间的翻译器。

【设计模式】
单例模式（Singleton）+ 双重检查锁（Double-Checked Locking）：
- 整个进程共享同一个注册表
- 线程安全（使用 threading.Lock）
- 支持 reset() 重置（用于测试或进程重启）

【核心操作】
- register(name, agent_id):    注册「名字 → ID」映射
- resolve(name_or_id):         查找：输入名字返回 ID，输入 ID 也返回 ID
- unregister(name):            取消注册
- list_all():                  列出所有注册信息

【使用场景】
1. 创建团队时，注册领导者和成员的名称
2. 发送消息时，将目标名字解析为 Agent ID
3. 删除团队时，取消注册
"""

from __future__ import annotations

import threading


class AgentNameRegistry:
    """
    Agent 名称注册表（线程安全的单例）。

    内部维护一个字典：{name: agent_id}
    支持双向查找：
    - 输入名字 → 返回 agent_id
    - 输入 agent_id → 直接返回（因为它已经在 values 中）
    """
    _instance: AgentNameRegistry | None = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._names: dict[str, str] = {}  # name -> agent_id


    @classmethod
    def instance(cls) -> AgentNameRegistry:
        """
        获取全局单例实例（双重检查锁）。

        为什么用双重检查锁？
        - 第一次检查：避免不必要的锁竞争（大多数情况实例已创建）
        - 加锁后第二次检查：防止两个线程同时通过第一次检查时重复创建
        """
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance


    @classmethod
    def reset(cls) -> None:
        """重置单例（用于测试或进程重启时清空注册表）"""
        with cls._lock:
            cls._instance = None


    def register(self, name: str, agent_id: str) -> None:
        """注册一个名称 → Agent ID 的映射"""
        self._names[name] = agent_id

    def resolve(self, name_or_id: str) -> str | None:
        """
        解析名称或 ID。

        查找逻辑：
        1. 先尝试作为名字查找 → 返回对应的 agent_id
        2. 再尝试作为 ID 查找（检查是否在 values 中）→ 直接返回
        3. 都找不到 → 返回 None

        这样调用方不需要区分输入的是名字还是 ID。
        """
        if name_or_id in self._names:
            return self._names[name_or_id]
        if name_or_id in self._names.values():
            return name_or_id
        return None

    def unregister(self, name: str) -> None:
        """取消注册（团队解散或成员离开时调用）"""
        self._names.pop(name, None)


    def list_all(self) -> dict[str, str]:
        """列出所有注册信息（返回副本，防止外部修改）"""
        return dict(self._names)
