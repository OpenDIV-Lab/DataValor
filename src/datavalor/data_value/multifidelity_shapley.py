"""Multi-fidelity Shapley estimators for small provider-level games."""

from __future__ import annotations

import itertools
import math
import random
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from datavalor.core import ComponentSpec, RunContext

from .interfaces import ContributionValuator, UtilityFunction
from .models import ContributionReport, ContributionRequest, ValueEstimate

CoalitionUtility = Callable[[tuple[str, ...], RunContext | None], float]


@dataclass(frozen=True)
class MultiFidelityCost:
    """Transparent raw and high-fidelity-equivalent evaluation cost."""

    high_calls: int
    low_calls: int
    low_cost_ratio: float

    @property
    def equivalent_high_calls(self) -> float:
        return self.high_calls + self.low_calls * self.low_cost_ratio


@dataclass(frozen=True)
class MultiFidelityShapleyResult:
    """Estimated values, uncertainty, allocation, and realized cost."""

    ids: tuple[str, ...]
    values: tuple[float, ...]
    standard_errors: tuple[float, ...]
    cost: MultiFidelityCost
    stratum_counts: Mapping[tuple[str, int], int]


def _coalition(ids: tuple[str, ...], mask: int) -> tuple[str, ...]:
    return tuple(owner for index, owner in enumerate(ids) if mask & (1 << index))


def _evaluate(
    utility: CoalitionUtility,
    selection: tuple[str, ...],
    context: RunContext | None,
    fidelity: str,
) -> float:
    try:
        value = float(utility(selection, context))
    except Exception as exc:
        raise RuntimeError(
            f"{fidelity}-fidelity utility failed for coalition {selection!r}: {exc}"
        ) from exc
    if not math.isfinite(value):
        raise ValueError(
            f"{fidelity}-fidelity utility must be finite for coalition {selection!r}"
        )
    return value


def _masks_without_player(n_players: int, player: int, size: int) -> tuple[int, ...]:
    others = tuple(index for index in range(n_players) if index != player)
    masks = []
    for subset in itertools.combinations(others, size):
        mask = 0
        for member in subset:
            mask |= 1 << member
        masks.append(mask)
    return tuple(masks)


def _standard_error(samples: Sequence[float]) -> float:
    if len(samples) < 2:
        return 0.0
    mean = sum(samples) / len(samples)
    variance = sum((value - mean) ** 2 for value in samples) / (len(samples) - 1)
    return math.sqrt(variance / len(samples))


