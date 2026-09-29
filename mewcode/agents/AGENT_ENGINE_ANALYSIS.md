# MewCode 主 Agent 引擎（`agent.py`）深度解析

## 一、定位与核心地位

**`agent.py` 是 MewCode 项目的心脏**，实现了 AI Agent 的「思考-行动-观察」循环（Agent Loop）。整个项目的所有能力——工具调用、权限控制、上下文压缩、记忆提取、子 Agent 协作——都通过 Agent 引擎串联起来。

```
┌─────────────────────────────────────────────────────────────────┐
│                        UI 层 (TUI/Web)                          │
│                    消费 AgentEvent 事件流                         │
└──────────────────────────┬──────────────────────────────────────┘
                           │ async for event in agent.run()
┌──────────────────────────▼──────────────────────────────────────┐
│                    agent.py — Agent 引擎                         │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐           │
│  │ LLMClient│ │ToolRegist│ │PermissChk│ │  Memory  │           │
│  │(client.py)│ │(tools/)  │ │(perms/)  │ │(memory/) │           │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘           │
│  ┌──────────────────┐  ┌──────────────────┐                     │
│  │ ConversationMgr  │  │  Context Manager  │                     │
│  │(conversation.py) │  │ (context/mgr.py)  │                     │
│  └──────────────────┘  └──────────────────┘                     │
└─────────────────────────────────────────────────────────────────┘
```

---

## 二、事件驱动架构：Agent 如何与 UI 通信

### 设计思想

Agent 引擎采用**事件驱动 + 异步生成器**模式。`run()` 方法是一个 `AsyncIterator[AgentEvent]`，通过 `yield` 把事件逐个推送给 UI 层。这种设计有几个关键优势：

1. **解耦**：Agent 核心不关心 UI 怎么展示，只管产出事件
2. **实时性**：LLM 流式输出的每个文字片段都能立即推送给 UI
3. **可组合**：事件流可以自然地被 `async for` 消费

### 事件类型体系

```python
AgentEvent = (
    StreamText           # LLM 正在生成文字（流式）
    | ThinkingText       # LLM 的思考过程（扩展思考模式）
    | RetryEvent         # 输出被截断，正在重试
    | ToolUseEvent       # LLM 请求调用工具
    | ToolResultEvent    # 工具执行完毕
    | TurnComplete       # 一轮结束
    | LoopComplete       # 整个循环结束
    | UsageEvent         # Token 用量统计
    | ErrorEvent         # 不可恢复的错误
    | PermissionRequest  # 需要用户确认权限
    | CompactNotification# 上下文压缩通知
    | HookEvent          # Hook 生命周期通知
)
```

> **设计亮点**：`PermissionRequest` 内嵌了一个 `asyncio.Future`，这是整个系统最巧妙的地方——Agent 通过 Future 实现**异步暂停等待用户输入**，而不需要阻塞整个事件循环。

---

## 三、对话循环（Agent Loop）完整流程

### 3.1 核心流程图

