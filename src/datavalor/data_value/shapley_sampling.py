"""Dependency-free sampling estimators for ordinary Data Shapley."""

from __future__ import annotations

import itertools
import math
import random
from collections.abc import Callable, Sequence

from datavalor.core import ComponentSpec, RunContext

from .interfaces import ContributionValuator, UtilityFunction
from .models import ContributionReport, ContributionRequest, ValueEstimate

CoalitionUtility = Callable[[tuple[str, ...], RunContext | None], float]


def _names(ids: Sequence[str]) -> tuple[str, ...]:
    names = tuple(str(owner) for owner in ids)
    if len(set(names)) != len(names):
        raise ValueError("contribution unit IDs must be unique")
    if not names:
        raise ValueError("at least one contribution unit is required")
    return names


def _value(
    utility: CoalitionUtility,
    coalition: tuple[str, ...],
    context: RunContext | None,
) -> float:
    result = float(utility(coalition, context))
    if not math.isfinite(result):
        raise ValueError(f"utility must be finite for coalition {coalition!r}")
    return result


def _estimates(
    ids: tuple[str, ...], samples: Sequence[Sequence[float]]
) -> tuple[ValueEstimate, ...]:
    result = []
    for owner, observations in zip(ids, samples, strict=True):
        mean = sum(observations) / len(observations)
        variance = (
            sum((value - mean) ** 2 for value in observations) / (len(observations) - 1)
            if len(observations) > 1
            else 0.0
        )
        result.append(
            ValueEstimate(
                owner,
                mean,
                "utility",
                uncertainty={"std_error": math.sqrt(variance / len(observations))},
                diagnostics={"samples": len(observations)},
            )
        )
    return tuple(result)


def _permutation_marginals(
    ids: tuple[str, ...],
    order: Sequence[int],
    utility: CoalitionUtility,
    baseline: float,
    context: RunContext | None,
) -> tuple[list[float], int]:
    contributions = [0.0] * len(ids)
    coalition = []
    previous = baseline
    calls = 0
    for index in order:
        coalition.append(ids[index])
        current = _value(utility, tuple(coalition), context)
        contributions[index] = current - previous
        previous = current
        calls += 1
    return contributions, calls


def antithetic_shapley_values(
    ids: Sequence[str],
    utility: CoalitionUtility,
    *,
    permutations: int,
    seed: int,
    context: RunContext | None = None,
) -> ContributionReport:
    """Pair random permutations with their reverses."""
    names = _names(ids)
    if permutations < 1:
        raise ValueError("permutations must be positive")
    rng = random.Random(seed)
    baseline = _value(utility, (), context)
    observations = [[] for _ in names]
    calls = 1
    paired = 0
    completed = 0
    while completed < permutations:
        order = list(range(len(names)))
        rng.shuffle(order)
        marginals, used = _permutation_marginals(names, order, utility, baseline, context)
        calls += used
        for index, value in enumerate(marginals):
            observations[index].append(value)
        completed += 1
        if completed < permutations:
            marginals, used = _permutation_marginals(
                names, tuple(reversed(order)), utility, baseline, context
            )
            calls += used
            for index, value in enumerate(marginals):
                observations[index].append(value)
            completed += 1
            paired += 1
    return ContributionReport(
        "",
        "shapley_antithetic",
        _estimates(names, observations),
        utility_calls=calls,
        converged=True,
        diagnostics={
            "seed": seed,
            "permutations": permutations,
            "paired_permutations": paired,
            "unpaired_permutations": permutations - 2 * paired,
        },
    )


def owen_shapley_values(
    ids: Sequence[str],
    utility: CoalitionUtility,
    *,
    samples: int,
    seed: int,
    context: RunContext | None = None,
) -> ContributionReport:
    """Estimate Shapley values through Owen's multilinear-extension identity."""
    names = _names(ids)
    if samples < 1:
        raise ValueError("samples must be positive")
    rng = random.Random(seed)
    observations = [[] for _ in names]
    calls = 0
    for _ in range(samples):
        probability = rng.random()
        uniforms = [rng.random() for _ in names]
        for index, owner in enumerate(names):
            subset = tuple(
                candidate
                for other_index, candidate in enumerate(names)
                if other_index != index and uniforms[other_index] < probability
            )
            without = _value(utility, subset, context)
            with_owner = _value(utility, (*subset, owner), context)
            observations[index].append(with_owner - without)
            calls += 2
    return ContributionReport(
        "",
        "shapley_owen",
        _estimates(names, observations),
        utility_calls=calls,
        converged=True,
        diagnostics={"seed": seed, "samples": samples},
    )


