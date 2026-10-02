"""Independent replay and threshold audit for the frozen MacQueen protocol."""

from __future__ import annotations

import hashlib
import json
import math
import random
import statistics
from pathlib import Path


HERE = Path(__file__).resolve().parent
FROZEN_HASH = "ffcb257ec4538f85e471221b256825e193b2e43d0230d0a1486ff6a1c422288f"


def distance(a, b):
    return sum((x - y) * (x - y) for x, y in zip(a, b, strict=True))


def reference_fit(points, k):
    # Store cluster sums instead of incrementally updating centers.
    sums = [list(point) for point in points[:k]]
    counts = [1] * k
    for point in points[k:]:
        current = [[value / counts[i] for value in sums[i]] for i in range(k)]
        chosen = min(range(k), key=lambda i: distance(point, current[i]))
        for d, value in enumerate(point):
            sums[chosen][d] += value
        counts[chosen] += 1
    return [tuple(value / counts[i] for value in sums[i]) for i in range(k)], counts


def closest(point, centers):
    return min(range(len(centers)), key=lambda i: distance(point, centers[i]))


def class_of(point):
    return int((point[0] > 5) == (point[1] > 5))


def verify_a(saved):
    rng = random.Random(1967)
    train = [tuple(rng.randrange(1, 11) for _ in range(4)) for _ in range(250)]
    test = [tuple(rng.randrange(1, 11) for _ in range(4)) for _ in range(250)]
    a = [point for point in train if class_of(point) == 1]
    b = [point for point in train if class_of(point) == 0]
    centers = reference_fit(a, 8)[0] + reference_fit(b, 8)[0]
    correct = sum((closest(point, centers) < 8) == bool(class_of(point)) for point in test)
    test_a = sum(class_of(point) for point in test)
    baseline = max(test_a, 250 - test_a) / 250
    accuracy = correct / 250
    assert saved["train_counts"] == {"A": len(a), "B": len(b)}
    assert saved["test_counts"] == {"A": test_a, "B": 250 - test_a}
    assert saved["correct"] == correct and saved["total"] == 250
    assert math.isclose(saved["accuracy"], accuracy, abs_tol=1e-12)
    assert math.isclose(saved["majority_baseline"], baseline, abs_tol=1e-12)
    for observed, expected in zip(saved["centers_A"] + saved["centers_B"], centers, strict=True):
        assert all(math.isclose(x, y, abs_tol=1e-12) for x, y in zip(observed, expected, strict=True))
    accepted = accuracy >= 0.75 and accuracy - baseline >= 0.10
    assert saved["accepted"] == accepted
    return {"accuracy": accuracy, "majority_baseline": baseline, "accepted": accepted}


def verify_b(saved):
    ratios = []
    assert saved["seeds"] == list(range(1000, 1030))
    for trial, seed in zip(saved["trials"], range(1000, 1030), strict=True):
        rng = random.Random(seed)
        points = []
        while len(points) < 150:
            x, y = rng.random() * 100 - 50, rng.random() * 100 - 50
            if max(abs(x), abs(y)) > 30:
                points.append((x, y))
        y_values = [point[1] for point in points]
        random.Random(seed + 1_000_000).shuffle(y_values)
        mixed = list(zip((point[0] for point in points), y_values, strict=True))
        assert sorted(y_values) == sorted(point[1] for point in points)
        values = []
        for sample in (points, mixed):
            centers, counts = reference_fit(sample, 12)
            assert sum(counts) == 150
            values.append(sum(min(distance(point, center) for center in centers) for point in sample) / 150)
        ratio = values[1] / values[0]
        assert trial["seed"] == seed
        for key, expected in zip(("original_variance", "scrambled_variance", "ratio"), (*values, ratio), strict=True):
            assert math.isclose(trial[key], expected, rel_tol=1e-10, abs_tol=1e-10), (seed, key, trial[key], expected)
        ratios.append(ratio)
    median = statistics.median(ratios)
    above_one = sum(value > 1 for value in ratios)
    accepted = median >= 1.10 and above_one >= 21
    assert math.isclose(saved["median_ratio"], median, rel_tol=1e-10)
    assert saved["ratios_above_one"] == above_one
    assert saved["accepted"] == accepted
    return {"median_ratio": median, "ratios_above_one": above_one, "accepted": accepted}


def main():
    protocol_bytes = (HERE / "protocol.md").read_bytes()
    normalized_bytes = protocol_bytes.replace(b"\r\n", b"\n")
    actual_hash = hashlib.sha256(normalized_bytes).hexdigest()
    assert actual_hash == FROZEN_HASH, "frozen protocol changed"
    saved = json.loads((HERE / "results.json").read_text(encoding="utf-8"))
    assert saved["protocol_sha256"] == actual_hash
    centers, counts = reference_fit([(0,), (10,), (2,), (8,)], 2)
    tie_centers, tie_counts = reference_fit([(0,), (2,), (1,)], 2)
    assert centers == [(1.0,), (9.0,)] and counts == [2, 2]
    assert tie_centers == [(0.5,), (2.0,)] and tie_counts == [2, 1]
    assert saved["algorithm_examples"]["accepted"] is True
    a = verify_a(saved["experiment_A"])
    b = verify_b(saved["experiment_B"])
    verdict = "PARTIAL" if a["accepted"] and b["accepted"] else "FAIL"
    assert saved["verdict"] == verdict
    report = {"protocol_sha256": actual_hash, "algorithm_examples": "PASS", "experiment_A": a, "experiment_B": b, "verdict": verdict}
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
