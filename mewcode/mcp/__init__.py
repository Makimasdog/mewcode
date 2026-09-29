"""
mcp — MCP 外部工具协议集成
=============================================================

【这个模块做什么】
通过 MCP (Model Context Protocol) 协议接入外部工具生态：
- MCPClient: 与单个 MCP Server 的通信封装
- MCPManager: 多服务器生命周期管理
- MCPToolWrapper: 将 MCP 工具适配为 MewCode Tool 接口

【什么是 MCP】
MCP = Model Context Protocol（模型上下文协议）
一个开放协议，让 AI Agent 能调用外部工具服务器提供的工具。
类比：USB 接口标准 — 任何设备只要遵循标准就能接入。

【模块结构】
mcp/
├── client.py       MCP 客户端（stdio/HTTP 连接）
├── tool_wrapper.py 工具适配器（适配器模式）
└── manager.py      多服务器管理器

【连接方式】
stdio: 启动本地进程，通过 stdin/stdout 通信
  └─ 适合: 本地工具（filesystem、git 等）
HTTP: 连接远程服务，通过 HTTP 请求通信
  └─ 适合: 远程服务（云 API、数据库等）

【配置示例】
# .mewcode/config.yaml
mcpServers:
  filesystem:
    command: npx
    args: ["-y", "@modelcontextprotocol/server-filesystem", "/path"]
  remote-api:
    url: https://api.example.com/mcp
    headers:
      Authorization: "Bearer $API_KEY"

【与工具系统的关系】
- MCP 工具通过 MCPToolWrapper 适配为 Tool 接口
- tool_filter.py 第 0 层过滤对 MCP 工具始终放行
- should_defer=True: MCP 工具延迟加载，需通过 ToolSearch 发现
"""


from __future__ import annotations

from mewcode.mcp.manager import MCPManager

__all__ = ["MCPManager"]

