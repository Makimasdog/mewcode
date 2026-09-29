# MewCode 结构审计

审计基线：`8aa1da6`（2026-09-28）。

## 1. 可直接删除的构建或测试临时产物

| 路径 | 判断依据 | 处理 |
| --- | --- | --- |
| `.archify/` | Archify 的候选 JSON、HTML、浏览器检查、源码快照和临时脚本；未被运行时代码引用 | 删除，并加入 `.gitignore` |
| `.qoder/` | Qoder 生成的 repowiki、缓存和索引；未被运行时代码或打包配置引用 | 删除，并加入 `.gitignore` |
| `docs/qgraphflow/` | 已提交的静态渲染 JSON/HTML；不被代码或文档入口引用，且图中 `sourceRef` 已落后于当前提交 | 删除，保留 DSL/DOT/Markdown 源视图 |
| `.pytest_cache/`、各级 `__pycache__/`、`*.pyc` | 测试和 Python 运行时缓存 | 本地删除；继续由 `.gitignore` 忽略 |
| `.venv/` | 本地依赖环境，不属于源码发布物 | 保留给当前工作区使用，不提交到 Git |
| `.gitignore` 中的 `memory` 裸模式 | 会把仍受版本控制的根目录兼容模块下的新文件静默隐藏 | 删除该模式；只忽略明确的运行时目录 `.mewcode/` |

同时保留 `.mewcode/`：它保存配置、会话、记忆、Run 和 DAG 状态，是运行时数据，不是临时构建产物。

## 2. 兼容性说明

| 内容 | 证据 | 结论 |
| --- | --- | --- |
| 根目录历史镜像 | 曾与 `mewcode/` 重复，且不属于 wheel 打包入口 | 已删除；运行时源码统一使用 `mewcode/` |
| `mewcode/conversation.py` 的旧字段同步逻辑 | 源码注释明确写有“向后兼容”，旧会话可能仍读取这些字段 | 保留，直到会话格式有迁移策略 |
| `mewcode/validator.py` 的 list 配置格式 | 校验器保留 list 形式的向后兼容入口 | 保留，并在配置迁移时再移除 |
| `mewcode/mcp/tool_wrapper.py` 的 `inputSchema` / `input_schema`、`mimeType` / `mime_type` 双字段读取 | MCP SDK 版本间字段命名不同；测试覆盖两种对象模型 | 保留，避免升级 SDK 后破坏工具注册和结果提取 |

其余兼容逻辑承担会话格式、配置格式和 MCP SDK 字段差异的兼容，不涉及源码目录镜像。

## 3. 需要合并或重写的说明文档

| 文档 | 问题 | 本次处理 |
| --- | --- | --- |
| `architecture/mewcode.architecture-understanding.md`、`mewcode.evidence.md`、`.dsl`、`.dot` | 原来是分散维护的架构说明，时间、入口和推断边界不一致 | 统一到同一提交基线，补充入口说明和证据索引 |
| `README.md`、`PROJECT_TUTORIAL.md`、`mewcode/README.md` | 同时承担产品介绍、教程和架构说明，容易重复或把镜像路径当成实现 | 架构事实集中到 `architecture/`；产品和教程只保留使用说明并链接架构入口 |
| `docs/qgraphflow/` | 只有渲染结果，没有稳定的源码维护入口 | 删除生成物；需要预览时从 DSL/DOT 或 Archify 候选重新生成 |

## 结论

发布和运行路径统一使用 `mewcode/`；生成物从仓库清除；
架构事实以 `architecture/` 下的 DSL、DOT、证据索引和入口说明组成的文档集为准。
