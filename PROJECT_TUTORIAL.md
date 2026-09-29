# MewCode 项目教程：架构、Agent、前端与后端实现指南

> 本文基于当前仓库代码整理，目标是让新开发者能够理解 MewCode 的运行链路、修改正确的模块，并完成一个可控的功能扩展。

## 0. 先建立正确的项目认知

MewCode 是一个运行在终端中的 AI 编程助手，技术核心是 Python、Textual、Anthropic/OpenAI SDK、MCP 和 Git Worktree。它以本地 TUI 为主要交互入口，同时提供不依赖 Textual 的 `AgentRuntime` 和可选 FastAPI/SSE 适配层：

- 本地交互界面由 Textual 负责输入、流式输出、工具调用展示、权限确认和会话操作。
- `AgentRuntime` 负责后台 Run 的创建、状态持久化、取消、超时、重试、事件回放和会话恢复。
- 可选的 `mewcode-server` 通过 FastAPI/SSE 暴露 Run 提交、状态查询、取消和事件流接口。
- 当前没有 PostgreSQL、MySQL 等 SQL 数据库；会话、Run 快照、事件和 DAG 状态使用 JSON/JSONL 文件保存，适合本地单用户部署。
- “后端”由 Agent 决策循环、LLM 协议适配、工具执行、权限、安全策略、Runtime 和本地文件持久化组成。

本文优先描述当前代码已经实现的 TUI、Runtime 和可选 HTTP/SSE 接口；涉及多用户数据库、认证和分布式调度的内容会明确标注为后续演进方案。

## 1. 项目定位与快速运行

### 1.1 运行入口和源码真相

`pyproject.toml` 将脚本入口配置为 `mewcode.__main__:main`，并且只把 `mewcode/` 目录打包为 wheel。因此实际开发时应以 `mewcode/` 下的代码为准。

系统边界、入口关系和源码证据集中维护在 [`architecture/README.md`](architecture/README.md)。

运行时代码统一位于 `mewcode/` 包内，根目录不再保留历史源码镜像。修改功能时请直接编辑 `mewcode/` 下对应模块。

### 1.2 环境

- Python >= 3.11（当前虚拟环境为 Python 3.12）。
- 至少一个 Anthropic、OpenAI 或 OpenAI-compatible API Key。
- Git；如果使用 Agent Worktree 或团队模式，还需要可用的 Git repository。
- `uv` 是项目文档推荐的依赖管理器；若本机没有 `uv`，可以直接使用 `.venv/Scripts/python.exe` 或系统 Python 安装依赖。

```bash
uv sync
uv run mewcode
uv run mewcode -p "解释一下这个项目的架构"
```

Windows PowerShell 示例：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m mewcode -p "检查项目结构"
```

### 1.3 最小配置

配置加载优先级从低到高为：

1. `~/.mewcode/config.yaml`
2. `<project>/.mewcode/config.yaml`
3. `<project>/.mewcode/config.local.yaml`

```yaml
providers:
  - name: anthropic
    protocol: anthropic
    base_url: https://api.anthropic.com
    model: claude-sonnet-4-6
    api_key: ${ANTHROPIC_API_KEY}

permission_mode: default
```

配置由 `mewcode/config.py` 解析，由 `mewcode/validator.py` 校验。API Key 支持 `${ENV_VAR}` 展开，但本地覆盖文件不应提交到 Git。

## 2. 系统整体架构

### 2.1 分层架构

```text
┌──────────────────────────────────────────────────────────────┐
│ CLI / TUI 入口                                                │
│ mewcode.__main__: 参数、配置、Hook、交互/非交互模式             │
└──────────────────────────┬───────────────────────────────────┘
                           │
             ┌─────────────▼─────────────┐
             │ MewCodeApp (Textual TUI)  │
             │ 输入、渲染、命令、对话状态   │
             └─────────────┬─────────────┘
                           │ Agent.run / run_to_completion
             ┌─────────────▼─────────────┐
             │ Agent 决策循环              │
             │ prompt → LLM → tool → loop │
             └──────┬──────────┬──────────┘
                    │          │
       ┌────────────▼───┐  ┌───▼─────────────────┐
       │ LLMClient       │  │ ToolRegistry         │
       │ Anthropic       │  │ 内置工具/MCP/Agent    │
       │ OpenAI Responses│  │ Skill/Team 工具       │
       │ OpenAI Chat     │  └──────────┬──────────┘
       └────────┬───────┘             │
                │                     │
       ┌────────▼────────┐   ┌────────▼───────────────┐
       │ Provider API     │   │ 权限、Hook、沙箱、Git   │
       │ 流式文本/工具调用 │   │ Worktree、MCP 外部系统  │
       └──────────────────┘   └────────────────────────┘

       ┌────────────────────────────────────────────────────────┐
       │ 横切持久化：Conversation / Session JSONL / Memory /     │
       │ Context compact / File cache / Team mailbox / YAML 配置 │
       └────────────────────────────────────────────────────────┘
