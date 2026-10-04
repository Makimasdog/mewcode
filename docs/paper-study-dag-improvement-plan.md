# MewCode `paper_study_DAG` 后续改进方案

> 目标：在已经能够完成 KMeans 论文复现的基础上，优先提升可靠性、可观测性和复用能力。
> 方案以“小步交付、每步可验收”为原则，不把项目改造成复杂的平台。

## 1. 现状判断

### 1.1 已经具备的能力

当前 `paper_study_DAG` 已形成一条可复现的固定流程：

```text
PaperSearch → PaperProtocol → PaperStudy → Verification
```

已有能力包括：

- DAG 依赖调度和阶段状态记录；
- 论文来源、协议和实验产物落盘；
- 协议 SHA-256 校验，防止下游使用被修改的协议；
- KMeans 的独立数值校验器，不把模型输出中的 `PASS` 当作证据；
- 断点续跑和历史运行事件记录；
- 本地 REST/SSE 接口和无前端构建依赖的轻量 Web 控制台；
- 已验证的 KMeans 流程：20 组实验、7 个边界用例、项目回归 `586 passed, 1 skipped`。

这意味着下一阶段的主线应是“把已有流程做稳、做易用”，而不是扩大 Agent 数量或引入重量级前端。

### 1.2 主要证据和改进切入点

| 领域 | 当前证据 | 影响 |
| --- | --- | --- |
| 运行恢复 | `mewcode/runtime/service.py::recover` 会把 `RUNNING` 任务改回 `PENDING` 后重新调度；恢复时没有单独的恢复状态和幂等保护 | 崩溃发生在边界时，可能重复执行或留下无法继续的任务 |
| 事件存储 | `mewcode/runtime/store.py::append_event` 每次追加都读取整个 JSONL，再取最后序号 | 事件增多后写入成本随日志长度增长；多进程时仅有进程内锁 |
| SSE 控制台 | `mewcode/runtime/http.py` 已提供 REST/SSE，但没有心跳、`Last-Event-ID` 和统一错误结构 | 浏览器断线、代理超时或从末尾序号开始订阅时体验不稳定 |
| 服务启动 | `mewcode/runtime/server.py` 构建 runtime 后直接启动 uvicorn，恢复动作没有明确绑定到应用启动生命周期 | 重启后未完成任务不能保证自动恢复 |
| 验证安全 | Verification 主要通过工具过滤和提示词约束只读；Bash 仍可能修改工作区 | 验证阶段存在污染实验输入或协议的边界 |
| Provider 配置 | `mewcode/config.py` 默认使用第一个 provider，模型选择不够显式 | 多模型或百炼配置出现问题时，诊断成本高 |
| Coordinator | Coordinator 与 DAG 的证据门、协议哈希、确定性审计尚未完全共用 | 两条分支的行为可能再次分叉，维护成本上升 |

## 2. 设计原则

1. **先保证可恢复，再增加能力**：任何新功能都不能牺牲已有 KMeans 复现的确定性。
2. **程序证据优先于模型声明**：来源、命令、退出码、哈希和数值结果由程序记录并校验。
3. **默认单机本地可用**：先支持 Windows/Linux 的单进程场景；多进程部署明确报出限制，不提前引入数据库集群。
4. **每个阶段都有可回归的最小验收**：代码、测试、CLI 和 Web 控制台保持同一套运行状态语义。
5. **保持安装简单**：优先使用现有 Python、FastAPI/uvicorn 可选依赖和标准库，不引入前端构建链。

## 3. 分阶段路线

### P0：运行可靠性（建议第一迭代）

#### P0.1 修复 Runtime 恢复状态机

**方案**

- 增加明确的恢复事件和状态转换：`RUNNING → RECOVERING → PENDING/RUNNING`；若已达到 `max_attempts`，直接落为 `FAILED` 并记录原因。
- 为每个恢复动作设置幂等键，避免同一 `run_id` 被重复加入 `_tasks`。
- 恢复前保存上次 attempt、开始时间和恢复时间；恢复后由新的 attempt 规则决定是否重试。
- 将 `recover()` 接入 FastAPI/uvicorn startup 生命周期，并提供显式的关闭处理。

**收益**：进程重启后不会出现“任务既未完成又无法继续”的状态，恢复行为可以审计。

**改动范围**：`mewcode/runtime/service.py`、`mewcode/runtime/server.py`、`tests/test_recovery.py`、`tests/test_runtime.py`。

**成本/风险**：中等；需要统一旧事件与新状态的兼容读取。不要改变已完成任务的历史状态。

**验收标准**

- 模拟 `RUNNING` 任务重启后能继续或明确失败；
- `attempt == max_attempts` 时不会卡在 `PENDING`；
- 同一运行重复调用 `recover()` 不会创建两个执行任务；
- 现有运行时回归测试全部通过。

