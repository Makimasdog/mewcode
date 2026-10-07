import numpy as np
import matplotlib.pyplot as plt
from typing import Tuple, List, Optional
import os


def kmeans(X: np.ndarray, k: int, max_iters: int = 100, tol: float = 1e-4) -> Tuple[np.ndarray, np.ndarray, List[float]]:
    """
    Standard k-means clustering algorithm.

    Args:
        X: Input data points, shape (n_samples, n_features)
        k: Number of clusters
        max_iters: Maximum number of iterations
        tol: Convergence tolerance

    Returns:
        centroids: Final cluster centroids, shape (k, n_features)
        labels: Cluster assignments for each point, shape (n_samples,)
        inertia_history: Sum of squared distances history
    """
    if len(X) == 0:
        raise ValueError("Input data X cannot be empty")
    if k <= 0:
        raise ValueError("Number of clusters k must be positive")
    if k > len(X):
        raise ValueError(f"Number of clusters k={k} cannot exceed number of samples {len(X)}")

    n_samples, n_features = X.shape

    # Initialize centroids randomly using k-means++ initialization
    centroids = np.zeros((k, n_features))
    # First centroid is random
    centroids[0] = X[np.random.randint(0, n_samples)]

    # k-means++ initialization for remaining centroids
    for i in range(1, k):
        # Calculate distance squared from each point to nearest existing centroid
        distances_sq = np.array([
            min([np.sum((x - c) ** 2) for c in centroids[:i]]) for x in X
        ])
        # Choose next centroid with probability proportional to distance squared
        probs = distances_sq / distances_sq.sum()
        cumulative_probs = np.cumsum(probs)
        r = np.random.rand()
        for j, p in enumerate(cumulative_probs):
            if r < p:
                centroids[i] = X[j]
                break

    # Main k-means loop
    inertia_history = []
    for iteration in range(max_iters):
        # Assignment step: assign each point to nearest centroid
        distances = np.zeros((n_samples, k))
        for i in range(k):
            distances[:, i] = np.sum((X - centroids[i]) ** 2, axis=1)

        labels = np.argmin(distances, axis=1)

        # Calculate inertia (sum of squared distances)
        inertia = 0.0
        for i in range(k):
            cluster_points = X[labels == i]
            if len(cluster_points) > 0:
                inertia += np.sum((cluster_points - centroids[i]) ** 2)
        inertia_history.append(inertia)

        # Update step: recalculate centroids as mean of assigned points
        new_centroids = np.zeros_like(centroids)
        for i in range(k):
            cluster_points = X[labels == i]
            if len(cluster_points) > 0:
                new_centroids[i] = np.mean(cluster_points, axis=0)
            else:
                # If empty cluster, reinitialize randomly
                new_centroids[i] = X[np.random.randint(0, n_samples)]

        # Check for convergence
        if np.all(np.abs(centroids - new_centroids) < tol):
            centroids = new_centroids
            break

        centroids = new_centroids

    return centroids, labels, inertia_history


def generate_sample_data(n_samples: int = 300, n_clusters: int = 3, noise: float = 0.5) -> np.ndarray:
    """Generate synthetic 2D data for testing."""
    np.random.seed(42)
    centers = np.array([[2, 2], [-2, -2], [2, -2]])

    # Ensure we have at least one sample per cluster
    if n_samples < n_clusters:
        n_samples = n_clusters

    # Distribute samples among clusters
    samples_per_cluster = n_samples // n_clusters
    remaining = n_samples % n_clusters

    X = np.zeros((n_samples, 2))

    start_idx = 0
    for i, center in enumerate(centers[:n_clusters]):
        # Add one extra sample to first 'remaining' clusters
        cluster_size = samples_per_cluster + (1 if i < remaining else 0)
        if cluster_size > 0:
            cluster_data = np.random.normal(center, noise, (cluster_size, 2))
            X[start_idx:start_idx + cluster_size] = cluster_data
            start_idx += cluster_size

    return X


def main():
    """Main function to run k-means on sample data."""
    print("Running k-means clustering...")

    # Generate sample data
    X = generate_sample_data(n_samples=300, n_clusters=3, noise=0.5)

    # Run k-means
    k = 3
    centroids, labels, inertia_history = kmeans(X, k)

    # Print results
    print(f"K-means completed in {len(inertia_history)} iterations")
    print(f"Final inertia: {inertia_history[-1]:.4f}")
    print(f"Centroids:\n{centroids}")

    # Save results to current directory
    np.save("centroids.npy", centroids)
    np.save("labels.npy", labels)
    np.save("inertia_history.npy", np.array(inertia_history))

    # Create visualization
    try:
        plt.figure(figsize=(12, 4))

        # Plot data points colored by cluster assignment
        plt.subplot(1, 3, 1)
        colors = ['red', 'blue', 'green', 'purple', 'orange']
        for i in range(k):
            cluster_points = X[labels == i]
            plt.scatter(cluster_points[:, 0], cluster_points[:, 1],
                       c=colors[i % len(colors)], label=f'Cluster {i}', alpha=0.6)
        plt.scatter(centroids[:, 0], centroids[:, 1], c='black', marker='x', s=200, linewidths=3)
        plt.title('Cluster Assignments')
        plt.legend()

        # Plot inertia history
        plt.subplot(1, 3, 2)
        plt.plot(inertia_history)
        plt.xlabel('Iteration')
        plt.ylabel('Inertia')
        plt.title('Convergence History')

        # Plot original data
        plt.subplot(1, 3, 3)
        plt.scatter(X[:, 0], X[:, 1], c='gray', alpha=0.6)
        plt.title('Original Data')

        plt.tight_layout()
        plt.savefig("kmeans_results.png", bbox_inches='tight')
        plt.close()
    except ImportError:
        print("Matplotlib not available, skipping visualization")

    print("Results saved to current directory")

if __name__ == "__main__":
    main()