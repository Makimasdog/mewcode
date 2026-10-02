# Paper-Study 协调者/团队模式 需求与实现说明

> **分支**：`paper_study_coordinator`（MewCode 双路线并行实验的协调者路线；对照路线见 `paper_study_DAG`）
> **目的**：用「协调者（Coordinator）/ 团队（Team）」这一动态编排范式，实现一个"给定研究领域 → 检索优质论文 → 选定并复现其方法 → 独立验证"的多 Agent 工作流。
> **交付对象**：本文档将提交给多个评审 Agent 做判断与意见补充。文末列出**聚焦评审问题**。
> **写作原则**：所有机制描述均以当前仓库源码为准并标注 `文件#行`，避免臆测。凡"依赖尚不存在的功能"处均标记为 **[GAP]** 或 **[风险]**。
> **实现状态**：首版采用普通后台子 Agent 共享主工作目录，失败后以完整上下文重新派发；验证由全新 Agent 在独立上下文中执行。已加入 `PaperSearch`、`PaperProtocol`、`PaperStudy`，启用协调者和 `Verification`，修正协调者提示词，并使各 Agent 的 Bash 命令在其 `work_dir` 下执行。`TeamCreate` 暂用作协调者模式激活入口，不创建 teammate。`SendMessage`/`TaskStop`、进程隔离与 Bash 强制文件沙箱仍不是首版能力。

---

## 1. 背景与目标

### 1.1 背景
MewCode 是终端 AI 编程助手，具备多种多 Agent 编排能力。针对"论文研读 + 代码复现"这一类**形状半已知、但过程需要临场判断**的任务，我们选择探索**协调者模式**：让主 Agent 扮演 Manager，把研究、实现、验证委派给若干 worker，自身负责理解需求、综合结果、动态纠偏。

### 1.2 目标（In-Scope）
- G1：给定一个研究领域关键词，系统能检索并筛选出该领域的高质量论文（3~10 篇候选）。
- G2：从候选中选定 1 篇最值得复现的论文，并产出其方法规格（算法/公式/超参/数据/评测）。
- G3：用代码复现该论文核心方法，能实际运行并产出结果。
- G4：由**全新、独立上下文的**验证 worker 复跑并核对结果，输出通过/失败/部分通过判定；首版不要求独立 OS 进程。
- G5：全程由协调者（主 Agent）编排，可向用户汇报阶段性结论。

### 1.3 非目标（Out-of-Scope）
- 不追求顶会级完整复现（不要求刷到 SOTA 指标），只复现"核心方法 + 关键实验"。
- 不实现新的框架级工具（如原生 `WebSearch`）；联网用现有能力（Bash/API 或外部 MCP）。
- 论文全文版权受限时的合法获取不在范围内（依赖公开 PDF / 摘要 / 官方代码）。

---

## 2. 术语

| 术语 | 含义 |
|------|------|
| Coordinator / Lead | 协调者，启用后接管主 Agent，只调度不执行 |
| Worker / Teammate | 被派发的执行子 Agent |
| Teammate（严格义） | 通过 `Agent(team_name=…)` 派生、有独立 worktree、经 SendMessage 协作的成员 |
| Plain sub-agent | 通过 `Agent`（无 team_name）派生的普通子 Agent，运行在主工作目录 |
| `<task-notification>` | worker 完成结果以 user 角色回流给 lead 的 XML 包装 |
| `<team-notification>` | 团队成员发给 lead 的邮箱消息聚合；首版不使用 teammate 路线 |
| 独立验证 | 新建验证 Agent，独立读取复现产物和事先固定的验收协议；不等同于进程隔离或强制只读沙箱 |

---

## 3. 已验证的事实与约束（源码依据，评审请重点核对）

