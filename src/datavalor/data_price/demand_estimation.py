"""Dependency-free estimation of monotone price acceptance."""

from __future__ import annotations

import bisect
import math
from collections.abc import Sequence


def fit_monotone_acceptance(
    prices: Sequence[float],
    accepted: Sequence[int | bool],
    price_grid: Sequence[float],
) -> tuple[float, ...]:
    """Fit the non-increasing current-status NPMLE with weighted PAVA."""
    offered = tuple(float(value) for value in prices)
    outcomes = tuple(int(value) for value in accepted)
    grid = tuple(float(value) for value in price_grid)
    if not offered or len(offered) != len(outcomes):
        raise ValueError("prices and accepted must be non-empty matching sequences")
    if any(value not in (0, 1) for value in outcomes):
        raise ValueError("accepted observations must be binary")
    if not all(math.isfinite(value) for value in (*offered, *grid)):
        raise ValueError("prices and price_grid must be finite")

    grouped: dict[float, list[int]] = {}
    for price, outcome in zip(offered, outcomes, strict=True):
        totals = grouped.setdefault(price, [0, 0])
        totals[0] += outcome
        totals[1] += 1
    sorted_prices = sorted(grouped)
    blocks = []
    for index, price in enumerate(sorted_prices):
        successes, count = grouped[price]
        blocks.append([index, index, float(successes), count])
        while len(blocks) >= 2:
            left = blocks[-2]
            right = blocks[-1]
            if left[2] / left[3] >= right[2] / right[3]:
                break
            blocks[-2:] = [[left[0], right[1], left[2] + right[2], left[3] + right[3]]]
    fitted = [0.0] * len(sorted_prices)
    for start, end, successes, count in blocks:
        for index in range(start, end + 1):
            fitted[index] = successes / count

    predictions = []
    for price in grid:
        index = bisect.bisect_right(sorted_prices, price) - 1
        index = min(max(index, 0), len(sorted_prices) - 1)
        predictions.append(fitted[index])
    return tuple(predictions)


def select_revenue_price(
    prices: Sequence[float], acceptance: Sequence[float]
) -> float:
    """Return the lowest price maximizing price times acceptance."""
    grid = tuple(float(value) for value in prices)
    probabilities = tuple(float(value) for value in acceptance)
    if not grid or len(grid) != len(probabilities):
        raise ValueError("prices and acceptance must be non-empty matching sequences")
    if not all(math.isfinite(value) and value >= 0 for value in grid):
        raise ValueError("prices must be finite and non-negative")
    if not all(math.isfinite(value) and 0 <= value <= 1 for value in probabilities):
        raise ValueError("acceptance probabilities must be finite and in [0, 1]")
    revenues = tuple(price * probability for price, probability in zip(grid, probabilities, strict=True))
    maximum = max(revenues)
    return min(price for price, revenue in zip(grid, revenues, strict=True) if revenue == maximum)


__all__ = ["fit_monotone_acceptance", "select_revenue_price"]
