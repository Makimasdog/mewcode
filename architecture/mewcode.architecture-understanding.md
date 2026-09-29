# MewCode — 架构理解（C4）

- **产出技能**：`c4model` 基础技能（architecture-visualization 插件）。
- **权威源文件**：`architecture/mewcode.structurizr.dsl`
- **运行时 / 部署拓扑**：`architecture/mewcode-runtime-topology.dot`（Graphviz DOT，派生视图）
- **证据索引**：`architecture/mewcode.evidence.md`
- **状态**：当前状态（current-state）模型，基于 2026-09-26 的代码审查。
- **可信度**：所有节点/连线均为**高**——每一项都可追溯到源码文件（见证据索引）。

## 目的

为 MewCode 提供一份稳定的、具备 C4 语义的架构视图：它是什么、谁在使用它、
依赖哪些外部系统、由哪些运行时单元构成，以及核心 Agent Engine 内部如何协作。

## 受众

- 需要在代码库中快速定位的新贡献者。
- 评估系统边界与外部依赖的架构 / 运维评审者。
- 需要判断某处改动应归属何处（TUI、Server、Engine 还是 Tools）的人。

## 范围

单一软件系统 —— **MewCode** —— 按三个 C4 层级建模：

1. **系统上下文（System Context）** —— MewCode、其用户，以及直接依赖的外部系统。
2. **容器（Container）** —— 运行时 / 可部署单元，以及状态存储。
3. **组件（Component）** —— **Agent Engine** 与 **Runtime Server** 两个容器的内部结构。

另附一张 **运行时 / 部署拓扑图**（`mewcode-runtime-topology.dot`，Graphviz DOT）：
按插件的格式选择规范，部署 / 资源拓扑用 DOT 而非 C4 表达，它展示三种进程入口
（TUI、`-p` 无头、`mewcode-server`）在本地主机上的分布、本地存储、MCP 子进程
与出站外部依赖。该图为派生视图，C4 事实仍以 `.dsl` 为准。

不在范围内：单个工具的实现细节、逐条命令处理器、类级别的代码图。DAG 编排
（`runtime/dag.py` + `tools/dag_tools.py`）属于团队 / 工具路径，不在 Runtime
Server 的 HTTP 请求链上，故未纳入 Server 组件视图。

## 阅读顺序

1. `SystemContext` —— 理解系统边界与外部依赖。
2. `Containers` —— 查看两个前端（TUI、Runtime Server）、共享的 Agent Engine，
   以及 `.mewcode/` 状态存储。
3. `AgentEngineComponents` —— 深入主循环：prompt → LLM → tools，并受
   permissions / hooks / context 的约束，由 MCP、子 Agent、团队、技能、记忆扩展。
4. `RuntimeServerComponents` —— 查看 Server 的请求链：HTTP/SSE 适配器 →
   AgentRuntime 服务（提交 / 重试 / 超时 / 取消 / 订阅 / 恢复）→ RunStore
   事件存储，以及 bootstrap 如何复用 CLI 的装配把执行委托给 Agent Engine。
5. `mewcode-runtime-topology.dot` —— 从部署视角看三种进程入口、本地存储、
   MCP 子进程与出站外部调用。

## 关键建模决策

- **两个前端，一个引擎。** `mewcode` 命令（交互式 Textual TUI 与 `-p` 单次执行）
  和 `mewcode-server` 命令（FastAPI HTTP/SSE）被建模为两个独立容器；二者驱动
  同一个与 UI 无关的 **Agent Engine**。`runtime.bootstrap.build_runtime()` 复用了
  CLI 的 provider、权限、会话与工具装配 —— 这是引擎被共享的直接证据。
- **将 Agent Engine 建模为容器。** 引擎是两个前端都链接进来的核心运行时库，
  因此被建模为容器，并且是唯一提供组件视图的容器。其内部拆分（主循环、LLM 客户端、
  工具、MCP、子 Agent、团队、权限、上下文、技能、Hook、记忆、Prompt 构建）可由
  包结构与 import 关系直接佐证。
- **状态存储基于文件。** `.mewcode/` 保存配置、权限规则、会话、运行快照 + JSONL
  事件日志、DAG 运行以及记忆文件。它被标记为 `Database` 并绘制为圆柱体。
- **本地工作区与 Git 仓库、MCP 服务器均为外部系统**，而非容器 —— 它们位于
  MewCode 进程边界之外。

## 假设与缺口

- **假设**：`CI / Automation` 被绘制为 Runtime Server 与 `-p` 模式的调用方。
  未检查任何 CI 配置；该角色代表文档所述的用法，而非经过验证的流水线。
- 递归关系 `子 Agent 系统 → 主循环`（嵌套循环）由 `AgentTool` 接收 `parent_agent`
  并派生 agent 推断而来；它反映的是预期行为，而非单次可追踪的调用链。
- 组件视图仅覆盖 Agent Engine。TUI 与 Runtime Server 容器未做分解 —— 仅在有代码
  证据表明其内部职责稳定时，才为它们补充组件视图。
- 协议标注（HTTPS、stdio、SSE）来自 SDK / 配置的用法及 README 的 API 表格；
  未通过真实网络抓包验证。

## 如何查看

用 Qoder 的 **Structurizr DSL 预览器**打开 `architecture/mewcode.structurizr.dsl`
即可看到 C4 各视图（含新增的 `RuntimeServerComponents`），或将其粘贴到官方
Structurizr Playground。运行时 / 部署拓扑用 Qoder 的 **Graphviz DOT 预览器**打开
`architecture/mewcode-runtime-topology.dot`。`.dsl` 为 C4 权威源；DOT 拓扑为派生
视图 —— 如二者出现事实冲突，以 `.dsl` 与代码为准，并修改源而非渲染产物。