```
                    ┌─────────────────────┐
                    │   初始化阶段          │
                    │ 注入环境信息 + 记忆    │
                    │ 触发 session_start    │
                    └─────────┬───────────┘
                              │
                    ┌─────────▼───────────┐
              ┌────►│  迭代计数 +1         │
              │     │  检查最大迭代次数     │
              │     └─────────┬───────────┘
              │               │
              │     ┌─────────▼───────────┐
              │     │ 消费团队邮箱消息       │
              │     │ 添加外部通知          │
              │     └─────────┬───────────┘
              │               │
              │     ┌─────────▼───────────┐
              │     │ 自动压缩上下文        │◄── 接近 token 上限时触发
              │     │ (auto_compact)       │
              │     └─────────┬───────────┘
              │               │
              │     ┌─────────▼───────────┐
              │     │ 构建 System Prompt   │
              │     │ 获取工具 Schema       │
              │     └─────────┬───────────┘
              │               │
              │     ┌─────────▼───────────┐
              │     │ 应用工具结果预算       │◄── 截断/落盘过大的工具输出
              │     └─────────┬───────────┘
              │               │
              │     ┌─────────▼───────────┐
              │     │ 调用 LLM (流式)      │
              │     │ StreamCollector 收集  │
              │     └─────────┬───────────┘
              │               │
              │     ┌─────────▼───────────┐
              │     │ 处理 max_tokens 截断  │◄── 提升输出上限 / 恢复重试
              │     └─────────┬───────────┘
              │               │
              │     ┌─────────▼───────────┐
              │     │ 有工具调用吗？        │
              │     └──┬─────────────┬────┘
              │     否  │             │ 是
              │        │    ┌────────▼──────────┐
              │        │    │ 加入对话历史        │
              │        │    │ 分批执行工具        │
              │        │    │ (权限检查+执行)     │
              │        │    │ 工具结果加入对话    │
              │        │    └────────┬──────────┘
              │        │             │
              │        │    ┌────────▼──────────┐
              │        │    │ 连续未知工具 >= 3?  │◄── 安全终止
              │        │    └──┬──────────┬─────┘
              │        │    否  │          │ 是 → ErrorEvent + break
              │        │       │          │
              │     ┌──▼───────▼──────────┐
              │     │  LoopComplete        │
              │     │  提取记忆 + Hook      │
              │     │  创建文件快照          │
              │     └─────────────────────┘
              │               │
              └───────────────┘  (回到循环顶部)
```

### 3.2 初始化阶段

```python
# 1. 注入环境信息（工作目录、技能目录、Agent 目录）
env_context = build_environment_context(
    self.work_dir, self.active_skills, self._skill_catalog, self._agent_catalog
)
conversation.inject_environment(env_context)

# 2. 注入长期记忆（用户指令 + 自动提取的记忆）
memory_content = self.memory_manager.load() if self.memory_manager else ""
conversation.inject_long_term_memory(self.instructions_content, memory_content)

# 3. 触发 session_start Hook
if self.hook_engine:
    ctx = self._build_hook_context("session_start")
    await self.hook_engine.run_hooks("session_start", ctx)
```

**设计意图**：环境信息和记忆被注入为对话历史的第一条 `user` 消息，这样 LLM 在每次请求中都能看到它们。

### 3.3 核心循环的退出条件

| 退出条件 | 触发事件 |
|---------|---------|
| 无工具调用（LLM 认为任务完成） | `LoopComplete` |
| 超过最大迭代次数 | `ErrorEvent` |
| 连续 3 次未知工具调用 | `ErrorEvent` |
| 调用了 ExitPlanMode 工具 | `TurnComplete` + `LoopComplete` |

---

## 四、工具调用：发起、执行和结果处理

### 4.1 工具调用的完整生命周期

```
LLM 流式输出
    │
    ▼
ToolCallStart ──► ToolCallDelta(×N) ──► ToolCallComplete
    │                                        │
    │ (StreamCollector 收集)                   │
    ▼                                        ▼
yield ToolUseEvent                   LLMResponse.tool_calls
  (给 UI 展示)                             │
                                    ┌──────▼──────┐
                                    │ 分批 (partition)│
                                    └──────┬──────┘
                                    ┌──────▼──────┐
                              ┌─────┤  批次类型？   ├─────┐
                              │     └─────────────┘     │
                         并发安全                   需要串行
                              │                        │
                    ┌─────────▼─────────┐    ┌────────▼────────┐
                    │ _execute_batch_   │    │ _execute_tool() │
                    │ parallel()        │    │ (逐个执行)        │
                    │ (asyncio.gather)  │    │                  │
                    └─────────┬─────────┘    └────────┬────────┘
                              │                        │
                              └────────┬───────────────┘
                                       ▼
                              ToolResultBlock 加入对话历史
                                       │
                                       ▼
                              yield ToolResultEvent (给 UI)
```

