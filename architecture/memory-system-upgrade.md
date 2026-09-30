# 记忆系统升级（第一阶段）

## 当前实现

长期记忆继续兼容以下 Markdown 文件：

- `~/.mewcode/memories.md`
- `<project>/.mewcode/memories.md`
- `~/.mewcode/memory/**/*.md`
- `<project>/.mewcode/memory/**/*.md`

会话记录仍然使用 JSONL，不属于长期记忆数据库。

## 结构化存储

第一阶段新增 SQLite 存储：

- 用户级：`~/.mewcode/memory.db`
- 项目级：`<project>/.mewcode/memory.db`

实现位于 `mewcode/memory/store.py`，由 `MemoryManager` 兼容门面调用。
数据库提供稳定 ID、作用域、类型、状态、置信度、来源字段和事件日志，
并在可用时启用 FTS5；不支持 FTS5 时自动回退到 `LIKE` 查询。

## 兼容模式

通过 `MEWCODE_MEMORY_MODE` 选择存储模式：

| 模式 | 行为 |
| --- | --- |
| `legacy` | 只读写 Markdown |
| `dual` | Markdown 与 SQLite 双写，读取时去重 |
| `structured` | SQLite 为主，Markdown 作为回退和迁移来源 |

默认使用 `dual`，因此已有项目无需迁移即可继续运行。数据库不可用时，
`MemoryManager` 保留 Markdown 路径，不阻塞主对话。

## 迁移和命令

`mewcode.memory.migration.import_legacy_memory` 支持扁平 Markdown 和带
frontmatter 的记忆文件，重复执行是幂等的，不会删除源文件。

新增命令：

```text
/memory import
/memory search <关键词>
/memory show <id>
/memory approve <id>
/memory reject <id>
/memory archive <id>
/memory forget <id>
```

现有的 `/memory list`、`/memory clear`、`/memory edit` 保持兼容。

## 尚未切换的能力

自动提取仍兼容旧版完整 `memories.md` 输出；JSON 候选记忆、冲突审核、
embedding 检索和向量索引留在后续阶段，避免改变现有 Agent 的调用契约。
