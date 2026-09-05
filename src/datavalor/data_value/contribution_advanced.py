"""Group, interaction and bootstrap contribution analysis."""

from __future__ import annotations

import itertools
import math
import random
from collections.abc import Mapping, Sequence

from datavalor.core import ComponentSpec, RunContext

from .contribution import exact_shapley_values
from .interfaces import ContributionValuator, UtilityFunction
from .models import ContributionReport, ContributionRequest, ValueEstimate


def group_shapley_values(groups: Mapping[str, Sequence[str]], utility, *, max_groups: int = 8, context: RunContext | None = None) -> ContributionReport:
    """Compute exact Shapley values over groups and retain member lists."""
    names = tuple(str(name) for name in groups)
    if len(names) > max_groups:
        raise ValueError(f"Group Shapley exceeds max_groups={max_groups}")
    if len(set(names)) != len(names) or any(len(set(map(str, members))) != len(members) for members in groups.values()):
        raise ValueError("group IDs and members must be unique")
    def score(selection, ctx):
        members = tuple(member for group in selection for member in groups[group])
        return float(utility(members, ctx))
    report = exact_shapley_values(names, score, max_records=max_groups, context=context)
    estimates = tuple(ValueEstimate(item.target_id, item.value, "utility", explanation={"members": tuple(groups[item.target_id])}, diagnostics=item.diagnostics) for item in report.contributions)
    return ContributionReport("", "group_shapley_exact", estimates, report.utility_calls, report.converged, {**report.diagnostics, "group_count": len(names)})


def pairwise_interactions(ids: Sequence[str], utility, *, context: RunContext | None = None) -> tuple[ValueEstimate, ...]:
    """Estimate pairwise synergy relative to the empty coalition."""
    names = tuple(str(item) for item in ids)
    if len(set(names)) != len(names):
        raise ValueError("interaction IDs must be unique")
    baseline = float(utility((), context)); result = []
    for left, right in itertools.combinations(names, 2):
        left_value = float(utility((left,), context)); right_value = float(utility((right,), context)); together = float(utility((left, right), context))
        result.append(ValueEstimate(f"{left}::{right}", together - left_value - right_value + baseline, "utility_interaction", components={"utility_pair": together, "utility_left": left_value, "utility_right": right_value, "utility_baseline": baseline}, explanation={"left": left, "right": right}))
    return tuple(result)


def bootstrap_loo_values(ids: Sequence[str], utility, *, samples: int = 128, seed: int = 0, context: RunContext | None = None) -> ContributionReport:
    """Bootstrap LOO contributions and report percentile intervals."""
    names = tuple(str(item) for item in ids)
    if len(set(names)) != len(names):
        raise ValueError("bootstrap IDs must be unique")
    sample_count = max(2, int(samples)); rng = random.Random(seed); values = {name: [] for name in names}; calls = 0
    for _ in range(sample_count):
        draw = tuple(rng.choice(names) for _ in names)
        full = float(utility(draw, context)); calls += 1
        for name in names:
            without = list(draw)
            try:
                without.remove(name)
            except ValueError:
                marginal = 0.0
            else:
                marginal = full - float(utility(tuple(without), context)); calls += 1
            values[name].append(marginal)
    estimates = []
    for name, samples_for_name in values.items():
        ordered = sorted(samples_for_name); mean = sum(ordered) / len(ordered); variance = sum((value - mean) ** 2 for value in ordered) / (len(ordered) - 1)
        low = ordered[max(0, int(0.025 * len(ordered)) - 1)]; high = ordered[min(len(ordered) - 1, int(0.975 * len(ordered)))]
        estimates.append(ValueEstimate(name, mean, "utility", uncertainty={"std_error": math.sqrt(variance / len(ordered)), "lower_95": low, "upper_95": high}, diagnostics={"bootstrap_samples": len(ordered)}))
    return ContributionReport("", "loo_bootstrap", tuple(estimates), calls, converged=True, diagnostics={"seed": seed, "samples": sample_count})


class GroupShapleyValuator(ContributionValuator):
    @property
    def spec(self) -> ComponentSpec:
        return ComponentSpec("contribution.group_shapley", "1.0.0", "data_value", "contribution_valuator", capabilities=("group", "shapley"))

    def value_contributions(self, request: ContributionRequest, utility: UtilityFunction, context: RunContext) -> ContributionReport:
        groups = request.method_options.get("groups")
        if not isinstance(groups, Mapping):
            raise ValueError("GroupShapleyValuator requires method_options['groups'] mapping")
        scorer = utility.score if hasattr(utility, "score") else utility
        report = group_shapley_values(groups, lambda selection, ctx: scorer(request.product, selection, request.task, ctx), max_groups=int(request.method_options.get("max_groups", 8)), context=context)
        return ContributionReport(request.product.product_id, report.method, report.contributions, report.utility_calls, report.converged, report.diagnostics)


__all__ = ["GroupShapleyValuator", "bootstrap_loo_values", "group_shapley_values", "pairwise_interactions"]