### 4.2 分批策略：`partition_tool_calls`

LLM 可能一次返回多个工具调用（比如同时读取 5 个文件），这些读取操作互不依赖，可以并行执行。

```python
def partition_tool_calls(tool_calls, registry) -> list[ToolBatch]:
    batches = []
    for tc in tool_calls:
        tool = registry.get(tc.tool_name)
        safe = tool.is_concurrency_safe and registry.is_enabled(tc.tool_name)
        
        if safe and batches and batches[-1].concurrent:
            batches[-1].calls.append(tc)  # 合并到上一个并行批次
        else:
            batches.append(ToolBatch(concurrent=safe, calls=[tc]))
    return batches
```

**关键规则**：只有**相邻的**并发安全工具才会合并到一个批次。一旦遇到不安全工具，就会"断开"批次。这保证了执行顺序的语义正确性。

> **对比 Claude Code**：Claude Code 也有类似的并行工具执行优化，但 MewCode 的实现更简洁——通过 `Tool.is_concurrency_safe` 属性声明，而不是硬编码工具名列表。

### 4.3 工具执行的两条路径

| 路径 | 适用场景 | 权限检查 | 执行方式 |
|------|---------|---------|---------|
| **并行路径** | `is_concurrency_safe` 的只读工具 | 跳过 | `asyncio.gather` 并发 |
| **串行路径** | 需要写权限的工具 | 完整检查流程 | 逐个执行，可 yield `PermissionRequest` |

### 4.4 工具输出处理：`_maybe_persist_or_truncate`

工具输出可能非常长（比如读取一个大文件），需要分级处理：

```
输出长度
    │
    ├── > 50,000 字符 → 保存到磁盘文件，对话中只留 2KB 预览 + 文件路径
    │
    ├── > 10,000 字符 → 直接截断，添加 "… (output truncated)"
    │
    └── ≤ 10,000 字符 → 原样保留
```

---

## 五、权限确认的完整流程

### 五层安全防线

```
工具调用请求
    │
    ▼
┌─ Layer 0: Plan 模式例外 ────────────────────────┐
│ Plan 模式下白名单工具/写规划文件 → allow          │
└──────────────────────────┬──────────────────────┘
                           │
┌─ Layer 1: 安全只读命令 ──────────────────────────┐
│ command 类 + 命中安全命令列表 (ls/git status/...)   │
│ → allow                                           │
└──────────────────────────┬──────────────────────┘
                           │
┌─ Layer 1b: 危险命令黑名单 ───────────────────────┐
│ command 类 + 命中危险检测 (rm -rf /...)             │
│ → deny                                            │
└──────────────────────────┬──────────────────────┘
                           │
┌─ Layer 2: 路径沙箱 ─────────────────────────────┐
│ read/write 类 + 路径越出项目目录 → deny            │
└──────────────────────────┬──────────────────────┘
                           │
┌─ Layer 3: 规则引擎 ─────────────────────────────┐
│ 用户自定义规则匹配 (如 "allow git*" / "deny *.env")│
│ → allow / deny (命中即返回)                       │
└──────────────────────────┬──────────────────────┘
                           │
┌─ Layer 4: 权限模式兜底 ─────────────────────────┐
│ bypass → allow | default+read → allow             │
│ default+write → ask                               │
└──────────────────────────┬──────────────────────┘
                           │
┌─ Layer 5: 人工确认 (HITL) ──────────────────────┐
│ → ask（弹出对话框让用户选择）                      │
└─────────────────────────────────────────────────┘
```

### 用户交互的异步实现

当权限检查返回 `ask` 时，Agent 通过 `asyncio.Future` 实现异步等待：

```python
# 1. yield 权限请求给 UI（UI 展示对话框）
yield PermissionRequest(
    tool_name=tc.tool_name,
    description=desc,
    future=future,  # ← Future 在这里！
)

# 2. 异步等待用户决定（不阻塞事件循环！）
response = await future

# 3. 根据用户决定执行
if response == ALLOW_ALWAYS:
    # 写入本地规则，以后不再询问
    self.permission_checker.rule_engine.append_local_rule(...)
```