#### P0.2 让事件存储可持续运行

**方案**

- 在 `RunStore` 内维护每个运行的最后序号缓存，正常追加不再读取整个文件；进程启动时只扫描一次末尾有效事件。
- 对损坏行保留跳过策略，但增加损坏计数和诊断事件，避免静默丢失线索。
- 增加事件日志大小阈值和归档策略（例如按运行完成后归档，默认不删除）。
- 文档明确当前存储为单进程本地模式；若要支持多进程，再引入文件锁或 SQLite，而不是继续扩大 JSONL 锁的职责。

**收益**：长时间运行的 Agent 不会因事件数量增加而持续变慢，故障更容易定位。

**改动范围**：`mewcode/runtime/store.py`、`tests/test_runtime.py`，可新增 `tests/test_runtime_store.py`。

**验收标准**

- 追加 10,000 个事件的耗时不随事件数量呈平方级增长；
- 并发线程追加后序号唯一且连续；
- 含损坏行的日志仍可读取有效事件，并生成可见诊断。

#### P0.3 保护论文复现输入和结果

**方案**

- 将 `source.json`、`contract.md`、`protocol.md`、输入数据和 checker 的 SHA-256 统一写入检查点。
- Verification 执行前后分别计算工作区快照；发现协议、输入或 checker 被修改时立即失败。
- 将命令、工作目录、退出码、stdout/stderr 截断规则写入 `execution.json`，避免只依赖自然语言报告。

**收益**：复现结果可以解释、复核和重新运行，减少“模型说通过但证据不完整”的问题。

**改动范围**：`mewcode/paper_workflow.py`、`mewcode/paper_audit.py`、`tests/test_paper_workflow.py`。

**验收标准**：任一受保护文件被修改时，续跑和最终验证均拒绝；正常 KMeans 复现结果不变。

### P1：控制台和交付体验（第二迭代）

#### P1.1 可靠 SSE 和健康检查

**方案**

- 增加 `GET /health`，返回存储目录、运行时状态和版本信息。
- 支持 `Last-Event-ID` 和 `after` 二选一的续传语义；超过末尾时先返回当前快照，再进入等待。
- 每 15～30 秒发送 SSE 注释心跳；客户端断线后按最后序号重连。
- 统一错误结构：`{"error": {"code", "message", "run_id"}}`，控制台显示可读信息。

**验收标准**：浏览器刷新或短暂断网后不会丢失事件；健康检查可用于本地脚本和 CI。

#### P1.2 保持轻量的 Web 控制台升级

- 增加状态筛选、关键词筛选和分页；
- 展示阶段、最近错误、attempt、协议/结果哈希和命令退出码；
- 增加“复制运行 ID”和“导出运行 JSON”按钮；
- 本地模式可选 Token 鉴权，默认仍只监听 `127.0.0.1`；
- 所有新功能继续使用内嵌 HTML/原生 JS，暂不引入 React/Vite。

**改动范围**：`mewcode/runtime/http.py`、`tests/test_http.py`。

#### P1.3 清晰的命令入口和配置示例

- 增加 `mewcode paper run --paper kmeans [--output ...] [--resume]` 的稳定入口，保留现有模块命令兼容性；
- 提供 `.env.example`，只包含变量名，不包含任何真实密钥；
- 增加百炼 OpenAI 兼容协议的最小配置和 Windows PowerShell 安装/启动示例；
- 配置加载失败时指出 provider、protocol、model 和缺失环境变量。

## 4. P2：Coordinator 与 DAG 融合（第三迭代）

### 4.1 抽取通用论文工作流内核

新增小型内部接口（名称可调整）：

```text
PaperWorkflow
├── SourceEvidence
├── ProtocolContract
├── ImplementationArtifact
├── DeterministicVerification
└── ArtifactManifest
```

DAG 和 Coordinator 都调用这套接口，复用：

- 证据门：没有来源和算法证据时阻止下游；
- 协议哈希：协议变化必须重新执行下游；
- 确定性审计：检查输入、命令、产物和退出码；
- 独立数值验证：KMeans 只是第一个 preset。

### 4.2 补齐 Coordinator 生命周期

- 记录阶段任务、依赖、重试次数和取消原因；
- TeamCreate 失败或中断时确保清理 TeamDelete；
- 将 Coordinator 的工具过滤和 DAG 的论文工具权限写成可测试的策略；
- 暂不支持 Coordinator 与 DAG 任意混合嵌套，先定义单向调用边界：Coordinator 调用可复用的 Workflow，而不是直接修改 DAG 内部状态。

**验收标准**：同一份 KMeans contract 在 DAG 和 Coordinator 模式下产生相同的验证结论和 manifest；失败、取消、重试均有完整事件链。