```

### 2.2 启动时序

1. `mewcode/__main__.py` 创建 `.mewcode/` 并初始化日志。
2. `load_config()` 合并 YAML 配置，校验 provider、权限、MCP、Worktree 和功能开关。
3. 根据 `-p` 是否存在选择非交互模式或 Textual TUI。
4. TUI 启动 `MewCodeApp`，用户选择 provider 后执行 `_select_provider()`。
5. `_select_provider()` 依次装配：权限检查器、指令/记忆、会话、基础工具、Skill、Worktree、子 Agent、团队、Hook 和 MCP。
6. 创建 `Agent`，为其注入 `LLMClient`、`ToolRegistry`、`PermissionChecker`、上下文窗口和持久化目录。
7. 用户输入进入 `ConversationManager`，Agent 开始流式决策循环。

非交互模式复用相同的核心组件，但由 `__main__._run_prompt()` 手动装配并调用 `Agent.run_to_completion()`，不会创建 TUI。

### 2.3 模块划分

| 模块 | 关键文件 | 职责 | 依赖方向 |
|---|---|---|---|
| 启动与配置 | `mewcode/__main__.py`、`config.py`、`validator.py` | CLI 参数、配置合并、依赖装配 | 依赖所有基础设施 |
| TUI | `mewcode/app.py`、`styles.tcss`、`driver.py` | 页面布局、输入、事件渲染、弹窗 | 调用 Agent/Command |
| Agent 核心 | `mewcode/agent.py`、`prompts.py` | LLM 循环、工具调用、重试、事件 | 依赖 client/tools/context |
| LLM 适配 | `mewcode/client.py`、`serialization.py` | Anthropic/OpenAI 请求与流式事件归一化 | 依赖 provider SDK |
| 对话模型 | `mewcode/conversation.py` | provider 无关的消息历史和 token 锚点 | 被 Agent/Session 使用 |
| 工具 | `mewcode/tools/` | 文件、命令、Agent、Skill、团队等能力 | 被 Agent 调用 |
| 权限 | `mewcode/permissions/` | 模式、规则、路径沙箱、危险命令检测 | Agent 执行工具前调用 |
| MCP | `mewcode/mcp/` | stdio/HTTP MCP client 和工具包装器 | 注册进 ToolRegistry |
| 子 Agent | `mewcode/agents/` | 定义加载、后台任务、追踪树、工具过滤 | 由 Agent 工具启动 |
| 团队 | `mewcode/teams/` | Leader/Teammate、Mailbox、共享任务、后端探测 | AgentTool/TeamTool 调用 |
| 技能 | `mewcode/skills/` | Markdown frontmatter、技能激活、fork 执行 | LoadSkill/SkillExecutor |
| 上下文 | `mewcode/context/` | 工具结果裁剪、落盘、自动摘要、恢复附件 | Agent 每轮调用 |
| 记忆 | `mewcode/memory/` | 用户/项目记忆、相关记忆召回 | Agent/TUI 横切注入 |
| Worktree | `mewcode/worktree/` | 隔离目录、分支、清理、恢复 | Agent/Team 使用 |
| Hook | `mewcode/hooks/` | 生命周期动作、工具拒绝、prompt 注入 | Agent/TUI 事件流 |
| Agent Runtime | `mewcode/runtime/` | Run 持久化、事件回放、可选 HTTP/SSE 服务 | 复用 Agent 与 Session |
| DAG 编排 | `mewcode/runtime/dag.py`、`mewcode/tools/dag_tools.py` | 依赖校验、就绪节点并行与状态快照 | 调用现有 AgentTool |

### 2.4 技术栈与选择理由

- **Python 3.11+**：异步 IO、SDK 生态和快速扩展适合 Agent 编排。
- **Textual + Rich**：在终端提供组件化 UI、键盘绑定、Markdown 和异步消息循环。
- **Pydantic 2**：工具参数模型和动态 MCP 参数模型；YAML 应用配置由 `config.py` 解析、`validator.py` 校验。
- **Anthropic SDK / OpenAI SDK**：分别适配 Anthropic Messages、OpenAI Responses 和 Chat Completions。
- **MCP SDK + httpx**：接入外部工具服务，支持 stdio 和 streamable HTTP。
- **PyYAML**：项目/用户配置、权限规则和 Hook 配置。
- **Git Worktree**：让子 Agent 或队友在隔离目录中修改代码，降低并发冲突。
- **JSONL/JSON/Markdown**：本地单用户场景下可读、可审计、无外部数据库依赖。

### 2.5 一次用户请求的数据流

```text
TextArea.Submitted
  → MewCodeApp._dispatch_command
  → MewCodeApp._send_message
  → ConversationManager.add_user_message
  → Agent.run
  → build_system_prompt + apply_tool_result_budget
  → LLMClient.stream
  → StreamCollector 归一化为 AgentEvent
  → 若有 tool_calls：PermissionChecker/Hook → Tool.execute
  → ToolResultBlock 写回 ConversationManager
  → 下一轮 LLM 调用
  → LoopComplete
  → TUI 渲染并 Session.append 持久化
```

关键设计是“LLM provider 与业务逻辑解耦”：`Agent` 不知道 Anthropic 的具体事件格式，只消费 `TextDelta`、`ToolCallComplete`、`StreamEnd` 等统一事件。

## 3. Agent 智能体设计

### 3.1 Agent 的核心职责

`mewcode/agent.py` 中的 `Agent` 同时承担以下职责：

1. 构建环境上下文、项目指令、记忆、Skill 和子 Agent 目录。
2. 调用 LLM 并把 provider 流转换成统一事件。
3. 解析工具调用并进行参数校验、权限判断和 Hook 拦截。
4. 按工具是否支持并发执行调用，收集结果并追加到会话。
5. 处理 max token、未知工具、网络/API 异常和最大迭代次数。
6. 接近上下文上限时执行两层压缩。
7. 对后台任务、团队 mailbox、记忆提取和会话摘要提供协作入口。

### 3.2 决策流程与状态机

```text
START
  │ 注入 environment / long-term memory
  ▼
