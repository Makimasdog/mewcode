# MewCode `agents/` 模块深度解析

## 1. 全局概览

**定位**：`agents/` 模块是 MewCode 的**子 Agent 管理系统**，负责定义、加载、派发和执行子 Agent，是 MewCode 实现「多 Agent 协作」的核心基础设施。

如果把主 Agent（`mewcode/agent.py`）比作一个「项目经理」，那 `agents/` 模块就是它的「人力资源部」——负责招募（加载）、培训（配置）、派遣（fork/派发）和考核（追踪）各类专业人员。

### 在整体架构中的位置

```
用户 → app.py（应用层）
         ↓
       agent.py（主 Agent 引擎 — 对话循环）
         ↓ 调用 Agent 工具
       tools/agent_tool.py（子 Agent 调用桥梁）
         ↓ 使用
       agents/（子 Agent 管理系统）
         ├─ parser.py     → 定义格式
         ├─ loader.py     → 加载 & 热重载
         ├─ fork.py       → 上下文继承
         ├─ tool_filter.py → 权限隔离
         ├─ task_manager.py → 生命周期管理
         ├─ trace.py      → 调用链追踪
         └─ notification.py → 结果回传
```8

---

## 2. 文件结构与职责

| 文件 | 核心职责 | 关键类/函数 |
|------|---------|------------|
| `__init__.py` | 模块公共 API 出口 | 聚合导出所有核心符号 |
| `parser.py` | Agent 定义文件的解析与校验 | `AgentDef`, `parse_agent_file`, `parse_frontmatter` |
| `loader.py` | 多来源 Agent 加载、优先级管理、热重载 | `AgentLoader` |
| `fork.py` | 从父对话 fork 出子对话，继承上下文 | `build_forked_messages` |
| `tool_filter.py` | 按角色/场景过滤子 Agent 可用工具 | `resolve_agent_tools`, `build_teammate_tools` |
| `task_manager.py` | 后台任务生命周期管理（重试、超时、恢复） | `TaskManager`, `BackgroundTask` |
| `trace.py` | Agent 调用链的树形追踪 | `TraceManager`, `TraceNode` |
| `notification.py` | 后台任务完成后向主 Agent 注入通知 | `format_task_notification`, `inject_task_notifications` |
| `builtins/*.md` | 内置 Agent 定义 | YAML frontmatter + Markdown body |

---

## 3. 核心流程详解

### 3.1 Agent 定义与解析（`parser.py`）

**文件**：`mewcode/agents/parser.py`
**职责**：定义 Agent 的数据模型和解析规则

#### 核心数据模型 — `AgentDef`

```python
@dataclass
class AgentDef:
    agent_type: str          # Agent 名称，如 "Explore"、"Plan"
    when_to_use: str         # 描述何时使用此 Agent（给 LLM 看的选型指南）
    system_prompt: str       # 系统提示词（Markdown body 部分）
    tools: list[str]         # 允许使用的工具白名单
    disallowed_tools: list[str]  # 禁用的工具黑名单
    model: str               # 模型选择："inherit" / "sonnet" / "opus" / "haiku"
    max_turns: int           # 最大迭代轮数，防止失控
    permission_mode: str     # 权限模式："default" / "acceptEdits" / "dontAsk"
    background: bool         # 是否后台运行
    isolation: str           # 隔离方式："" / "worktree"
    file_path: Path | None   # 来源文件路径（用于热重载）
    source: str              # 来源标记："builtin" / "project" / "user" / "plugin"
```

**设计意图**：用一个 dataclass 统一描述所有来源的 Agent 定义，不论来自内置、项目级还是用户级。`source` 字段看似不起眼，但在 `tool_filter.py` 中用于区分对待自定义 Agent（更严格的工具限制）。

#### 解析格式 — YAML Frontmatter + Markdown

```markdown
---
name: Explore
description: 快速只读搜索代码的子 Agent
disallowedTools:
  - Agent
  - EditFile
model: haiku
maxTurns: 30
---

你是一个文件搜索专家。这是一个只读探索任务。
...
```

