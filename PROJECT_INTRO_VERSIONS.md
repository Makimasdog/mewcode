# MewCode 项目介绍版本

## 版本一：精简版

**AI 应用开发（项目时间按实际填写）**

**项目简介：**参考 Claude Code 架构实现 MewCode 终端 AI 编程助手，基于 Agent 决策循环与 Tool Calling 构建任务执行闭环，集成多模型适配、Skill、上下文压缩、Memory、MCP、Multi-Agent 协作和权限安全机制，提升复杂代码任务的执行效率与稳定性。

**技术栈：**Python、Textual、Anthropic/OpenAI SDK、MCP、Pydantic、asyncio、Git Worktree、pytest

**技术亮点：**

- **统一模型适配：**兼容 Anthropic、OpenAI 及兼容协议，统一处理流式输出、工具调用和 Token 统计。
- **Agent 执行闭环：**实现“模型推理—Tool Calling—结果回写—持续迭代”，支持文件操作、命令执行、MCP 和 Skill 扩展。
- **上下文与记忆管理：**通过长期记忆、自动压缩、工具结果缓存和会话恢复，提升长任务处理稳定性并降低 Token 消耗。
- **Multi-Agent 与安全控制：**支持子 Agent、团队协作和 Git Worktree 隔离开发；结合权限模式、沙箱、危险命令检测、Hook 和人工确认保障执行安全。

## 版本二：标准版

**AI 应用开发（项目时间按实际填写）**

**项目简介：**参考 Claude Code 架构设计并实现 MewCode 终端 AI 编程助手，基于 Python + Textual 构建交互式 TUI，通过 Agent 决策循环和 Tool Calling 实现“代码理解—工具调用—结果反馈—持续迭代”的任务闭环。项目支持 Anthropic、OpenAI 及兼容协议，集成 MCP 外部工具、Skill 扩展、长期记忆、上下文压缩、Multi-Agent 协作和 Git Worktree 隔离开发，面向代码生成、重构、测试、审查等开发场景。

**技术栈：**Python 3.11+、Textual、Rich、Anthropic SDK、OpenAI SDK、MCP、Pydantic、PyYAML、asyncio、Git Worktree、pytest、uv

**技术亮点：**

- **统一模型适配：**设计 `LLMClient` 抽象层，兼容 Anthropic、OpenAI 和 OpenAI-compatible API，统一处理流式文本、思考内容、工具调用、停止原因和 Token 统计。
- **Agent 执行闭环：**实现模型推理、工具调用、权限检查、结果回写和多轮迭代流程，支持文件读写、命令执行、代码搜索、测试运行、MCP 和 Skill 等工具。
- **上下文与记忆管理：**通过长期记忆、工具结果缓存、自动上下文压缩和会话恢复机制，降低长对话中的上下文溢出风险，提升复杂任务的连续执行能力。
- **Multi-Agent 协作：**支持 Explore、Plan、General-purpose、Verification 等子 Agent，以及 Coordinator/Teammate 团队模式；结合 Git Worktree 实现并行任务的目录和分支隔离。
- **权限与安全控制：**结合权限模式、路径沙箱、危险命令检测、Hook 拦截和人工确认，对模型生成的文件修改、命令执行及外部 MCP 工具调用进行多层风险控制。

## 版本三：详细版

**AI 应用开发（项目时间按实际填写）**

**项目简介：**参考 Claude Code 的产品形态与架构思路，设计并实现 MewCode 终端 AI 编程助手。项目基于 Python、Textual 和异步事件循环构建交互式 TUI，通过 Agent 决策循环连接大模型、工具和本地代码仓库，形成“Prompt 构建—模型推理—Tool Calling—权限审查—工具执行—结果回写—持续迭代”的任务执行闭环。系统支持多模型供应商、MCP 外部工具、Skill 扩展、会话持久化、长期记忆、上下文压缩、子 Agent 团队协作和 Git Worktree 隔离开发，可用于代码探索、功能实现、重构、测试和代码审查等复杂开发任务。

**技术栈：**Python 3.11+、Textual、Rich、asyncio、Anthropic SDK、OpenAI SDK、MCP SDK、httpx、Pydantic 2、PyYAML、JSONL、Git Worktree、pytest、pytest-asyncio、uv

**技术亮点：**

- **多模型协议适配：**设计统一 `LLMClient` 和流式事件模型，屏蔽 Anthropic、OpenAI 及 OpenAI-compatible API 在请求格式、流式事件、工具调用和 Token 统计方面的差异，使 Agent 核心逻辑与具体模型供应商解耦。
- **可扩展工具体系：**基于 Tool Registry 统一注册内置工具、MCP 工具、Skill 和 Agent 工具；MCP 支持 stdio 与 Streamable HTTP 两种连接方式，便于接入本地进程和远程工具服务。
- **Agent 任务执行闭环：**实现模型响应解析、工具参数校验、权限判断、工具执行、错误反馈和多轮重试；针对只读任务进行受控并行，对文件写入、命令执行等副作用操作默认采用串行策略，降低竞态风险。
- **分层上下文治理：**在接近上下文窗口上限时触发自动压缩，将历史消息和大体积工具结果进行摘要、裁剪与缓存，并通过 `compact_boundary` 支持会话恢复，在保证信息可追溯性的同时控制 Token 成本。
- **长期记忆与会话持久化：**将用户偏好、项目约定和执行经验沉淀为可复用记忆，并以 JSONL 记录用户消息、模型响应、工具结果和压缩边界，支持跨会话恢复与审计。
- **Multi-Agent 协作与隔离：**提供 Explore、Plan、General-purpose、Verification 等子 Agent，并支持 Coordinator/Teammate 团队模式；结合 Git Worktree 为并行任务创建独立目录和分支，降低代码覆盖和协作冲突。
- **多层权限与安全审查：**通过 `default`、`accept-edits`、`plan`、`bypass` 等权限模式，结合路径沙箱、危险命令识别、Hook 拦截和 Human-in-the-loop 确认，对模型生成的高风险操作进行分层控制。
- **交互与自动化双模式：**基于 Textual 提供流式输出、命令补全、文件 `@` 引用和权限弹窗，同时支持 CLI 非交互模式，满足本地开发、脚本调用和 CI 自动化场景。

## 使用建议

- **简历空间有限：**优先使用版本一。
- **常规项目经历：**推荐使用版本二。
- **面试、述职或技术分享：**使用版本三，并结合个人实际负责模块补充代码细节和结果数据。

> 项目时间、性能指标、成本下降比例等内容请根据真实经历填写，不建议虚构量化数据。
