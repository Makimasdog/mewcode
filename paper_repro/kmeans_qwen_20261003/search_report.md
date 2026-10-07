# Search Report: MacQueen (1967) — Online K-Means Clustering

## Source Evidence
- **URL**: https://www.cs.cmu.edu/~bhiksha/courses/mlsp.fall2010/class14/macqueen.pdf
- **HTTP Status**: 200 (verified by local download)
- **PDF Page Count**: 17 (verified via PyPDF2 `len(reader.pages)`)
- **PDF Size**: 1,402,602 bytes (≈1.34 MB)
- **Local Copy**: `macqueen.pdf` + `macqueen_pages.txt`

## Sections Found

### 1. Introduction (p.1–2)
Purpose: describe a process for partitioning an N-dimensional population into k sets on the basis of a sample. Called "k-means." Minimises within-class variance W²(S). Applications include similarity grouping, nonlinear prediction, approximating multivariate distributions, nonparametric tests.

Key definitions:
- S = {S₁, S₂, …, Sₖ} a partition of ℝᴺ
- uᵢ = conditional mean of p over Sᵢ
- W²(S) = Σᵢ ∫_{Sᵢ} |z − uᵢ|² dp(z)

### 2. The k-means Process / Methodology

#### Section 2.1 — The k-means process (p.3)
**Core update rule (verbatim formula):**

For a given k-tuple X = (X₁, X₂, ..., Xₖ), xi ∈ ℝᴺ:
Define minimum distance partition S(x) by:
```
(2.1) Si(x) = Ti(x) \ S2(x) \ ... \ S_{k-1}(x)
where
(2.2) Ti(x) = {z : z ∈ ℝᴺ, |z − xi| < |z − xj|, j ≠ i}
```

Sample k-means initialization and sequential update:
```
x_i^1 = z_i,   W_i^1 = 1,   for i = 1, 2, ..., k

For n = 1, 2, ..., if z_{k+n} ∈ S_j(x^(n)):
    x_j^{n+1} = (W_j^n * x_j^n + z_{k+n}) / (W_j^n + 1)
    W_j^{n+1} = W_j^n + 1
    x_i^{n+1} = x_i^n            for i ≠ j
    W_i^{n+1} = W_i^n            for i ≠ j
```

Informal description: "starting with k groups each of which consists of a single random point, and thereafter adding each new point to the group whose mean the new point is nearest. After a point is added to a group, the mean of that group is adjusted in order to take account of the new point."

Additional formulas:
- W(X) = ∫ Σᵢ |z − xᵢ|² dp(z)
- V(X) = ∫ minⱼ |z − xⱼ|² dp(z)
- V(X) ≤ W(X) [since V uses min over all means, W sums deviation from assigned mean]

**Unbiasedness condition**: xᵢ is unbiased relative to πᵢ if xᵢ = uᵢ where uᵢ = ∫_{Sᵢ(x)} z dp(z) / πᵢ

#### Section 2.2 — Proofs (p.4–8)
Uses martingale theory (Lemma 3 after Doob). Key convergence result (formula 2.8):
```
E[W(x^{n+1}) | W_n] ≤ W(xⁿ) − Σᵢ E[|xᵢⁿ − uᵢⁿ|² · (pᵢⁿ)² · (2Wᵢⁿ + 1)/(Wᵢⁿ + 1)²] + O(n⁻¹)
```
Establishes almost sure (a.s.) convergence of W(xⁿ).

#### Section 2.3 — Examples (p.8)
Two-component mixture normal distribution example showing potential oscillation when cluster overlap is large.

### 3. Applications (p.9–12)

#### Program Modifications
Two parameters introduced:
- **C (coarsening threshold)**: If the nearest pair of centroids has distance < C, average them together using weights → reduces number of clusters.
- **R (refinement threshold)**: If within-group variation / between-group variation > R, split the largest group along direction of greatest spread → increases number of clusters.

Starts with user-specified k, takes first k points as initial means.

#### Computer Experiment 1: Semantic Differential Data (p.9–10)
Words like "calm, dusky, lake, peace, sleep, white" vs. "beggar, deformed, frigid, lagging, low" vs. "statue, sunlight, time, trees, truthful, wise."

#### Computer Experiment 2: Synthetic Classification (p.11–12)
- Sample size: 250 four-dimensional random vectors
- Each dimension independently uniformly distributed on integers 1–10
- Two dimensions selected; classification rule:
  - Point is class A if "high" (>5) on BOTH or "low" (≤5) on BOTH
  - Otherwise class B
- Result: 121 A's, 129 B's
- k=8 applied separately to A's and B's → 16 centroid vectors
- Prediction accuracy on new 250-point sample: 96%
- Standard error of estimate: 2.8

### References Mentioned
[F1] Fisher, W.D.
[F2] Cox, D.R.
[F3] Doob
[F4] Series convergence theorem reference
[F5] Blackwell
[F6] Fix and Hodges
[F11–F12] Marschak

---

**Sections NOT FOUND / BLOCKED:**
- No explicit hyperparameters table
- No experimental hardware specification
- No computational complexity analysis (only "computationally economical")
- Convergence rate bounds: mentioned as part of proof but no closed-form rate given
