# MewCode

> 一只会写代码的猫，你的终端 AI 编程助手 🐱

MewCode 是一个运行在终端里的 AI 编程助手，支持多 LLM 提供商、MCP 协议、子 Agent 调度、Agent 团队协作等能力。灵感来源于 Claude Code，使用 Python + Textual 构建 TUI 交互界面。

## 功能特性

- **多提供商支持** — Anthropic、OpenAI、OpenAI 兼容协议均可接入，支持多模型热切换
- **终端图形界面** — 基于 Textual 框架的 TUI，支持鼠标/键盘操作、命令补全、文件 `@` 引用
- **权限控制** — 四种权限模式：`default`（默认询问）、`accept-edits`（自动接受编辑）、`plan`（规划模式）、`bypass`（YOLO 全自动）
- **Slash 命令** — 内置 `/help`、`/compact`、`/clear`、`/plan`、`/session`、`/memory`、`/mcp`、`/status`、`/rewind`、`/permission`、`/tasks`、`/trace`、`/worktree`、`/skill`、`/review` 等命令
- **MCP 协议** — 完整支持 Model Context Protocol，可接入外部工具服务器
- **技能系统** — 内置 `commit`、`review`、`test`、`backend-interview` 等技能包，支持自定义扩展
- **子 Agent** — 内置 Explore（代码探索）、Plan（架构设计）、General-purpose（通用任务）、Verification（代码审查）子 Agent
- **Agent 团队** — 支持 Coordinator 模式，Leader Agent 可创建多个 Teammate 并行协作
- **Git Worktree** — 集成 Git Worktree 管理，子 Agent 可在隔离的 worktree 中工作
- **会话管理** — 会话持久化、恢复、摘要生成、对话回退（Rewind）
- **上下文压缩** — 自动压缩超长对话，突破上下文窗口限制
- **记忆系统** — 用户记忆、项目记忆、反馈记忆，跨会话持久化
- **Prompt 缓存** — Anthropic 协议下自动启用 prompt caching，降低费用
- **Hook 系统** — 支持 `startup`、`shutdown` 等生命周期 Hook
- **非交互模式** — 通过 `-p` 参数直接执行 prompt 并输出结果，适合脚本/CI 场景

## 环境要求

- Python >= 3.11
- 至少一个 LLM API Key（Anthropic 或 OpenAI）

## 快速开始

```bash
git clone <repo-url> mewcode && cd mewcode && uv sync && uv run mewcode
```

## 安装

```bash
# 克隆项目
git clone <repo-url> mewcode
cd mewcode

# 安装依赖（项目使用 uv 管理）
uv sync
```

## 配置

MewCode 通过 YAML 文件配置，加载优先级从低到高（后者覆盖前者）：

1. `~/.mewcode/config.yaml` — 用户级全局配置
2. `.mewcode/config.yaml` — 项目级配置
3. `.mewcode/config.local.yaml` — 本地覆盖（建议加入 .gitignore）

### 最简配置

```yaml
providers:
  - name: anthropic
    protocol: anthropic
    base_url: https://api.anthropic.com
    model: claude-sonnet-4-6
    api_key: ${ANTHROPIC_API_KEY}

permission_mode: default
```

### 完整配置示例