## 5. P3：扩展能力（第四迭代以后）

### 5.1 通用论文复现协议

将当前 KMeans preset 抽象为配置对象：

```yaml
source: {url: ..., sha256: ...}
protocol: {sections: ..., constraints: ...}
implementation: {entrypoint: ..., language: python}
verification: {commands: [...], reference: ...}
artifacts: {required: [...], immutable: [...]}
```

用户只需提供论文 URL、实验目录和算法类型，系统生成同样的证据链。KMeans 继续作为默认模板，避免一开始支持过多论文类型。

### 5.2 Provider 路由

- 支持按阶段显式指定 provider/model；
- 记录模型、协议、温度和请求 ID 到运行 manifest；
- 额度或 HTTP 错误可分类显示，并允许从最后成功阶段续跑。

### 5.3 发布质量

- 增加最小 CI：Windows + Linux、单元测试、文档检查、KMeans 无 API 回归；
- 提供可选 Docker/打包脚本，但只有在本地命令和 Web 控制台稳定后再做。

## 6. 推荐迭代顺序

| 迭代 | 交付内容 | 建议完成定义 |
| --- | --- | --- |
| 第 1 个 | P0.1 + P0.2 | 恢复、重试、事件序号和损坏日志测试通过 |
| 第 2 个 | P0.3 + P1.1 | 论文输入受保护，SSE 可续传，`/health` 可用 |
| 第 3 个 | P1.2 + P1.3 | 控制台可筛选/导出，Windows 一条命令可启动 |
| 第 4 个 | P2 | Coordinator 复用 Workflow，失败和取消可审计 |
| 后续 | P3 | 扩展第二种论文 preset、Provider 路由和 CI 发布 |

## 7. 明确暂不做的事情

以下功能当前投入产出比低，且会增加安装和运维复杂度：

- 不引入 React/Vite、消息队列或微服务；
- 不把本地 JSONL 存储直接升级成需要运维的数据库集群；
- 不让模型自行决定 Verification 的最终通过状态；
- 不在没有第二种论文 preset 需求前设计过度通用的插件系统；
- 不默认开放公网监听或内置复杂账户体系。

## 9. 不围绕论文复现的通用产品化方向

论文复现适合作为一个高质量 preset，但 MewCode 的主要产品价值仍是帮助用户完成真实的软件开发任务。下面这些方向可以直接服务代码编写、调试和团队使用。

### 9.1 Agent 执行质量：让任务“可控地完成”

**改进点**

- 在 `mewcode/agent.py` 中把“思考、工具调用、工具结果、最终回复”记录为结构化步骤，而不是只依赖文本日志；
- 增加单任务最大轮数、总耗时、工具调用次数和输出大小上限；
- 区分可重试错误（网络超时、临时限流）与不可重试错误（参数错误、权限拒绝、语法错误）；
- 工具调用失败时保留上下文，让 Agent 先修正参数再重试；
- 统一取消信号，使 TUI、CLI、Web 控制台和 Runtime 都能停止同一个任务。

**技术亮点**：基于状态机的 Agent loop、错误分类重试和统一取消令牌。

**落地方式**：先增加 `RunLimits` 和 `ToolCallRecord` 两个小模型，再把现有循环中的隐式计数迁移进去，不改动已有工具协议。

**验收标准**：超出任一限制时任务进入明确的 `failed`/`cancelled` 状态；重试次数可解释；同一任务从 CLI 和 Web 取消都能在 1 秒内停止。

### 9.2 工具安全：从“能执行”升级为“可审计地执行”

当前权限模式、文件工具和 Bash 工具已经存在，下一步重点是让用户知道即将发生什么，并保留审计证据。

- 执行命令前展示标准化预览：工作目录、命令、预计影响范围；
- 增加 `dry-run` 模式，允许只生成补丁和命令计划；
- 对写文件、删除文件、Git 操作分别设置 allowlist；
- 记录命令退出码、修改文件列表和执行耗时；
- 为验证 Agent 使用只读工作目录快照，检测验证期间的额外修改；
- 对工作区外路径默认拒绝，并在错误中给出允许范围。

**技术亮点**：命令策略 + 工作区快照 + 可回放审计日志。

**涉及模块**：`mewcode/permissions/`、`mewcode/tools/`、`mewcode/filehistory/`、`mewcode/runtime/`。

**验收标准**：用户可以在一次运行结束后回答“执行了哪些命令、改了哪些文件、哪些操作被拒绝”；拒绝策略不会被普通工具参数绕过。

### 9.3 上下文与记忆：减少重复解释和无效读取

MewCode 已有上下文压缩、会话和记忆模块，可以从“有功能”优化到“可衡量”。

