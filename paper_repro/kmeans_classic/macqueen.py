"""MacQueen's 1967 sequential k-means procedure (section 2.1)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class Fit:
    centers: tuple[tuple[float, ...], ...]
    counts: tuple[int, ...]


def squared_distance(a: Sequence[float], b: Sequence[float]) -> float:
    return sum((x - y) ** 2 for x, y in zip(a, b, strict=True))


def nearest(point: Sequence[float], centers: Sequence[Sequence[float]]) -> int:
    """Choose the lowest numbered center when distances tie."""
    if not centers:
        raise ValueError("at least one center is required")
    return min(range(len(centers)), key=lambda i: squared_distance(point, centers[i]))


def fit(points: Sequence[Sequence[float]], k: int) -> Fit:
    if not 1 <= k <= len(points):
        raise ValueError("k must be between 1 and the number of points")
    dimension = len(points[0])
    if dimension < 1 or any(len(point) != dimension for point in points):
        raise ValueError("points must have the same positive dimension")

    centers = [list(map(float, point)) for point in points[:k]]
    counts = [1] * k
    for point in points[k:]:
        index = nearest(point, centers)
        count = counts[index]
        centers[index] = [
            (count * old + value) / (count + 1)
            for old, value in zip(centers[index], point, strict=True)
        ]
        counts[index] = count + 1
    return Fit(tuple(tuple(center) for center in centers), tuple(counts))


def mean_nearest_squared_distance(
    points: Sequence[Sequence[float]], centers: Sequence[Sequence[float]]
) -> float:
    return sum(squared_distance(point, centers[nearest(point, centers)]) for point in points) / len(points)
