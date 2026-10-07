import sys
import os
import numpy as np

# Add the current directory to path so we can import kmeans
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from kmeans import kmeans, generate_sample_data
except ImportError as e:
    print(f"Import error: {e}")
    sys.exit(1)


def test_kmeans_basic():
    """Test basic k-means functionality."""
    print("Testing k-means implementation...")

    # Generate simple test data
    X = generate_sample_data(n_samples=100, n_clusters=2, noise=0.3)

    # Run k-means
    k = 2
    try:
        centroids, labels, inertia_history = kmeans(X, k, max_iters=50)
    except Exception as e:
        print(f"k-means failed: {e}")
        return False

    # Basic assertions
    assert len(centroids) == k, f"Expected {k} centroids, got {len(centroids)}"
    assert len(labels) == len(X), f"Labels length mismatch: {len(labels)} vs {len(X)}"
    assert len(inertia_history) > 0, "Inertia history should not be empty"

    print(f"[PASS] Basic test passed: {len(X)} points clustered into {k} groups")
    print(f"[INFO] Final inertia: {inertia_history[-1]:.4f}")

    return True


def test_edge_cases():
    """Test edge cases."""
    print("Testing edge cases...")

    # Test with small dataset
    X_small = np.array([[1, 1], [2, 2], [8, 8], [9, 9]])
    try:
        centroids, labels, inertia_history = kmeans(X_small, k=2, max_iters=10)
    except Exception as e:
        print(f"Small dataset test failed: {e}")
        return False

    assert len(centroids) == 2
    assert len(labels) == 4

    print("[PASS] Edge case test passed")
    return True


if __name__ == "__main__":
    try:
        success = True
        success &= test_kmeans_basic()
        success &= test_edge_cases()

        if success:
            print("[RESULT] All tests passed!")
            sys.exit(0)
        else:
            print("[RESULT] Some tests failed")
            sys.exit(1)
    except Exception as e:
        print(f"[ERROR] Test failed with exception: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)