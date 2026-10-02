# 论文检索与选题记录

检索日期：2026-10-02。目标是复现经典 **k-means** 算法，而非后来的改进初始化或加速方法。

| 候选 | 可核查来源 | 与目标的关系 | 取舍 |
| --- | --- | --- | --- |
| J. MacQueen, “Some Methods for Classification and Analysis of Multivariate Observations,” *Proceedings of the Fifth Berkeley Symposium on Mathematical Statistics and Probability*, vol. 1, pp. 281–297, 1967 | [加州大学伯克利馆藏记录](https://digicoll.lib.berkeley.edu/record/113015)、[馆藏 PDF](https://digicoll.lib.berkeley.edu/record/113015/files/math_s5_v1_article-17.pdf)、[CMU 保存的公开 PDF](https://www.cs.cmu.edu/~bhiksha/courses/mlsp.fall2010/class14/macqueen.pdf) | 第 2.1 节明确给出逐点更新算法，第 3.2、3.4 节描述可重新生成的合成数据实验 | **选用**；CMU PDF 可访问并已阅读，17 页，SHA-256 为 `55dc4458c47e13ccfb0f8afbc57862b3edd8432905bf391e61e75859c41aa1c0`。伯克利 PDF 在本环境返回 HTTP 202，无法下载。 |
| S. P. Lloyd, “Least squares quantization in PCM,” *IEEE Transactions on Information Theory*, 28(2), pp. 129–137, 1982 | [Crossref DOI 记录](https://doi.org/10.1109/TIT.1982.1056489) | 经典批量重分配与重算中心方法；与 MacQueen 第 2.1 节的逐点更新不是同一算法 | 不选；此处要复现 MacQueen 原始 k-means 过程。未取得并阅读 Lloyd 全文。 |
| J. A. Hartigan and M. A. Wong, “Algorithm AS 136: A K-Means Clustering Algorithm,” *Applied Statistics*, 28(1), 1979 | [Crossref DOI 记录](https://doi.org/10.2307/2346830) | 后来的转移/快速转移优化算法 | 不选；并非 MacQueen 的原始过程。未取得并阅读该全文。 |

## MacQueen 原文证据

- 第 2.1 节，印刷页 283：以样本前 k 个点初始化中心，各组权重为 1；后续点归入最近中心，更新该组的均值和权重。距离相等时分配给序号较低的组。论文称这些中心始终是其所代表组的均值。
- 第 3.2 节，印刷页 291：生成 250 个四维向量，各维独立均匀取整数 1–10；任选两维，同为高值（>5）或同为低值（≤5）标为 A，否则为 B。原文训练样本有 121 个 A、129 个 B；分别求 A、B 的 k=8 个中心，再对新生成的 250 个点按最近中心预测，报告 87% 正确率。
- 第 3.4 节，印刷页 292：生成 150 个二维点，均匀分布于边长 100 的外方形、边长 60 的内方形之外；以 k=12 聚类，再独立打乱各维的对应关系，比较打乱前后组内方差。原文对单次样本报告方差增加 1.6 倍。

原文没有给出伪随机种子、随机数发生器或逐点样本，因此无法逐数复现 87% 与 1.6。第 3.1 节还介绍了另加合并阈值 C 和细分阈值 R 的应用程序；本复现明确选择第 2.1 节的基础过程，不把 C/R 变体混入上述实验。
