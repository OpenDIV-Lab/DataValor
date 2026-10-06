"""Paired case-level statistical comparisons for leaderboard families."""

from __future__ import annotations

import hashlib
import math
from dataclasses import asdict, dataclass, replace
from itertools import combinations
from typing import Iterable

import numpy as np
from scipy.stats import wilcoxon

from .leaderboard import canonical_case_values
from .models import BenchmarkResult


@dataclass(frozen=True)
class PairwiseComparison:
    track: str
    setting: str
    metric: str
    direction: str
    family_a: str
    family_b: str
    common_case_count: int
    mean_delta: float
    median_delta: float
    ci95_low: float
    ci95_high: float
    wins: int
    ties: int
    losses: int
    p_value: float | None
    adjusted_p_value: float | None
    conclusion: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def holm_adjust(p_values: list[float]) -> list[float]:
    if not p_values:
        return []
    order = sorted(range(len(p_values)), key=p_values.__getitem__)
    adjusted = [0.0] * len(p_values)
    running = 0.0
    count = len(p_values)
    for position, index in enumerate(order):
        running = max(running, min(1.0, (count - position) * float(p_values[index])))
        adjusted[index] = running
    return adjusted


def cliffs_delta(left: Iterable[float], right: Iterable[float]) -> float:
    """Probability-of-superiority effect size with ties removed symmetrically."""
    left_values = tuple(float(value) for value in left)
    right_values = tuple(float(value) for value in right)
    if not left_values or not right_values:
        raise ValueError("Cliff's delta requires two non-empty samples")
    greater = sum(a > b for a in left_values for b in right_values)
    lower = sum(a < b for a in left_values for b in right_values)
    return (greater - lower) / (len(left_values) * len(right_values))


def geometric_mean(values: Iterable[float]) -> float:
    materialized = tuple(float(value) for value in values)
    if not materialized or any(value <= 0 or not math.isfinite(value) for value in materialized):
        raise ValueError("geometric mean requires finite positive values")
    return float(math.exp(sum(math.log(value) for value in materialized) / len(materialized)))


def _seed(setting: str, family_a: str, family_b: str) -> int:
    digest = hashlib.sha256(f"0.3.0|{setting}|{family_a}|{family_b}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


def _bootstrap_interval(
    deltas: np.ndarray,
    *,
    samples: int,
    seed: int,
) -> tuple[float, float]:
    if samples <= 0:
        raise ValueError("bootstrap_samples must be positive")
    if len(deltas) == 1:
        value = float(deltas[0])
        return value, value
    rng = np.random.default_rng(seed)
    indices = rng.integers(0, len(deltas), size=(samples, len(deltas)))
    means = np.mean(deltas[indices], axis=1)
    low, high = np.quantile(means, (0.025, 0.975))
    return float(low), float(high)


def paired_comparisons(
    results: Iterable[BenchmarkResult],
    setting: str,
    *,
    view: str = "all",
    bootstrap_samples: int = 10_000,
) -> tuple[PairwiseComparison, ...]:
    case_values = canonical_case_values(results, setting, view=view)
    families: dict[str, dict[str, float]] = {}
    metadata: dict[str, tuple[str, str, str]] = {}
    for row in case_values:
        families.setdefault(row.family_id, {})[row.case_id] = row.value
        metadata[row.family_id] = (row.track, row.metric, row.direction)
    comparisons = []
    for family_a, family_b in combinations(sorted(families), 2):
        common = sorted(set(families[family_a]).intersection(families[family_b]))
        if not common:
            continue
        track, metric, direction = metadata[family_a]
        if metadata[family_b] != (track, metric, direction):
            raise ValueError(f"incompatible family comparison: {family_a}/{family_b}")
        raw = np.asarray(
            [families[family_a][case] - families[family_b][case] for case in common],
            dtype=float,
        )
        deltas = raw if direction == "maximize" else -raw
        tolerance = 1e-12
        wins = int(np.sum(deltas > tolerance))
        losses = int(np.sum(deltas < -tolerance))
        ties = len(deltas) - wins - losses
        low, high = _bootstrap_interval(
            deltas,
            samples=bootstrap_samples,
            seed=_seed(setting, family_a, family_b),
        )
        nonzero = deltas[np.abs(deltas) > tolerance]
        if len(nonzero) == 0:
            p_value: float | None = 1.0
            conclusion = "indistinguishable"
        elif len(nonzero) < 5:
            p_value = None
            conclusion = "insufficient_cases"
        else:
            p_value = float(wilcoxon(nonzero, alternative="two-sided", method="auto").pvalue)
            conclusion = "pending_adjustment"
        comparisons.append(
            PairwiseComparison(
                track,
                setting,
                metric,
                direction,
                family_a,
                family_b,
                len(common),
                round(float(np.mean(deltas)), 15),
                round(float(np.median(deltas)), 15),
                low,
                high,
                wins,
                ties,
                losses,
                p_value,
                p_value if p_value == 1.0 else None,
                conclusion,
            )
        )
    tested = [index for index, row in enumerate(comparisons) if row.p_value is not None]
    adjusted = holm_adjust([float(comparisons[index].p_value) for index in tested])
    for index, adjusted_p in zip(tested, adjusted, strict=True):
        row = comparisons[index]
        if adjusted_p < 0.05 and row.ci95_low > 0:
            conclusion = "a_better"
        elif adjusted_p < 0.05 and row.ci95_high < 0:
            conclusion = "b_better"
        else:
            conclusion = "indistinguishable"
        comparisons[index] = replace(row, adjusted_p_value=adjusted_p, conclusion=conclusion)
    return tuple(comparisons)


__all__ = [
    "PairwiseComparison",
    "cliffs_delta",
    "geometric_mean",
    "holm_adjust",
    "paired_comparisons",
]
