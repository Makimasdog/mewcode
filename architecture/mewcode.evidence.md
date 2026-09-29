# MewCode 架构证据索引

基线提交：`8aa1da6`。路径相对于仓库根目录。这里记录的是源码能直接证明
的事实；使用场景、未来演进和没有配置支持的部署角色不作为当前架构事实。

## 入口与装配

| 事实 | 证据 |
| --- | --- |
| `mewcode` 打包入口 | `pyproject.toml` 的 `[project.scripts]`；`mewcode/__main__.py:15` 的 `main` |
| `mewcode-server` 打包入口 | `pyproject.toml`；`mewcode/runtime/server.py:29` 的 `main` |
| TUI 和 `-p` 分支 | `mewcode/__main__.py:15-78`；`mewcode/__main__.py:79` 后的 `_run_prompt` |
| Runtime 装配 | `mewcode/runtime/bootstrap.py:47` 的 `build_runtime`；创建 Agent、会话工厂、保存器和 RunStore |
| wheel 只打包 `mewcode/` | `pyproject.toml` 的 `tool.hatch.build.targets.wheel.packages` |

## Agent Engine

| 组件 | 证据 |
| --- | --- |
| 主循环 | `mewcode/agent.py:427` 的 `Agent`；`run_to_completion` 在文件后段定义 |
| 流式事件归一化 | `mewcode/agent.py:262` 的 `StreamCollector`；`mewcode/tools/base.py` 的事件类型 |
| provider 适配 | `mewcode/client.py:125`、`:285`、`:400` 的 Anthropic/OpenAI/兼容客户端；`create_client` 在 `:560` |
| 工具注册 | `mewcode/tools/__init__.py:30` 的 `ToolRegistry`；`create_default_registry` 在 `:212` |
| 权限门禁 | `mewcode/permissions/checker.py:34` 的 `PermissionChecker`；`check` 在 `:59` |
| 路径和命令安全 | `mewcode/permissions/sandbox.py:12`、`dangerous.py:64`、`rules.py:113` |
| Context / Memory / Hook | `mewcode/context/manager.py`、`mewcode/memory/auto_memory.py:43`、`mewcode/hooks/engine.py:50` |
| 子 Agent、团队、DAG | `mewcode/tools/agent_tool.py:92`、`team_create.py:38`、`dag_tools.py:60`；`mewcode/teams/manager.py:32` |
| MCP | `mewcode/mcp/client.py:45`、`manager.py:34`、`tool_wrapper.py:99` |

## Runtime Server

| 组件 | 证据 |
| --- | --- |
| HTTP/SSE 路由 | `mewcode/runtime/http.py:36` 的 `create_app`；`POST /v1/runs`、状态、取消和 `/events` |
| Run 状态模型 | `mewcode/runtime/models.py:32` 的 `RunStatus`、`:50` 的 `AgentRun`、`:119` 的 `RunEvent` |
| Run 服务 | `mewcode/runtime/service.py:50` 的 `AgentRuntime`；`submit:84`、`cancel:240`、`subscribe:252`、`recover:281` |
| 文件存储 | `mewcode/runtime/store.py:30` 的 `RunStore`；写入 `.mewcode/runs/<id>.json` 和 `.events.jsonl` |
| 可选 FastAPI 依赖 | `mewcode/runtime/http.py` 在 `create_app` 内延迟导入 FastAPI；`pyproject.toml` 的 `server` extra |

## 外部 I/O 和状态

| 关系 | 证据 |
| --- | --- |
| LLM 出站调用 | `mewcode/client.py` 的三个 provider 客户端；配置模型见 `mewcode/config.py` |
| MCP stdio/HTTP | `mewcode/mcp/client.py` 的连接和 `call_tool`；服务器配置见 `mewcode/config.py` |
| 工作区文件和 shell | `mewcode/tools/{bash,read_file,edit_file,write_file,glob,grep}.py` |
| 会话和记忆 | `mewcode/memory/session.py` 的 `SessionManager`；`mewcode/memory/auto_memory.py` 的 `MemoryManager` |
| DAG 状态 | `mewcode/runtime/dag.py` 和 `mewcode/tools/dag_tools.py`；写入 `.mewcode/dag-runs/` |

## 需要保留的兼容面

- `mewcode/conversation.py` 明确同步旧字段，避免旧会话读取失败。
- `mewcode/validator.py` 保留 list 配置格式。
- `mewcode/mcp/tool_wrapper.py` 同时读取 SDK 的 camelCase 和 snake_case 字段。
- 根目录镜像由历史路径和教程引用，但 `pyproject.toml` 不把它们作为 wheel 源码。
