import sys
import os
import numpy as np

# Ensure we're using ASCII encoding for Windows compatibility
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='ascii', errors='backslashreplace')
    except:
        pass

# Add the current directory to path to import kmeans
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from kmeans import main

    print("Starting MacQueen k-means reproduction...")
    print("=" * 50)

    # Run the main function
    main()

    print("=" * 50)
    print("K-means execution completed successfully.")

except Exception as e:
    print(f"Error during execution: {e}")
    import traceback
    traceback.print_exc(file=sys.stdout)

    # Exit with error code
    sys.exit(1)