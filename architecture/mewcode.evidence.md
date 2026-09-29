# MewCode — C4 证据索引

`mewcode.structurizr.dsl` 中的每个节点/连线都可追溯到以下来源。
除非另有说明，可信度均为**高**。路径相对于仓库根目录
（`E:/Projects/wyy/Mewcode`）。

## 人员与外部系统

| 元素 | 证据 |
| --- | --- |
| Developer（人员） | `README.md`（交互式 TUI 用法、快捷键、slash 命令） |
| CI / Automation | **假设** —— `README.md` 非交互 `-p` 模式 + Runtime Server API 表格；未检查 CI 配置 |
| Anthropic API | `mewcode/client.py:11`（`from anthropic import AsyncAnthropic`）、`AnthropicClient` 类 |
| OpenAI / 兼容 API | `mewcode/client.py:12`（`AsyncOpenAI`）、`OpenAIClient`、`OpenAICompatClient` 类 |
| MCP 工具服务器 | `mewcode/mcp/manager.py:9-12`、`mewcode/mcp/client.py`、`mewcode/mcp/tool_wrapper.py`；`README.md` MCP 配置 |
| 本地工作区与 Git 仓库 | `mewcode/tools/bash.py`、`read_file.py`、`edit_file.py`、`write_file.py`、`glob.py`、`grep.py`；`mewcode/worktree/` |

## 容器

| 容器 | 证据 |
| --- | --- |
| CLI 与 TUI 应用 | `mewcode/__main__.py:20-81`（参数解析、交互式 `MewCodeApp` 启动、`-p` 无头路径）；`mewcode/app.py`（Textual 应用）；`pyproject.toml:17`（`mewcode = mewcode.__main__:main`） |
| Runtime Server | `mewcode/runtime/server.py:1-7`、`mewcode/runtime/http.py`；`pyproject.toml:18`（`mewcode-server = mewcode.runtime.server:main`）；`README.md` “Agent Runtime” 章节（POST /v1/runs、SSE 事件） |
| Agent Engine | `mewcode/agent.py:48-84`（import client、context、conversation、memory、permissions、hooks、prompts、tools）；被两个前端复用 |
| 状态存储（.mewcode/） | `README.md`（`.mewcode/config.yaml`、`permissions.yaml`、`runs/<id>.events.jsonl`、`<id>.json`、`dag-runs/`）；`mewcode/runtime/store.py`；`mewcode/memory/session.py`；`mewcode/__main__.py:22`（创建 `.mewcode` 目录） |

## Agent Engine 组件

| 组件 | 证据 |
| --- | --- |
| 主循环（Agent Loop） | `mewcode/agent.py`（`run_to_completion`、工具派发、通知注入） |
| LLM 客户端 | `mewcode/client.py`（`LLMClient`、`AnthropicClient`、`OpenAIClient`、`OpenAICompatClient`、`resolve_context_window`） |
| Prompt 构建 | `mewcode/prompts.py`（`build_system_prompt`、`build_environment_context`、`build_plan_mode_reminder`） |
| 工具系统 | `mewcode/tools/__init__.py`（`create_default_registry`、`ToolRegistry`）；`mewcode/tools/*.py` |
| MCP 集成 | `mewcode/mcp/manager.py`、`client.py`、`tool_wrapper.py` |
| 子 Agent 系统 | `mewcode/agents/loader.py`、`task_manager.py`、`trace.py`、`builtins/{explore,plan,general-purpose,verification}.md` |
| Agent 团队 | `mewcode/teams/{coordinator,manager,mailbox,shared_task,registry}.py`；`mewcode/runtime/dag.py`；`mewcode/tools/{team_create,team_delete,dag_tools}.py` |
| 权限系统 | `mewcode/permissions/{checker,rules,dangerous,sandbox,modes}.py`；`mewcode/__main__.py:116-125` |
| 上下文管理器 | `mewcode/context/manager.py`；`mewcode/agent.py:50` |
| 技能系统 | `mewcode/skills/{loader,executor,directory,parser}.py`、`builtins/{commit,review,test,backend-interview}` |
| Hook 引擎 | `mewcode/hooks/{engine,loader,events,conditions,executors,models}.py`；`mewcode/__main__.py:16,55-60` |
| 记忆系统 | `mewcode/memory/{auto_memory,instructions,recall,session}.py`；`mewcode/agent.py:69` |

## Runtime Server 组件