> **设计亮点**：`Future` 模式让 Agent 的事件循环不会被阻塞。在等待用户决定期间，UI 仍然可以响应其他事件。`ALLOW_ALWAYS` 选项会自动写入规则引擎，后续同类操作不再打扰用户。

---

## 六、上下文管理与压缩机制

### 6.1 Token 估算：锚点 + 增量

```python
def current_tokens(self) -> int:
    if self.baseline_tokens <= 0:
        # 冷启动：纯字符估算（字符数 / 3.5）
        return estimate_tokens(self.history)
    # 有锚点：真实用量 + 仅对锚点之后的新消息做字符估算
    tail = self.history[self.anchor_count:]
    return self.baseline_tokens + estimate_tokens(tail)
```

每次 LLM API 返回响应时记录真实 token 用量（`record_usage_anchor`），之后只对新增消息做粗略估算，避免全量计算。

### 6.2 Layer 1：工具结果预算控制

`apply_tool_result_budget()` 采用**三趟扫描**策略：

```
Pass 1: 单条超限检查
  │  单条工具结果 > 50,000 字符？
  │  → 落盘为文件，对话中换成 2KB 预览
  ▼
Pass 2: 聚合超限检查
  │  同一条消息内所有结果加起来 > 200,000 字符？
  │  → 从大到小逐个落盘，直到总量回到限制内
  ▼
Pass 3: 旧结果裁剪
  │  超过最近 10 轮的旧工具结果？
  │  → 裁剪为 "<snipped>" + 200 字符预览
  ▼
返回「瘦身版副本」+ 替换记录
```

**关键设计决策**：这个函数**不修改原对象**，而是返回一个全新的 `ConversationManager` 副本，避免副作用。

### 6.3 Layer 2：全对话自动压缩（Auto-Compact）

```
对话历史: [msg1, msg2, ..., msgN]
                    │
                    ▼
        ┌─── 计算保留窗口 ───┐
        │  从尾部向前遍历      │
        │  保留 ≥ 10,000 tokens│
        │  或 ≥ 5 条消息       │
        │  但不超过 40,000 tok │
        └─────────┬─────────┘
                  │
    ┌─────────────▼─────────────┐
    │  前缀 (to_summarize)       │  →  交给 LLM 生成结构化摘要
    │  尾部 (keep_tail)          │  →  原样保留
    └─────────┬─────────────────┘
              │
    ┌─────────▼─────────────────┐
    │  重建对话 = 摘要 + 尾部     │
    │  + 恢复附件（文件快照等）    │
    │  清空 token 锚点            │
    └───────────────────────────┘
```

**压缩后的恢复机制**（`RecoveryState`）：压缩会清空大部分历史，但 Agent 需要"记住"之前读过哪些文件。`RecoveryState` 保存了最近读取的 **5 个文件**内容、已激活的**技能 SOP** 正文、当前可用**工具列表**，让 LLM 在压缩后仍有足够的工作上下文。

**熔断器保护**：连续 3 次压缩失败后自动熔断，避免无限重试。

---

## 七、System Prompt 的构建过程

System Prompt 采用**分段优先级**构建模式：

```python
def build_system_prompt(...) -> str:
    b = PromptBuilder()
    b.add(IDENTITY_SECTION)          # priority=0:  身份 + 安全约束
    b.add(SYSTEM_SECTION)            # priority=10: 系统行为规则
    b.add(DOING_TASKS_SECTION)       # priority=20: 任务执行准则
    b.add(EXECUTING_ACTIONS_SECTION) # priority=30: 操作审慎原则
    b.add(USING_TOOLS_SECTION)       # priority=40: 工具使用指南
    b.add(TONE_STYLE_SECTION)        # priority=50: 语气风格
    b.add(TEXT_OUTPUT_SECTION)       # priority=60: 文本输出规范
    b.add(environment_section())     # priority=70: 环境信息
    # 可选段落
    b.add(PlanMode)                  # priority=85: Plan 模式指令
    b.add(CustomInstructions)        # priority=80: 用户自定义指令
    b.add(Skills)                    # priority=90: 技能内容
    b.add(Memory)                    # priority=95: 记忆内容
    return b.build()
```