TURN_START Hook
  │ 消费 mailbox / 后台任务通知
  ▼
自动 compact？──是──> 摘要前缀 + 保留尾部 + 恢复附件
  │否
  ▼
PRE_SEND Hook → 构建 system prompt → 发送 tools schema
  ▼
LLM streaming
  ├─ 文本 → StreamText → UI
  ├─ thinking → ThinkingText → UI
  ├─ max_tokens → 提高输出上限/恢复提示 → 重试
  └─ tool_calls
          ▼
      Hook pre_tool_use
          ▼
      PermissionChecker
       ├─ deny → 错误 ToolResult
       ├─ ask  → PermissionRequest → 等待用户
       └─ allow
          ▼
      Pydantic 参数校验 → Tool.execute
          ▼
      Hook post_tool_use → ToolResultBlock
          ▼
      TURN_END → 回到下一轮

无 tool_calls → assistant message → SESSION_END → LOOP_COMPLETE
```

### 3.3 Agent 状态模型

| 状态 | 作用 | 生命周期 |
|---|---|---|
| `client` / `protocol` | 当前 LLM provider 和协议 | Agent 实例级 |
| `registry` | 可用工具和 deferred 工具发现状态 | provider 选择后初始化 |
| `permission_checker` | 工具权限和路径沙箱 | Agent 实例级，可切换模式 |
| `ConversationManager` | 原始消息、token 锚点、注入标记 | 会话级 |
| `replacement_state` | 工具结果裁剪决定，保持 prompt cache 稳定 | Agent 实例级 |
| `recovery_state` | 最近读取文件和激活 Skill 的快照 | Agent 实例级 |
| `active_skills` | 当前激活的 Skill SOP | 当前对话级 |
| `session_id` | JSONL transcript 关联 | 会话级 |
| `agent_id/parent_id/trace_id` | 子 Agent 追踪树 | Agent/团队级 |
| `team_name/_team_manager` | 团队 mailbox 协作上下文 | Teammate 级 |
| `total_input_tokens/output_tokens` | 累计用量展示和统计 | Agent 实例级 |

实现注意：`ConversationManager` 只保存 provider 无关的消息对象；`serialization.py` 在真正请求 provider 时再转换格式。不要在业务层直接拼 Anthropic/OpenAI 的消息字典。

### 3.4 LLM 多协议适配

`LLMClient` 是抽象接口，只有一个核心方法：

```python
async def stream(
    self,
    conversation: ConversationManager,
    system: str = "",
    tools: list[dict[str, Any]] | None = None,
) -> AsyncIterator[StreamEvent]: ...
```

当前有三种实现：

- `AnthropicClient`：Messages API，支持 thinking、tool use、prompt cache。
- `OpenAIClient`：Responses API，处理 `response.output_text.delta` 和 function call。
- `OpenAICompatClient`：Chat Completions API，兼容 vLLM、Ollama、Together、Azure 等实现。

新增 provider 时应遵循以下步骤：

1. 在 `validator.VALID_PROTOCOLS` 增加协议名。
2. 新建 `LLMClient` 子类，产出统一的 `TextDelta`、`ToolCallComplete`、`StreamEnd`。
3. 在 `create_client()` 注册构造分支。
4. 在 `serialization.build_messages()` 或独立转换函数中补充消息格式。
5. 处理认证、限流、网络错误，映射到 `AuthenticationError`、`RateLimitError`、`NetworkError`。
6. 用 Mock LLM 编写流式文本、工具调用、错误和 token 统计测试。

### 3.5 工具系统与工具调用决策

所有工具继承 `mewcode.tools.base.Tool`，至少需要：

```python
class MyTool(Tool):
    name = "MyTool"
    description = "工具用途和限制"
    params_model = MyParams
    category = "read"          # read / write / command
    is_concurrency_safe = False

    async def execute(self, params: MyParams) -> ToolResult:
        return ToolResult(output="...")
