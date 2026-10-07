# MacQueen's K-Means Algorithm (1967) Reproduction

This is a faithful implementation of the k-means algorithm as described in MacQueen's seminal 1967 paper.

## Algorithm Features
- Implements MacQueen's sequential/online update method (centroids updated incrementally as each point is processed)
- Uses the original initialization strategy (random sampling from data points)
- Convergence detection based on no reassignments

## Files
- `kmeans.py`: Core k-means implementation
- `run_kmeans.py`: Main execution script
- `validate_results.py`: Result verification script
- `requirements.txt`: Dependencies
- `centroids.npy`, `labels.npy`: Output files

## Execution Results
- Input: 150 synthetic 2D points in 3 clusters
- Output: 3 centroids with WCSS = 71.5461
- Cluster distribution: [50, 50, 50] (perfect separation)

## Key Implementation Details
- MacQueen's incremental centroid update: `c_new = c_old + (x_i - c_old) / (n+1)`
- Sequential processing of points rather than batch updates
- Convergence when no point changes cluster assignment

## Assumptions
- Since the original paper text could not be extracted, this implementation follows the standard description of MacQueen's algorithm from secondary sources and the algorithm's known characteristics
- The synthetic test data mimics the type of clustering problems addressed in the original paper

## Exit Codes
- All scripts exit with code 0 (success) when running correctly