**F1 — 首版普通子 Agent 不能调度其他 Agent。** `Agent` 工具在 [`ALL_AGENT_DISALLOWED_TOOLS`](file:///e:/Projects/wyy/Mewcode/mewcode/agents/tool_filter.py#L35-L43) 中被剥离；[`resolve_agent_tools`](file:///e:/Projects/wyy/Mewcode/mewcode/agents/tool_filter.py#L88-L148) 用于普通子 Agent。默认 in-process teammate 则走 [`build_teammate_tools`](file:///e:/Projects/wyy/Mewcode/mewcode/agents/tool_filter.py#L151-L212)，其白名单同样不含 `Agent`。→ **首版编排由 lead 发起。**

**F2 — 协调者模式由 `TeamCreate` 触发激活，非启动即生效。** 见 [`TeamCreateTool.execute`](file:///e:/Projects/wyy/Mewcode/mewcode/tools/team_create.py#L126-L135)：仅当双开关为真时，才 `coordinator_mode=True`、备份 `_full_registry`、把注册表 [收窄为派发专用](file:///e:/Projects/wyy/Mewcode/mewcode/agents/tool_filter.py#L215-L226)。系统提示词经 [`build_system_prompt(coordinator_mode=True, agent_catalog=…)`](file:///e:/Projects/wyy/Mewcode/mewcode/agent.py#L695-L699) 切换为协调者人格。

**F3 — 双开关。** [`is_coordinator_mode`](file:///e:/Projects/wyy/Mewcode/mewcode/teams/coordinator.py#L7-L10) 要求：配置 `enable_coordinator_mode: true` **且** 环境变量 `MEWCODE_COORDINATOR_MODE ∈ {1,true,yes}`。缺一不激活。

**F4 — Lead 的实际工具集取决于注册表。** [`COORDINATOR_MODE_ALLOWED_TOOLS`](file:///e:/Projects/wyy/Mewcode/mewcode/agents/tool_filter.py#L77-L80) 现仅含 `Agent`、`SyntheticOutput`、`TeamCreate`、`TeamDelete`，仍是**过滤白名单**，不是实际注册清单。TUI 初始化注册四者（[`app.py`](file:///e:/Projects/wyy/Mewcode/mewcode/app.py#L813-L885)）；CLI 初始化未注册 `SyntheticOutput`（[`__main__.py`](file:///e:/Projects/wyy/Mewcode/mewcode/__main__.py#L143-L170)）。主 Agent 未注册 `SendMessage` 或 `TaskStop`；后者没有工具实现。协调者激活后也没有 Read/Write/Bash，因此 lead 不能亲自读写文件或运行命令。协调者提示词已按此修正。

**F5 — Teammate 运行在独立 worktree、权限模式强制 DONT_ASK。** [`_execute_as_teammate`](file:///e:/Projects/wyy/Mewcode/mewcode/tools/agent_tool.py#L322-L470)：要求 `worktree_manager`，为每个队友创建独立 git worktree，`work_dir=wt.path`，`PermissionMode.DONT_ASK`。[`TEAMMATE_ADDENDUM`](file:///e:/Projects/wyy/Mewcode/mewcode/tools/agent_tool.py#L79-L89) 要求其只用相对路径、经 SendMessage 通信，但这是提示词约束。Bash 已按 Agent `work_dir` 设置 shell 工作目录；命令仍可显式访问目录外，不能称为强制文件沙箱。

**F6 — Teammate 工具集。** [`build_teammate_tools`](file:///e:/Projects/wyy/Mewcode/mewcode/agents/tool_filter.py#L151-L212) 注入协作工具（TaskCreate/Get/List/Update/SendMessage）；in-process 后端限 [白名单](file:///e:/Projects/wyy/Mewcode/mewcode/agents/tool_filter.py#L69-L74)（含 Read/Write/Edit/Bash/Glob/Grep）。

**F7 — 团队后端当前恒为 in-process。** [`detect_backend`](file:///e:/Projects/wyy/Mewcode/mewcode/teams/backend_detect.py#L29-L34) **无条件返回 `IN_PROCESS`**；文件中的 `detect_pane_backend` 当前未被调用。→ Windows 环境无需 tmux/iTerm2，但也不能声称 teammate 是独立进程。

**F8 — 验证 Agent 需显式启用。** `Verification` 内置 Agent 仅在 `enable_verification_agent=true` 时被 [`_load_builtins` 收录](file:///e:/Projects/wyy/Mewcode/mewcode/agents/loader.py#L114-L119)。其定义 [`verification.md`](file:///e:/Projects/wyy/Mewcode/mewcode/agents/builtins/verification.md) 禁用 Edit/Write 文件工具，但仍允许 Bash（见 F12）。

**F9 — 联网工具当前不存在。** 默认注册表 [`create_default_registry`](file:///e:/Projects/wyy/Mewcode/mewcode/tools/__init__.py#L212-L244) 只有 Read/Write/Edit/Bash/Glob/Grep；`WebSearch/WebFetch` 仅出现在白名单里为**预留名**，无实现；当前 `config.yaml` 未配置任何 MCP。**[GAP]**：联网必须靠 `Bash` 打公开 API，或外部接入 `mcp__*`（MCP 工具在过滤[第 0 层始终放行](file:///e:/Projects/wyy/Mewcode/mewcode/agents/tool_filter.py#L108-L110)）。

**F10 — 协调者激活期间无法使用 DAG 工具。** 工具收窄会剔除 `DAGCreate/DAGStatus`；`TeamDelete` 恢复注册表后可再次使用。因此两种编排方式不能在**同一次协调者模式运行中**混用。

**F11 — 普通后台 Agent 不支持 SendMessage 续跑。** [`AgentTool.execute`](file:///e:/Projects/wyy/Mewcode/mewcode/tools/agent_tool.py#L279-L301) 将普通后台 Agent 交给 `TaskManager.launch`；[`TaskManager._run_background`](file:///e:/Projects/wyy/Mewcode/mewcode/agents/task_manager.py#L210-L237) 只有 `team_name` 存在时才进入团队邮箱的 follow-up 循环。普通后台任务完成后仅通过任务通知回流；下一轮应新建 Agent，并在 prompt 中传入失败上下文。

**F12 — Verification 的只读性并非执行边界。** [`verification.md`](file:///e:/Projects/wyy/Mewcode/mewcode/agents/builtins/verification.md) 禁用 `EditFile`/`WriteFile` 并用提示词禁止改动，但仍可调用 `Bash`；[`PermissionChecker`](file:///e:/Projects/wyy/Mewcode/mewcode/permissions/checker.py#L80-L95) 的路径检查仅适用于文件类工具。因此可以要求验证不改项目，但不能声称现有工具强制保证其只读。

**F13 — 普通后台任务的命令与写入须使用自动执行权限。** [`PermissionMode.DEFAULT`](file:///e:/Projects/wyy/Mewcode/mewcode/permissions/modes.py#L43-L50) 对写入和命令返回 `ask`；[`Agent._execute_tool_call`](file:///e:/Projects/wyy/Mewcode/mewcode/agent.py#L1500-L1525) 在非交互任务中拒绝需询问的调用。论文任务的 `PaperSearch`、`PaperProtocol`、`PaperStudy` 和已启用的 `Verification` 因此设置 `permissionMode: dontAsk`，各自限定可见工具并在提示词中限制行为；Bash 仍需信任执行环境。

---

## 4. 需求

### 4.1 功能需求（FR）
- **FR1 领域解析**：lead 从用户输入提取领域关键词，必要时构造中英文检索式。
- **FR2 并行检索**：lead 一次派发 ≥2 个只读研究 worker（不同来源/角度），各自返回可核验来源、论文版本、公开全文/代码/数据状态与候选依据；无法取得的材料明确标为未知。
- **FR3 综合与筛选**：lead **亲自**去重并按相关性、方法清晰度、公开材料、数据/算力可得性、评测可操作性初筛，引用量与时效仅作辅助。对优先候选再派一个定向精读 worker，从公开全文及官方材料提取方法、公式、数据和评测的章节/页码依据；lead 根据这些证据最终选定 1 篇。禁止"基于你的发现"式甩锅（见 [协调者提示词反模式](file:///e:/Projects/wyy/Mewcode/mewcode/teams/coordinator.py#L241-L247)）。只有摘要、缺少关键方法或数据时，不应承诺复现原文指标；可改选论文或先向用户报告约束。
- **FR4 方法与验收规格化**：选定后、编码前，由 lead 根据 worker 提供的论文证据拟定自包含规格：论文及版本/来源、算法步骤与关键公式、超参、数据及许可/划分、基线、随机种子、环境和资源上限、执行命令、评测指标与预先设定的容差/趋势判定。lead 无写文件工具，因此先派一个普通 Agent **只负责**把该规格写成 `protocol.md` 并返回文件哈希；待其完成，lead 将路径与哈希传给实现和验证 worker。实现 worker 不得改协议；确需修订时须停止当前尝试、记录原因并重新固定新版本。
- **FR5 代码复现**：一个实现 worker 依规格写代码并运行，产出可复现产物与日志。
- **FR6 独立验证**：一个**全新的、独立上下文**的 `Verification` worker 按事先落盘的协议复跑并核对，输出 `VERDICT: PASS/FAIL/PARTIAL`，附命令、输出及差异。首版“只读”是行为要求，不是已实现的硬隔离。
- **FR7 失败纠偏**：普通后台 worker 失败时，lead 综合错误与已有产物，最多重新派发指定次数的**新** worker；每次 prompt 包含路径、命令、错误输出、修正范围和停止条件。不得写 `SendMessage(同一普通 worker)`。
- **FR8 汇报**：lead 用文本汇报候选、选定理由、复现结果、验证结论；TUI 可选用 `SyntheticOutput`，CLI 不依赖它。
- **FR9 生命周期收尾**：全部普通后台任务完成或取消后调用 `TeamDelete`，并确认恢复 lead 全工具（[team_delete 恢复逻辑](file:///e:/Projects/wyy/Mewcode/mewcode/tools/team_delete.py#L77-L81)）。中途失败也执行收尾；若删除失败，报告模式仍处于收窄状态及处理方式。

### 4.2 非功能需求（NFR）
- **NFR1 验证分离**：实现者可在开发中自测，但最终验收必须由全新的验证 worker 独立复跑；“不同 Agent 上下文”是首版硬约束，进程/容器隔离不作承诺。
- **NFR2 prompt 自包含**：worker 看不到 lead 对话，每个派发 prompt 必须自带全部所需上下文。
- **NFR3 并发安全**：检索任务原则上只读并行；协议落盘、实现和验证按顺序执行；写同一批文件的任务串行。验证前固定所读的代码版本，并核对协议哈希。首版只读依赖 worker 指令，不能作为权限保证。
- **NFR4 可观测**：每个 `已验证` 结论必须附实际命令、退出状态、关键输出、数据/代码版本和指标计算方式；lead 汇报可溯源。
- **NFR5 成本与终止**：每个 worker 有 `maxTurns`，阶段各有最多 1 次纠偏重新派发，且设置总任务/时间/资源预算。当前没有已注册的 `TaskStop` 工具；首版不得声称 lead 可用该工具中断正在运行的普通 worker，须以现有运行界面的中断能力或新增能力另行验收。
- **NFR6 跨平台**：默认 in-process，Windows 无需 tmux/iTerm2。

---

## 5. 能力缺口与首版处理

| 编号 | 缺口 | 影响 | 建议方案 |
|------|------|------|----------|
| GAP-1 | 无原生联网工具（F9） | 检索/抓取论文 | 已由 PaperSearch 使用 Bash 调公开 API；实测 arXiv/OpenAlex/Crossref 可达，Semantic Scholar 返回 429，因此前两者作主检索，后两者仅按可用性补充 |
| GAP-2 | 缺少复现 worker | 无复现执行者 | 已新增内置 `PaperStudy`，并增 `PaperSearch`、`PaperProtocol` |
| GAP-3 | `Verification` 默认未启用 | 无法独立验证 | 配置样例已设 `enable_verification_agent: true`，定义已针对论文复现补充协议核验 |
| GAP-4 | 协调者需要双开关 | lead 不会变 Manager | 配置样例已设 `enable_coordinator_mode: true`；将样例合入本地配置，运行前仍须设 `MEWCODE_COORDINATOR_MODE=1` |
| GAP-5 | 内置 Agent 不热重载 | 已运行的会话看不到新 worker | 更新后重启 mewcode 触发 `load_all()` |
| GAP-6 | lead 未注册 `SendMessage`/`TaskStop`，普通后台 Agent 无邮箱续跑（F4/F11） | 无同 worker 续跑与模型内停止 | 协调者白名单/提示词已修正；首版失败后新起 worker，通用续跑/停止列为后续能力 |
| GAP-7 | Bash 原先未绑定 `work_dir`，命令仍不受文件路径沙箱约束（F5/F12） | 相对命令目录错误、无法强制只读 | 已按 Agent 绑定 Bash `cwd` 并加并发回归测试；强隔离仍需容器或命令级限制 |
| GAP-8 | 无固定的论文复现协议和验收阈值 | “能跑”可能被误判为复现成功 | 已新增 PaperProtocol，在实现前落盘 `protocol.md` 并报告 SHA-256；分层规则见 §10 |

首版运行前仍需有效 API Key、公开网络访问、可用的论文全文/数据和 `MEWCODE_COORDINATOR_MODE=1`。GAP-6 的通用续跑/停止和 GAP-7 的强隔离不属于首版承诺。

---

## 6. 方案设计

### 6.1 激活与生命周期

```
启动 mewcode（config: enable_coordinator_mode + enable_verification_agent；env: MEWCODE_COORDINATOR_MODE=1）
   │
用户："帮我复现〈领域〉的一篇代表论文"
   │
Lead: TeamCreate("paper-study")        ← 首版仅用作激活入口；不创建 teammate
   │
   ├─（派普通后台 worker，见 6.3；本次会话仅使用 TUI 已注册工具或文本输出）
   │
Lead: TeamDelete("paper-study")        ← 全部任务已结束后执行；失败路径也要执行
   │
Lead: 文本汇总给用户（TUI 可选 SyntheticOutput）
```

### 6.2 两种派发方式的选择（关键设计决策）

Lead 在协调者模式下用 `Agent` 工具派 worker，有**两条不同代码路径**，取舍直接影响"文件是否互通"：

| 维度 | (A) Teammate：`Agent(team_name=…)` | (B) Plain sub-agent：`Agent`（无 team_name） |
|------|-----------------------------------|---------------------------------------------|
| 代码路径 | [`_execute_as_teammate`](file:///e:/Projects/wyy/Mewcode/mewcode/tools/agent_tool.py#L322-L470) | [`execute` 路径3](file:///e:/Projects/wyy/Mewcode/mewcode/tools/agent_tool.py#L159-L320) |
| 工作目录 | 各自**独立 git worktree**（隔离） | **主工作目录**（共享） |
| 通信 | 必须 SendMessage + 邮箱 | 前台直接返回文本；后台通过 `<task-notification>` 回流 |
| 跨 worker 文件可见 | ❌ 默认不可见（各自 worktree） | ✅ 同一目录，可互相读取 |
| 生命周期 | 可由团队邮箱唤醒；默认 in-process | 一次性，完成后发通知 |
| 权限 | 强制 `DONT_ASK` | 由 worker 定义决定 |

> **[设计选择]** paper-study 是"复现产物要被验证 worker 读取"的**流水线**，文件共享是硬需求。
> - 若用 **(A) Teammate**：复现 worker 的代码落在它自己的 worktree，验证 worker 在**另一个 worktree**，**默认看不到**——需要额外的 git 分支合并/路径传递机制。
> - 若用 **(B) Plain sub-agent**：复现与验证都在主目录，验证可直接读 `paper_repro/`。
>
> **首版决策**：核心流水线用 **(B) plain background sub-agent**（`Agent(run_in_background=true)`，无 `team_name`，且 Agent 定义不设置 `isolation: worktree`）。`TeamCreate` 暂仅作为**激活协调者模式的开关**，不生成 teammate；这是现有框架入口的临时耦合。普通后台 Agent 不支持团队邮箱续跑；失败后新起 Agent。后续若增加纯协调者入口，再移除空团队的创建/删除。

### 6.3 paper-study 编排流程（以方案 B 为例）

```
用户输入领域
   │
Lead ── Agent(PaperSearch, run_in_background=true)  → 检索：arXiv API，返回候选 A
Lead ── Agent(PaperSearch, run_in_background=true)  → 检索：OpenAlex，返回候选 B（Crossref 核 DOI）
        └─ <task-notification> 回流候选 A、B、来源 URL/DOI、全文/代码/数据可得性
   │
Lead（Synthesis，亲自做）：去重→检查证据与资源→初筛优先候选
Lead ── Agent(PaperSearch, run_in_background=true) → 定向精读公开全文/官方代码，报告公式、实验协议和章节/页码证据
        └─ 若关键材料不可得：回到候选清单选下一篇，或报告仅能做 PARTIAL 的边界
Lead（Synthesis，亲自做）：依据精读证据最终选定 1 篇并制定验收协议
Lead ── Agent(PaperProtocol, run_in_background=true, "仅将以下完整协议写为 paper_repro/<slug>/protocol.md，报告 SHA-256；不实现代码")
        └─ <task-notification>：协议路径 + SHA-256；此时尚未开始实现
   │
Lead ── Agent(PaperStudy, run_in_background=true, "按已固定的 protocol.md 及哈希复现；不得修改协议")
        └─ <task-notification>：文件路径 + 依赖/运行命令 + 原始输出 + 与协议指标对比
        └─（失败）Lead 综合错误→新建 Agent(PaperStudy, 完整错误与文件上下文)；最多 1 次
   │
Lead ── Agent(Verification, run_in_background=true, "先核对 protocol.md 哈希，再独立复跑产物并核对固定阈值；不要修改项目")
        └─ <task-notification>：协议哈希/命令/退出状态/输出/指标差异 + VERDICT
   │
Lead ── TeamDelete（任务全结束后，包含失败路径）
   │
Lead ── 文本汇报：候选清单 / 选定理由 / 方法摘要 / 复现代码路径 / 运行结果 / 验证结论 / 偏差
```

### 6.4 Worker 清单与 subagent_type 映射

| 阶段 | subagent_type | 来源 | 工具需求 | 状态 |
|------|---------------|------|----------|------|
| 检索×N | `PaperSearch`（只读行为约束） | 内置 `paper_search.md` | Bash+网络(GAP-1)、Read | 已新增；`maxTurns: 16` |
| 候选初筛/最终选题 | lead 自做 Synthesis | — | lead 无读取工具，依据 worker 证据推理 | — |
| 定向精读 | `PaperSearch`（只读行为约束） | 内置 | Bash+网络/Read | 已新增；报告原文位置 |
| 协议落盘 | `PaperProtocol`（单次、仅写协议） | 内置 `paper_protocol.md` | Write/Bash（计算哈希） | 已新增；`maxTurns: 8` |
| 复现 | `PaperStudy` | 内置 `paper_study.md` | Read/Write/Edit/Bash | 已新增；`maxTurns: 40` |
| 验证 | `Verification` | 内置，项目配置已启用 | Read/Bash；Bash 可产生写入 | 已补论文协议核验；`maxTurns: 24` |

### 6.5 已交付的首版产物
1. `mewcode/agents/builtins/paper_search.md`、`paper_protocol.md`、`paper_study.md` — 三种有明确 `maxTurns`、工具范围和非交互权限的 worker 定义；均以普通后台 Agent 运行。
2. `mewcode/agents/builtins/verification.md` — 增加论文协议哈希、复跑与分层判定要求；保留通用软件验证场景。
3. `examples/paper-study-config.yaml` — 可跟踪的配置样例；本地 `.mewcode/config.yaml` 被 git 忽略，须复制或合入开关；启动时另设 `MEWCODE_COORDINATOR_MODE=1`。
4. `mewcode/teams/coordinator.py` — 使用实际可用工具描述首版论文流程；失败后新起 worker，结束时先 `TeamDelete` 后最终汇报。
5. `mewcode/tools/bash.py` 与 `mewcode/agent.py` — 绑定各 Agent 的 shell 工作目录；仍不限制命令显式访问其他目录。
6. 运行时产物 `paper_repro/<slug>/protocol.md` — PaperProtocol 在实现开始前写入并报告 SHA-256；实现和验证 worker 均接收该哈希。代码、依赖版本、数据来源、原始输出及指标脚本由 PaperStudy 交付。

---

## 7. 关键设计决策与取舍

| 决策 | 选择 | 理由 | 备选/代价 |
|------|------|------|-----------|
| 编排范式 | 协调者（动态） | 筛选/精读需 lead 亲自理解、过程需纠偏 | 静态 DAG：更确定更省，但 lead 不参与综合 |
| 派发方式 | Plain background sub-agent 为主；失败后新起 Agent | 流水线需跨 worker 文件共享，普通 Agent 无邮箱续跑 | Teammate：文件默认不互通（§6.2） |
| 联网 | Bash 公开 API 为主，MCP 可选 | 现状无原生工具；先验证目标环境的网络和命令 | MCP：来源更丰富但需配置 server，部分服务需 key |
| 复现范围 | 核心方法 + 关键实验 | 成本与成功率 | 完整复现：可能长尾失败、烧 token |
| 验证 | 独立新 worker + 编码前固定协议 | 减少自我验收偏误与事后修改标准（NFR1） | 真正强制只读/进程隔离需额外实现 |

---

## 8. 与 DAG 路线（`paper_study_DAG` 分支）对比

| 维度 | 协调者路线（本文档） | DAG 路线 |
|------|----------------------|----------|
| 编排时机 | 运行中由 lead 逐轮决定 | 发起前声明全部节点与依赖 |
| 综合筛选 | lead 亲自做（质量高） | 作为独立节点，靠 prompt 约束 |
| 并行 | lead 多条 Agent 调用 | 无依赖节点引擎自动并行 |
| 数据流 | 经 `<task-notification>` 回流 + lead 再写 prompt | 沿依赖边自动注入下游 |
| 确定性/成本 | 低确定、token 高 | 高确定、可复现、落盘 |
| 失败处理 | lead 综合错误后限次新起 worker | 引擎重试 + fail_fast + BLOCKED 传播 |
| 互斥 | 启用后 `DAGCreate` 被剔除 | 二者不可同开 |

---

## 9. 风险与开放问题

- **[风险 R1] Teammate 文件隔离**：若采用 teammate，复现产物在独立 worktree，验证 worker 读不到（F5）；首版已选择 plain sub-agent。以后若切换路线，先设计提交/合并或明确的产物移交与完整性校验。
- **[风险 R2] 命令执行边界**：论文任务的普通 worker 与验证 worker 均设置 `dontAsk`，可自动使用 `Bash`。shell 已绑定 Agent `work_dir`，但命令可显式访问其他目录，也不受文件工具路径沙箱约束。首版用明确路径、预设命令和资源上限降低误操作；强隔离不能靠提示词实现，须引入容器或命令级限制。
- **[风险 R3] 非确定性**：lead 临场编排，每次流程可能不同，难做回归测试与复现。
- **[风险 R4] 成本失控**：多 worker + 长 `maxTurns` + 反复重新派发，token 与运行成本高；需阶段预算、最多一次纠偏和超时策略。当前无已注册 `TaskStop`，不能把它当作首版中断保障。
- **[风险 R5] 联网可靠性**：公开 API 可能限流且元数据不等于全文。当前环境的最小联网检查：arXiv 200、OpenAlex 200、Crossref 200、Semantic Scholar 429；主路线采用 arXiv + OpenAlex，Semantic Scholar 不作前置依赖。
- **[风险 R6] 激活耦合**：首版创建空团队只为切换角色；若遗漏 `TeamDelete`，lead 持续处于工具收窄态。所有结束分支都要收尾，长期应提供不依赖团队的协调者入口。
- **[GAP] 复现正确性**：论文复现本身难度高，"能跑"不等于"对齐原文指标"；按 §10 的预设层级判定，不能由实现者事后放宽标准。

---

## 10. 验收标准与测试要点

- **AC1 候选证据**：给定领域，产出 ≥3 篇候选论文；每篇含标题、作者、年份、DOI/arXiv ID 或原始来源 URL、论文版本、公开全文/代码/数据状态与关键限制。引用量/venue 可作为辅助信息，不作为独立质量证明。
- **AC2 选题与协议**：lead 明确选定 1 篇并给出可核验的评分与取舍；精读结果有公开全文/官方资料链接及关键方法、实验的章节或页码依据。编码前固定方法、数据划分、随机种子、依赖/硬件预算、指标计算、目标值及容差或趋势判定。单独的协议落盘 Agent 在实现启动前写入 `paper_repro/<slug>/protocol.md` 并报告 SHA-256；实现和验证阶段使用相同哈希，不得按结果回改阈值。
- **AC3 运行证据**：`paper_repro/<slug>/` 下有代码、运行说明、依赖版本、数据来源及许可/校验信息、实际执行命令、退出状态、关键原始输出和指标计算方式。能跑通但无法核对论文关键结论，不能判为完全复现。
- **AC4 独立验证**：全新 `Verification` Agent 在与实现者不同的上下文中先核对协议 SHA-256，再实际复跑并给出命令、退出状态、关键输出、观测值与预设标准的差异，以及 `VERDICT: PASS/FAIL/PARTIAL`。协议哈希不符直接 `FAIL`；默认 in-process，不要求独立 OS 进程。验证前后记录工作树状态，确认没有意外修改，但不宣称由当前工具强制只读。
- **AC5 结论分层**：`PASS` 表示核心方法、关键实验和预设指标/趋势均满足协议；`PARTIAL` 表示代码可运行且核心方法有证据，但受公开数据、算力或论文信息缺口限制，未满足全部预设比较；`FAIL` 表示无法运行、关键方法不符、评测不可核验或未达到预设最低标准。偏差和限制须逐项列明。
- **AC6 生命周期**：lead 汇报候选、选题、协议、产物和验证结论；全部普通后台任务结束后（含失败分支）`TeamDelete` 成功并确认工具恢复。若团队删除失败，必须明确报告。
- **测试建议**：
  - 静态：`AgentLoader.load_all()` 确认 `PaperStudy`/`Verification`/`general-purpose` 均可加载；`parse_agent_file` 校验新 md 的 frontmatter 合法。
  - 机制：可复用 `tests/test_teams.py` 检查双开关、过滤和提示词；另断言激活后的**实际注册表**，避免把白名单中不存在的工具当作可用工具。
  - 执行器：在目标 Windows 环境验证 `Bash` 实际工作目录、公开 API 连通与失败输出；验证任务前后比较工作树状态。
  - 端到端：先用公开全文、代码和小数据集俱全的论文跑通一次；人工核对论文来源、协议是否在结果出现前固定、指标计算与 `VERDICT` 的证据链。

---

## 11. 供评审 Agent 的聚焦问题

- **Q1（架构）** 首版已选 **plain background sub-agent（共享主目录）**。若以后改用 teammate，如何在不绕过隔离的情况下移交并校验复现产物？
- **Q2（联网）** Bash 公开 API 作为主通道是否足够？哪些环节非 MCP 不可（如 PDF 全文解析）？
- **Q3（分工粒度）** 检索/精读由 worker 提供证据、选题与协议由 lead 综合，这一分工对 token 与判断质量的影响如何量化？
- **Q4（成本与终止）** 阶段 `maxTurns`、并发上限、最多一次纠偏和总资源预算是否足够？无 `TaskStop` 时如何中断运行中的任务？
- **Q5（安全）** Bash 工作目录已绑定；如何进一步提供真正的文件/命令隔离，尤其是验证阶段？
- **Q6（验收）** 所选论文的指标容差或趋势阈值是否可在编码前客观设定？资源受限的 `PARTIAL` 边界由谁确认？
- **Q7（生命周期）** 何时将 `TeamCreate` 的临时激活方式替换为纯协调者入口？如何保证异常路径恢复工具集？

---

## 12. 附录：源码事实索引

| 事实 | 位置 |
|------|------|
| 子 Agent 禁用 `Agent`/`AskUserQuestion` | `mewcode/agents/tool_filter.py#L35-L43` |
| worker 工具四层过滤 | `mewcode/agents/tool_filter.py#L88-L148` |
| teammate 工具集 | `mewcode/agents/tool_filter.py#L151-L212` |
| lead 收窄工具集 | `mewcode/agents/tool_filter.py#L77-L80, L215-L226` |
| 各 Agent 的 Bash 工作目录 | `mewcode/agent.py`、`mewcode/tools/bash.py` |
| 论文 worker 定义 | `mewcode/agents/builtins/paper_search.md`、`paper_protocol.md`、`paper_study.md` |
| 协调者激活点 | `mewcode/tools/team_create.py#L126-L135` |
| 协调者双开关 | `mewcode/teams/coordinator.py#L7-L10` |
| 协调者系统提示词（工作流/反模式） | `mewcode/teams/coordinator.py#L104-L311` |
| teammate 走独立 worktree + DONT_ASK | `mewcode/tools/agent_tool.py#L322-L470` |
| 普通子 Agent 路径 | `mewcode/tools/agent_tool.py#L159-L320` |
| lead 系统提示词切换 | `mewcode/agent.py#L695-L699` |
| TeamDelete 恢复全工具 | `mewcode/tools/team_delete.py#L77-L81` |
| 后端默认 in-process | `mewcode/teams/backend_detect.py#L29-L34` |
| 内置加载器与验证开关 | `mewcode/agents/loader.py#L77-L125` |
| Agent 定义解析与校验 | `mewcode/agents/parser.py#L108-L181` |
| 默认工具注册表（无联网） | `mewcode/tools/__init__.py#L212-L244` |
| 内置 worker 示例 | `mewcode/agents/builtins/*.md` |

*（首版实现的启动条件见 §5；通用续跑、强隔离和纯协调者入口仍是已知限制，不得写成现有能力。）*
