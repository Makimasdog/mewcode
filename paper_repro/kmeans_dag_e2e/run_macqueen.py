import numpy as np
import sys
import os

# Add the current directory to path to import the module
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from paper_repro_kmeans_macqueen import macqueen_kmeans, compute_wcss


def main():
    # Use deterministic seed for reproducibility
    np.random.seed(42)

    # Generate synthetic 2D data with known structure
    # This creates data that should be separable into k clusters
    n_per_cluster = 50
    k = 3

    # Create three well-separated clusters
    cluster1 = np.random.normal([0, 0], 0.8, (n_per_cluster, 2))
    cluster2 = np.random.normal([4, 0], 0.8, (n_per_cluster, 2))
    cluster3 = np.random.normal([2, 4], 0.8, (n_per_cluster, 2))

    points = np.vstack([cluster1, cluster2, cluster3])

    print("MacQueen's (1967) k-means Algorithm - Exact Implementation")
    print("=" * 60)
    print(f"Input data shape: {points.shape}")
    print(f"Number of clusters (k): {k}")
    print(f"First 5 points:\n{points[:5]}")
    print(f"Last 5 points:\n{points[-5:]}")

    # Run MacQueen's algorithm
    centroids, labels = macqueen_kmeans(points, k)

    # Compute metrics
    wcss = compute_wcss(points, centroids, labels)

    # Count points per cluster
    unique_labels, cluster_counts = np.unique(labels, return_counts=True)

    print("\nRESULTS:")
    print("-" * 30)
    print(f"Final centroids:\n{centroids}")
    print(f"\nCluster assignments (first 10): {labels[:10]}...")
    print(f"\nPoints per cluster: {dict(zip(unique_labels, cluster_counts))}")
    print(f"\nWithin-Cluster Sum of Squares (WCSS): {wcss:.6f}")

    # Verify initialization (first k points are initial centroids)
    print(f"\nINITIALIZATION CHECK:")
    print(f"Initial centroids (first {k} points):\n{points[:k]}")

    # Show how centroids evolved
    print(f"\nCENTROID EVOLUTION:")
    print(f"Centroid 0: {points[0]} -> {centroids[0]}")
    print(f"Centroid 1: {points[1]} -> {centroids[1]}")
    print(f"Centroid 2: {points[2]} -> {centroids[2]}")


if __name__ == "__main__":
    main()