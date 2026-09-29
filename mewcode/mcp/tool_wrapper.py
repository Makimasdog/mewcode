"""
tool_wrapper.py — MCP 工具适配器（桥接 MCP 与 MewCode 工具系统）
=============================================================

【这个模块做什么】
将 MCP 工具包装为 MewCode 的 Tool 接口：
- 动态生成 Pydantic 参数模型（从 JSON Schema）
- 转换 MCP 结果内容为文本
- 处理连接断开时的自动重连

【为什么需要这个】
MCP 工具和 MewCode 内置工具的接口不同：
- MCP: inputSchema (JSON Schema) + call_tool()
- MewCode: params_model (Pydantic) + execute()

MCPToolWrapper 是「适配器模式」的典型应用，
让外部工具无缝接入内部工具系统。

【设计亮点】
- 动态模型生成: 用 create_model() 从 JSON Schema 动态创建 Pydantic 模型
- should_defer=True: MCP 工具默认延迟加载（需通过 ToolSearch 发现）
- 自动重连: 执行时检测连接断开，尝试重新连接
- 容错处理: 工具调用失败返回 ToolResult(is_error=True)，不中断对话
"""
from __future__ import annotations

from typing import Any

from mcp import types as mcp_types
from pydantic import BaseModel, create_model

from mewcode.mcp.client import MCPClient
from mewcode.tools.base import Tool, ToolResult


def _build_params_model(
    tool_name: str, input_schema: dict[str, Any]
) -> type[BaseModel]:
    """
    从 JSON Schema 动态生成 Pydantic 参数模型。
    
    MCP 工具的参数定义用 JSON Schema 描述，
    这个函数将其转换为 Pydantic BaseModel，
    使 MewCode 的参数验证机制能统一处理。
    """
    properties = input_schema.get("properties", {})
    required = set(input_schema.get("required", []))

    field_definitions: dict[str, Any] = {}
    for name, prop in properties.items():
        py_type = _json_type_to_python(prop.get("type", "string"))
        if name in required:
            field_definitions[name] = (py_type, ...)  # 必填字段
        else:
            field_definitions[name] = (py_type | None, None)  # 可选字段

    return create_model(f"{tool_name}Params", **field_definitions)


def _json_type_to_python(json_type: str) -> type:
    """JSON Schema 类型 → Python 类型映射"""
    mapping: dict[str, type] = {
        "string": str,
        "integer": int,
        "number": float,
        "boolean": bool,
        "object": dict,
        "array": list,
    }
    return mapping.get(json_type, str)


def _extract_text(content: list[Any]) -> str:
    """
    提取 MCP 工具返回内容中的文本。
    
    MCP 返回内容可能是多种类型：
    - TextContent: 文本
    - ImageContent: 图片（只返回 MIME 类型描述）
    - EmbeddedResource: 嵌入资源
    """
    parts: list[str] = []
    for block in content:
        if isinstance(block, mcp_types.TextContent):
            parts.append(block.text)
        elif isinstance(block, mcp_types.ImageContent):
            # MCP SDK versions expose either camelCase or snake_case fields.
            mime_type = getattr(block, "mimeType", None) or getattr(block, "mime_type", "")
            parts.append(f"[image: {mime_type}]")
        elif isinstance(block, mcp_types.EmbeddedResource):
            resource = block.resource
            if hasattr(resource, "text"):
                parts.append(resource.text)
            else:
                parts.append(f"[binary resource: {resource.uri}]")
    return "\n".join(parts) if parts else "(no output)"


class MCPToolWrapper(Tool):
    """
    MCP 工具适配器 — 将 MCP 工具包装为 MewCode Tool 接口。
    
    设计要点：
    - 工具名格式: mcp_{server_name}_{tool_name}（避免命名冲突）
    - should_defer=True: 延迟加载，需通过 ToolSearch 发现
    - is_concurrency_safe=False: MCP 工具不支持并发调用
    - 自动重连: 执行时检测连接断开，尝试重新连接
    """

    def __init__(
        self,
        server_name: str,
        tool_def: mcp_types.Tool,
        client: MCPClient,
    ) -> None:
        self._server_name = server_name
        self._tool_def = tool_def
        self._client = client
        self.name = f"mcp_{server_name}_{tool_def.name}"  # 唯一名称
        self.description = tool_def.description or tool_def.name
        self.category = "command"
        self.is_concurrency_safe = False  # MCP 工具不支持并发
        self.should_defer = True  # 延迟加载（需通过 ToolSearch 发现）
        # 从 JSON Schema 动态生成 Pydantic 参数模型
        input_schema = getattr(tool_def, "inputSchema", None)
        if input_schema is None:
            input_schema = getattr(tool_def, "input_schema", {})
        self.params_model = _build_params_model(tool_def.name, input_schema)

    @property
    def mcp_tool_name(self) -> str:
        """原始 MCP 工具名称（不含服务器前缀）"""
        return self._tool_def.name


    def get_schema(self) -> dict[str, Any]:
        """获取工具 schema（用于 LLM 工具描述）"""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": getattr(self._tool_def, "inputSchema", None)
            or getattr(self._tool_def, "input_schema", {}),
        }


    async def execute(self, params: BaseModel) -> ToolResult:
        """
        执行 MCP 工具。
        
        流程：
        1. 检查连接状态，断开时尝试重连
        2. 调用 MCP 工具
        3. 转换结果为文本
        4. 失败时标记连接断开，下次自动重连
        """
        # 检查连接状态，断开时尝试重连
        if not self._client.is_alive:
            try:
                await self._client.connect()
            except Exception as e:
                return ToolResult(
                    output=f"MCP server '{self._server_name}' reconnect failed: {e}",
                    is_error=True,
                )

        try:
            result = await self._client.call_tool(
                self._tool_def.name, params.model_dump(exclude_none=True)
            )
        except Exception as e:
            self._client._alive = False  # 标记断开，下次自动重连
            return ToolResult(
                output=f"MCP tool call failed: {e}",
                is_error=True,
            )

        text = _extract_text(result.content)
        return ToolResult(output=text, is_error=bool(result.isError))
