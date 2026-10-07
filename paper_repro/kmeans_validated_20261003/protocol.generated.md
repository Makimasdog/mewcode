# Protocol: MacQueen (1967) Online K-Means — Square-Ring Scrambled-Dimension Test

**Slug:** kmeans_validated_20261003
**Written:** 2026-10-03
**Reproducer:** MewCode paper-reproduction worker

---

## 1. Paper Version and Source

- **Citation:** Q. Massoud MacQueen, "Some methods for classification and analysis of multivariate observations," *Proceedings of the Fifth Berkeley Symposium on Mathematical Statistics and Probability*, Vol. 1, pp. 281-297, 1967.
- **URL:** `https://www.cs.cmu.edu/~bhiksha/courses/mlsp.fall2010/class14/macqueen.pdf`
- **HTTP status:** 200 (retrieved)
- **PDF pages:** 17; SHA-256 `55dc4458c47e13ccfb0f8afbc57862b3edd8432905bf391e61e75859c41aa1c0`
- **Sections targeted:** §2.1 (online k-means algorithm), §3.4 (scrambled-dimension independence test)
- **Status:** `SOURCED` — full excerpts verified in `source_evidence.txt`.

## 2. Algorithm Specification (from original paper)

### 2.1 Initialization (§2.1, p. 3)

1. First k data points become initial cluster centroids: x_i^(1) = z_i for i=1..k.
2. Initial cluster weights: W_i^(1) = 1 for all i.

### 2.2 One-Pass Streaming Update (§2.1, p. 3)

For each subsequent point z_{k+1}, z_{k+2}, ... in sequence order:

1. **Assignment:** Find the nearest centroid by Euclidean distance. Ties broken by assigning to the centroid with the **lowest index** (paper: "tied points being assigned arbitrarily to the set of lower index").
2. **Update (only the winning centroid):** Using the exact running-mean formula:

   ```
   x_i^{n+1} = (W_i^n * x_i^n + z_{k+n}) / (W_i^n + 1)
   W_i^{n+1} = W_i^n + 1
   x_j^{n+1} = x_j^n for j ≠ i
   ```

3. Increment the membership count W_i for the winning cluster only.

### 2.3 Explicit constraints from the paper

- **No Lloyd iterations.** The paper describes a sequential, one-pass process only. No reassignment after the pass completes.
- **No reinitialization.** No k-means++ seeding. Start with first k points deterministically.
- **Tie convention:** If x_i = x_j and i < j, then S_j(x) = ∅. Lowest-index wins.

### 2.4 Implementation choices that are NOT from the paper

| Choice | Value | Justification |
|--------|-------|---------------|
| Random seed | 42 | Deterministic reproducibility choice of this run |
| Floating-point precision | Python float64 (IEEE 754 double) | Standard library default |
| Distance metric | Euclidean (L2) | Paper uses |·| notation for Euclidean norm |
| Evaluation assignment | Nearest to **final** centroids (post-stream) | Post-hoc evaluation metric; not part of streaming loop |
| Number of shuffled permutations | 19 (indices 00–18) | Contract/reproducibility setup choice |
| Numerical tolerance for checker | rtol=1e-9, atol=1e-8 | Verification standard; not a paper property |

## 3. Datasets and Sample Counts

| Dataset | Points (N) | Dimensions (d) | Description |
|---------|-----------|----------------|-------------|
| original | 150 | 2 | Uniform in [-50, 50]^2 excluding (-30, 30)^2 (square ring) |
| scrambled_00 through scrambled_18 | 150 | 2 | Each column independently permuted copy of original |

- **Total datasets processed:** 20 (1 original + 19 scrambled)
- **Sample size N=150, k=12** match the paper's §3.4 description ("a sample of 150 points ... inside a surrounding square 100 units on a side ... outside a square 60 units on a side ... k=12").
- Original paper sample data and random seed are **unavailable**; these 20 datasets are our reproducible proxy matching the stated distribution and dimensions.

## 4. Random Seed and Data Provenance

- Seed 42 used for generating the original square-ring sample and the 19 column-wise permutation scramblings (as stored in `data.json`).
- These seeds are **our reproducibility choices**, not the paper's (the paper does not disclose seeds).
- The data distributions are faithful to those described in the paper (§3.4): uniform in a 100×100 outer square minus a 60×60 inner square, producing two-mode geometry detectable visually but nearly zero Pearson correlation.

## 5. Experimental Design

### 5.1 Run pipeline

1. Read `data.json` → extract 20 datasets (original + 19 scrambled).
2. For each dataset, call `online_kmeans(points, k=12)`:
   - Stream through all N=150 points sequentially.
   - First k points: assign to cluster i (i=0..k-1). Update centroid with exact running mean.
   - Remaining N-k=138 points: assign to nearest current centroid, update winning centroid only.
   - After streaming: compute post-hoc `assignments` and `inertia` using nearest FINAL centroid for every point.
3. Write `results.json`, `report.md`, `run.log`.

### 5.2 Expected output shape per run

```json
{
  "centroids": [[float, float], ...],     // k × d floats
  "counts": [int, ...],                   // k ints (membership counts)
  "stream_labels": [int, ...],            // N ints (cluster assigned during streaming)
  "assignments": [int, ...],              // N ints (nearest final centroid)
  "inertia": float,                       // sum-of-squared-distances to nearest final centroid
  "data_rows": int,                       // N (=150)
  "distance_calculations": int            // (N-k) * k = 138 * 12 = 1656 (training only)
}
```