解析分两步：
1. **`parse_frontmatter()`**：提取 `---` 包裹的 YAML 元数据 + Markdown 正文
2. **`_validate_agent_meta()`**：校验必填字段（`name`、`description`）和枚举值（`model`、`permissionMode`、`isolation`）

**设计亮点**：用 YAML frontmatter 格式（类似 Jekyll/Hugo 的静态站点风格）让 Agent 定义文件既能被程序解析，又方便人类阅读和编辑。

---

### 3.2 Agent 加载（`loader.py`）

**文件**：`mewcode/agents/loader.py`
**职责**：多来源 Agent 扫描、优先级管理、缓存与热重载

#### 三级优先级加载 — `load_all()`

```python
def load_all(self) -> dict[str, AgentDef]:
    seen: dict[str, AgentDef] = {}
    
    # 优先级 1：项目级 .mewcode/agents/（最高）
    project_path = Path(self._work_dir) / PROJECT_AGENTS_DIR
    for agent_def in self._scan_directory(project_path, "project"):
        if agent_def.agent_type not in seen:
            seen[agent_def.agent_type] = agent_def

    # 优先级 2：用户级 ~/.mewcode/agents/
    user_path = Path(USER_AGENTS_DIR).expanduser()
    for agent_def in self._scan_directory(user_path, "user"):
        if agent_def.agent_type not in seen:
            seen[agent_def.agent_type] = agent_def
    
    # 优先级 3：内置 builtins/
    for agent_def in self._load_builtins():
        if agent_def.agent_type not in seen:
            seen[agent_def.agent_type] = agent_def
    
    self._agents = seen
    return seen
```

**设计意图**：采用「就近覆盖」策略——项目级 > 用户级 > 内置。这意味着用户可以在项目目录下放一个同名的 `explore.md` 来覆盖内置的 Explore Agent，实现**零代码定制**。

这与 Git 的配置系统（local > global > system）是同一设计哲学。

#### 热重载机制 — `get()`

```python
def get(self, agent_type: str) -> AgentDef | None:
    cached = self._agents.get(agent_type)
    if cached is None:
        return None
    
    # 从文件热重载
    if cached.file_path is not None and cached.file_path.exists():
        try:
            reloaded = parse_agent_file(cached.file_path)
            reloaded.source = cached.source
            self._agents[agent_type] = reloaded
            return reloaded
        except AgentParseError as e:
            log.warning("Hot reload failed for %s, using cached: %s", agent_type, e)
    return cached
```

**设计亮点**：每次 `get()` 时都尝试从磁盘重新读取文件，实现了**无感热重载**。用户修改 `.mewcode/agents/explore.md` 后无需重启 MewCode，下次调用该 Agent 时自动生效。解析失败时优雅降级到缓存版本。

---

### 3.3 子 Agent 的 Fork 机制（`fork.py`）

**文件**：`mewcode/agents/fork.py`
**职责**：从父对话的上下文中 fork 出一个独立的子对话

#### 核心函数 — `build_forked_messages()`

执行流程：

1. **防递归检查**：遍历父对话历史，如果发现 `<fork_boilerplate>` 标记，说明父对话本身就是 fork 出来的，抛出 `ForkError` 阻止嵌套 fork
   ```python
   for msg in conversation.history:
       if FORK_BOILERPLATE_TAG in msg.content:
           raise ForkError("Cannot fork from a forked agent.")
   ```

2. **深拷贝对话历史**：`copy.deepcopy(conversation.history)` — 子 Agent 继承父对话的完整上下文，但修改互不影响

3. **修复悬挂的 tool_use**：如果父对话最后一条消息是 assistant 发出的 tool_use 但还没有 tool_result，子 Agent 的 LLM 会因 API 格式要求报错。这里自动填充 `"interrupted"` 占位符

4. **注入 Fork 指令**：
   ```python
   fork_conv.add_user_message(f"{FORK_BOILERPLATE}\n\n你的任务：\n{task}")
   ```
   其中 `FORK_BOILERPLATE` 是一段硬编码的规则，告诉子 Agent：
   - 不能再 Fork
   - 不要提问、不要请求确认
   - 直接用工具干活
   - 最终报告控制在 500 字以内

