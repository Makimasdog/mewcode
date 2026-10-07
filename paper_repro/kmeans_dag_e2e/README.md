# MacQueen's (1967) k-means Algorithm - Exact Implementation

This directory contains the exact implementation of MacQueen's (1967) k-means algorithm as specified in the digest step.

## Implementation Details

✅ **Initialization**: Uses the first `k` points as initial centroids
✅ **One-by-one assignment**: Processes each remaining point in order
✅ **Immediate centroid update**: Updates only the assigned centroid using the online formula: `μ_j ← (n_j × μ_j + x_t) / (n_j + 1)`
✅ **Single-pass**: Terminates after one full pass with no convergence loop

## Key Characteristics

- **Order-dependent**: Results depend on input point ordering
- **No batch iteration**: Unlike Lloyd's algorithm, no re-assignment passes
- **Deterministic initialization**: First-k seeding (no random_state parameter)
- **Online algorithm**: Processes points sequentially without storing all data

## Files

- `paper_repro_kmeans_macqueen.py`: Core implementation
- `run_final.py`: Verification script with metrics
- `requirements.txt`: Dependencies

## Verification Command and Output

**Command**: `python paper_repro\kmeans_dag_e2e\run_final.py`

**Exit code**: 0 (success)

**Raw output**: See below

```
MACQUEEN'S (1967) K-MEANS ALGORITHM - EXACT IMPLEMENTATION
=================================================================
Command: python paper_repro\kmeans_dag_e2e\run_final.py
Date: 2026-10-02 22:00:55
Working directory: E:\Projects\wyy\Mewcode
Input data shape: (150, 2)
Number of clusters (k): 3

METRICS:
------------------------------
WCSS: 713.343961
Execution time: 3.09 ms
Points per cluster: {0: 15, 1: 110, 2: 25}

FINAL CENTROIDS:
------------------------------
Centroid 0: [0.112197, -0.927180]
Centroid 1: [2.792631, 1.854436]
Centroid 2: [-0.518384, 0.507015]

VERIFICATION OF MACQUEEN'S SPECIFICATION:
---------------------------------------------
[OK] Initialization: First k points used as initial centroids
[OK] One-by-one assignment: Each point processed in order
[OK] Immediate centroid update: Incremental formula applied after each assignment
[OK] Single-pass: No batch iteration or convergence loop

First 15 assignments: [0 1 2 1 2 2 0 2 2 0 1 0 2 2 2]
Last 15 assignments: [1 1 1 1 1 1 1 1 1 1 1 1 1 1 1]
```

## Metrics Summary

- **WCSS**: 713.343961
- **Execution time**: 3.09 ms
- **Cluster distribution**: {0: 15, 1: 110, 2: 25}
- **Centroids**: [[0.112197, -0.927180], [2.792631, 1.854436], [-0.518384, 0.507015]]

## Compliance Verification

All MacQueen-specific requirements are satisfied:
- No Lloyd's batch iteration
- Exact incremental centroid update formula
- Deterministic first-k initialization
- Single-pass processing
- Order-dependent behavior confirmed by assignment pattern