```

注册方式：

```python
registry.register(MyTool())
```

`ToolRegistry` 还负责：

- 输出 provider 对应的 JSON Schema。
- 禁用/启用工具。
- 延迟工具（`should_defer=True`）的发现和 schema 加载。
- 对 MCP、Skill、Agent 和团队工具提供统一命名空间。

Agent 用 `partition_tool_calls()` 把一个模型响应拆成批次：只有 `is_concurrency_safe=True` 且相邻的工具调用才会并行；写文件、命令、MCP 和 Agent 默认串行，避免竞态和副作用交错。

### 3.6 权限决策链

`PermissionChecker.check()` 的顺序是：

1. Plan 模式只允许 Agent、ToolSearch、AskUserQuestion、ExitPlanMode，并允许写入当前计划文件。
2. 只读命令自动放行。
3. 危险命令检测器拦截格式化磁盘、fork bomb、远程脚本管道执行等模式。
4. `PathSandbox` 限制文件访问在项目根目录、临时目录和显式允许目录内。
5. `RuleEngine` 从用户级、项目级、本地级 YAML 规则匹配 `allow/deny`。
6. 权限模式矩阵做最终判定。
7. `ask` 触发 Human-in-the-loop 的 `PermissionRequest`。

权限模式的实际矩阵：

| 模式 | read | write | command |
|---|---|---|---|
| `default` | allow | ask | ask |
| `acceptEdits` | allow | allow | ask |
| `plan` | allow | deny | deny |
| `bypassPermissions` | allow | allow | allow |
| `custom` | ask | ask | ask |
| `dontAsk` | allow | allow | allow |

开发注意：任何新工具都必须选择正确的 `category`；如果把有副作用的操作标成 `read`，会绕过核心权限边界。

### 3.7 两层上下文管理

#### Layer 1：工具结果预算

`apply_tool_result_budget()` 不修改原始会话，而是生成供 API 使用的副本：

- 单个工具结果超过 50,000 字符：完整内容写入 `.mewcode/session/tool-results/<tool_use_id>.txt`，消息只保留预览。
- 所有工具结果累计超过 200,000 字符：按结果大小从大到小继续落盘和替换。
- 超过最近 10 轮的旧结果只保留短片段。
- 替换决定写入 `replacement_records.jsonl`，保证跨轮次和 prompt cache 的稳定性。

#### Layer 2：自动摘要

当 `ConversationManager.current_tokens()` 达到 `context_window - 20,000 - safety_margin` 时触发 `auto_compact()`：

1. 从尾部保留约 10,000 token 或至少 5 条消息，最多 40,000 token。
2. 确保 tool_use 与 tool_result 不被拆开。
3. 只把前缀发送给摘要 LLM，生成九段结构化摘要。
4. 追加最近读取文件、已激活 Skill、可用工具列表等恢复附件。
5. 用“摘要 user 消息 + 原样尾部”替换历史。
6. 通过 `compact_boundary` 记录让会话恢复无需重放旧前缀。
7. 连续失败三次后熔断自动压缩，提示使用 `/compact` 手动处理。

### 3.8 子 Agent、后台任务与团队

#### 子 Agent

`AgentTool` 通过 `AgentToolParams` 接收：`prompt`、`description`、`subagent_type`、`model`、`run_in_background`、`isolation` 和 `team_name`。

Agent 定义是带 YAML frontmatter 的 Markdown，加载优先级为：项目级 `.mewcode/agents/` > 用户级 `~/.mewcode/agents/` > 内置定义。内置有 Explore、Plan、general-purpose；Verification 受 `enable_verification_agent` 开关控制。

创建子 Agent 时会：

1. 加载 AgentDef 并按 `tools/disallowedTools` 过滤工具。
2. 选择继承 provider 或模型别名。
3. 创建独立的 `PermissionChecker` 和上下文。
4. 设置 `parent_id`、`trace_id`，在 `TraceManager` 中登记节点。
5. 同步执行直接返回结果；后台执行交给 `TaskManager` 并返回 task id。

#### 团队

团队由 Leader、长期 Teammate、共享任务 JSON 和 Mailbox 组成。`TeamManager` 根据配置/平台探测 `in-process`、tmux 或 iTerm2 后端。每个队友通常拥有：

- 独立 Git Worktree。
- 自己的 Agent 实例和工具过滤结果。
- `~/.mewcode/teams/<team>/mailbox/` 下的文件型消息队列。
- `SendMessage`、任务列表和进度状态。

队友的文本回复不会自动对 Leader 可见，必须调用 `SendMessage`；这是团队 Agent 的关键交互约束。

#### Worktree 隔离

`WorktreeManager.create()` 执行 `git worktree add -B worktree-<slug>`，随后复制本地配置、配置 hooks、建立依赖目录软链接和复制 `.worktreeinclude` 指定的 ignored 文件。退出或自动清理前会检查未提交变更和新 commit，避免误删工作成果。

### 3.9 Skill、MCP 与 Hook 集成

- **Skill**：Markdown + frontmatter，支持 `inline`（把 SOP 注入主 Agent）和 `fork`（用独立 Agent 执行），可限制允许工具和上下文范围。
- **MCP**：`MCPClient` 支持 stdio 与 streamable HTTP；`MCPToolWrapper` 把远程工具转换为普通 `Tool`，默认 deferred，使用 `ToolSearch` 发现后才加载 schema。
- **Hook**：支持 session/turn/tool/message/system 等生命周期；action 类型有 command、prompt、http、agent（agent executor 当前是 stub）。`pre_tool_use` Hook 可以拒绝工具。

Hook、MCP 和 Skill 都属于扩展点，扩展时要避免把外部内容未经标记地拼入高优先级系统提示，必须考虑提示注入和敏感信息泄露。

## 4. 前端架构设计（Textual TUI）

### 4.1 页面结构

`MewCodeApp.compose()` 当前的组件树可以概括为：

```text
MewCodeApp
├─ #title-bar                  Banner、版本、模型、工作目录
├─ #provider-select (可选)      多 provider 选择列表
│  └─ #provider-list
├─ #chat-area (VerticalScroll)  用户消息、AI Markdown、工具块、队友树
└─ #input-area
   ├─ #chat-input (ChatInput)   输入、历史、/ 命令和 @ 文件补全
   ├─ #status-bar
   │  ├─ #mode-label            权限模式
   │  ├─ #teammates-label       队友数量
   │  └─ #model-label           当前模型
   └─ CompletionPopup            补全弹层
