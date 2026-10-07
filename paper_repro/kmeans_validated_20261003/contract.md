# KMeans reproduction test contract (choices for this run, not historical facts)
Scope: reproduce MacQueen (1967) section 2.1 online method and section 3.4 square-ring
scrambled-dimension experiment. Do not claim reproduction of every theorem/application.
Source: paper.pdf, paper.txt, source.json, source_evidence.txt; verify against original excerpts.
Data: data.json has {seed:42, k:12, datasets:{original:[[x,y],...], scrambled_00:...,
through scrambled_18:...}}. Each dataset has 150 points. Original is uniform in
[-50,50]^2 excluding (-30,30)^2. Each scrambled column is a permutation of an
original column. N=150, k=12 and square side lengths 100 and 60 come from section 3.4.
Seed 42, 19 permutations and this exact sample/order are our reproducibility choices.
Original paper sample and seed are unavailable. Ratio 1.6 is a historical comparison,
NOT a PASS threshold. A finite run cannot prove asymptotic convergence.

Implement run.py with online_kmeans(points, k) returning a JSON-compatible dict:
centroids (k by d floats), counts (online membership counts, including first k seeds),
stream_labels (n ints; first k are 0..k-1), assignments (n ints, nearest FINAL center),
inertia (sum squared distance to nearest FINAL center), data_rows (n),
distance_calculations ((n-k)*k, ONLY training distances; evaluation excluded).
Initial centers=first k points, initial counts=1, tie=lowest index, one pass over the
remaining points, update only the chosen center with its exact running mean.
Do not add Lloyd iterations, k-means++, reinitialization, or repeated training passes.
Use Python standard library. No dependency installation. Paths relative to __file__.
online_kmeans must also support k=1, n=k, duplicate seeds, and equal-distance ties.

Running run.py reads data.json and writes results.json={runs:{name:online_kmeans result}}
for all 20 datasets. Use if __name__ == '__main__' so import does not run experiments.
Also write report.md (observed metrics, comparison to paper, limitations) and run.log.
Report WCSS original, first and mean scrambled/original ratios, and permutation p
=(1 + number of scrambled WCSS <= original WCSS)/20. Do not tune seed to match 1.6.

PASS means successful execution, files present, all 20 results matching an independent
sequential reference and 7 tie/duplicate/random edge fixtures (rtol=1e-9, atol=1e-8).
Protocol, source, contract and input data must not be changed by implementation.
The independent checker is python -m mewcode.kmeans_check <experiment-directory>.
