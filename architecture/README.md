# MewCode 架构说明入口

本文档目录只保留经过源码核对的架构视图。运行时代码的权威位置是
`mewcode/`；根目录不再保留历史源码镜像。

## 阅读顺序

1. [`mewcode.architecture-understanding.md`](mewcode.architecture-understanding.md)：系统边界、入口、核心链路和限制。
2. [`mewcode.evidence.md`](mewcode.evidence.md)：节点、关系和持久化行为的源码证据。
3. [`mewcode.structurizr.dsl`](mewcode.structurizr.dsl)：C4 的可渲染源文件。
4. [`mewcode-runtime-topology.dot`](mewcode-runtime-topology.dot)：三种进程入口、本地文件和外部网络的运行时拓扑。

## 当前系统边界

```text
用户 / 脚本
    ├─ mewcode                 → Textual TUI 或 -p 无头执行
    └─ mewcode-server          → FastAPI/SSE 运行时接口（可选依赖）
                                  │
                                  ▼
                         Agent Engine（进程内复用）
                    prompt → LLM → permission/hook → tool → loop
                       │          │                 │
                       ▼          ▼                 ▼
                 Conversation  Provider API     工作区、MCP、
                 / Context     Anthropic/OpenAI  子 Agent、团队、Skill
                       │
                       ▼
                 .mewcode/（JSON、JSONL、YAML）
```

`mewcode/__main__.py` 和 `mewcode/runtime/bootstrap.py` 都会装配 Agent，
但三种入口并不共享完全相同的工具注册和交互能力。`AgentRuntime` 是可选的
后台运行服务，不是所有 CLI/TUI 请求的统一启动器。

## 维护规则

- 代码引用统一使用 `mewcode/...`，运行时源码也统一位于该包内。
- DSL 和 DOT 是人工维护的源视图；生成的 HTML、JSON、浏览器检查结果放在
  `.archify/`，不提交到仓库。
- 新增架构事实时，先在 `mewcode.evidence.md` 添加源码证据，再修改 DSL 或叙述。
- 没有源码或配置证据的调用方、部署环境和协议必须标记为推断，不能写成已实现能力。
- `.mewcode/` 是运行时数据目录，不能当作构建缓存删除。
