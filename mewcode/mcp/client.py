"""
client.py — MCP 客户端（与外部工具服务器的通信桥梁）
=============================================================

【这个模块做什么】
封装与单个 MCP Server 的连接和通信：
- 支持两种连接方式: stdio（本地进程）和 HTTP（远程服务）
- 管理连接生命周期（连接、初始化、关闭）
- 提供工具发现和调用接口

【什么是 MCP】
MCP = Model Context Protocol（模型上下文协议）
一个开放协议，让 AI Agent 能调用外部工具服务器提供的工具。
类比：USB 接口标准 — 任何设备只要遵循 USB 标准就能接入电脑。
MCP 让任何工具服务器只要遵循协议就能接入 Agent。

【连接方式对比】
stdio: 启动本地进程，通过 stdin/stdout 通信
  └─ 适合: 本地工具（如 filesystem、git 等）
HTTP: 连接远程服务，通过 HTTP 请求通信
  └─ 适合: 远程服务（如云 API、数据库等）

【设计亮点】
- AsyncExitStack: 统一管理多个异步上下文（连接、会话、HTTP 客户端）
- 容错关闭: cancel scope 异常在关闭时是预期的，不报错
- 环境变量解析: 支持 $ENV_VAR 格式的环境变量引用
"""
from __future__ import annotations

import logging
import os
from contextlib import AsyncExitStack
from typing import Any

import httpx
from mcp import ClientSession, types
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamable_http_client

from mewcode.config import MCPServerConfig, build_child_env, resolve_env_vars

logger = logging.getLogger(__name__)


class MCPClient:
    """
    MCP 客户端 — 与单个 MCP Server 的通信封装。
    
    生命周期：
    1. connect(): 建立连接（stdio 或 HTTP）
    2. list_tools(): 发现工具
    3. call_tool(): 调用工具
    4. close(): 关闭连接
    """

    def __init__(self, config: MCPServerConfig) -> None:
        self.config = config
        self.name = config.name
        self._session: ClientSession | None = None  # MCP 会话
        self._stack: AsyncExitStack | None = None    # 异步上下文栈
        self._alive = False                          # 连接状态


    @property
    def is_alive(self) -> bool:
        """连接是否存活"""
        return self._alive


    async def connect(self) -> None:
        """
        建立与 MCP Server 的连接。
        
        流程：
        1. 创建 AsyncExitStack（管理异步资源的统一关闭）
        2. 根据配置选择 stdio 或 HTTP 连接
        3. 创建 ClientSession 并初始化
        """
        if self._alive:
            return

        self._stack = AsyncExitStack()
        await self._stack.__aenter__()

        try:
            if self.config.is_stdio:
                read, write = await self._connect_stdio()
            else:
                read, write = await self._connect_http()

            session = await self._stack.enter_async_context(
                ClientSession(read, write)
            )
            await session.initialize()  # MCP 协议握手
            self._session = session
            self._alive = True
            logger.info("MCP server '%s' connected", self.name)
        except Exception:
            await self._cleanup_stack()
            raise


    async def _connect_stdio(self) -> tuple[Any, Any]:
        """
        stdio 连接 — 启动本地进程并通过 stdin/stdout 通信。
        
        适用场景: 本地工具服务器（如 filesystem、sqlite 等）
        """
        assert self._stack is not None
        assert self.config.command is not None

        params = StdioServerParameters(
            command=self.config.command,
            args=self.config.args,
            env=build_child_env(self.config.env),
        )
        devnull = open(os.devnull, "w")  # 丢弃 stderr
        self._stack.callback(devnull.close)
        read, write = await self._stack.enter_async_context(
            stdio_client(params, errlog=devnull)
        )
        return read, write

    async def _connect_http(self) -> tuple[Any, Any]:
        """
        HTTP 连接 — 连接远程 MCP Server。
        
        适用场景: 远程工具服务（如云 API、数据库服务等）
        支持: 环境变量解析（$ENV_VAR 格式）
        """
        assert self._stack is not None
        assert self.config.url is not None

        # 解析请求头中的环境变量
        resolved_headers = {
            k: resolve_env_vars(v) for k, v in self.config.headers.items()
        }
        http_client = httpx.AsyncClient(
            headers=resolved_headers,
            follow_redirects=True,
        )
        await self._stack.enter_async_context(http_client)

        result = await self._stack.enter_async_context(
            streamable_http_client(self.config.url, http_client=http_client)
        )
        read, write = result[0], result[1]
        return read, write


    async def list_tools(self) -> list[types.Tool]:
        """发现 MCP Server 提供的所有工具"""
        assert self._session is not None
        result = await self._session.list_tools()
        return list(result.tools)


    async def call_tool(
        self, name: str, arguments: dict[str, Any]
    ) -> types.CallToolResult:
        """调用 MCP 工具"""
        assert self._session is not None
        return await self._session.call_tool(name, arguments)

    async def close(self) -> None:
        """关闭连接，释放资源"""
        self._alive = False
        self._session = None
        await self._cleanup_stack()

    async def _cleanup_stack(self) -> None:
        """
        清理异步上下文栈。
        
        注意: cancel scope 异常在关闭时是预期的（如进程退出时），
        不报错，只记录 debug 日志。
        """
        if self._stack is not None:
            try:
                await self._stack.__aexit__(None, None, None)
            except RuntimeError as e:
                if "cancel scope" in str(e):
                    logger.debug("Cancel scope cleanup (expected during shutdown): %s", e)
                else:
                    raise
            except Exception:
                logger.debug("Error closing stack for '%s'", self.name, exc_info=True)
            self._stack = None