```

### 4.2 组件职责

| 组件 | 职责 | 关键交互 |
|---|---|---|
| `ChatInput` | 输入文本、历史持久化、键盘绑定 | Enter 发送、Shift+Enter 换行、Tab 补全 |
| `ToolCallBlock` | 展示工具调用和结果 | 点击展开/折叠、错误着色、耗时 |
| `ToolGroupSummary` | 合并多个可折叠只读工具 | Ctrl+O 批量展开/收起 |
| `SubAgentBlock` | 展示 Agent 子任务状态和统计 | 显示类型、描述、token/耗时 |
| `TeammateTree` | 周期刷新团队成员和进度 | mailbox/共享任务状态可视化 |
| Inline permission widget | 展示权限询问 | allow/deny/always |
| Inline plan widget | Plan 模式审批 | 读取计划、批准或继续规划 |
| Inline ask-user widget | Agent 主动提问 | 选项选择、恢复 Agent Future |

### 4.3 前端状态

`MewCodeApp` 将 UI 状态和业务对象集中在 App 实例中：

- `client`、`agent`、`conversation`：核心业务状态。
- `session_manager`、`session`：持久化句柄。
- `skill_loader`、`skill_executor`：Skill 状态。
- `task_manager`、`trace_manager`、`team_manager`：异步协作状态。
- `_streaming`、`_agent_task`、`_subagent_task`：当前操作生命周期。
- `_mcp_init_task`、`_teammate_timer`、`_notification_check_task`：后台轮询任务。

Textual 本身就是事件循环和 UI 状态容器，因此当前项目没有 Redux、Vuex 或 React Context。修改 UI 时应优先通过 Textual Message、`post_message()`、`call_after_refresh()` 和 `run_worker()` 与事件循环协作，不要在后台线程直接操作 Widget。

### 4.4 用户交互流程

1. `ChatInput.action_submit()` 记录历史到 `.mewcode/history`，发送 `Submitted` 消息。
2. `/command` 进入 `CommandRegistry`；普通文本进入 `_send_message()`。
3. `_send_message()` 先展开 `@file` 引用，再异步召回相关 Memory。
4. 每个 `AgentEvent` 映射为 UI 更新：文本流、工具块、权限弹窗、Hook 通知、压缩通知、完成状态。
5. `TurnComplete` 将新增消息追加到当前 Session；`LoopComplete` 更新摘要、token 和 Plan 审批。
6. Esc/Ctrl+C 取消任务；若是后台子 Agent，可将其转移到 `TaskManager` 继续运行。

### 4.5 前端扩展示例

添加一个新的本地 Slash 命令：

```python
MY_COMMAND = Command(
    name="mycommand",
    aliases=["mc"],
    description="执行一个本地动作",
    type=CommandType.LOCAL,
    handler=handle_mycommand,
)
```

然后在 `mewcode/commands/handlers/__init__.py` 的 `ALL_COMMANDS` 中注册。命令处理器通过 `CommandContext` 访问 Agent、Conversation、Session 和 UI，不要直接依赖 Textual 的具体 Widget。

添加新的流式 UI 事件时，建议流程是：

1. 在 `agent.py` 定义 dataclass 事件。
2. 在 `Agent.run()` 的合适阶段 `yield`。
3. 在 `MewCodeApp._send_message()` 中消费并渲染。
4. 为取消、异常、恢复和非交互模式补充行为。

## 5. 后端架构设计

### 5.1 当前实现：Python Runtime API 与可选 HTTP API

当前项目的“API”主要是 Python 协议和异步接口：

| 接口 | 输入 | 输出 | 用途 |
|---|---|---|---|
| `LLMClient.stream()` | Conversation、system、tool schemas | `StreamEvent` 异步流 | provider 适配 |
| `Tool.get_schema()` | Pydantic 参数模型 | JSON Schema | 暴露给 LLM |
| `Tool.execute()` | Pydantic 参数实例 | `ToolResult` | 执行能力 |
| `Agent.run()` | ConversationManager | `AgentEvent` 异步流 | 交互式决策循环 |
| `Agent.run_to_completion()` | task、可选 Conversation | 最终文本 | 非交互/后台任务 |
| `CommandHandler` | `CommandContext` | UI 副作用/提示 | Slash 命令 |
| `MCPClient.call_tool()` | tool name、JSON args | MCP CallToolResult | 外部工具调用 |
| `AgentRuntime.submit()` | task、session、重试/超时配置 | `AgentRun` | 创建可持久化后台任务 |
| `AgentRuntime.subscribe()` | run id、事件游标 | `RunEvent` 异步流 | 事件回放和实时订阅 |

这些接口形成了执行核心的业务边界。TUI、`-p` CLI 和可选 HTTP 服务都复用 `Agent` 等核心组件，但当前分别在 `app.py`、`__main__.py` 和 `runtime/bootstrap.py` 装配；TUI 与 `-p` CLI 并不通过 `AgentRuntime` 启动。仅使用本地 TUI/CLI 时无需启动 HTTP 服务。

### 5.2 当前已实现的服务化 API

安装 `server` 可选依赖后，`mewcode/runtime/http.py` 提供以下 FastAPI/SSE 路由：

```text
POST   /v1/runs                        提交 Agent 任务
GET    /v1/runs/{run_id}               查询任务状态
POST   /v1/runs/{run_id}/cancel        取消 Agent 运行
GET    /v1/runs/{run_id}/events        SSE 流式事件（支持 after 游标）
```

事件由 `RunStore` 持久化为 JSONL，SSE 先按 `after` 游标回放历史事件，再订阅实时队列。客户端可用 sequence 补读已持久化事件；当前回放与订阅之间存在竞争窗口，不能保证单次连接完整接收窗口内的新事件。会话管理、权限审批、Agent 目录和团队 mailbox 的 HTTP 路由目前仍属于后续服务化扩展。

### 5.3 实际持久化结构（代替 SQL 数据库）

当前使用文件系统，下面的“表”是逻辑数据模型：

| 逻辑实体 | 实际文件 | 主要字段 |
|---|---|---|
| Session metadata | `.mewcode/sessions/<id>.meta` | id、title、summary、message_count、total_tokens、created_at、last_active |
| Session event log | `.mewcode/sessions/<id>.jsonl` | type、content、timestamp、tool_use_id、is_error |
| Compact boundary | 同一 JSONL | summary、keep（内联的消息记录） |
| Tool result blob | `.mewcode/session/tool-results/<tool_use_id>.txt` | 完整工具输出 |
| Replacement log | `.mewcode/session/tool-results/replacement_records.jsonl` | tool_use_id、replacement、kind |
| Flat memory | `~/.mewcode/memories.md`、`.mewcode/memories.md` | 用户偏好、反馈、项目知识、参考资料 |
| File memory | `~/.mewcode/memory/*.md`、`.mewcode/memory/**/*.md` | frontmatter name/description/type + 正文 |
| Permission rules | `permissions.yaml` 三层路径 | rule、effect |
| Agent Run | `.mewcode/runs/<run_id>.json`、`.events.jsonl` | 状态快照、顺序事件 |
| DAG Run | `.mewcode/dag-runs/<run_id>.json` | 节点依赖、状态与结果 |
| Team config | `~/.mewcode/teams/<slug>/config.json` | name、lead_agent_id、members、description |
| Team tasks | `~/.mewcode/teams/<slug>/tasks.json` | 共享任务、状态、负责人 |
| Team mailbox | `~/.mewcode/teams/<slug>/mailbox/` | 发件人、收件人、类型、正文、时间 |
| Worktree session | `.mewcode/worktree_session.json` | original_cwd、worktree_path、branch、head commit |

Session JSONL 的 record type 包括 `user`、`assistant`、`tool_result`、`compression` 和 `compact_boundary`。`SessionManager.resume()` 会从最后一个 compact boundary 重建压缩后的消息，旧前缀仅作为审计保留。

### 5.4 如果引入 SQL，推荐的最小表结构

服务化或多用户部署时可以把上述文件模型迁移为：

```sql
users(id, external_subject, created_at)
projects(id, user_id, root_uri, permission_policy_json)
sessions(id, project_id, title, summary, status, total_input_tokens,
         total_output_tokens, created_at, last_active)
