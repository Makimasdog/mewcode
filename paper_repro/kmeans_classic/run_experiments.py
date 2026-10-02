"""Run the experiments frozen in protocol.md with only the Python standard library."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import random
import statistics
from pathlib import Path

from macqueen import fit, mean_nearest_squared_distance, nearest


PROTOCOL_SHA256 = "ffcb257ec4538f85e471221b256825e193b2e43d0230d0a1486ff6a1c422288f"


def label(point: tuple[int, ...]) -> str:
    return "A" if (point[0] > 5) == (point[1] > 5) else "B"


def experiment_a() -> dict:
    rng = random.Random(1967)
    train = [tuple(rng.randint(1, 10) for _ in range(4)) for _ in range(250)]
    test = [tuple(rng.randint(1, 10) for _ in range(4)) for _ in range(250)]
    a = [point for point in train if label(point) == "A"]
    b = [point for point in train if label(point) == "B"]
    centers = fit(a, 8).centers + fit(b, 8).centers
    test_a = sum(label(point) == "A" for point in test)
    correct = sum(("A" if nearest(point, centers) < 8 else "B") == label(point) for point in test)
    accuracy = correct / len(test)
    baseline = max(test_a, len(test) - test_a) / len(test)
    return {
        "seed": 1967,
        "train_counts": {"A": len(a), "B": len(b)},
        "test_counts": {"A": test_a, "B": len(test) - test_a},
        "correct": correct,
        "total": len(test),
        "accuracy": accuracy,
        "majority_baseline": baseline,
        "improvement": accuracy - baseline,
        "centers_A": centers[:8],
        "centers_B": centers[8:],
        "accepted": accuracy >= 0.75 and accuracy - baseline >= 0.10,
    }


def square_ring(rng: random.Random) -> list[tuple[float, float]]:
    points = []
    while len(points) < 150:
        x, y = rng.uniform(-50, 50), rng.uniform(-50, 50)
        if abs(x) <= 30 and abs(y) <= 30:
            continue
        points.append((x, y))
    return points


def experiment_b() -> dict:
    trials = []
    for seed in range(1000, 1030):
        points = square_ring(random.Random(seed))
        ys = [y for _, y in points]
        random.Random(seed + 1_000_000).shuffle(ys)
        scrambled = [(point[0], ys[i]) for i, point in enumerate(points)]
        original_v = mean_nearest_squared_distance(points, fit(points, 12).centers)
        scrambled_v = mean_nearest_squared_distance(scrambled, fit(scrambled, 12).centers)
        trials.append({
            "seed": seed,
            "original_variance": original_v,
            "scrambled_variance": scrambled_v,
            "ratio": scrambled_v / original_v,
        })
    median_ratio = statistics.median(trial["ratio"] for trial in trials)
    above_one = sum(trial["ratio"] > 1.0 for trial in trials)
    return {
        "seeds": list(range(1000, 1030)),
        "trials": trials,
        "median_ratio": median_ratio,
        "ratios_above_one": above_one,
        "accepted": median_ratio >= 1.10 and above_one >= 21,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    protocol_bytes = (Path(__file__).resolve().parent / "protocol.md").read_bytes()
    normalized_bytes = protocol_bytes.replace(b"\r\n", b"\n")
    if hashlib.sha256(normalized_bytes).hexdigest() != PROTOCOL_SHA256:
        raise RuntimeError("frozen protocol hash mismatch")

    first = fit([(0,), (10,), (2,), (8,)], 2)
    tie = fit([(0,), (2,), (1,)], 2)
    examples = {
        "four_points": {"centers": first.centers, "counts": first.counts},
        "tie": {"centers": tie.centers, "counts": tie.counts},
        "accepted": first.centers == ((1.0,), (9.0,)) and first.counts == (2, 2)
        and tie.centers == ((0.5,), (2.0,)) and tie.counts == (2, 1),
    }
    a = experiment_a()
    b = experiment_b()
    verdict = "PARTIAL" if examples["accepted"] and a["accepted"] and b["accepted"] else "FAIL"
    result = {
        "paper": "MacQueen 1967, Some Methods for Classification and Analysis of Multivariate Observations",
        "protocol_sha256": PROTOCOL_SHA256,
        "python_version": platform.python_version(),
        "algorithm_examples": examples,
        "experiment_A": a,
        "experiment_B": b,
        "verdict": verdict,
        "limitation": "Original random samples and seed are unavailable; reported 87% and 1.6 cannot be checked exactly.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "protocol_sha256": PROTOCOL_SHA256,
        "python_version": result["python_version"],
        "algorithm_examples_pass": examples["accepted"],
        "experiment_A_accuracy": a["accuracy"],
        "experiment_A_baseline": a["majority_baseline"],
        "experiment_A_pass": a["accepted"],
        "experiment_B_median_ratio": b["median_ratio"],
        "experiment_B_ratios_above_one": b["ratios_above_one"],
        "experiment_B_pass": b["accepted"],
        "verdict": verdict,
    }, indent=2))
    return 0 if verdict == "PARTIAL" else 1


if __name__ == "__main__":
    raise SystemExit(main())
