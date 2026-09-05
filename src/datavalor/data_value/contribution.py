"""Model-agnostic contribution estimators with DataValor result models."""

from __future__ import annotations

import itertools
import math
import random
from typing import Any, Sequence

from datavalor.core import ComponentSpec, RunContext

from .interfaces import ContributionValuator, UtilityFunction
from .models import ContributionReport, ContributionRequest, ValueEstimate


def allocate_value_by_contribution(
    total_value: float,
    contributions: Sequence[ValueEstimate],
    *,
    negative_policy: str = "zero",
) -> tuple[ValueEstimate, ...]:
    """Allocate a monetary estimate proportionally to positive utility contributions.

    This is an explicit accounting transformation, not a new valuation method:
    the source report remains in utility units and the returned estimates carry
    ``unit='monetary_allocation'`` plus the original contribution.  Negative
    contributions are either zeroed (default) or retained in the denominator
    when ``negative_policy='signed'``.
    """
    amount = float(total_value)
    if not math.isfinite(amount) or amount < 0:
        raise ValueError("total_value must be a finite non-negative number")
    if negative_policy not in {"zero", "signed"}:
        raise ValueError("negative_policy must be 'zero' or 'signed'")
    weights = [float(item.value) if negative_policy == "signed" else max(0.0, float(item.value)) for item in contributions]
    denominator = sum(weights)
    if denominator == 0:
        return tuple(ValueEstimate(item.target_id, 0.0, "monetary_allocation", components={"source_contribution": float(item.value), "allocation_total": amount}, explanation={"negative_policy": negative_policy}) for item in contributions)
    return tuple(ValueEstimate(item.target_id, amount * weight / denominator, "monetary_allocation", components={"source_contribution": float(item.value), "allocation_total": amount}, explanation={"negative_policy": negative_policy}) for item, weight in zip(contributions, weights))


def _ids(records: Sequence[Any]) -> tuple[str, ...]:
    result = []
    for index, item in enumerate(records):
        value = getattr(item, "target_id", None)
        if value is None:
            value = item.get("id", index) if isinstance(item, dict) else index
        result.append(str(value))
    return tuple(result)


def leave_one_out_values(ids: Sequence[str], utility, *, context: RunContext | None = None) -> ContributionReport:
    ids = tuple(str(item) for item in ids)
    if len(set(ids)) != len(ids):
        raise ValueError("contribution unit IDs must be unique")
    baseline = float(utility((), context)); full = float(utility(ids, context)); estimates = []
    for i, target_id in enumerate(ids):
        without = ids[:i] + ids[i + 1 :]
        utility_without = float(utility(without, context))
        estimates.append(ValueEstimate(str(target_id), full - utility_without, "utility", explanation={"utility_without": utility_without, "utility_full": full}))
    return ContributionReport("", "leave_one_out", tuple(estimates), utility_calls=len(ids) + 2,
                              diagnostics={"baseline_utility": baseline, "full_utility": full})


def exact_shapley_values(ids: Sequence[str], utility, *, max_records: int = 10, context: RunContext | None = None) -> ContributionReport:
    ids = tuple(str(item) for item in ids); n = len(ids)
    if len(set(ids)) != n:
        raise ValueError("contribution unit IDs must be unique")
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
    ids = tuple(str(item) for item in ids)
    if len(set(ids)) != len(ids):
        raise ValueError("contribution unit IDs must be unique")
    sample_count = max(1, int(samples)); values = [[] for _ in ids]; rng = random.Random(seed); calls = 0
    baseline = float(utility((), context)); calls += 1
    for _ in range(sample_count):
        permutation = list(range(len(ids))); rng.shuffle(permutation); coalition: list[str] = []; previous = baseline
        for index in permutation:
            coalition.append(ids[index]); current = float(utility(tuple(coalition), context)); calls += 1
            values[index].append(current - previous); previous = current
    estimates = []
    for index, target_id in enumerate(ids):
        vals = values[index]; mean = sum(vals) / len(vals) if vals else 0.0
        variance = sum((v - mean) ** 2 for v in vals) / max(1, len(vals) - 1) if vals else 0.0
        estimates.append(ValueEstimate(target_id, mean, "utility", uncertainty={"std_error": math.sqrt(variance / max(1, len(vals)))}, diagnostics={"samples": len(vals)}))
    return ContributionReport("", "shapley_monte_carlo", tuple(estimates), utility_calls=calls, converged=True, diagnostics={"seed": seed, "samples": sample_count, "baseline_utility": baseline})