def exact_low_residual_shapley(
    ids: Sequence[str],
    high_utility: CoalitionUtility,
    low_utility: CoalitionUtility,
    *,
    equivalent_budget: float,
    low_cost_ratio: float,
    seed: int,
    context: RunContext | None = None,
) -> MultiFidelityShapleyResult:
    """Estimate high-fidelity Shapley using an exact low game and residuals.

    Every player/predecessor-size stratum receives at least one paired residual
    sample. Additional sample counts are fixed before any utility observation,
    preserving finite-budget unbiasedness.
    """

    names = tuple(str(owner) for owner in ids)
    if len(set(names)) != len(names):
        raise ValueError("contribution unit IDs must be unique")
    if not math.isfinite(low_cost_ratio) or not 0 < low_cost_ratio < 1:
        raise ValueError("low_cost_ratio must be finite and strictly between zero and one")
    if not math.isfinite(equivalent_budget) or equivalent_budget <= 0:
        raise ValueError("equivalent_budget must be finite and positive")

    n_players = len(names)
    low_calls = 1 << n_players
    strata = tuple((player, size) for player in range(n_players) for size in range(n_players))
    minimum_high_calls = 2 * len(strata)
    minimum_cost = minimum_high_calls + low_calls * low_cost_ratio
    if equivalent_budget + 1e-12 < minimum_cost:
        raise ValueError(
            f"equivalent_budget must be at least {minimum_cost:.12g} for full low-table "
            "coverage and one residual sample per stratum"
        )

    low_table = {
        mask: _evaluate(low_utility, _coalition(names, mask), context, "low")
        for mask in range(low_calls)
    }
    marginal_budget = int((equivalent_budget - low_calls * low_cost_ratio) // 2)
    counts = dict.fromkeys(strata, 1)
    extra_samples = marginal_budget - len(strata)
    complete_rounds, remainder = divmod(extra_samples, len(strata)) if strata else (0, 0)
    for key in strata:
        counts[key] += complete_rounds
    rng = random.Random(seed)
    if remainder:
        for key in rng.sample(strata, remainder):
            counts[key] += 1

    values = [0.0] * n_players
    standard_errors = [0.0] * n_players
    high_calls = 0
    for player in range(n_players):
        player_bit = 1 << player
        stratum_values = []
        stratum_errors = []
        for size in range(n_players):
            key = (player, size)
            population = _masks_without_player(n_players, player, size)
            low_marginals = [
                low_table[mask | player_bit] - low_table[mask] for mask in population
            ]
            residuals = []
            for _ in range(counts[key]):
                mask = population[rng.randrange(len(population))]
                without = _coalition(names, mask)
                with_player = _coalition(names, mask | player_bit)
                high_without = _evaluate(high_utility, without, context, "high")
                high_with = _evaluate(high_utility, with_player, context, "high")
                high_calls += 2
                low_marginal = low_table[mask | player_bit] - low_table[mask]
                residuals.append(high_with - high_without - low_marginal)
            stratum_values.append(sum(low_marginals) / len(low_marginals) + sum(residuals) / len(residuals))
            stratum_errors.append(_standard_error(residuals))
        if n_players:
            values[player] = sum(stratum_values) / n_players
            standard_errors[player] = math.sqrt(sum(error**2 for error in stratum_errors)) / n_players

    cost = MultiFidelityCost(high_calls, low_calls, low_cost_ratio)
    if cost.equivalent_high_calls > equivalent_budget + 1e-9:
        raise RuntimeError("internal cost allocation exceeded equivalent_budget")
    named_counts = MappingProxyType(
        {(names[player], size): count for (player, size), count in counts.items()}
    )
    return MultiFidelityShapleyResult(
        names,
        tuple(values),
        tuple(standard_errors),
        cost,
        named_counts,
    )


class ExactLowResidualShapleyValuator(ContributionValuator):
    """DataValor wrapper for exact-low residual Shapley estimation."""

    @property
    def spec(self) -> ComponentSpec:
        return ComponentSpec(
            "contribution.shapley_exact_low_residual",
            "1.0.0",
            "data_value",
            "contribution_valuator",
            capabilities=("shapley", "multi_fidelity", "stratified", "unbiased"),
        )

    def value_contributions(
        self,
        request: ContributionRequest,
        utility: UtilityFunction,
        context: RunContext,
    ) -> ContributionReport:
        options = request.method_options
        low_utility: Any = options.get("low_utility")
        if low_utility is None:
            raise ValueError("method_options['low_utility'] is required")

        def score(candidate: Any, selection: tuple[str, ...], ctx: RunContext | None) -> float:
            if hasattr(candidate, "score"):
                return float(candidate.score(request.product, selection, request.task, ctx))
            return float(candidate(selection, ctx))

        result = exact_low_residual_shapley(
            tuple(unit.target_id for unit in request.units),
            lambda selection, ctx: score(utility, selection, ctx),
            lambda selection, ctx: score(low_utility, selection, ctx),
            equivalent_budget=float(options["equivalent_budget"]),
            low_cost_ratio=float(options["low_cost_ratio"]),
            seed=int(options.get("seed", context.seed)),
            context=context,
        )
        estimates = tuple(
            ValueEstimate(
                target_id,
                value,
                "utility",
                uncertainty={"std_error": standard_error},
                diagnostics={
                    "stratum_samples": tuple(
                        result.stratum_counts[(target_id, size)]
                        for size in range(len(result.ids))
                    )
                },
            )
            for target_id, value, standard_error in zip(
                result.ids, result.values, result.standard_errors, strict=True
            )
        )
        return ContributionReport(
            request.product.product_id,
            "shapley_exact_low_residual",
            estimates,
            utility_calls=result.cost.high_calls + result.cost.low_calls,
            converged=True,
            diagnostics={
                "high_calls": result.cost.high_calls,
                "low_calls": result.cost.low_calls,
                "low_cost_ratio": result.cost.low_cost_ratio,
                "equivalent_high_calls": result.cost.equivalent_high_calls,
                "seed": int(options.get("seed", context.seed)),
            },
        )


__all__ = [
    "ExactLowResidualShapleyValuator",
    "MultiFidelityCost",
    "MultiFidelityShapleyResult",
    "exact_low_residual_shapley",
]