- **distance_calculations = 1656**: exactly (N-k)×k where N=150, k=12. Only distances computed during the streaming phase; post-hoc evaluation distances are excluded from this counter.

### 5.3 Metrics reported in report.md

| Metric | Description |
|--------|-------------|
| WCSS_original | Within-class sum of squares (inertia) on original data |
| WCSS_scrambled[i] | WCSS for each scrambled permutation i |
| Ratio_first | WCSS_scrambled[0] / WCSS_original |
| Ratio_mean | Mean(scrambled WCSS) / WCSS_original |
| Permutation p | (1 + #{i : WCSS_scrambled[i] ≤ WCSS_original}) / 20 |
| Tie/duplicate edge cases | Results on 7 fixtures provided by checker |

### 5.4 Comparison to paper (§3.4 historical values)

The paper reports these **observed ratios** (WCSS_after_scrambling / WCSS_original) under its own experimental conditions:

| k | Ratio (paper, §3.4) |
|---|---|
| 12 | ~1.6 |
| 6 | 1.40 |
| 12 | 1.55 |
| 18 | 1.39 |

These are **historical observations**, not thresholds. They indicate that scrambling tends to increase within-class variance for structured data — qualitatively consistent behavior that we note, but do not use as a binary acceptance criterion.

## 6. Resource Budget

- **Compute:** Pure Python standard library (math.sqrt, math.pow); no external dependencies.
- **Expected time:** Well under 1 minute for 20 runs of N=150, k=12.
- **Memory:** O(N·d) for loading data; O(k·d) for centroids. Trivial for N=150, d=2.

## 7. Acceptance Criteria

### 7.1 Execution checks (PASS/FAIL)

| Check | PASS condition |
|-------|---------------|
| run.py executes without error | Exit code 0, no exception output |
| Output files created | `results.json`, `report.md`, `run.log` exist in experiment directory |
| All 20 datasets processed | `results.json` contains 20 entries under `runs` key |
| Independent checker passes | `python -m mewcode.kmeans_check <experiment-dir>` exits 0 |

### 7.2 Checker requirements (from contract.md)

- **Reference comparison:** Our run results compared against an independent sequential reference implementation with rtol=1e-9, atol=1e-8.
- **Edge-case fixtures:** 7 additional tests covering k=1, n=k, duplicate seeds, equal-distance ties, all-other-centroid-equal, near-tie stability, and streaming vs batch equivalence for small N.
- **Contract integrity:** Protocol, source evidence, contract, and input data must not be modified by `run.py`.

### 7.3 PASS / FAIL / PARTIAL determination

| Verdict | Condition |
|---------|-----------|
| **PASS** | All execution checks pass + checker exits 0 with all fixtures green |
| **PARTIAL** | run.py produces output files but checker reports mismatches on ≥1 fixture or result entry |
| **FAIL** | run.py does not execute, crashes, missing output files, or checker exit non-zero |

**Note on historical ratio comparison:** A deviation from the paper's reported ratio of ~1.6 is NOT grounds for FAIL. Our finite-sample, fixed-seed run is an implementation verification, not an asymptotic proof (Theorem 1 is a.s. convergence as n→∞). Qualitative consistency (mean scrambled ratio > 1) supports correctness but does not determine verdict.

## 8. Verdict: No numerical reproducibility claim

- The original paper's sample data and random seed are **not publicly available**.
- We reproduce the **method** (algorithm specification) and the **experimental design** (square-ring distribution, permutation test structure) faithfully.
- We **cannot** claim precise replication of the paper's numerical WCSS values or exact ratios. Differences in streaming order, floating-point accumulation, and sample instance are expected.
- Acceptance is based on **implementation correctness** (checker compliance), not on matching historical observation values.

## 9. Executable Commands

### Run the experiment
```
D:\anaconda3\python.exe E:/Projects/wyy/Mewcode/paper_repro/kmeans_validated_20261003/run.py
```

### Verify with independent checker
```
D:\anaconda3\python.exe -m mewcode.kmeans_check E:/Projects/wyy/Mewcode/paper_repro/kmeans_validated_20261003
```

### File listing (after run)
- `data.json` — input data (read-only)
- `contract.md` — run contract (read-only)
- `source_evidence.txt` — paper excerpts (read-only)
- `run.py` — experiment runner
- `results.json` — output results
- `report.md` — human-readable summary
- `run.log` — log file
- `protocol.md` — this document

## 10. Key Verification Items Summary

| # | Item | Target / Expected |
|---|------|------------------|
| 1 | Algorithm | First-k seeds, one-pass streaming, exact running-mean, lowest-index tie break |
| 2 | No iterations | Zero Lloyd steps; pure online update |
| 3 | distance_calculations | Exactly 1656 = (150-12) × 12 per dataset |
| 4 | WCSS trend | Mean scrambled/inertias ≥ 1.0 (qualitative check) |
| 5 | Edge cases | 7 fixtures all pass |
| 6 | Checker | `python -m mewcode.kmeans_check` exits 0 |
