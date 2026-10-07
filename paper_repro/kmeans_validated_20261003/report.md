# Report: MacQueen (1967) Online K-Means — Square-Ring Scrambled-Dimension Test

## Metrics

| Metric | Value |
|--------|-------|
| WCSS_original | 17375.243521 |
| Ratio_first (scrambled_00 / original) | 1.092171 |
| Ratio_mean (mean scrambled / original) | 1.170887 |
| Permutation p | 0.2000 |
| Paper reported ratio (k=12) | ~1.6 |

## Scrambled WCSS values

| Dataset | Inertia | Ratio vs Original |
|---------|---------|-------------------|
| scrambled_00 | 18976.741992 | 1.092171 |
| scrambled_01 | 19890.739604 | 1.144775 |
| scrambled_02 | 16830.474182 | 0.968647 |
| scrambled_03 | 19339.402064 | 1.113044 |
| scrambled_04 | 20058.495417 | 1.154430 |
| scrambled_05 | 22721.125280 | 1.307672 |
| scrambled_06 | 21592.318894 | 1.242706 |
| scrambled_07 | 19708.641778 | 1.134294 |
| scrambled_08 | 25406.332570 | 1.462214 |
| scrambled_09 | 20131.500492 | 1.158631 |
| scrambled_10 | 19931.223938 | 1.147105 |
| scrambled_11 | 16912.106602 | 0.973345 |
| scrambled_12 | 17036.166600 | 0.980485 |
| scrambled_13 | 18358.705827 | 1.056601 |
| scrambled_14 | 24845.798645 | 1.429954 |
| scrambled_15 | 21216.062553 | 1.221051 |
| scrambled_16 | 19666.706889 | 1.131881 |
| scrambled_17 | 25703.652068 | 1.479326 |
| scrambled_18 | 18218.335796 | 1.048523 |

## Comparison to Paper (§3.4)

The paper reports 1.6 for the 2D square-ring example at k=12; its 1.40, 1.55 and 1.39 ratios concern a separate 5D sample. Our finite-sample, fixed-seed run is an implementation verification; differences in sample instance, floating-point accumulation, and streaming order are expected.

Qualitatively, scrambling dimensions should increase within-class variance on average in the paper proposal. Here p=0.20 does not reject independence at 0.05. An increased mean ratio does not by itself prove correctness and is not used as a binary acceptance criterion.

## Limitations

- Original paper sample data and random seed are **unavailable**. We use seed 42 to generate a structurally faithful proxy.
- No Lloyd iterations, no reinitialization — strictly one-pass streaming.
- Numerical precision: Python float64 (IEEE 754 double).
- Acceptance based on **checker compliance** (rtol=1e-9, atol=1e-8) rather than matching historical WCSS values.

## Files

- `run.py` — this implementation
- `data.json` — input data (read-only)
- `results.json` — all 20 run outputs
- `report.md` — this file
- `run.log` — execution log
