# MacQueen (1967) k-means 检索与复现

本目录复现 MacQueen 原文第 2.1 节的**逐点** k-means 算法，以及第 3.2、3.4 节中可重新生成的两个合成实验。检索及原文依据见 [sources.md](sources.md)，实施前固定的样本规则、指标与阈值见 [protocol.md](protocol.md)。实施前保存的协议原始字节 SHA-256 为 `f04e9642d61bcecb3ae116985e47b6d5b1c722dd56c0b429f46e3aa43bad0df7`。校验时统一换行为 LF，得到可跨系统复核的 SHA-256 `ffcb257ec4538f85e471221b256825e193b2e43d0230d0a1486ff6a1c422288f`；协议内容及阈值未改动。

## 运行

在仓库根目录，使用 Python 3.11 或更新版本；只用标准库：

```powershell
python paper_repro/kmeans_classic/run_experiments.py --output paper_repro/kmeans_classic/results.json
python paper_repro/kmeans_classic/verify.py
```

实际完整运行的命令、Python 版本、标准输出与退出码记录在 [run.log](run.log)；独立重算记录在 [verification.log](verification.log)。逐种子数据和 16 个分类中心均在 [results.json](results.json)。

## 本次结果

| 检查 | 本次结果 | 预先阈值 | 判定 |
| --- | ---: | ---: | --- |
| 手算样例及平局规则 | 均吻合 | 均吻合 | 通过 |
| 相关分类准确率 | 229/250 = 91.6% | ≥ 75% | 通过 |
| 相对多数类基线提升 | 40.8 个百分点，基线 50.8% | ≥ 10 个百分点 | 通过 |
| 方环打乱后方差比中位数 | 1.187858 | ≥ 1.10 | 通过 |
| 方差比大于 1 的次数 | 27/30 | ≥ 21/30 | 通过 |

**VERDICT: PARTIAL。** 方法与预设趋势检查通过。论文仅给出一次实验的 87% 和 1.6，未给出原始样本、随机数发生器和种子，因此无法逐数复现这些历史结果。本实验采用事先写明的新样本和种子，不能把 91.6% 或 1.187858 当作原文数值的验证。

曾尝试让 `paper_study_coordinator` 通过真实百炼模型完成完整流程；该次运行在多轮 PaperSearch 截断摘要及阶段文件读取失败后中止，没有产出协议或代码。失败日志保存在仓库本地的 `.mewcode/paper-study-kmeans-20261002/run.log`。本目录成果是在保留该证据后手动完成、执行并独立核验的，不代表协调者已成功完成流程。