class LeaveOneOutValuator(ContributionValuator):
    @property
    def spec(self) -> ComponentSpec: return ComponentSpec("contribution.leave_one_out", "1.0", "data_value", "contribution_valuator")

    def value_contributions(self, request: ContributionRequest, utility: UtilityFunction, context: RunContext) -> ContributionReport:
        ids = tuple(target.target_id for target in request.units)
        scorer = utility.score if hasattr(utility, "score") else utility
        report = leave_one_out_values(ids, lambda selection, ctx: scorer(request.product, selection, request.task, ctx), context=context)
        return ContributionReport(request.product.product_id, report.method, report.contributions, report.utility_calls, report.converged, report.diagnostics)


class ExactShapleyValuator(ContributionValuator):
    """Exact Shapley wrapper with an explicit size guard."""

    @property
    def spec(self) -> ComponentSpec:
        return ComponentSpec("contribution.shapley_exact", "1.0.0", "data_value", "contribution_valuator", capabilities=("shapley", "exact"))

    def value_contributions(self, request: ContributionRequest, utility: UtilityFunction, context: RunContext) -> ContributionReport:
        scorer = utility.score if hasattr(utility, "score") else utility
        result = exact_shapley_values(
            tuple(unit.target_id for unit in request.units),
            lambda selection, ctx: scorer(request.product, selection, request.task, ctx),
            max_records=int(request.method_options.get("max_records", 10)),
            context=context,
        )
        return ContributionReport(request.product.product_id, result.method, result.contributions, result.utility_calls, result.converged, result.diagnostics)


class MonteCarloShapleyValuator(ContributionValuator):
    """Monte Carlo Shapley wrapper exposing sample count and seed in diagnostics."""

    @property
    def spec(self) -> ComponentSpec:
        return ComponentSpec("contribution.shapley_monte_carlo", "1.0.0", "data_value", "contribution_valuator", capabilities=("shapley", "monte_carlo"))

    def value_contributions(self, request: ContributionRequest, utility: UtilityFunction, context: RunContext) -> ContributionReport:
        scorer = utility.score if hasattr(utility, "score") else utility
        result = monte_carlo_shapley_values(
            tuple(unit.target_id for unit in request.units),
            lambda selection, ctx: scorer(request.product, selection, request.task, ctx),
            samples=int(request.method_options.get("samples", 256)),
            seed=int(request.method_options.get("seed", context.seed)),
            context=context,
        )
        return ContributionReport(request.product.product_id, result.method, result.contributions, result.utility_calls, result.converged, result.diagnostics)


class BanzhafValuator(ContributionValuator):
    """Compute normalized Banzhaf values by enumerating coalitions."""

    @property
    def spec(self) -> ComponentSpec:
        return ComponentSpec("contribution.banzhaf", "1.0.0", "data_value", "contribution_valuator", capabilities=("banzhaf", "exact"))

    def value_contributions(self, request: ContributionRequest, utility: UtilityFunction, context: RunContext) -> ContributionReport:
        ids = tuple(unit.target_id for unit in request.units)
        if len(set(ids)) != len(ids):
            raise ValueError("contribution unit IDs must be unique")
        max_records = int(request.method_options.get("max_records", 16))
        if len(ids) > max_records:
            raise ValueError(f"Exact Banzhaf exceeds max_records={max_records}")
        scorer = utility.score if hasattr(utility, "score") else utility
        values = [0.0] * len(ids); calls = 0
        for index, unit_id in enumerate(ids):
            others = [item for offset, item in enumerate(ids) if offset != index]
            for mask in range(1 << len(others)):
                coalition = tuple(others[offset] for offset in range(len(others)) if mask & (1 << offset))
                with_unit = coalition + (unit_id,)
                values[index] += float(scorer(request.product, with_unit, request.task, context)) - float(scorer(request.product, coalition, request.task, context)); calls += 2
        denominator = 2 ** max(0, len(ids) - 1)
        estimates = tuple(ValueEstimate(ids[index], value / denominator, "utility", diagnostics={"coalitions": denominator}) for index, value in enumerate(values))
        return ContributionReport(request.product.product_id, "banzhaf", estimates, utility_calls=calls, converged=True, diagnostics={"max_records": max_records})


__all__ = ["BanzhafValuator", "ExactShapleyValuator", "LeaveOneOutValuator", "MonteCarloShapleyValuator", "allocate_value_by_contribution", "leave_one_out_values", "exact_shapley_values", "monte_carlo_shapley_values"]