```yaml
# 可配置多个 Provider，启动时选择
providers:
  - name: anthropic
    protocol: anthropic
    base_url: https://api.anthropic.com
    model: claude-sonnet-4-6
    api_key: ${ANTHROPIC_API_KEY}
    thinking: true          # 启用 extended thinking
    context_window: 0       # 0=自动检测（推荐），或手动指定
    max_output_tokens: 8192

  - name: openai
    protocol: openai
    base_url: https://api.openai.com/v1
    model: gpt-4o
    api_key: ${OPENAI_API_KEY}

# 权限模式: default | accept-edits | plan | bypass
permission_mode: default

# MCP 工具服务器（可选）
mcp_servers:
  - name: filesystem
    command: npx
    args: ["-y", "@anthropic-ai/mcp-server-filesystem", "/path/to/allowed"]
  - name: github
    url: https://api.github.com/mcp
    headers:
      Authorization: Bearer ${GITHUB_TOKEN}

# Git Worktree 配置
worktree:
  symlink_directories:
    - node_modules
    - .venv
    - vendor
  stale_cleanup_interval: 3600   # 秒
  stale_cutoff_hours: 24

# Agent 团队模式
teammate_mode: ""              # 空字符串 = 默认, "in-process" = 进程内协作
enable_coordinator_mode: false # 是否启用协调者模式

# 功能开关
enable_fork: false             # 是否允许 fork 对话
enable_verification_agent: true # 是否启用验证 Agent

# 生命周期 Hook
hooks:
  - event: startup
    command: echo "MewCode started"
  - event: shutdown
    command: echo "MewCode stopped"
```

### API Key

配置中的 `api_key` 支持 `${ENV_VAR}` 语法引用环境变量。环境变量映射：

| 协议 | 环境变量 |
|------|----------|
| `anthropic` | `ANTHROPIC_API_KEY` |
| `openai` | `OPENAI_API_KEY` |
| `openai-compat` | `OPENAI_API_KEY` |

## 使用

```bash
# 交互模式（TUI）
uv run mewcode

# 非交互模式：执行单次 prompt 并输出结果
uv run mewcode -p "解释一下这个项目的架构"

# 指定权限模式
uv run mewcode --mode plan
uv run mewcode --mode bypass
```

### 快捷键

| 快捷键 | 功能 |
|--------|------|
| `Enter` | 发送消息 |
| `Shift+Enter` / `Ctrl+J` | 换行 |
| `Tab` | 命令/@文件补全 |
| `Shift+Tab` | 切换权限模式 |
| `Ctrl+O` | 展开/收起工具调用详情 |
| `Esc` | 取消当前操作 |
| `Ctrl+C` | 退出程序 |
| `Up` / `Down` | 浏览历史 / 补全菜单 |

### Slash 命令

| 命令 | 别名 | 说明 |
|------|------|------|
| `/help` | `/h`, `/?` | 显示帮助信息 |
| `/clear` | | 清除对话历史 |
| `/compact` | `/c` | 压缩上下文 |
| `/plan` | `/p` | 切换到 Plan 模式 |
| `/session` | | 会话管理（列表/恢复/删除） |
| `/memory` | | 记忆管理 |
| `/mcp` | | 查看 MCP 服务器状态 |
| `/permission` | | 权限规则管理 |
| `/status` | `/s` | 显示当前状态 |
| `/rewind` | | 回退到之前的对话节点 |
| `/tasks` | `/task` | 查看/取消后台任务 |
| `/trace` | `/tree` | 查看 Agent 父子追踪树 |
| `/worktree` | `/wt` | Git Worktree 管理 |
| `/skill` | `/skills` | 技能包管理 |
| `/review` | | 审查代码变更 |

### 文件 @ 引用

在输入框中输入 `@` 可以快速引用项目中的文件，支持自动补全。

```
帮我重构 @app.py 中的这个类
```

## 项目结构

