# paper_study_DAG：KMeans 复现修复验收

## 结论

- 分支：`paper_study_DAG`。
- 模型：百炼 `qwen3.7-flash-2026-07-15`，密钥从项目 `.env` 加载，未写入报告。
- 最终 DAG：`fe8432f22288`，四节点全部 `completed`。
- 独立执行的复现命令、数值验证命令退出码均为 **0**。
- 20 组实验、7 个边界用例及协议/输入哈希校验通过。
- 项目回归：`.venv/Scripts/python.exe -m pytest -q` → **586 passed, 1 skipped**。

## 实际运行经过

原来由父模型自由生成 DAG 时会遗漏节点或依赖，检索过程也会反复尝试 Windows
不支持的命令。新增固定 KMeans 入口，程序下载原文并保存证据，模型负责
PaperSearch、PaperProtocol、PaperStudy，Verification 由程序直接执行独立校验器。
审计绑定明确的实验目录，并在阶段间验证协议 SHA-256。

真实百炼运行 `d8190db16e8c` 完成前三阶段。独立检查器在实现阶段发现重复种子
的历史标签错误，模型修复后通过数值检查。原模型验证阶段随后遇到 HTTP 403
`AllocationQuota.FreeTierOnly`，未生成最终回复，因此原运行被如实保留为失败。

新增阶段检查点和 `--resume`，从原运行已完成的真实结果恢复前三阶段，最后由
程序再次执行生成代码和独立检查器。最终成功运行是一次续跑，未声称额度耗尽后
重新调用模型完成了一次从零运行。当前免费额度恢复前，不能重新生成新实验代码。

验收时对模型生成的协议做了文字勘误：作者为 J. MacQueen、正确列出实际边界
用例、区分方环与另一组五维实验的历史比值，以及消除重叠的判定文字。
原始协议保存在 `protocol.generated.md`，修订原因和前后哈希保存在检查点；
算法、种子、样本和数值容差未改变，修订后重新执行验证。

## 论文与复现范围

J. MacQueen, *Some Methods for Classification and Analysis of Multivariate
Observations*, 1967, Fifth Berkeley Symposium, vol. 1, pp. 281–297。

来源：<https://www.cs.cmu.edu/~bhiksha/courses/mlsp.fall2010/class14/macqueen.pdf>

实际下载 HTTP 200，PDF 17 页，SHA-256：
`55dc4458c47e13ccfb0f8afbc57862b3edd8432905bf391e61e75859c41aa1c0`。

复现第 2.1 节顺序 KMeans 和第 3.4 节方环实验：150 个二维样本、k=12、
外正方形边长 100、内正方形边长 60、一次顺序训练、19 次维度打乱。
随机种子 42 和本次样本顺序是复现设置。原论文没有公开原始样本/种子，
所以这是方法和实验设计复现，不涵盖论文的全部应用，也不宣称精确重现历史数值。

| 指标 | 实际结果 |
|---|---:|
| 原始数据 WCSS | 17375.2435207137 |
| 首次打乱 / 原始 WCSS | 1.0921712820 |
| 平均打乱 / 原始 WCSS | 1.1708871295 |
| 置换检验 p 值 | 0.20 |
| 论文方环实验报告比值 | 1.6 |

p=0.20 不足以在 0.05 水平拒绝独立性。通过表示算法与独立实现一致；
不表示本次样本重现了原论文的效果强度。

## 重跑

项目目录中直接执行，无需 API：

```powershell
.\.venv\Scripts\python.exe -m mewcode.paper_workflow --output paper_repro/kmeans_validated_20261003 --resume
```

仅重跑实验和检查：

```powershell
.\.venv\Scripts\python.exe paper_repro/kmeans_validated_20261003/run.py
.\.venv\Scripts\python.exe -m mewcode.kmeans_check paper_repro/kmeans_validated_20261003
```

恢复百炼可用额度后，从零运行：

```powershell
.\.venv\Scripts\python.exe -m mewcode.paper_workflow --paper kmeans
```

依赖与安装说明见项目 README；可选依赖组为 `paper`，生成的实验代码仅需 Python
标准库。检查点不会覆盖现有实验目录，输入或协议哈希不一致会拒绝续跑。

## 证据位置

`paper_repro/kmeans_validated_20261003/`：

- `paper.pdf` / `paper.txt` / `source.json` / `source_evidence.txt`：真实来源。
- `contract.md` / `protocol.md` / `checkpoint.json`：约定、协议、阶段记录与哈希。
- `run.py` / `data.json` / `results.json` / `report.md` / `run.log`：实验产物。
- `execution.json`：程序执行的真实参数、stdout、stderr、退出码。
- `verification.json`：最终数值验收、模型、Run ID、协议及输入哈希。
- `dag.json` / `dag_report.txt` / `events.jsonl`：DAG 状态和真实工具调用过程。

回归日志：`.mewcode/paper-regression-final.log`。测试只收集 `tests/`，避免历史
实验临时测试文件污染项目测试。修正了原有 Hook 测试对 POSIX `sleep` 的依赖和
后台任务未等待结束造成的 Windows 测试挂起。
