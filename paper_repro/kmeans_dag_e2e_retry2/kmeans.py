import numpy as np
import sys
import os


def kmeans_macqueen(X, k, max_iters=100, random_state=None):
    """
    K-means algorithm based on MacQueen (1967) - sequential/online update version.

    MacQueen's original algorithm processes points one at a time and updates
    centroids immediately after assigning each point to its nearest cluster.

    Parameters:
    -----------
    X : ndarray, shape (n_samples, n_features)
        Input data matrix
    k : int
        Number of clusters
    max_iters : int
        Maximum number of iterations (passes through the data)
    random_state : int, optional
        Random seed for reproducibility

    Returns:
    --------
    labels : ndarray, shape (n_samples,)
        Cluster assignments for each sample
    centroids : ndarray, shape (k, n_features)
        Final cluster centroids
    """
    if random_state is not None:
        np.random.seed(random_state)

    n_samples, n_features = X.shape

    # Initialize centroids randomly from the data points
    # MacQueen suggested using first k points or random sampling
    indices = np.random.choice(n_samples, k, replace=False)
    centroids = X[indices].copy()

    # Initialize cluster counts
    counts = np.zeros(k, dtype=int)

    # Store labels for each point
    labels = np.zeros(n_samples, dtype=int)

    # MacQueen's sequential algorithm: process each point once per iteration
    for iteration in range(max_iters):
        # Track if any reassignments happened
        changed = False

        # Process each point sequentially
        for i in range(n_samples):
            # Calculate distances to all centroids
            distances = np.sqrt(np.sum((centroids - X[i])**2, axis=1))

            # Find closest centroid
            closest = np.argmin(distances)

            # Assign point to closest cluster
            old_label = labels[i]
            labels[i] = closest

            # Update centroid incrementally (MacQueen's key contribution)
            # New centroid = old_centroid + (x_i - old_centroid) / (count + 1)
            if counts[closest] == 0:
                # First point assigned to this cluster
                centroids[closest] = X[i]
            else:
                # Incremental update: c_new = c_old + (x_i - c_old) / (n+1)
                centroids[closest] += (X[i] - centroids[closest]) / (counts[closest] + 1)

            counts[closest] += 1

            if old_label != closest:
                changed = True

        # If no changes, algorithm has converged
        if not changed:
            break

    return labels, centroids


def generate_test_data():
    """Generate synthetic test data with known clusters"""
    np.random.seed(42)
    # Create 3 clusters
    cluster1 = np.random.normal([2, 2], 0.5, (50, 2))
    cluster2 = np.random.normal([6, 6], 0.5, (50, 2))
    cluster3 = np.random.normal([2, 6], 0.5, (50, 2))

    X = np.vstack([cluster1, cluster2, cluster3])
    return X


def main():
    """Main function to run k-means on test data"""
    print("Running MacQueen's k-means algorithm (1967)")

    # Generate test data
    X = generate_test_data()
    print(f"Generated test data with shape: {X.shape}")

    # Run k-means
    k = 3
    labels, centroids = kmeans_macqueen(X, k, max_iters=10, random_state=42)

    print(f"\nFinal centroids:\n{centroids}")
    print(f"\nCluster assignments for first 10 points: {labels[:10]}")

    # Calculate within-cluster sum of squares (WCSS)
    wcss = 0
    for i in range(len(X)):
        wcss += np.sum((X[i] - centroids[labels[i]])**2)

    print(f"\nWithin-Cluster Sum of Squares (WCSS): {wcss:.4f}")

    # Save results
    np.save('centroids.npy', centroids)
    np.save('labels.npy', labels)

    print("\nResults saved to current directory")


if __name__ == "__main__":
    main()