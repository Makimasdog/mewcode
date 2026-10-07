# Protocol: Reproduce MacQueen (1967) Online K-Means

## 1. Objective
Reproduce J. MacQueen's (1967) **online/sequential k-means clustering** algorithm as described in *"Some Methods for Classification and Analysis of Multivariate Observations," Fifth Berkeley Symposium, pp. 281–297.*

## 2. Source Evidence
All algorithmic details derive verbatim from the local PDF `macqueen.pdf` (HTTP 200, 17 pages, verified via PyPDF2). See `search_report.md`.

## 3. Algorithm Specification (from Section 2.1)

### 3.1 Initialization
Given user-specified number of clusters **k**:
- Read first k data points z₁, z₂, ..., zₖ
- Set initial centroids: **xᵢ¹ = zᵢ** for i = 1, 2, ..., k
- Set initial weights: **Wᵢ¹ = 1** for all i

### 3.2 Sequential Update Rule (for n = 1, 2, 3, ...)
For each subsequent point z_{k+n}:

1. **Assign** z_{k+n} to the nearest centroid cluster j where:
   ```
   |z_{k+n} − xⱼⁿ| ≤ |z_{k+n} − xᵢⁿ|  for all i ≠ j
   ```
   (ties broken arbitrarily — we break by smallest index)

2. **Update** centroid j and its weight:
   ```
   xⱼⁿ⁺¹ = (Wⱼⁿ · xⱼⁿ + z_{k+n}) / (Wⱼⁿ + 1)
   Wⱼⁿ⁺¹ = Wⱼⁿ + 1
   ```

3. **Leave unchanged** all other centroids and weights:
   ```
   xᵢⁿ⁺¹ = xᵢⁿ   for i ≠ j
   Wᵢⁿ⁺¹ = Wᵢⁿ   for i ≠ j
   ```

### 3.3 Within-Class Variance (WCSS)
After processing N total points, compute:
```
WCSS = Σᵢ Σ_{z ∈ Cᵢ} |z − xᵢ|²
```
where Cᵢ is the set of points assigned to centroid i.

This corresponds to formula W(X) = ∫ Σᵢ |z − xᵢ|² dp(z) from the paper.

## 4. Synthetic Dataset

We implement TWO test cases, both from the computer experiments in the paper:

### Test Case A — Semantic Differential Analogue (conceptual)
The semantic differential example cannot be faithfully reproduced without original Swarthmore College data. This test serves only to validate the algorithm runs correctly. We skip quantitative comparison.

### Test Case B — 4D Uniform Classification (from paper, Section "Computer Experiment")

**Dataset Generation:**
- Sample size: **N = 250**
- Dimensionality: **d = 4**
- Each dimension independently uniformly distributed on integers {1, 2, ..., 10}
- Label assignment (this defines two classes for later evaluation):
  - Class A: high (>5) on BOTH dims 0 and 1, OR low (≤5) on BOTH dims 0 and 1
  - Class B: otherwise (mixed)

**Note:** The label assignment is used ONLY for evaluation purposes (to compare with the paper's claimed result), NOT during clustering itself. The clustering is purely unsupervised.

### Test Case C — Extended Validation (additional experiment)

To verify robustness beyond the paper's single experiment:
- N = 500, d = 3
- Three Gaussian clusters in ℝ³:
  - Cluster 1: mean=(2, 2, 2), cov=0.5·I
  - Cluster 2: mean=(-2, -2, -2), cov=0.5·I
  - Cluster 3: mean=(2, -2, 2), cov=0.5·I
- Labels are known; use for separate supervised comparison only

## 5. Hyperparameters

| Parameter | Value (Test B) | Value (Test C) |
|-----------|----------------|----------------|
| k (clusters) | 8 | 3 |
| Seed | 42 | 42 |
| Point order | sequential (as given) | sequential (shuffle first if desired) |
| Tie-breaking | smallest cluster index | smallest cluster index |

## 6. Evaluation Metrics

1. **WCSS trajectory** — WCSS value after every batch of 50 points processed (log for analysis)
2. **Final WCSS** — computed on training data (all points) after algorithm finishes
3. **Cluster inertia per centroid** — sum of squared distances from points to their centroid
4. **Separation** — minimum pairwise distance between final centroids
5. **Empty cluster check** — no centroid should have W=0 (no assigned points)
6. **Centroid stability** — change in centroids between consecutive updates

### Pass/Fail Criteria (each must be met)

| # | Criterion | Threshold | Type |
|---|-----------|-----------|------|
| PC1 | Algorithm completes without error | exit code 0 | HARD |
| PC2 | No empty clusters at end | min weight ≥ 1 | HARD |
| PC3 | Final centroids differ from initialization | max centroid shift > 0 | HARD |
| PC4 | WCSS decreases monotonically after burn-in (first 10 points) | d(WCSS)/dt ≤ 0 for t≥10 | SOFT |
| PC5 | Centroids converge (last 10% of updates have < 5% centroid shift) | relative shift < 0.05 | SOFT |
| PC6 | Test B: prediction accuracy ≥ 90% on held-out sample | accuracy ≥ 0.90 | HARD |
| PC7 | Test B: final WCSS < 10000 | WCSS < 10000 | HARD |
| PC8 | Deterministic reproducibility — running twice with same seed gives identical results | exact match | HARD |

## 7. Implementation Requirements

- Language: Python 3.x
- Dependencies: numpy only (no ML libraries — this is from 1967, keep it simple)
- All files under `paper_repro/kmeans_qwen_20261003/`

## 8. Executable Command

```bash
cd paper_repro/kmeans_qwen_20261003
python macqueen_kmeans.py
```

Expected outputs:
- `results.json` — structured JSON with all metrics
- `log.txt` — human-readable step-by-step log
- `centroids_final.npy` — numpy array of final centroids [k, d]
- `assignments_final.npy` — numpy array of point assignments [N,]
- `verify.sh` — script to rerun and check outputs

## 9. Verification Procedure

Run:
```bash
cd paper_repro/kmeans_qwen_20261003
python macqueen_kmeans.py && python verify_outputs.py
```

Check:
1. All output files exist
2. results.json parses and contains required fields
3. PC1-PC8 criteria checked by verify_outputs.py