- 展示当前上下文使用量、压缩次数和被裁剪的消息范围；
- 对代码文件建立轻量索引，优先读取与任务相关的符号和调用点；
- 将用户记忆、项目记忆和反馈记忆分开设置 TTL、来源和删除入口；
- 对重复的只读文件查询增加短期缓存，并在文件变更后失效；
- 允许用户用 `/context` 查看“为什么这些文件被放进上下文”。

**技术亮点**：基于 token 预算的上下文编排、可解释的文件召回和失效缓存。

**落地方式**：第一步只做 token 统计、文件读取缓存和 `/context` 命令，不引入向量数据库。

### 9.4 Provider 与模型路由：提升稳定性并控制成本

当前 Provider 配置已经支持多协议，但选择主要依赖配置顺序。可以增加轻量的显式路由：

- 按任务类型或阶段指定 `provider/model`；
- 启动时执行一次 API 健康检查，提前报告 endpoint、模型和密钥变量；
- 对超时、限流、额度耗尽和认证失败给出不同提示；
- 可选 fallback：主模型失败后切换到备用模型，并记录切换原因；
- 在运行详情中记录模型、输入/输出 token、耗时和估算成本。

**技术亮点**：Provider capability 检测、可解释 fallback、运行级成本统计。

**验收标准**：模型不可用时在首次请求前给出诊断；fallback 不会重复执行有副作用的写操作；运行记录可以比较不同模型的成功率和延迟。

### 9.5 开发者体验：把“能安装”变成“容易开始”

- 增加 `mewcode doctor`：检查 Python、uv、配置文件、API Key、可选依赖和 Git 状态；
- 提供 `mewcode init` 生成 `.mewcode/config.yaml` 和 `.env.example`；
- 统一 `mewcode run`、`mewcode serve`、`mewcode paper` 命令的帮助和退出码；
- Windows PowerShell、Linux/macOS 各提供一条可复制的安装命令；
- 将常见错误转成“原因 + 修复命令”，避免用户阅读堆栈才能定位问题。

**技术亮点**：环境自检、跨平台命令一致性和可复制诊断报告。

### 9.6 可观测性与评测：知道质量是否真的提升

- 为每个用户请求生成 `trace_id`，串联 Agent、工具、子 Agent 和 Runtime 事件；
- 支持人类可读日志和 JSON 日志两种格式；
- 增加小型离线评测集：代码问答、文件修改、测试修复、取消和权限拒绝；
- 每次改动自动比较成功率、平均轮数、工具错误率、延迟和 token 使用量；
- 在 Web 控制台展示最近失败原因，而不是只显示“失败”。

**技术亮点**：可回放 trace + 固定任务集回归，能把 Agent 优化从主观感受变成数据比较。

### 9.7 Skills/MCP 扩展：建立稳定的能力边界

- 为 Skill 增加版本、输入 schema、所需权限和失败处理声明；
- MCP server 启动后执行能力探测和健康检查；
- 工具注册表输出机器可读清单，便于 Web 控制台和诊断命令使用；
- Skill 失败时返回结构化错误，避免把长堆栈直接塞进上下文；
- 为常用任务提供少量官方 Skill：测试修复、依赖升级、变更总结、发布检查。

**原则**：先稳定 Skill/MCP 的契约，再考虑第三方市场或在线安装。

## 10. 通用产品化路线建议

如果目标是提升整个 MewCode，而不是只提升论文复现，建议采用双轨路线：

| 优先级 | 通用产品交付 | 论文复现交付 |
| --- | --- | --- |
| P0 | Agent 限制与取消、工具审计、Runtime 恢复、配置诊断 | 输入/协议/结果哈希保护 |
| P1 | `/doctor`、上下文可视化、Provider 健康检查、SSE 稳定性 | 控制台展示阶段和验证证据 |
| P2 | trace、离线评测集、Skill/MCP 契约、模型 fallback | Coordinator 复用 Workflow |
| P3 | 轻量插件生态、成本分析、团队共享运行记录 | 第二种论文 preset |

推荐的第一个通用版本只交付四项：

1. `mewcode doctor` 环境诊断；
2. Agent 任务限制、取消和结构化事件；
3. 工具命令预览与修改审计；
4. `/context` 上下文使用量和文件来源展示。

这四项改动范围可控，既能改善日常编程体验，也能直接增强论文复现和 Coordinator 的稳定性。

## 11. 最终建议

`paper_study_DAG` 继续作为可验证工作流的样板，通用 Agent Runtime 则作为 MewCode 的产品主线。先完成执行控制、工具安全、上下文可解释性和环境诊断，再把这些能力提供给论文复现、Coordinator、CLI、TUI 和 Web 控制台共同使用。这样项目的开发价值不会绑定在单一论文场景上，同时保留当前 KMeans 流程的可运行性。