messages(id, session_id, seq, role, content_json, created_at)
tool_calls(id, message_id, tool_use_id, name, arguments_json, status)
tool_results(id, tool_call_id, content_uri, preview, is_error, created_at)
runs(id, session_id, agent_id, parent_run_id, status, started_at, ended_at)
tasks(id, run_id, task_type, status, result_json, started_at, ended_at)
memory_documents(id, scope, project_id, type, name, description, content,
                 mtime, checksum)
permission_rules(id, scope, project_id, tool_name, pattern, effect)
team_members(team_id, agent_id, name, agent_type, worktree_path, status)
team_messages(id, team_id, from_agent, to_agent, message_type, content, read_at)
```

迁移时必须保留 `seq` 和 `tool_use_id`，否则无法保证工具调用与工具结果的顺序配对；大工具输出建议继续放对象存储，只在数据库保存 URI 和预览。

### 5.5 业务逻辑层实现建议

当前代码已经隐含了四层业务结构：

1. **协议层**：`client.py`、`serialization.py`，只处理外部 LLM/MCP 协议。
2. **编排层**：`agent.py`，负责循环、重试、工具调度和状态转换。
3. **领域能力层**：`tools/`、`permissions/`、`memory/`、`worktree/`、`teams/`。
4. **适配/UI 层**：`app.py`、CLI、命令 Handler、文件系统。

新增业务功能时应遵循：

- 外部 API 错误在适配层转换，不要让 SDK 异常直接泄漏到 UI。
- 领域工具只返回 `ToolResult`，不要直接操作 Textual Widget。
- UI 通过 AgentEvent 和 CommandContext 获取结果。
- 所有会修改文件或执行命令的逻辑，都必须经过权限检查器或明确标记为系统内部动作。
- 长任务必须交给 `TaskManager`，不能阻塞 Textual 事件循环。

## 6. 安全策略

### 6.1 当前已有防线

- API Key 从环境变量读取，避免写入仓库。
- 配置结构和协议/模式有白名单校验。
- 文件路径使用 realpath 检查，阻止符号链接逃逸项目根目录。
- Bash 有安全命令白名单和危险正则拦截。
- 写入/命令默认需要用户确认。
- Plan 模式拒绝真正的编辑和命令，只允许写计划文件。
- Hook 可以在 `pre_tool_use` 阶段拒绝工具。
- MCP 子进程环境只传递 PATH 和显式声明的变量。
- Worktree 为子 Agent 提供隔离目录；退出时检查未提交变更，降低误删风险。
- 工具参数使用 Pydantic 校验，避免直接把不受控字典传入实现。

### 6.2 仍需重点注意的风险

1. `bypassPermissions`/`dontAsk` 是全自动模式，应只在隔离环境或 CI 沙箱中启用。
2. Hook 的 command action 使用 shell 执行；不要把未经过滤的用户输入拼接到 Hook 配置。
3. MCP 工具是外部信任边界，远程返回内容可能包含 prompt injection；系统提示已经要求 Agent 对可疑内容进行标记，但产品层仍应显示来源。
4. `@file` 引用会读取并注入文件内容，敏感文件应通过项目规则、忽略目录和权限沙箱控制。
5. 记忆文件是跨会话上下文，写入前要过滤凭据、Token、个人数据和临时状态。
6. 文件型 mailbox 适合单机协作；多进程/多主机部署必须增加原子写入、锁或数据库队列。
7. Team Worktree 的 `.env`、ignored 文件复制策略要按项目敏感性收紧，避免把生产凭据复制到子目录。

### 6.3 安全扩展 checklist

- 新工具是否正确声明 `category` 和 `is_concurrency_safe`？
- 是否通过 `params_model` 校验所有输入？
- 文件路径是否经过 `PathSandbox`？
- 命令是否拒绝 shell 元字符、危险模式和远程脚本管道？
- 是否在 `pre_tool_use`/`post_tool_use` Hook 记录审计信息？
- 是否对 LLM、MCP、Hook 返回内容标记来源并防止提示注入？
- 是否为超大输出设置落盘和访问控制？
- 是否在取消、重试和异常路径释放子进程、HTTP client、文件句柄和 Worktree？

## 7. 开发者上手路线

### 7.1 推荐阅读顺序

1. `pyproject.toml`：依赖、入口和构建范围。
2. `mewcode/__main__.py`：启动装配和非交互模式。
3. `mewcode/app.py`：TUI 组件和用户交互。
4. `mewcode/agent.py`：主循环、工具执行和 AgentEvent。
5. `mewcode/client.py` + `mewcode/serialization.py`：多 provider 适配。
6. `mewcode/tools/__init__.py` + `tools/base.py`：工具注册和 schema。
7. `mewcode/permissions/checker.py`：权限决策链。
8. `mewcode/context/manager.py`：大输出处理和上下文压缩。
9. `mewcode/memory/session.py`、`memory/recall.py`：恢复、摘要和记忆。
10. `mewcode/tools/agent_tool.py`、`teams/manager.py`、`worktree/manager.py`：并行 Agent 体系。

### 7.2 添加一个只读工具

```python
from pydantic import BaseModel
from mewcode.tools.base import Tool, ToolResult

