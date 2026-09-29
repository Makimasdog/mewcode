"""
manager.py — MCP 管理器（多服务器生命周期编排）
=============================================================

【这个模块做什么】
管理多个 MCP Server 的生命周期：
- 加载配置: 从 config.yaml 读取 MCP 服务器配置
- 连接并注册工具: 连接所有服务器并将工具注册到 ToolRegistry
- 按需重连: 连接断开时自动重建
- 统一关闭: 应用退出时清理所有连接

【工作流程】
1. load_configs(): 加载 MCP 服务器配置
2. register_all_tools(): 连接所有服务器并注册工具
3. get_client(): 按需获取客户端（支持重连）
4. shutdown(): 关闭所有连接

【调用关系】
- 被谁调用: __main__.py / app.py（启动时）
- 调用了谁: MCPClient（连接）、MCPToolWrapper（包装）、ToolRegistry（注册）
"""
from __future__ import annotations

import logging

from mewcode.config import MCPServerConfig
from mewcode.mcp.client import MCPClient
from mewcode.mcp.tool_wrapper import MCPToolWrapper
from mewcode.tools import ToolRegistry

logger = logging.getLogger(__name__)


class MCPManager:
    """
    MCP 管理器 — 管理多个 MCP Server 的生命周期。
    
    职责：
    - 配置管理: 存储所有 MCP 服务器配置
    - 连接管理: 维护客户端连接池
    - 工具注册: 将 MCP 工具包装并注册到 ToolRegistry
    - 容错重连: 连接断开时自动重建
    """


    def __init__(self) -> None:
        self._configs: dict[str, MCPServerConfig] = {}  # 服务器名称 → 配置
        self._clients: dict[str, MCPClient] = {}        # 服务器名称 → 客户端


    def load_configs(self, configs: list[MCPServerConfig]) -> None:
        """加载 MCP 服务器配置"""
        for cfg in configs:
            self._configs[cfg.name] = cfg


    async def register_all_tools(self, registry: ToolRegistry) -> list[str]:
        """
        连接所有 MCP 服务器并注册工具。
        
        流程：
        1. 遍历所有配置
        2. 连接每个服务器
        3. 发现工具并包装为 MCPToolWrapper
        4. 注册到 ToolRegistry
        
        返回: 错误列表（连接失败的服务器）
        """
        errors: list[str] = []
        for name, config in self._configs.items():
            try:
                client = MCPClient(config)
                await client.connect()
                self._clients[name] = client

                tools = await client.list_tools()
                for tool_def in tools:
                    wrapper = MCPToolWrapper(name, tool_def, client)
                    registry.register(wrapper)
                    logger.info("Registered MCP tool: %s", wrapper.name)

            except Exception as e:
                msg = f"MCP server '{name}': {e}"
                logger.warning(msg)
                errors.append(msg)

        return errors


    async def get_client(self, name: str) -> MCPClient | None:
        """
        获取 MCP 客户端（支持按需连接和重连）。
        
        流程：
        1. 检查缓存：有且存活则直接返回
        2. 检查配置：无配置则返回 None
        3. 新建连接：创建客户端并连接
        4. 重连逻辑：连接断开时自动重建
        """
        client = self._clients.get(name)
        if client is None:
            config = self._configs.get(name)
            if config is None:
                return None
            client = MCPClient(config)
            await client.connect()
            self._clients[name] = client
            return client

        if not client.is_alive:
            logger.info("Reconnecting MCP server '%s'", name)
            await client.close()
            client = MCPClient(self._configs[name])
            await client.connect()
            self._clients[name] = client

        return client


    async def shutdown(self) -> None:
        """关闭所有 MCP 连接"""
        for name, client in self._clients.items():
            try:
                await client.close()
                logger.info("MCP server '%s' closed", name)
            except Exception:
                logger.debug("Error closing MCP server '%s'", name, exc_info=True)
        self._clients.clear()
