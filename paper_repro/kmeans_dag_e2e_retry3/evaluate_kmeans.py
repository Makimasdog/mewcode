import numpy as np
import sys
from kmeans import kmeans, generate_synthetic_data


def evaluate_kmeans(n_runs=5, n_samples=300, n_features=2, n_clusters=3):
    """
    Evaluate k-means performance over multiple runs.
    """
    inertias = []
    accuracies = []

    print(f"Running k-means {n_runs} times...")

    for i in range(n_runs):
        # Generate synthetic data
        X, y_true = generate_synthetic_data(n_samples=n_samples, n_features=n_features,
                                          n_clusters=n_clusters, random_state=i)

        # Run k-means
        centroids, labels, inertia = kmeans(X, k=n_clusters)

        # Calculate accuracy (simple matching - note this is not perfect due to label permutation)
        # We'll use a simple approach: find best permutation of labels
        from sklearn.metrics import adjusted_rand_score, silhouette_score
        try:
            # Try to compute ARI if sklearn is available
            from sklearn.metrics import adjusted_rand_score
            ari = adjusted_rand_score(y_true, labels)
        except ImportError:
            ari = 0.0

        # Simple accuracy (not perfect due to label permutation)
        correct_labels = np.sum(labels == y_true)
        accuracy = correct_labels / len(y_true)

        inertias.append(inertia)
        accuracies.append(accuracy)

        print(f"Run {i+1}: Inertia={inertia:.4f}, Accuracy={accuracy:.4f}, ARI={ari:.4f}")

    print(f"\nSummary over {n_runs} runs:")
    print(f"Inertia - Mean: {np.mean(inertias):.4f}, Std: {np.std(inertias):.4f}")
    print(f"Accuracy - Mean: {np.mean(accuracies):.4f}, Std: {np.std(accuracies):.4f}")

    return inertias, accuracies


if __name__ == "__main__":
    # Run evaluation
    inertias, accuracies = evaluate_kmeans()

    # Write results to file
    with open('evaluation_results.txt', 'w', encoding='ascii', errors='backslashreplace') as f:
        f.write(f"K-Means Evaluation Results\n")
        f.write(f"========================\n")
        f.write(f"Number of runs: {len(inertias)}\n")
        f.write(f"Inertia mean: {np.mean(inertias):.4f}\n")
        f.write(f"Inertia std: {np.std(inertias):.4f}\n")
        f.write(f"Accuracy mean: {np.mean(accuracies):.4f}\n")
        f.write(f"Accuracy std: {np.std(accuracies):.4f}\n")

    print("\nResults written to evaluation_results.txt")
