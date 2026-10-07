import numpy as np


def macqueen_kmeans(points, k, seed=None):
    """
    MacQueen's (1967) k-means algorithm - online, single-pass.

    Parameters:
    -----------
    points : np.ndarray, shape (n_samples, n_features)
        Input data points
    k : int
        Number of clusters
    seed : int, optional
        For reproducibility (though MacQueen's is deterministic given input order)

    Returns:
    --------
    centroids : np.ndarray, shape (k, n_features)
        Final centroids
    labels : np.ndarray, shape (n_samples,)
        Cluster assignments for each point
    """
    n_points, n_features = points.shape

    # Validate input
    if k <= 0 or k > n_points:
        raise ValueError(f"k must be between 1 and {n_points}, got {k}")

    # Step 1: Initialize k centroids to the first k points
    centroids = points[:k].copy()

    # Track count of points assigned to each centroid
    counts = np.ones(k, dtype=int)

    # Initialize labels array
    labels = np.zeros(n_points, dtype=int)
    # First k points are assigned to themselves
    labels[:k] = np.arange(k)

    # Step 2: Process remaining points one-by-one in order
    for t in range(k, n_points):
        x_t = points[t]

        # Find nearest centroid
        distances = np.linalg.norm(centroids - x_t, axis=1)
        j = np.argmin(distances)

        # Assign point to cluster j
        labels[t] = j

        # Step 3: Immediately update only centroid j using incremental formula
        # μ_j ← (n_j × μ_j + x_t) / (n_j + 1)
        centroids[j] = (counts[j] * centroids[j] + x_t) / (counts[j] + 1)
        counts[j] += 1

    return centroids, labels


def compute_wcss(points, centroids, labels):
    """
    Compute Within-Cluster Sum of Squares (WCSS)
    """
    wcss = 0.0
    for i in range(len(points)):
        cluster_center = centroids[labels[i]]
        wcss += np.sum((points[i] - cluster_center) ** 2)
    return wcss


if __name__ == "__main__":
    # Example usage with synthetic data
    np.random.seed(42)

    # Generate simple 2D data for testing
    # Create 3 clusters for k=3
    cluster1 = np.random.normal([0, 0], 0.5, (30, 2))
    cluster2 = np.random.normal([3, 3], 0.5, (30, 2))
    cluster3 = np.random.normal([0, 3], 0.5, (30, 2))

    points = np.vstack([cluster1, cluster2, cluster3])

    # Ensure deterministic ordering as required by MacQueen
    # The algorithm is sensitive to input order
    k = 3

    print("Running MacQueen's (1967) k-means algorithm...")
    print(f"Input points shape: {points.shape}")
    print(f"Number of clusters (k): {k}")

    centroids, labels = macqueen_kmeans(points, k)

    wcss = compute_wcss(points, centroids, labels)

    print(f"\nFinal centroids:\n{centroids}")
    print(f"\nWCSS: {wcss:.4f}")

    # Count points per cluster
    unique, counts_per_cluster = np.unique(labels, return_counts=True)
    print(f"\nPoints per cluster: {dict(zip(unique, counts_per_cluster))}")

    # Verify MacQueen-specific behavior: first k points are initial centroids
    print(f"\nInitial centroids (first {k} points):\n{points[:k]}")
    print(f"Final centroids:\n{centroids}")