class InspectParams(BaseModel):
    path: str

class InspectTool(Tool):
    name = "Inspect"
    description = "读取并返回项目内某个文件的摘要"
    params_model = InspectParams
    category = "read"
    is_concurrency_safe = True

    async def execute(self, params: InspectParams) -> ToolResult:
        # 真实实现应先使用 PathSandbox 或复用 ReadFile 的安全逻辑。
        return ToolResult(output=f"inspect: {params.path}")
```

在 `MewCodeApp._select_provider()` 和非交互 `_run_prompt()` 共享的注册路径中注册它；更好的做法是扩展 `create_default_registry()`，避免交互和非交互模式行为不一致。

### 7.3 添加一个 Agent 类型

在项目中创建 `.mewcode/agents/my-agent.md`：

```markdown
---
name: my-agent
description: 处理某类只读分析任务
tools:
  - ReadFile
  - Grep
  - Glob
disallowedTools:
  - WriteFile
  - EditFile
maxTurns: 20
permissionMode: default
---

你是一个专注于……的分析 Agent。
```

项目级定义优先于用户级和内置定义；加载器会对文件做热重载。

### 7.4 添加一个 Skill

在 `.mewcode/skills/my-skill/SKILL.md` 中声明 `name`、`description`、`mode`、`context` 和 `allowedTools`，正文通过 `$ARGUMENTS` 接收命令参数。`inline` Skill 注入主 Agent；`fork` Skill 使用独立上下文和受限工具集。

### 7.5 调试方法

- 启动日志：`.mewcode/debug.log`。
- 会话事件：`.mewcode/sessions/*.jsonl`。
- 会话元信息：`.mewcode/sessions/*.meta`。
- 大工具结果：`.mewcode/session/tool-results/`。
- 团队配置和 mailbox：`~/.mewcode/teams/`。
- 使用 `/status`、`/trace`、`/tasks`、`/mcp`、`/permission` 检查运行状态。
- 通过 Mock `LLMClient` 测试 Agent，不要在单元测试中依赖真实 API。

## 8. 测试与当前验证结果

项目使用 pytest，测试覆盖 Agent、上下文压缩、权限、团队、Worktree、Hook、序列化、记忆和 MCP 等模块。

本次在 Windows 环境执行：

```powershell
.\.venv\Scripts\python.exe -m pytest -q -x
```

结果为 **166 个测试通过，`tests/test_hooks.py::TestCommandExecutor::test_timeout` 失败**。失败原因是测试固定使用 Unix 命令 `sleep 10`，而当前 Windows shell 无法识别 `sleep`，实际返回“`sleep` is not recognized”，没有进入超时分支。这更像测试环境/跨平台测试夹具问题，而不是 Hook 超时逻辑本身；跨平台修复可以改用 Python 进程、PowerShell `Start-Sleep`，或在测试中按平台选择命令。

开发新功能时建议至少补充：

- 正常流式文本和空响应。
- 工具参数校验失败、未知工具和工具异常。
- 权限 allow/deny/ask 三条路径。
- 取消任务、超时、限流和网络错误。
- context compact 前后的 tool_use/tool_result 配对。
- 子 Agent 后台完成通知和 mailbox 消费。
- Windows、Linux、macOS 的 shell 差异。

## 9. 设计取舍与后续演进建议

### 当前设计的优点

- provider、工具和 UI 之间有明确适配边界。
- 文件型持久化可读、可审计，适合个人终端助手。
- Agent、Skill、MCP、团队和 Worktree 形成了较完整的扩展体系。
- 两层上下文管理兼顾了大工具输出、prompt cache 和摘要恢复。
- 权限链在执行前集中处理，工具实现不必重复询问逻辑。

### 当前设计的边界

- 全局文件状态和内存对象不适合多用户远程服务。
- 团队 mailbox 和任务文件缺少分布式锁，跨主机并发需要重构。
- Hook 的 `agent` action 目前只是 stub，不能当作可用的 Agent 编排 API。
- 一些测试夹具假设 Unix shell，Windows CI 需要额外适配。
- 运行时代码统一位于 `mewcode/`，避免了重复源码造成的修改错位。

### 推荐演进顺序

1. 先统一源码目录和测试夹具，建立跨平台 CI。
2. 为 AgentEvent、SessionRecord、ToolResult 增加版本字段，保证持久化兼容。
3. 抽出 `AgentService`/`SessionRepository` 接口，允许从文件实现平滑切换到 SQL/对象存储。
4. 在现有 SSE Run 事件流基础上，按需求补充权限审批、会话管理与 WebSocket 接口。
5. 增加用户认证、项目级租户隔离、密钥托管和审计日志。
6. 最后再引入远程团队调度和分布式任务队列。

## 10. 关键文件索引

- 启动与装配：`mewcode/__main__.py`、`mewcode/config.py`
- UI：`mewcode/app.py`、`mewcode/styles.tcss`
- Agent：`mewcode/agent.py`、`mewcode/prompts.py`
- LLM：`mewcode/client.py`、`mewcode/serialization.py`
- 对话与会话：`mewcode/conversation.py`、`mewcode/memory/session.py`
- 工具：`mewcode/tools/base.py`、`mewcode/tools/__init__.py`
- 权限：`mewcode/permissions/checker.py`、`mewcode/permissions/modes.py`
- 上下文：`mewcode/context/manager.py`
- MCP：`mewcode/mcp/client.py`、`mewcode/mcp/tool_wrapper.py`
- 子 Agent：`mewcode/tools/agent_tool.py`、`mewcode/agents/loader.py`
- 团队：`mewcode/teams/manager.py`、`mewcode/teams/mailbox.py`
- Worktree：`mewcode/worktree/manager.py`
- Skill：`mewcode/skills/loader.py`、`mewcode/skills/executor.py`
- Hook：`mewcode/hooks/engine.py`、`mewcode/hooks/executors.py`
- Runtime：`mewcode/runtime/service.py`、`mewcode/runtime/http.py`、`mewcode/runtime/store.py`
- DAG：`mewcode/runtime/dag.py`、`mewcode/tools/dag_tools.py`
- 测试：`tests/`

## 11. 当前实现的 Runtime 与 DAG 能力

### 11.1 Agent Runtime 服务化

`mewcode/runtime/service.py` 提供不依赖 Textual 的 `AgentRuntime` 应用服务，处理 Run 创建、Agent 工厂、会话恢复、事件发布、取消和状态查询。`RunStore` 将每个 Run 的快照保存为 `.mewcode/runs/<run_id>.json`，将事件追加保存为 `.events.jsonl`。当前 HTTP 服务使用该 Runtime；TUI 和 `-p` CLI 仍有各自的装配流程。

`mewcode/runtime/http.py` 是可选 FastAPI/SSE 适配器，只有安装 `fastapi` 后才导入；`mewcode/runtime/server.py` 提供 `mewcode-server` 入口。SSE 支持 `after` 游标，先回放持久化事件，再订阅实时队列。客户端可补读已提交事件，但回放和订阅之间的竞争窗口仍需进一步处理。

### 11.2 Durable Agent

`AgentRun` 使用 `pending/running/waiting_approval/completed/failed/cancelled` 状态模型，记录尝试次数、超时、结果和错误。`AgentRuntime` 和增强后的 `TaskManager` 都支持：

- 超时取消与显式取消。
- 最大尝试次数和指数退避重试。
- `run_created/run_started/run_retrying/run_completed/run_failed/run_cancelled` 事件。
- 进程重启后由 `recover()` 通过应用层 Agent factory 显式恢复未完成 Run。
- 使用已有 `SessionManager` JSONL 继续保存对话历史，而不是另造一套消息格式。

恢复需要调用方提供 Agent factory，因为 provider、权限模式和会话上下文属于应用配置；没有 factory 时 Run 会保留在磁盘中，不会被静默丢弃。

### 11.3 DAG 多 Agent 编排

`mewcode/runtime/dag.py` 中的 `DAGScheduler` 支持节点依赖校验、环检测、就绪节点并行、失败传播、节点级重试、结果传递和运行快照。`DAGCreate`/`DAGStatus` 工具已注册到交互与非交互 Agent 的 ToolRegistry，可描述如下流程：

```text
explore ──┐
          ├── implement ──> test ──> review
analyze ──┘
```

下游节点收到以节点 ID 标记的依赖节点文本输出；节点执行器通过注入的 callback 调用现有 `AgentTool`，沿用其权限、Agent 类型过滤、模型选择和追踪逻辑。DAG 状态保存到 `.mewcode/dag-runs/`，可通过 `DAGStatus` 查询。
