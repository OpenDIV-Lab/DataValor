"""Model-agnostic contribution estimators with DataValor result models."""

from __future__ import annotations

import itertools
import math
import random
from typing import Any, Sequence

from datavalor.core import ComponentSpec, RunContext

from .interfaces import ContributionValuator, UtilityFunction
from .models import ContributionReport, ContributionRequest, ValueEstimate


def _ids(records: Sequence[Any]) -> tuple[str, ...]:
    return tuple(str(getattr(item, "target_id", item.get("id", i) if isinstance(item, dict) else i)) for i, item in enumerate(records))


def leave_one_out_values(ids: Sequence[str], utility, *, context: RunContext | None = None) -> ContributionReport:
    ids = tuple(ids); baseline = float(utility((), context)); full = float(utility(ids, context)); estimates = []
    for i, target_id in enumerate(ids):
        without = ids[:i] + ids[i + 1 :]
        estimates.append(ValueEstimate(str(target_id), full - float(utility(without, context)), "utility", explanation={"utility_without": float(utility(without, context))}))
    return ContributionReport("", "leave_one_out", tuple(estimates), utility_calls=len(ids) + 2,
                              diagnostics={"baseline_utility": baseline, "full_utility": full})


def exact_shapley_values(ids: Sequence[str], utility, *, max_records: int = 10, context: RunContext | None = None) -> ContributionReport:
    ids = tuple(ids); n = len(ids)
    if n > max_records: raise ValueError(f"Exact Shapley exceeds max_records={max_records}")
    baseline = float(utility((), context)); values = [0.0] * n; calls = 1
    for permutation in itertools.permutations(range(n)):
        coalition: list[str] = []; previous = baseline
        for index in permutation:
            coalition.append(ids[index]); current = float(utility(tuple(coalition), context)); calls += 1
            values[index] += current - previous; previous = current
    denominator = float(math.factorial(n)) if n else 1.0
    estimates = tuple(ValueEstimate(ids[i], values[i] / denominator, "utility") for i in range(n))
    return ContributionReport("", "shapley_exact", estimates, utility_calls=calls, converged=True,
                              diagnostics={"baseline_utility": baseline, "max_records": max_records})


def monte_carlo_shapley_values(ids: Sequence[str], utility, *, samples: int = 256, seed: int = 0, context: RunContext | None = None) -> ContributionReport:
    ids = tuple(ids); values = [[] for _ in ids]; rng = random.Random(seed); calls = 0
    for _ in range(max(1, int(samples))):
        permutation = list(range(len(ids))); rng.shuffle(permutation); coalition: list[str] = []; previous = float(utility((), context)); calls += 1
        for index in permutation:
            coalition.append(ids[index]); current = float(utility(tuple(coalition), context)); calls += 1
            values[index].append(current - previous); previous = current
    estimates = []
    for index, target_id in enumerate(ids):
        vals = values[index]; mean = sum(vals) / len(vals) if vals else 0.0
        variance = sum((v - mean) ** 2 for v in vals) / max(1, len(vals) - 1) if vals else 0.0
        estimates.append(ValueEstimate(target_id, mean, "utility", uncertainty={"std_error": math.sqrt(variance / max(1, len(vals)))}, diagnostics={"samples": len(vals)}))
    return ContributionReport("", "shapley_monte_carlo", tuple(estimates), utility_calls=calls, converged=True, diagnostics={"seed": seed, "samples": samples})


class LeaveOneOutValuator(ContributionValuator):
    @property
    def spec(self) -> ComponentSpec: return ComponentSpec("contribution.leave_one_out", "1.0", "data_value", "contribution_valuator")

    def value_contributions(self, request: ContributionRequest, utility: UtilityFunction, context: RunContext) -> ContributionReport:
        ids = tuple(target.target_id for target in request.units)
        scorer = utility.score if hasattr(utility, "score") else utility
        report = leave_one_out_values(ids, lambda selection, ctx: scorer(request.product, selection, request.task, ctx), context=context)
        return ContributionReport(request.product.product_id, report.method, report.contributions, report.utility_calls, report.converged, report.diagnostics)


__all__ = ["LeaveOneOutValuator", "leave_one_out_values", "exact_shapley_values", "monte_carlo_shapley_values"]