**设计意图**：Fork 的核心价值是**上下文继承**。比如用户说「帮我重构这个模块」，主 Agent 已经搜索了代码、理解了架构，此时 fork 出的子 Agent 天然拥有这些上下文，不需要重新探索。

**与 Claude Code 的对比**：Claude Code 的子 Agent 总是从空白上下文开始（通过 Task 工具），MewCode 的 fork 模式则允许继承对话历史，这是一个差异化设计。

---

### 3.4 任务管理（`task_manager.py`）

**文件**：`mewcode/agents/task_manager.py`
**职责**：管理后台子 Agent 的完整生命周期——启动、重试、超时、取消、恢复

#### 核心数据模型 — `BackgroundTask`

```python
@dataclass
class BackgroundTask:
    id: str                        # 任务唯一 ID
    name: str                      # 展示名称
    agent: Agent                   # 绑定的 Agent 实例
    task: str                      # 任务描述
    status: str                    # "running" / "completed" / "failed" / "cancelled"
    result: str                    # 执行结果
    start_time: float              # 开始时间
    end_time: float | None         # 结束时间
    cancel: Callable[[], None]     # 取消回调
    progress: ProgressInfo         # 进度信息（token 用量、工具调用次数）
    run_id: str                    # 持久化 Run ID
    attempt: int                   # 当前重试次数
    max_attempts: int              # 最大重试次数
    timeout_seconds: float | None  # 超时时间
```

#### 任务启动 — `launch()`

```python
def launch(self, agent, task, name="", fork_conversation=None, *,
           max_attempts=1, timeout_seconds=None) -> str:
    task_id = uuid.uuid4().hex[:8]
    bg = BackgroundTask(...)
    self._tasks[task_id] = bg
    
    # 持久化到 RunStore（支持进程重启后恢复）
    run = AgentRun(id=task_id, task=task, status=RunStatus.RUNNING, ...)
    self.store.save(run)
    self.store.append_event(task_id, "run_created", run.to_dict())
    
    # 创建 asyncio 后台任务
    async_task = asyncio.create_task(self._run_background(task_id, fork_conversation))
    bg.cancel = async_task.cancel
    return task_id
```

**设计亮点**：
- **事件溯源（Event Sourcing）**：每个状态变化都通过 `store.append_event()` 追加事件记录，支持完整的历史回溯和断点恢复
- **返回 task_id 而非阻塞等待**：主 Agent 拿到 ID 后立即继续工作，实现异步解耦

#### 重试与超时 — `_run_background()`

```python
async def _run_background(self, task_id, fork_conversation=None):
    while bg.attempt < bg.max_attempts:
        bg.attempt += 1
        try:
            if bg.timeout_seconds and bg.timeout_seconds > 0:
                result = await asyncio.wait_for(coro, timeout=bg.timeout_seconds)
            else:
                result = await coro
        except asyncio.TimeoutError:
            if bg.attempt >= bg.max_attempts:
                raise RuntimeError(run.error)
            continue  # 重试
        except Exception as exc:
            if bg.attempt >= bg.max_attempts:
                raise
            await asyncio.sleep(min(2 ** (bg.attempt - 1), 8))  # 指数退避
            continue
        # 成功 → break
```

**设计模式**：经典的 **Retry with Exponential Backoff** 模式。退避上限 8 秒（`min(2^(attempt-1), 8)`），避免长时间阻塞。

#### 进程恢复 — `recover()`

```python
def recover(self, agent_factory: Callable[[AgentRun], Agent]) -> list[str]:
    recovered: list[str] = []
    for run in self.store.list_runs():
        if run.status not in {RunStatus.PENDING, RunStatus.RUNNING}:
            continue
        agent = agent_factory(run)
        bg = BackgroundTask(...)
        self._tasks[run.id] = bg
        task = asyncio.create_task(self._run_background(run.id))
        recovered.append(run.id)
    return recovered
```

**设计意图**：进程崩溃重启后，能从 `RunStore` 中恢复未完成的后台任务。`agent_factory` 回调让调用方决定如何重建 Agent 实例（因为 Agent 的创建依赖应用上下文）。这是 **持久化 + 恢复** 的经典模式。

