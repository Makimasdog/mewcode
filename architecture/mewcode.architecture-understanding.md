# MewCode 当前架构

基线提交：`8aa1da6`（2026-09-28）。源码证据见
[`mewcode.evidence.md`](mewcode.evidence.md)，结构清理记录见
[`structure-audit.md`](structure-audit.md)。

## 系统边界

MewCode 是一个本地优先的终端 AI 编程助手。打包入口来自
`pyproject.toml`：`mewcode` 指向 `mewcode.__main__:main`，
`mewcode-server` 指向 `mewcode.runtime.server:main`。

系统外部边界包括：

- 开发者或脚本调用方：使用 TUI、`-p` 或 Runtime HTTP API。
- Anthropic、OpenAI 和 OpenAI-compatible provider：由 `mewcode/client.py` 适配。
- MCP 工具服务器：通过 stdio 子进程或 HTTP 连接提供工具。
- 当前工作区和 Git 仓库：内置工具在其中读写文件并运行 git/shell。

## 入口与装配

| 入口 | 代码 | 责任 | 运行关系 |
| --- | --- | --- | --- |
| 交互式 CLI/TUI | `mewcode/__main__.py`、`mewcode/app.py` | 解析参数、加载配置、启动 Textual、装配 Agent | 进程内调用 Agent Engine |
| 无头 CLI | `mewcode/__main__.py::_run_prompt` | 使用一个 prompt 执行一次 Agent 循环 | 不创建 Textual；复用核心 Agent 和基础工具 |
| Runtime Server | `mewcode/runtime/server.py`、`http.py` | FastAPI/SSE 的 Run 提交、查询、取消和事件订阅 | `bootstrap.py` 创建 AgentRuntime 和 Agent 工厂 |

三种入口共享核心模块，但工具注册、会话保存和交互能力并不完全相同。
`AgentRuntime` 是后台服务抽象，不能概括为所有入口的统一装配层。

## 核心执行链路

```text
输入
  → ConversationManager
  → Agent.run / run_to_completion
  → Prompt 构建 + LLMClient 流式请求
  → StreamCollector 归一化事件
  → 工具参数校验
  → PermissionChecker + HookEngine
  → ToolRegistry 中的工具执行
  → ToolResult 写回会话
  → 继续下一轮，直到完成、失败、取消或达到限制
```

`Agent` 是 UI 无关的主循环。`LLMClient` 屏蔽 provider 事件差异；
`ToolRegistry` 统一内置工具、MCP 工具、Agent/Team/DAG 工具和 Skill 入口。
权限、危险命令检测、路径沙箱和 Hook 在副作用工具执行前形成门禁。

## 运行时模块

| 层 | 目录/文件 | 主要职责 |
| --- | --- | --- |
| 启动与配置 | `mewcode/__main__.py`、`config.py`、`validator.py` | 参数、YAML 合并、provider 和功能开关校验、依赖装配 |
| Agent 核心 | `agent.py`、`prompts.py`、`conversation.py` | prompt、流式响应、工具调用、多轮循环和会话消息 |
| provider | `client.py`、`serialization.py` | Anthropic、OpenAI、兼容 API 的请求和事件归一化 |
| 工具 | `tools/` | 文件、shell、搜索、询问用户、Skill、Agent、Team、DAG |
| 安全 | `permissions/`、`hooks/` | 权限模式、规则、危险命令、路径沙箱、Hook 拦截 |
| 扩展 | `mcp/`、`agents/`、`teams/`、`skills/`、`worktree/` | 外部工具、子 Agent、团队、技能和隔离工作区 |
| 上下文和记忆 | `context/`、`memory/`、`filehistory/` | 大输出裁剪、压缩、恢复、会话和长期记忆 |
| 后台 Runtime | `runtime/` | Run 状态机、重试/超时/取消、事件回放、JSONL 存储、HTTP/SSE |

## 持久化边界

`.mewcode/` 是文件型运行时状态：配置和权限使用 YAML，会话和记忆使用
JSON/JSONL，Runtime 使用 `runs/<id>.json` 与 `<id>.events.jsonl`，DAG 使用
`dag-runs/`。当前实现没有数据库、认证层或分布式调度；HTTP Server 适合本地
单用户场景。

## 兼容性边界

根目录不再保留历史源码镜像，wheel 与本地运行入口均统一使用 `mewcode/`。
真正的兼容逻辑位于 `mewcode/` 内部：会话旧字段、旧配置格式和 MCP SDK 字段
别名。它们必须在格式迁移或依赖升级方案确定后才能删除。

## 维护方式

修改架构时按以下顺序更新：

1. 先核对 `mewcode/` 中的入口、调用和实际 I/O。
2. 在 `mewcode.evidence.md` 登记事实和来源。
3. 更新 `mewcode.structurizr.dsl` 或 `mewcode-runtime-topology.dot`。
4. 最后更新本叙述文档和 README/Tutorial 中的链接。