```
mewcode/
├── pyproject.toml          # 项目元信息和依赖
├── uv.lock                 # 依赖锁文件
├── mewcode/
│   ├── __main__.py         # 入口：参数解析和启动
│   ├── app.py              # TUI 主应用（Textual App）
│   ├── agent.py            # 核心 Agent 引擎
│   ├── client.py           # LLM 客户端（Anthropic / OpenAI）
│   ├── config.py           # 配置加载和模型
│   ├── conversation.py     # 对话管理器
│   ├── prompts.py          # System Prompt 构建
│   ├── serialization.py    # 消息序列化
│   ├── validator.py        # 配置校验
│   ├── cache.py            # 文件缓存
│   ├── driver.py           # Textual Driver
│   ├── teammate_tree.py    # 队友树 UI 组件
│   ├── styles.tcss         # TUI 样式表
│   ├── agents/             # 子 Agent 系统
│   │   ├── loader.py       # Agent 加载器
│   │   ├── task_manager.py # 后台任务管理器
│   │   ├── trace.py        # Agent 追踪树
│   │   └── builtins/       # 内置 Agent 定义
│   ├── commands/           # Slash 命令系统
│   │   ├── registry.py     # 命令注册表
│   │   ├── completion.py   # 命令补全
│   │   └── handlers/       # 命令处理器
│   ├── context/            # 上下文窗口管理
│   ├── hooks/              # Hook 引擎
│   ├── mcp/                # MCP 协议支持
│   ├── memory/             # 记忆系统
│   ├── permissions/        # 权限系统
│   ├── skills/             # 技能系统
│   │   ├── loader.py       # 技能加载器
│   │   ├── executor.py     # 技能执行器
│   │   └── builtins/       # 内置技能包
│   ├── teams/              # Agent 团队协作
│   ├── tools/              # 工具系统
│   │   ├── agent_tool.py   # 子 Agent 调用工具
│   │   ├── team_create.py  # 创建团队工具
│   │   └── ...             # 其他内置工具
│   └── worktree/           # Git Worktree 管理
└── tests/                  # 测试
```

## 架构说明

架构审计、当前系统边界、源码证据和可渲染图的入口在
[`architecture/README.md`](architecture/README.md)。运行时源码统一位于
`mewcode/` 包内。

## 开发者

### 运行测试

```bash
uv run pytest
```

### 技术栈