#### 团队协作集成

任务完成后，如果 Agent 属于某个团队，会：
1. 通过 Mailbox 向 lead 发送 `[idle]` 消息
2. 进入 60 秒的「待命轮询」循环，检查是否有新消息分配后续任务

这是 Agent 从「一次性执行」到「持续协作」的关键设计。

---

### 3.5 追踪机制（`trace.py`）

**文件**：`mewcode/agents/trace.py`
**职责**：维护 Agent 调用链的树形追踪结构

#### 数据模型 — `TraceNode`

```python
@dataclass
class TraceNode:
    agent_id: str           # 唯一标识
    parent_id: str | None   # 父 Agent ID（形成树形结构）
    trace_id: str           # 追踪链 ID（同一棵树下共享）
    agent_type: str         # Agent 类型
    input_tokens: int       # 输入 token 统计
    output_tokens: int      # 输出 token 统计
    tool_call_count: int    # 工具调用次数
    start_time: float       # 开始时间
    end_time: float | None  # 结束时间
    status: str             # "running" / "completed" / "failed"
```

**设计意图**：用 `trace_id` + `parent_id` 构建一棵调用树。当主 Agent fork 出子 Agent，子 Agent 又 fork 出孙 Agent 时（虽然 fork 模式禁止嵌套，但预设类型的子 Agent 理论上可以），所有节点共享同一个 `trace_id`，通过 `parent_id` 形成层级关系。

#### 核心方法

| 方法 | 作用 |
|------|------|
| `create()` | 创建追踪节点，自动生成 `agent_id`，可选继承 `trace_id` |
| `update()` | 更新节点的 token 用量等指标（通用 `**kwargs` 设计） |
| `complete()` | 标记节点完成 |
| `get_tree()` | 获取同一 `trace_id` 下所有节点（快照整棵调用树） |
| `get_total_tokens()` | 汇总整棵树的 token 消耗 |
| `complete_all_running()` | 批量结束某父节点下所有运行中的子节点（清理用） |

---

### 3.6 工具过滤机制（`tool_filter.py`）

**文件**：`mewcode/agents/tool_filter.py`
**职责**：按角色和场景层层过滤子 Agent 可用的工具集

#### 五层过滤管道 — `resolve_agent_tools()`

```
所有工具
  │
  ├─ 第 0 层：MCP 工具始终放行（不受后续过滤影响）
  │
  ├─ 第 1 层：全局禁用（Agent、TaskOutput、AskUserQuestion、Workflow 等）
  │     ↓
  ├─ 第 2 层：自定义 Agent 额外限制（source 为 project/user/plugin 时）
  │     ↓
  ├─ 第 3 层：后台任务白名单（只保留 ReadFile/Bash/EditFile 等基础工具）
  │     ↓
  ├─ 第 4 层：Agent 定义中的 disallowed_tools 黑名单
  │     ↓
  ├─ 第 5 层：Agent 定义中的 tools 白名单
  │
  ↓
最终工具集
```

**关键设计决策**：

1. **MCP 工具豁免**：外部 MCP 服务器提供的工具不受过滤限制，因为它们是用户显式集成的外部能力
   ```python
   mcp_tools = {name: tool for name, tool in all_tools.items() if _is_mcp_tool(name)}
   ```

2. **全局禁用 `Agent` 工具**：子 Agent 默认不能再 fork 子 Agent（防止递归失控），`ALL_AGENT_DISALLOWED_TOOLS` 中明确包含 `"Agent"`

3. **白名单 vs 黑名单的混用**：
   - 后台任务用**白名单** `ASYNC_AGENT_ALLOWED_TOOLS`（安全优先，只放行已知安全工具）
   - 普通子 Agent 用**黑名单** `disallowed_tools`（灵活优先，默认全开）

#### 团队成员工具构建 — `build_teammate_tools()`

团队成员除了基础工具外，还额外注入协调工具：
```python
coordination_tools = [
    TaskCreateTool(...),   # 创建团队任务
    TaskGetTool(...),      # 查询任务
    TaskListTool(...),     # 列出任务
    TaskUpdateTool(...),   # 更新任务状态
    SendMessageTool(...),  # 发送消息给队友
]
```