优先级数字越小越靠前，确保核心身份描述在最前面（LLM 对 prompt 开头的内容注意力更高）。

除了 System Prompt，还有**对话内注入**的信息：
- **环境上下文**（`build_environment_context`）：工作目录、操作系统、技能目录
- **长期记忆**（`inject_long_term_memory`）：用户指令 + 自动提取的记忆 + 当前日期

---

## 八、与子 Agent 系统的交互

### 两种运行模式

| 特性 | `run()` (交互模式) | `run_to_completion()` (非交互模式) |
|------|-------------------|-----------------------------------|
| 用途 | 主 Agent，面向用户 | 子 Agent，后台执行 |
| 事件处理 | yield 事件流给 UI | 不产生事件流，直接返回文本 |
| 权限处理 | 弹出对话框询问用户 | 自动拒绝需要确认的操作 |
| 使用场景 | 用户直接对话 | Agent 工具派发子任务 |

### 团队协作机制

Agent 内建了团队协作支持：

```python
# Agent 的团队相关属性
self._agent_catalog: str = ""           # 可用子 Agent 目录
self.agent_id: str = uuid.uuid4().hex[:12]  # 唯一 ID
self.parent_id: str | None = None       # 父 Agent ID
self.coordinator_mode: bool = False     # 协调者模式
self.team_name: str = ""                # 所属团队
self._team_manager: Any = None          # 团队管理器
self.notification_fn: Callable | None   # 通知回调
```

**邮箱消费**（`_consume_mailbox`）：每轮迭代开始时，Agent 会检查团队邮箱，把其他 Agent 发来的消息注入对话历史：

```python
def _consume_mailbox(self, conversation):
    messages = mailbox.consume(self.agent_id)
    for msg in messages:
        prefix = f"[Message from {msg.from_agent}]"
        conversation.add_user_message(f"{prefix} {msg.content}")
```

这实现了一种**异步消息传递**的多 Agent 协作模式。

---

## 九、错误处理与恢复机制

### max_tokens 截断恢复（精妙设计）

```python
if response.stop_reason == "max_tokens":
    if not max_tokens_escalated:
        # 第一次截断：提升输出上限到 64K
        self.client.set_max_output_tokens(64000)
        max_tokens_escalated = True
        conversation.add_user_message(
            "Output token limit hit. Resume directly from where you stopped. "
            "Do not apologize or repeat previous content."
        )
        yield RetryEvent(reason="max_tokens escalation")
        continue
    elif output_recoveries < 3:
        # 后续截断：有限重试，要求 LLM 拆分工作
        output_recoveries += 1
        conversation.add_user_message(
            "...Break remaining work into smaller pieces."
        )
        continue
```

**设计亮点**：渐进式升级（先提升上限，再有限重试）+ 防止重复（提示词明确要求"不要道歉或重复"）+ 有界恢复（最多 3 次，防止无限循环）。

### 多层错误恢复策略总览

| 错误类型 | 处理方式 |
|---------|---------|
| max_tokens 截断 | 第一次提升上限到 64K，后续最多重试 3 次 |
| 未知工具调用 | 连续 3 次 → 终止 Agent |
| 工具执行异常 | 捕获异常 → 返回错误结果给 LLM，Agent 继续运行 |
| 参数验证失败 | ValidationError → 返回错误信息给 LLM |
| 权限被拒绝 | 返回 "Permission denied" 给 LLM 调整策略 |
| 压缩失败 | 熔断器保护（3 次后停止） |
| LLM API 错误 | 分类处理：AuthError 立即终止、RateLimit 带 retry_after、NetworkError 网络错误 |
| Hook 执行失败 | 记录通知，不阻断主流程 |
| 记忆提取失败 | 静默忽略（debug 日志） |

