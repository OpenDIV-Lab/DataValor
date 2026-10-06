"""Exact, evaluator-owned property audits for small benchmark instances."""

from __future__ import annotations

import itertools

from .models import ValuationCase, ValuationOutput


def efficiency_residual(case: ValuationCase, output: ValuationOutput) -> float:
    target = float(case.utility(case.owner_ids) - case.utility(()))
    return abs(sum(float(value) for value in output.scores.values()) - target)


def dummy_violation(case: ValuationCase, output: ValuationOutput) -> float | None:
    owners = tuple(case.metadata.get("dummy_owners", ()))
    if not owners:
        return None
    return max(abs(float(output.scores[owner])) for owner in owners)


def symmetry_gap(case: ValuationCase, output: ValuationOutput) -> float | None:
    groups = tuple(case.metadata.get("symmetric_groups", ()))
    if not groups:
        return None
    gaps = []
    for group in groups:
        values = [float(output.scores[owner]) for owner in group]
        gaps.append(max(values) - min(values))
    return max(gaps, default=0.0)


def least_core_max_violation(case: ValuationCase, output: ValuationOutput) -> float | None:
    if "epsilon" not in output.diagnostics or len(case.owner_ids) > 14:
        return None
    epsilon = float(output.diagnostics["epsilon"])
    baseline = float(case.utility(()))
    maximum = 0.0
    for size in range(1, len(case.owner_ids)):
        for coalition in itertools.combinations(case.owner_ids, size):
            allocated = sum(float(output.scores[owner]) for owner in coalition)
            required = float(case.utility(coalition)) - baseline - epsilon
            maximum = max(maximum, required - allocated)
    return maximum


__all__ = [
    "dummy_violation",
    "efficiency_residual",
    "least_core_max_violation",
    "symmetry_gap",
]
