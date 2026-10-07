import numpy as np
import sys


def kmeans(X, k, max_iters=100, tol=1e-4):
    """
    Basic k-means clustering algorithm.

    Args:
        X: numpy array of shape (n_samples, n_features)
        k: number of clusters
        max_iters: maximum number of iterations
        tol: tolerance for convergence

    Returns:
        centroids: final cluster centers
        labels: cluster assignments for each point
        inertia: sum of squared distances to closest centroid
    """
    # Initialize centroids randomly
    n_samples, n_features = X.shape
    centroids = X[np.random.choice(n_samples, k, replace=False)]

    for iteration in range(max_iters):
        # Assign points to closest centroid
        distances = np.sqrt(((X - centroids[:, np.newaxis])**2).sum(axis=2))
        labels = np.argmin(distances, axis=0)

        # Update centroids
        new_centroids = np.array([X[labels == i].mean(axis=0) for i in range(k)])

        # Check for convergence
        if np.all(np.abs(centroids - new_centroids) < tol):
            break

        centroids = new_centroids

    # Calculate inertia
    inertia = np.sum([np.sum((X[labels == i] - centroids[i])**2) for i in range(k)])

    return centroids, labels, inertia


def generate_synthetic_data(n_samples=300, n_features=2, n_clusters=3, random_state=42):
    """
    Generate synthetic data for k-means testing.
    """
    np.random.seed(random_state)

    # Create cluster centers
    centers = np.array([
        [2, 2],
        [-2, -2],
        [2, -2]
    ])

    # Generate points around centers
    X = np.zeros((n_samples, n_features))
    labels_true = np.zeros(n_samples, dtype=int)

    samples_per_cluster = n_samples // n_clusters
    for i, center in enumerate(centers):
        start_idx = i * samples_per_cluster
        end_idx = start_idx + samples_per_cluster if i < n_clusters - 1 else n_samples

        X[start_idx:end_idx] = np.random.normal(center, 0.5, (end_idx - start_idx, n_features))
        labels_true[start_idx:end_idx] = i

    return X, labels_true


if __name__ == "__main__":
    # Generate synthetic data
    print("Generating synthetic data...")
    X, y_true = generate_synthetic_data()

    # Run k-means
    print("Running k-means...")
    centroids, labels, inertia = kmeans(X, k=3)

    # Print results
    print(f"Number of iterations: {len(centroids)}")
    print(f"Inertia: {inertia:.4f}")

    # Simple validation
    print(f"Data shape: {X.shape}")
    print(f"Centroids shape: {centroids.shape}")
    print(f"Labels shape: {labels.shape}")

    # Verify clustering quality (basic check)
    correct_labels = np.sum(labels == y_true)
    accuracy = correct_labels / len(y_true)
    print(f"Accuracy vs true labels: {accuracy:.4f}")