---

## 十、LLM 客户端的流式处理

### StreamCollector 的双重职责

```python
class StreamCollector:
    async def consume(self, stream) -> AsyncIterator[AgentEvent]:
        async for event in stream:
            if isinstance(event, TextDelta):
                self.response.text += event.text    # 累积给 Agent
                yield StreamText(text=event.text)   # 转发给 UI
            elif isinstance(event, ToolCallComplete):
                self.response.tool_calls.append(event)  # 记录工具调用
                yield ToolUseEvent(...)                 # 通知 UI
            elif isinstance(event, StreamEnd):
                self.response.stop_reason = event.stop_reason
                self.response.input_tokens = event.input_tokens
```

**双重职责**：一方面把碎片化的流式事件累积成完整的 `LLMResponse`（给 Agent 逻辑用），另一方面把事件实时转发给 UI（让用户看到打字效果）。

### 三种协议适配

```
LLMClient (抽象基类)
    │
    ├── AnthropicClient ──── Anthropic Messages API
    │   - 支持 thinking (扩展思考)
    │   - Prompt Cache (cache_control)
    │   - 流式事件：content_block_start/delta/stop
    │
    ├── OpenAIClient ─────── OpenAI Responses API
    │   - 较新的 /responses 端点
    │   - 流式事件：response.output_text.delta 等
    │
    └── OpenAICompatClient ── Chat Completions API
        - 兼容 vLLM/Ollama/Azure 等
        - 需要 tool schema 格式转换
        - 流式事件：choices[0].delta
```

### Prompt Cache 优化

Anthropic 客户端实现了 **Prompt Cache** 优化，通过在 system prompt、tool schema 和最后一条 user 消息上标记 `cache_control`，让 Anthropic 缓存这些稳定前缀。后续请求只要前缀不变，缓存命中的 token 只需支付 **10%** 的费用。

---

## 十一、Hook 生命周期

Agent 在关键时机触发 Hook，允许用户注入自定义逻辑：

```
session_start  →  会话开始
    │
    ├── turn_start  →  每轮迭代开始
    │       │
    │       ├── pre_send  →  发送给 LLM 前
    │       │
    │       ├── pre_tool_use  →  工具执行前（可拦截！）
    │       │
    │       ├── post_tool_use →  工具执行后
    │       │
    │       └── turn_end  →  每轮迭代结束
    │
    └── session_end  →  会话结束
```

`pre_tool_use` Hook 特别强大——它可以**拦截工具执行**，返回拒绝原因就能阻止工具运行。

---

## 十二、核心设计模式总结

| 设计模式 | 应用位置 | 解决的问题 |
|---------|---------|-----------|
| **事件驱动 + 异步生成器** | `run()` 方法 | Agent 与 UI 解耦，实时流式输出 |
| **策略模式** | `LLMClient` 三种实现 | 统一接口适配不同 LLM 协议 |
| **责任链模式** | `PermissionChecker` 五层裁决 | 多层安全检查，每层可独立返回 |
| **Future/Promise** | `PermissionRequest.future` | 异步等待用户输入，不阻塞事件循环 |
| **快照 + 增量估算** | `ConversationManager.current_tokens()` | 精确度与性能的平衡 |
| **熔断器模式** | `CompactCircuitBreaker` | 防止压缩失败导致的无限重试 |
| **不可变副本** | `apply_tool_result_budget()` | 避免副作用，提高可预测性 |
| **分段优先级构建** | `PromptBuilder` | System Prompt 模块化组装 |

> **核心哲学**：**用事件流串联一切，用分层防御保障安全，用渐进压缩突破上下文限制，用 Hook 机制保持可扩展性**。