def truncated_monte_carlo_shapley_values(
    ids: Sequence[str],
    utility: CoalitionUtility,
    *,
    high_call_budget: int,
    tolerance: float,
    seed: int,
    context: RunContext | None = None,
) -> ContributionReport:
    """Run TMC-Shapley and account for every actual utility call."""
    names = _names(ids)
    minimum = len(names) + 2
    if high_call_budget < minimum:
        raise ValueError(f"high_call_budget must be at least {minimum}")
    if not math.isfinite(tolerance) or tolerance < 0:
        raise ValueError("tolerance must be finite and non-negative")
    rng = random.Random(seed)
    empty = _value(utility, (), context)
    grand = _value(utility, names, context)
    calls = 2
    paths = 0
    truncated = 0
    totals = [0.0] * len(names)
    observations = [[] for _ in names]
    while calls + len(names) <= high_call_budget:
        order = list(range(len(names)))
        rng.shuffle(order)
        path = [0.0] * len(names)
        coalition = []
        previous = empty
        steps = 0
        for index in order:
            coalition.append(names[index])
            current = _value(utility, tuple(coalition), context)
            calls += 1
            steps += 1
            path[index] = current - previous
            previous = current
            if abs(grand - current) <= tolerance:
                break
        if steps < len(names):
            truncated += 1
        for index, value in enumerate(path):
            totals[index] += value
            observations[index].append(value)
        paths += 1
    estimates = _estimates(names, observations)
    return ContributionReport(
        "",
        "shapley_tmc",
        estimates,
        utility_calls=calls,
        converged=True,
        diagnostics={
            "seed": seed,
            "high_call_budget": high_call_budget,
            "tolerance": tolerance,
            "completed_paths": paths,
            "truncated_paths": truncated,
        },
    )


def _stratum_subsets(names: tuple[str, ...], owner: str, size: int) -> tuple[tuple[str, ...], ...]:
    others = tuple(candidate for candidate in names if candidate != owner)
    return tuple(itertools.combinations(others, size))


def stratified_shapley_values(
    ids: Sequence[str],
    utility: CoalitionUtility,
    *,
    high_call_budget: int,
    seed: int,
    context: RunContext | None = None,
) -> ContributionReport:
    """Estimate every player/size stratum with observation-independent quotas."""
    names = _names(ids)
    strata = tuple((owner, size) for owner in names for size in range(len(names)))
    minimum = 2 * len(strata)
    if high_call_budget < minimum:
        raise ValueError(f"high_call_budget must be at least {minimum}")
    marginal_budget = high_call_budget // 2
    counts = dict.fromkeys(strata, 1)
    extra = marginal_budget - len(strata)
    rounds, remainder = divmod(extra, len(strata))
    for key in strata:
        counts[key] += rounds
    rng = random.Random(seed)
    for key in rng.sample(strata, remainder):
        counts[key] += 1

    player_values = []
    player_errors = []
    for owner in names:
        stratum_means = []
        stratum_variances = []
        for size in range(len(names)):
            population = _stratum_subsets(names, owner, size)
            observations = []
            for _ in range(counts[(owner, size)]):
                subset = population[rng.randrange(len(population))]
                with_owner = (*subset, owner)
                observations.append(
                    _value(utility, with_owner, context) - _value(utility, subset, context)
                )
            mean = sum(observations) / len(observations)
            variance = (
                sum((value - mean) ** 2 for value in observations) / (len(observations) - 1)
                if len(observations) > 1
                else 0.0
            )
            stratum_means.append(mean)
            stratum_variances.append(variance / len(observations))
        player_values.append(sum(stratum_means) / len(names))
        player_errors.append(math.sqrt(sum(stratum_variances)) / len(names))
    contributions = tuple(
        ValueEstimate(
            owner,
            value,
            "utility",
            uncertainty={"std_error": error},
            diagnostics={
                "stratum_samples": tuple(counts[(owner, size)] for size in range(len(names)))
            },
        )
        for owner, value, error in zip(names, player_values, player_errors, strict=True)
    )
    return ContributionReport(
        "",
        "shapley_stratified",
        contributions,
        utility_calls=2 * sum(counts.values()),
        converged=True,
        diagnostics={
            "seed": seed,
            "high_call_budget": high_call_budget,
            "stratum_counts": {f"{owner}:{size}": counts[(owner, size)] for owner, size in strata},
        },
    )