| 组件 | 证据 |
| --- | --- |
| Server Entrypoint | `mewcode/runtime/server.py:10-24`（argparse `--host/--port` 默认 `127.0.0.1:8765`、`load_config`、`build_runtime`、`create_app`、`uvicorn.run`） |
| HTTP Adapter | `mewcode/runtime/http.py:19-78`（`create_app`；`POST /v1/runs`、`GET /v1/runs/{id}`、`POST .../cancel`、`GET .../events` SSE；FastAPI 懒加载，见 25-31 行） |
| Runtime Bootstrap | `mewcode/runtime/bootstrap.py:27-108`（`build_runtime`：`agent_factory`、`conversation_factory`、`conversation_saver`、`RunStore`；复用 CLI 的 provider/权限/工具/会话装配） |
| AgentRuntime Service | `mewcode/runtime/service.py:24-221`（`submit`、`_execute` 重试/超时、`cancel`、`_emit`、`subscribe` 回放+实时、`recover` 重启恢复；docstring 明确不依赖 Textual/FastAPI，见 26-29 行） |
| RunStore | `mewcode/runtime/store.py:11-101`（append-only 事件存储 + JSON 快照，`threading.RLock`，根目录 `.mewcode/runs`） |
| Run Models | `mewcode/runtime/models.py:10-108`（`RunStatus`、`AgentRun`、`RunEvent` 及 to_dict/from_dict） |

## 运行时 / 部署拓扑（DOT）

`mewcode-runtime-topology.dot` 为派生视图，证据如下：

| 拓扑元素 | 证据 |
| --- | --- |
| 三种进程入口（TUI / `-p` / server） | `mewcode/__main__.py:20-81,84-194`；`mewcode/runtime/server.py:10-24`；`pyproject.toml:17-18` |
| server 默认监听 127.0.0.1:8765 | `mewcode/runtime/server.py:12-13` |
| 进程内嵌入 Agent Engine（无独立服务） | `mewcode/runtime/service.py:98`（`agent.run_to_completion`）；`bootstrap.py:77-101`（factory 内联创建 `Agent`） |
| `.mewcode/` 状态目录内容 | `store.py:18,23-27`（runs/<id>.json、<id>.events.jsonl）；`README.md`（config/permissions/sessions/dag-runs/memory） |
| 本地工作区 & Git（cwd） | `bootstrap.py:35`（`os.getcwd`）；`mewcode/tools/{bash,read_file,edit_file,write_file}.py`；`mewcode/worktree/` |
| MCP stdio 子进程 / 远程 HTTP | `README.md` MCP 配置（`command: npx ...` stdio；`url: https://...` HTTP）；`mewcode/mcp/{manager,client}.py` |
| 出站 HTTPS 至 Anthropic/OpenAI | `mewcode/client.py:11-12,129,289,404`（AsyncAnthropic / AsyncOpenAI 适配器） |
| CI / Automation 调用方 | **假设（inferred）** —— 依据 `README.md` 非交互用法与 server API 表格；未检查 CI 配置 |

## 关键连线

| 关系 | 证据 |
| --- | --- |
| TUI/Server → Agent Engine | `mewcode/__main__.py:84-194`（构建 `Agent`）；`mewcode/runtime/bootstrap.py:6-24`（`build_runtime` 装配 `Agent`、client、tools、session） |
| Server → 状态存储（runs/events） | `mewcode/runtime/store.py`、`mewcode/runtime/service.py:10-11`；`README.md` 运行时持久化路径 |
| 主循环 → LLM 客户端 → provider | `mewcode/agent.py:48`；`mewcode/client.py` provider 适配器 |
| 主循环 → 工具系统 → MCP/子 Agent/团队/工作区 | `mewcode/agent.py:82`；`mewcode/tools/agent_tool.py`、`team_create.py`、`dag_tools.py`、`bash.py`；`mewcode/mcp/tool_wrapper.py` |
| 主循环 → 权限（门禁） | `mewcode/agent.py:71-76`；`mewcode/__main__.py:116-125` |
| 子 Agent → 主循环（嵌套） | **中等** —— 推断：`AgentTool(parent_agent=agent)` 派生 agent（`mewcode/tools/agent_tool.py`、`__main__.py:153-162`） |
| 记忆 → 状态存储 | `mewcode/memory/session.py`；`README.md` 记忆 / 会话持久化 |

## 校验说明

当前环境中没有可用的 Structurizr 解析器对 DSL 做机器校验。
该文件遵循插件的 DSL 语法（层级标识符、容器 / 组件引用使用完整点路径、
关系置于 `model` 内、`views` 置于 `workspace` 内、每个元素 / 关系 ≤4 个位置参数）。