- **TUI**: [Textual](https://textual.textualize.io/) — Python 终端 UI 框架
- **LLM SDK**: `anthropic` + `openai` — 双协议支持
- **序列化**: Pydantic — 配置和数据模型校验
- **包管理**: uv + hatchling

## Agent Runtime、可靠任务与 DAG 编排

除交互式 TUI 外，项目现在提供独立的 `AgentRuntime` 核心服务。Runtime 不依赖 Textual，能够持久化 Agent Run 快照和事件日志，支持取消、超时、重试、事件回放以及进程重启后的显式恢复。

安装可选服务依赖并启动 HTTP/SSE 适配层：

```bash
uv sync --extra server
uv run mewcode-server --host 127.0.0.1 --port 8765
```

启动后打开 <http://127.0.0.1:8765/> 可进入轻量 Web 控制台。控制台使用原生
HTML/JavaScript，无需单独构建前端，支持提交任务、查看运行历史、查看任务详情、
取消运行、重试失败任务，并通过 SSE 实时显示事件。

主要接口：

```text
POST /v1/runs                 提交 Agent 任务
GET  /v1/runs/{id}            查询任务状态
POST /v1/runs/{id}/cancel     取消任务
GET  /v1/runs/{id}/events     SSE 流式事件（支持 after 游标）
GET  /v1/runs                 运行历史（支持 status、limit 参数）
POST /v1/runs/{id}/retry      重试失败或取消的运行
```

Runtime 事件保存在 `.mewcode/runs/<run_id>.events.jsonl`，状态快照保存在同目录的 `<run_id>.json`。服务层通过 `mewcode.runtime.bootstrap.build_runtime()` 使用和 CLI 相同的 provider、权限、Session 和工具配置。

Agent 团队还提供 `DAGCreate` 和 `DAGStatus` 工具。DAG 节点可以声明 `depends_on`，就绪节点并行执行，依赖节点的输出自动注入下游 Prompt；运行快照保存在 `.mewcode/dag-runs/`。适合构建“探索 → 实现 → 测试 → 审查”的多 Agent 工作流。

论文复现 DAG 还提供确定性证据门：验证 Agent 的 `VERDICT: PASS` 只是必要条件，
系统会重新读取 `paper_repro/<slug>/protocol.md` 和结果 JSON，核对协议要求的距离
计算次数、数据行数与簇计数之和、以及 `algorithm_compliance` 是否与实际观测一致。
出现矛盾时 DAG 会失败并列出 `DISTANCE_MISMATCH`、`COUNT_MISMATCH` 或
`COMPLIANCE_MISMATCH`，避免模型仅凭文字报告误报成功。普通 DAG 没有协议文件时
不启用这层审计。

## KMeans 论文复现：一条命令完成四阶段

`paper_study_DAG` 分支新增固定流程入口：下载原文 → PaperSearch → PaperProtocol →
PaperStudy → Verification。程序固定依赖关系，模型负责前三阶段，最后由独立校验器
直接执行代码和数值验收，无需额外模型调用。

Windows / PowerShell（无需先安装 uv）：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[paper]"
.\.venv\Scripts\python.exe -m mewcode.paper_workflow --paper kmeans
```

如果已有通过 uv 创建的 `.venv`，可以使用：

```powershell
uv sync --extra paper
uv run --extra paper python -m mewcode.paper_workflow --paper kmeans
```

项目根目录 `.env` 中设置 `DASHSCOPE_API_KEY=你的百炼密钥`。入口自动加载 `.env`，
环境变量优先，默认使用百炼兼容接口和模型 `qwen3.7-flash-2026-07-15`。
可通过 `--model`、`--base-url` 覆盖模型及区域端点；这些参数仅作用于论文入口。
流程会执行模型生成的 Python 代码，请在用于论文实验的项目目录中运行。

每次默认创建新的 `paper_repro/kmeans_时间戳/`，也可用 `--output paper_repro/新目录`
指定目录。已有目录会被拒绝覆盖。失败返回非零退出码，详细过程在 `events.jsonl`
和 `.mewcode/dag-runs/<run_id>.json`，模型达到轮数上限会明确失败。
中途断网或额度不足时，可使用 `--output 原目录 --resume` 从检查点续跑：

```powershell
.\.venv\Scripts\python.exe -m mewcode.paper_workflow --output paper_repro/你的实验目录 --resume
```

续跑先检查源文件、数据和已完成协议的哈希；检索/协议/实现完成后，单独续跑验证
不需要模型 API。要重新生成实现，请开始新的实验目录。百炼返回
`AllocationQuota.FreeTierOnly` 表示免费额度耗尽，需要在百炼控制台调整额度设置后
才能启动新的模型阶段。

复现对象是 MacQueen (1967) 第 2.1 节在线 KMeans，以及第 3.4 节方环数据打乱实验：
150 个二维样本、12 个簇、1 组原始数据和 19 组维度打乱数据。随机种子 42 是本次
复现选择。原论文未公开样本/种子，因此复现方法与实验设计，并如实比较比值；
不宣称精确重现论文的 1.6 倍结果或完成论文中所有应用实验。

通过条件包含真实命令退出码、协议 SHA-256 保持一致、输入数据不变、20 组结果
与独立实现吻合，以及 7 个边界测试（并列距离、重复种子、k=1、n=k 和随机数据）。
`verification.json` 是最终验证记录，`execution.json` 保存程序再次执行的命令和输出，
`report.md` 是实验报告。下载的 PDF、抽取文本、协议、数据与生成代码均保留。

已有产物可离线重跑，不再调用 API（替换下面目录名）：

```powershell
.\.venv\Scripts\python.exe paper_repro/你的实验目录/run.py
.\.venv\Scripts\python.exe -m mewcode.kmeans_check paper_repro/你的实验目录
```

开发测试使用 `uv run pytest` 或项目虚拟环境中的 `python -m pytest`。
测试仅收集 `tests/`，避免历史实验的临时测试文件影响项目回归。

## License

MIT