#### Coordinator 模式 — `apply_coordinator_filter()`

协调者（Team Lead）只保留管理工具：
```python
COORDINATOR_MODE_ALLOWED_TOOLS = frozenset({
    "Agent",          # 派发子 Agent
    "TaskStop",       # 停止任务
    "SendMessage",    # 发送消息
    "SyntheticOutput", # 合成输出
    "TeamCreate",     # 创建团队
    "TeamDelete",     # 删除团队
})
```

**设计意图**：Coordinator 不亲自干活，只负责调度和协调。这是经典的 **Manager-Worker 模式**。

---

### 3.7 通知机制（`notification.py`）

**文件**：`mewcode/agents/notification.py`
**职责**：将后台任务的完成结果格式化为通知，注入主 Agent 的对话流

#### 通知格式 — `format_task_notification()`

```xml
<task-notification>
Task ID: a1b2c3d4
Agent: Explore
Status: completed
Elapsed: 12.3s
Tokens: input=15000, output=3200
Result:
Scope: 搜索用户认证模块的实现
Result: 完成
Key files: src/auth/login.py, src/auth/session.py
Files changed: None
Issues: None
</task-notification>
```

#### 注入机制 — `inject_task_notifications()`

```python
def inject_task_notifications(
    conversation: ConversationManager,
    completed_tasks: list[BackgroundTask],
) -> None:
    for task in completed_tasks:
        notification = format_task_notification(task)
        conversation.add_user_message(notification)
```

**设计意图**：通知以 `user message` 的形式注入对话，LLM 会自然地将其视为系统反馈并做出响应。用 XML 标签 `<task-notification>` 包裹是为了让 LLM 清晰区分通知内容和用户指令。

**与主循环的集成**：在 `agent.py` 的主循环中，每轮迭代开始时检查通知：
```python
if self.notification_fn:
    for note in self.notification_fn():
        conversation.add_system_reminder(note)
```

---

## 4. 内置 Agent 设计

### 4.1 Explore — 只读搜索专家

```yaml
name: Explore
model: haiku        # 使用轻量模型（搜索任务不需要强推理）
maxTurns: 30        # 搜索可能涉及大量文件，给足轮数
disallowedTools: [Agent, EditFile, WriteFile, NotebookEdit, EnterPlanMode, ExitPlanMode]
```

**设计意图**：用 `haiku`（最便宜最快）做搜索，是成本优化的体现。禁用所有写入工具，确保**只读安全**。

### 4.2 Plan — 架构规划师

```yaml
name: Plan
disallowedTools: [Agent, EditFile, WriteFile, NotebookEdit]
maxTurns: 15        # 规划不需要太多轮
```

**设计意图**：同样是只读，但 Plan 的输出是**结构化的实现计划**而非搜索结果。要求列出 3-5 个关键文件路径，为后续执行提供明确指引。

### 4.3 Verification — 验证专家

```yaml
name: Verification
background: true     # 后台运行（验证可能很耗时）
model: inherit       # 继承父模型（验证需要强推理能力）
```

**设计意图**：最有意思的 Agent——它的 system prompt 直接点出了 LLM 的两个已知失败模式：
1. **验证回避**：找理由不去实际运行验证
2. **被前 80% 迷惑**：看到漂亮的表面就放行

强制要求「读代码不算验证，必须运行它」，输出 `VERDICT: PASS/FAIL/PARTIAL` 的标准化判定。默认不加载（需要 `enable_verification: true` 配置）。

### 4.4 general-purpose — 通用工人

```yaml
name: general-purpose
disallowedTools: []  # 无限制，拥有全部工具
```

**设计意图**：当任务需要完整能力（读写文件、执行命令等）但需要独立上下文时使用。是「全栈工人」角色。

---

## 5. 端到端调用流程

以用户说「帮我探索一下认证模块的实现」为例：

