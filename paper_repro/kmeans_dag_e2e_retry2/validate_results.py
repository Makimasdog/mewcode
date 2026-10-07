import numpy as np
import sys

# Ensure ASCII encoding for Windows
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='ascii', errors='backslashreplace')
    except:
        pass

try:
    # Load results
    centroids = np.load('centroids.npy')
    labels = np.load('labels.npy')

    print("Validation Results:")
    print("=" * 30)
    print(f"Centroids shape: {centroids.shape}")
    print(f"Labels shape: {labels.shape}")
    print(f"Number of clusters: {len(centroids)}")
    print(f"Cluster distribution: {np.bincount(labels)}")

    # Basic sanity check: centroids should be reasonable
    print(f"\nCentroid coordinates:")
    for i, centroid in enumerate(centroids):
        print(f"Cluster {i}: [{centroid[0]:.4f}, {centroid[1]:.4f}]")

    print("\nValidation completed successfully.")

except Exception as e:
    print(f"Validation failed: {e}")
    import traceback
    traceback.print_exc(file=sys.stdout)
    sys.exit(1)