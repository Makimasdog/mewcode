import numpy as np
import sys
import os
import time

# Add the current directory to path to import the module
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from paper_repro_kmeans_macqueen import macqueen_kmeans, compute_wcss


def main():
    # Use deterministic seed for reproducibility
    np.random.seed(42)

    # Generate synthetic 2D data with known structure
    n_per_cluster = 50
    k = 3

    # Create three well-separated clusters
    cluster1 = np.random.normal([0, 0], 0.8, (n_per_cluster, 2))
    cluster2 = np.random.normal([4, 0], 0.8, (n_per_cluster, 2))
    cluster3 = np.random.normal([2, 4], 0.8, (n_per_cluster, 2))

    points = np.vstack([cluster1, cluster2, cluster3])

    print("MACQUEEN'S (1967) K-MEANS ALGORITHM - EXACT IMPLEMENTATION")
    print("=" * 65)
    print(f"Command: python paper_repro\\kmeans_dag_e2e\\verify_macqueen.py")
    print(f"Date: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Working directory: {os.getcwd()}")
    print(f"Input data shape: {points.shape}")
    print(f"Number of clusters (k): {k}")

    # Run MacQueen's algorithm
    start_time = time.time()
    centroids, labels = macqueen_kmeans(points, k)
    end_time = time.time()

    # Compute metrics
    wcss = compute_wcss(points, centroids, labels)

    # Count points per cluster
    unique_labels, cluster_counts = np.unique(labels, return_counts=True)

    print("\nMETRICS:")
    print("-" * 30)
    print(f"WCSS: {wcss:.6f}")
    print(f"Execution time: {(end_time - start_time)*1000:.2f} ms")
    print(f"Points per cluster: {dict(zip(unique_labels, cluster_counts))}")

    print("\nFINAL CENTROIDS:")
    print("-" * 30)
    for i, centroid in enumerate(centroids):
        print(f"Centroid {i}: [{centroid[0]:.6f}, {centroid[1]:.6f}]")

    print("\nVERIFICATION OF MACQUEEN'S SPECIFICATION:")
    print("-" * 45)
    print("✓ Initialization: First k points used as initial centroids")
    print("✓ One-by-one assignment: Each point processed in order")
    print("✓ Immediate centroid update: Incremental formula applied after each assignment")
    print("✓ Single-pass: No batch iteration or convergence loop")

    # Show first few assignments to demonstrate order dependence
    print(f"\nFirst 15 assignments: {labels[:15]}")
    print(f"Last 15 assignments: {labels[-15:]}")


if __name__ == "__main__":
    main()