```
1. 用户输入 → 主 Agent 对话循环 (agent.py:run)
   ↓
2. 主 Agent 决定调用 Agent 工具
   → LLM 输出 tool_call: Agent(prompt="探索认证模块", subagent_type="Explore")
   ↓
3. AgentTool.execute() 被调用 (agent_tool.py)
   ├─ agent_loader.get("Explore") → 获取 Explore AgentDef
   ├─ resolve_agent_tools() → 过滤工具集（只读工具）
   ├─ _select_llm() → 选择 haiku 模型
   ├─ 创建子 Agent 实例
   └─ trace_manager.create() → 创建追踪节点
   ↓
4a. 前台模式: sub_agent.run_to_completion() → 同步等待结果
4b. 后台模式: task_manager.launch() → 返回 task_id，异步执行
   ↓
5. 子 Agent 执行对话循环
   ├─ 使用 ReadFile/Grep/Glob 搜索代码
   ├─ 达到 max_turns 或无更多 tool_call 时结束
   └─ 返回结果文本
   ↓
6. 结果回传
   ├─ 前台：直接作为 ToolResult 返回给主 Agent
   └─ 后台：task_manager 通知 → notification 注入主对话
   ↓
7. trace_manager.complete() → 标记追踪节点完成
   ↓
8. 主 Agent 将结果转述给用户
```

---

## 6. 设计模式与亮点总结

### 架构模式

| 模式 | 体现 | 优势 |
|------|------|------|
| **策略模式** | `AgentDef` 统一描述不同角色的 Agent | 新增 Agent 类型只需添加一个 .md 文件 |
| **管道-过滤器** | `tool_filter.py` 的五层过滤管道 | 安全策略分层清晰，易扩展 |
| **观察者模式** | `notification.py` 异步通知主 Agent | 后台任务与主循环解耦 |
| **事件溯源** | `TaskManager` 的 `RunStore` + `append_event` | 支持断点恢复和历史审计 |
| **模板方法** | `run_to_completion()` 是 `run()` 的简化版 | 子 Agent 跳过交互式权限确认 |

### 值得学习的设计决策

1. **Markdown-as-Configuration**：用 YAML frontmatter + Markdown 定义 Agent，兼顾机器解析和人类可读。非技术用户也能修改 Agent 的提示词

2. **三级优先级覆盖**：项目 > 用户 > 内置，允许零代码定制。这是 Git/VS Code 等工具验证过的成熟模式

3. **热重载**：`get()` 时重新读取文件，修改 Agent 定义无需重启。开发体验极佳

4. **防递归 Fork**：通过检测 `<fork_boilerplate>` 标签阻止嵌套 fork，简单而有效

5. **MCP 工具豁免**：外部集成工具不受内部过滤策略影响，保持了扩展性的底线

6. **悬挂 tool_use 修复**：fork 时自动为未完成的 tool_use 填充占位 result，避免 API 格式错误——这是一个容易被忽视但至关重要的细节

7. **指数退避重试**：后台任务失败时 `min(2^(attempt-1), 8)` 秒后重试，兼顾恢复速度和资源节约

8. **Token 追踪树**：`TraceManager` 不仅追踪状态，还汇总整棵调用树的 token 消耗，为成本管控提供数据支撑

---

## 7. 模块关联图

```
agents/parser.py ─── 被 agents/loader.py 调用
       ↑
       ├── 被 tools/agent_tool.py 直接引用（构造 AgentDef）
       │
agents/loader.py ─── 被 app.py 初始化
       ↑                 ↓ 注入 Agent 目录到
       │            agent.py (set_agent_catalog)
       │
agents/fork.py ──── 被 tools/agent_tool.py 调用
       ↑
agents/tool_filter.py ──── 被 tools/agent_tool.py 调用
       ↑
agents/task_manager.py ─── 被 tools/agent_tool.py 启动
       ↑                    ↓ 完成后通知
       │              agents/notification.py
       │
agents/trace.py ──── 被 tools/agent_tool.py 注册节点
```

---

## 核心哲学

这套系统的核心哲学是：

> **用配置（.md 文件）代替代码来定义 Agent 行为，用分层过滤代替硬编码来实现安全隔离，用事件溯源代替内存状态来保证可靠性。**

这三个原则使得整个子 Agent 系统既灵活又安全，既强大又可控。
