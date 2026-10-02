# paper_study_DAG MacQueen/k-means Agent 测试报告

本报告只记录 `paper_study_DAG` 分支上的 DAG 工作流测试。没有把手工实现当作复现结果。

## 测试过程

| Run ID | 结果 | 发现 |
|---|---|---|
| `14e1e45b900e` | 失败 | 默认权限模式在非交互运行中无法批准 `DAGCreate`。 |
| `1a007109622c` | 误报完成 | 子 Agent 生成了代码，但验证脚本在 Windows GBK 下因 `✓` 退出码为 1；Verification 仍返回 `PASS`。 |
| `76da3ea42be4` | 失败（修复前） | Search/Digest 明确没有算法协议，PaperStudy 仍凭标准 k-means 常识实现；Verification 只复述上游报告并返回 `PASS`。 |
| `ad83c37c9cf3` | 失败但暴露新问题 | Search/Digest 无法提取协议；当时 PaperStudy 仍继续实现，Verification 的无命令 `PASS` 被拦截。随后补充了更严格的证据标记和“无法提取”阻塞词。 |
| `6d578cfe8b90` | 正确失败 | Search/Digest/Reproduce 完成；Verification 只返回 `PASS`，没有 `COMMAND`/`EXIT CODE` 字段，被证据门拒绝。 |

## 修复内容

- DAG 节点强制前台执行，并拒绝后台任务句柄；`enable_fork` 不再覆盖 `force_foreground`。
- 非交互父 Agent 的 `dontAsk` 权限传递给 DAG 子 Agent。
- PaperSearch 必须给出 HTTP 状态、PDF 页数和两个分节的原文摘录字段；缺失即失败。
- PaperStudy 遇到“无协议/无法提取/没有算法内容”等上游证据时停止，不得用标准算法补全。
- Verification 的 `PASS` 必须包含实际可执行命令和退出码，否则 DAG 失败。
- Verification 输出固定的 `COMMAND:`、`EXIT CODE:`、`FILES:` 字段，便于审计。
- 主进程和内置论文 Agent 约束 Windows 输出使用可编码文本，避免 GBK 编码异常。

## 验证结果

```text
python -m pytest -q --disable-warnings
483 passed, 81 skipped
```

新增 DAG 回归测试覆盖：前台执行、证据不足阻塞、验证命令证据门。
