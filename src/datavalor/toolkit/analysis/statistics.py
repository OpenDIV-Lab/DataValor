"""Deterministic statistics used by benchmark and market analysis."""

from __future__ import annotations

import math
import random
import statistics


def _quantile(sorted_values, probability):
    if not sorted_values:
        return None
    position = (len(sorted_values) - 1) * min(1.0, max(0.0, probability))
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return sorted_values[lower]
    weight = position - lower
    return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight


def bootstrap_mean_interval(
    values, *, confidence: float = 0.95, samples: int = 2000, seed: int = 0
):
    """Bootstrap confidence interval for a sample mean.

    Returns standard error, quantile bounds, and the number of resamples so a
    report can distinguish a point estimate from uncertainty.
    """

    values = [float(value) for value in values if value is not None and math.isfinite(float(value))]
    if not values:
        return None
    if not 0 < confidence <= 1:
        raise ValueError("confidence must be in (0, 1]")
    samples = max(1, int(samples))
    rng = random.Random(seed)
    means = [statistics.fmean(rng.choices(values, k=len(values))) for _ in range(samples)]
    means.sort()
    alpha = (1 - confidence) / 2
    point = statistics.fmean(values)
    return {
        "mean": point,
        "lower": _quantile(means, alpha),
        "upper": _quantile(means, 1 - alpha),
        "std_error": statistics.pstdev(means) if len(means) > 1 else 0.0,
        "n": len(values),
        "resamples": samples,
        "confidence": confidence,
        "seed": seed,
    }


def paired_difference(baseline, candidate):
    """Compute paired effects and descriptive uncertainty diagnostics."""

    pairs = [(float(c) - float(b)) for b, c in zip(baseline, candidate)]
    result = {
        "differences": pairs,
        "mean_difference": statistics.fmean(pairs) if pairs else None,
        "n": len(pairs),
    }
    if len(pairs) > 1:
        result["std_difference"] = statistics.stdev(pairs)
        result["standard_error"] = result["std_difference"] / math.sqrt(len(pairs))
    else:
        result["std_difference"] = 0.0
        result["standard_error"] = 0.0
    return result


def paired_bootstrap_difference(
    baseline, candidate, *, confidence=0.95, samples=2000, seed=0
):
    """Paired bootstrap interval preserving case-level dependence."""

    differences = paired_difference(baseline, candidate)["differences"]
    interval = bootstrap_mean_interval(
        differences, confidence=confidence, samples=samples, seed=seed
    )
    return {"mean_difference": interval["mean"] if interval else None, "interval": interval, "n": len(differences)}


def regret_summary(rewards, best_reward=None):
    """Summarize cumulative and per-round regret for finite experiments."""

    values = [float(value) for value in rewards]
    if not values:
        return {"rounds": 0, "cumulative_regret": 0.0, "mean_regret": 0.0}
    comparator = max(values) if best_reward is None else float(best_reward)
    regrets = [max(0.0, comparator - value) for value in values]
    return {
        "rounds": len(values),
        "best_reward": comparator,
        "cumulative_regret": sum(regrets),
        "mean_regret": statistics.fmean(regrets),
        "max_regret": max(regrets),
    }


def scalarized_score(row, weights, directions=None):
    """Compute a weighted score after converting minimize objectives."""

    directions = directions or {}
    return sum(
        float(weight)
        * (float(row[name]) if directions.get(name, "max") == "max" else -float(row[name]))
        for name, weight in weights.items()
    )


def pareto_frontier(rows, objectives, directions=None):
    """Return non-dominated rows under explicit max/min objective directions."""

    directions = directions or {}

    def oriented(row, name):
        value = float(row[name])
        return value if directions.get(name, "max") == "max" else -value

    def dominates(left, right):
        comparisons = [oriented(left, name) - oriented(right, name) for name in objectives]
        return all(item >= 0 for item in comparisons) and any(item > 0 for item in comparisons)

    return [
        row
        for index, row in enumerate(rows)
        if not any(dominates(other, row) for other_index, other in enumerate(rows) if index != other_index)
    ]


__all__ = [
    "bootstrap_mean_interval",
    "paired_bootstrap_difference",
    "paired_difference",
    "pareto_frontier",
    "regret_summary",
    "scalarized_score",
]
