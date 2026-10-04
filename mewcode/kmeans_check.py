"""Independent numerical verifier for the MacQueen reproduction preset.

Uses only the standard library. It does not import the generated implementation
for its reference calculations and never treats a model's PASS as evidence.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import random
from pathlib import Path


def make_datasets(seed: int = 42) -> dict:
    rng = random.Random(seed)
    points = []
    while len(points) < 150:
        point = [rng.uniform(-50, 50), rng.uniform(-50, 50)]
        if max(abs(x) for x in point) >= 30:
            points.append(point)
    datasets = {"original": points}
    for i in range(19):
        columns = [[row[j] for row in points] for j in range(2)]
        for column in columns:
            rng.shuffle(column)
        datasets[f"scrambled_{i:02d}"] = [list(row) for row in zip(*columns)]
    return {"seed": seed, "k": 12, "datasets": datasets}


def reference(points: list[list[float]], k: int) -> dict:
    """Section 2.1: first k observations, integer weights, online means."""
    centers = [list(point) for point in points[:k]]
    counts = [1] * k
    labels = list(range(k))

    def nearest(point):
        distances = [sum((a - b) ** 2 for a, b in zip(point, c)) for c in centers]
        label = min(range(k), key=distances.__getitem__)
        return label, distances[label]

    for point in points[k:]:
        label, _ = nearest(point)
        # Deliberately use the weighted-sum form, independently of an
        # implementation using c += (x-c)/n.
        centers[label] = [(counts[label] * a + b) / (counts[label] + 1)
                          for a, b in zip(centers[label], point)]
        counts[label] += 1
        labels.append(label)
    evaluated = [nearest(point) for point in points]
    return {
        "centroids": centers, "counts": counts, "stream_labels": labels,
        "assignments": [item[0] for item in evaluated],
        "inertia": sum(item[1] for item in evaluated),
        "distance_calculations": (len(points) - k) * k,
        "data_rows": len(points),
    }


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def compare(actual, expected, label: str) -> None:
    if isinstance(expected, dict):
        require(isinstance(actual, dict), f"{label}: expected object")
        for key, value in expected.items():
            require(key in actual, f"{label}: missing {key}")
            compare(actual[key], value, f"{label}.{key}")
    elif isinstance(expected, list):
        require(isinstance(actual, list) and len(actual) == len(expected), f"{label}: wrong shape")
        for i, (a, b) in enumerate(zip(actual, expected)):
            compare(a, b, f"{label}[{i}]")
    elif isinstance(expected, float):
        require(isinstance(actual, (int, float)) and math.isfinite(actual)
                and math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-8),
                f"{label}: observed {actual}, expected {expected}")
    else:
        require(type(actual) is type(expected) and actual == expected,
                f"{label}: observed {actual}, expected {expected}")


def verify(root: Path) -> dict:
    data = json.loads((root / "data.json").read_text(encoding="utf-8"))
    compare(data, make_datasets(), "immutable input")
    results = json.loads((root / "results.json").read_text(encoding="utf-8"))
    require(isinstance(results.get("runs"), dict), "results must contain runs")
    require(set(results["runs"]) == set(data["datasets"]), "missing or extra experiment runs")
    for name, points in data["datasets"].items():
        compare(results["runs"][name], reference(points, data["k"]), name)

    # Exercise generated code on data not present in the experiment file.
    spec = importlib.util.spec_from_file_location("generated_kmeans", root / "run.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    cases = [([[0.0], [2.0], [1.0]], 2),  # equal-distance tie -> lowest index
             ([[0.0], [0.0], [4.0], [8.0]], 2),  # duplicate seeds
             ([[1.0, 2.0], [3.0, 4.0]], 2),  # n == k
             ([[0.0], [2.0], [4.0]], 1)]
    rng = random.Random(917)
    for k in (2, 3, 5):
        cases.append(([[rng.uniform(-8, 8) for _ in range(3)] for _ in range(31)], k))
    for i, (points, k) in enumerate(cases):
        compare(module.online_kmeans([row[:] for row in points], k),
                reference(points, k), f"fixture {i}")
    original = results["runs"]["original"]["inertia"]
    scrambled = [results["runs"][f"scrambled_{i:02d}"]["inertia"] for i in range(19)]
    return {
        "verdict": "PASS", "experiments": 20, "algorithm_fixtures": len(cases),
        "data_rows": 150, "k": 12, "seed": 42,
        "original_wcss": original,
        "first_scramble_ratio": scrambled[0] / original,
        "mean_scramble_ratio": sum(scrambled) / (19 * original),
        "permutation_p": (1 + sum(value <= original for value in scrambled)) / 20,
        "paper_reported_ratio": 1.6,
        "scope": "Method and synthetic experiment reproduction; original sample/seed unavailable.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(verify(args.directory.resolve()), indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({"verdict": "FAIL", "error": str(exc)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
