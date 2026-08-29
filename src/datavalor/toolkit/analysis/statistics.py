"""Bootstrap, paired comparisons and Pareto frontier utilities."""

from __future__ import annotations

import random


def bootstrap_mean_interval(values, *, confidence: float = .95, samples: int = 2000, seed: int = 0):
    values = [float(value) for value in values]
    if not values: return None
    rng = random.Random(seed); means = [sum(rng.choices(values, k=len(values))) / len(values) for _ in range(max(1, samples))]; means.sort()
    alpha = (1 - confidence) / 2
    return {"mean": sum(values) / len(values), "lower": means[int(alpha * len(means))], "upper": means[min(len(means) - 1, int((1 - alpha) * len(means)))]}


def paired_difference(baseline, candidate):
    pairs = [(float(c) - float(b)) for b, c in zip(baseline, candidate)]
    return {"differences": pairs, "mean_difference": sum(pairs) / len(pairs) if pairs else None, "n": len(pairs)}


def pareto_frontier(rows, objectives):
    def dominates(left, right):
        return all(left[name] >= right[name] for name in objectives) and any(left[name] > right[name] for name in objectives)
    return [row for row in rows if not any(dominates(other, row) for other in rows if other is not row)]


__all__ = ["bootstrap_mean_interval", "paired_difference", "pareto_frontier"]