class _SamplingValuator(ContributionValuator):
    method = ""

    def _score(self, request: ContributionRequest, utility: UtilityFunction):
        scorer = utility.score if hasattr(utility, "score") else utility
        return lambda selection, ctx: scorer(request.product, selection, request.task, ctx) if hasattr(utility, "score") else scorer(selection, ctx)


class AntitheticShapleyValuator(_SamplingValuator):
    @property
    def spec(self) -> ComponentSpec:
        return ComponentSpec("contribution.shapley_antithetic", "1.0.0", "data_value", "contribution_valuator", capabilities=("shapley", "monte_carlo", "antithetic"))

    def value_contributions(self, request, utility, context):
        report = antithetic_shapley_values(tuple(unit.target_id for unit in request.units), self._score(request, utility), permutations=int(request.method_options.get("permutations", 256)), seed=int(request.method_options.get("seed", context.seed)), context=context)
        return ContributionReport(request.product.product_id, report.method, report.contributions, report.utility_calls, report.converged, report.diagnostics)


class OwenShapleyValuator(_SamplingValuator):
    @property
    def spec(self) -> ComponentSpec:
        return ComponentSpec("contribution.shapley_owen", "1.0.0", "data_value", "contribution_valuator", capabilities=("shapley", "monte_carlo", "multilinear_extension"))

    def value_contributions(self, request, utility, context):
        report = owen_shapley_values(tuple(unit.target_id for unit in request.units), self._score(request, utility), samples=int(request.method_options.get("samples", 256)), seed=int(request.method_options.get("seed", context.seed)), context=context)
        return ContributionReport(request.product.product_id, report.method, report.contributions, report.utility_calls, report.converged, report.diagnostics)


class TruncatedMonteCarloShapleyValuator(_SamplingValuator):
    @property
    def spec(self) -> ComponentSpec:
        return ComponentSpec("contribution.shapley_tmc", "1.0.0", "data_value", "contribution_valuator", capabilities=("shapley", "monte_carlo", "truncation"))

    def value_contributions(self, request, utility, context):
        report = truncated_monte_carlo_shapley_values(tuple(unit.target_id for unit in request.units), self._score(request, utility), high_call_budget=int(request.method_options.get("high_call_budget", 1024)), tolerance=float(request.method_options.get("tolerance", 1e-6)), seed=int(request.method_options.get("seed", context.seed)), context=context)
        return ContributionReport(request.product.product_id, report.method, report.contributions, report.utility_calls, report.converged, report.diagnostics)


class StratifiedShapleyValuator(_SamplingValuator):
    @property
    def spec(self) -> ComponentSpec:
        return ComponentSpec("contribution.shapley_stratified", "1.0.0", "data_value", "contribution_valuator", capabilities=("shapley", "stratified", "unbiased"))

    def value_contributions(self, request, utility, context):
        report = stratified_shapley_values(tuple(unit.target_id for unit in request.units), self._score(request, utility), high_call_budget=int(request.method_options.get("high_call_budget", 1024)), seed=int(request.method_options.get("seed", context.seed)), context=context)
        return ContributionReport(request.product.product_id, report.method, report.contributions, report.utility_calls, report.converged, report.diagnostics)


__all__ = [
    "AntitheticShapleyValuator",
    "OwenShapleyValuator",
    "StratifiedShapleyValuator",
    "TruncatedMonteCarloShapleyValuator",
    "antithetic_shapley_values",
    "owen_shapley_values",
    "stratified_shapley_values",
    "truncated_monte_carlo_shapley_values",
]
