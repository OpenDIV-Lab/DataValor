"""Exact-utility market consequences of estimated owner values."""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass
from typing import Mapping

from scipy.stats import spearmanr

from .coalition_games import CoalitionGameTable


@dataclass(frozen=True)
class AcquisitionOutcome:
    selected_ids: tuple[str, ...]
    oracle_ids: tuple[str, ...]
    exact_utility_regret: float
    selected_owner_disagreement: int
    budget_violation: float = 0.0


@dataclass(frozen=True)
class SequentialOutcome:
    selected_ids: tuple[str, ...]
    oracle_ids: tuple[str, ...]
    stop_index: int
    oracle_stop_index: int
    stopping_regret: int
    exact_utility_regret: float


@dataclass(frozen=True)
class MarketConsequences:
    top_k: Mapping[int, AcquisitionOutcome]
    knapsack: Mapping[float, AcquisitionOutcome]
    sequential: Mapping[float, SequentialOutcome]
    revenue_conservation_error: float
    rank_stability: float


def build_owner_costs(
    owner_row_counts: Mapping[str, int],
    *,
    unit_cost: float,
) -> dict[str, float]:
    if not math.isfinite(unit_cost) or unit_cost <= 0:
        raise ValueError("unit_cost must be finite and positive")
    result: dict[str, float] = {}
    for owner in sorted(owner_row_counts):
        count = owner_row_counts[owner]
        if not isinstance(count, int) or count <= 0:
            raise ValueError("owner row counts must be positive integers")
        result[owner] = float(count * unit_cost)
    return result


def _ordered(scores: Mapping[str, float], owners: tuple[str, ...]) -> tuple[str, ...]:
    if set(scores) != set(owners):
        raise ValueError("scores must match game owner IDs")
    if any(not math.isfinite(float(value)) for value in scores.values()):
        raise ValueError("scores must be finite")
    return tuple(sorted(owners, key=lambda owner: (-float(scores[owner]), owner)))


def _utility(game: CoalitionGameTable, owners: tuple[str, ...]) -> float:
    return float(game.value(owners) - game.values[0])


def _disagreement(left: tuple[str, ...], right: tuple[str, ...]) -> int:
    return len(set(left).symmetric_difference(right))


def evaluate_top_k(
    game: CoalitionGameTable,
    estimated_scores: Mapping[str, float],
    exact_scores: Mapping[str, float],
    *,
    k: int,
) -> AcquisitionOutcome:
    if not 1 <= k <= len(game.owner_ids):
        raise ValueError("k must be between one and the owner count")
    selected = _ordered(estimated_scores, game.owner_ids)[:k]
    oracle = _ordered(exact_scores, game.owner_ids)[:k]
    return AcquisitionOutcome(
        selected,
        oracle,
        max(0.0, _utility(game, oracle) - _utility(game, selected)),
        _disagreement(selected, oracle),
    )


def evaluate_knapsack(
    game: CoalitionGameTable,
    estimated_scores: Mapping[str, float],
    owner_costs: Mapping[str, float],
    *,
    budget_fraction: float,
) -> AcquisitionOutcome:
    if set(owner_costs) != set(game.owner_ids):
        raise ValueError("owner costs must match game owner IDs")
    if not 0 <= budget_fraction <= 1:
        raise ValueError("budget_fraction must be in [0, 1]")
    budget = budget_fraction * sum(float(value) for value in owner_costs.values())
    feasible = tuple(
        coalition
        for size in range(len(game.owner_ids) + 1)
        for coalition in itertools.combinations(game.owner_ids, size)
        if sum(float(owner_costs[owner]) for owner in coalition) <= budget + 1e-12
    )
    selected = max(
        feasible,
        key=lambda coalition: (
            sum(float(estimated_scores[owner]) for owner in coalition),
            _utility(game, coalition),
            tuple(reversed(coalition)),
        ),
    )
    oracle = max(feasible, key=lambda coalition: (_utility(game, coalition), tuple(reversed(coalition))))
    spent = sum(float(owner_costs[owner]) for owner in selected)
    return AcquisitionOutcome(
        selected,
        oracle,
        max(0.0, _utility(game, oracle) - _utility(game, selected)),
        _disagreement(selected, oracle),
        max(0.0, spent - budget),
    )


def _stop(
    game: CoalitionGameTable,
    order: tuple[str, ...],
    target: float,
) -> tuple[tuple[str, ...], int]:
    for index in range(1, len(order) + 1):
        coalition = order[:index]
        if _utility(game, coalition) >= target - 1e-12:
            return coalition, index
    return order, len(order)


def evaluate_sequential(
    game: CoalitionGameTable,
    estimated_scores: Mapping[str, float],
    exact_scores: Mapping[str, float],
    *,
    target_fraction: float,
) -> SequentialOutcome:
    if not 0 < target_fraction <= 1:
        raise ValueError("target_fraction must be in (0, 1]")
    target = target_fraction * _utility(game, game.owner_ids)
    selected, stop_index = _stop(game, _ordered(estimated_scores, game.owner_ids), target)
    oracle, oracle_index = _stop(game, _ordered(exact_scores, game.owner_ids), target)
    return SequentialOutcome(
        selected,
        oracle,
        stop_index,
        oracle_index,
        stop_index - oracle_index,
        max(0.0, _utility(game, oracle) - _utility(game, selected)),
    )


def evaluate_market_consequences(
    game: CoalitionGameTable,
    estimated_scores: Mapping[str, float],
    exact_scores: Mapping[str, float],
    owner_costs: Mapping[str, float],
) -> MarketConsequences:
    predicted = [float(estimated_scores[owner]) for owner in game.owner_ids]
    exact = [float(exact_scores[owner]) for owner in game.owner_ids]
    return MarketConsequences(
        {k: evaluate_top_k(game, estimated_scores, exact_scores, k=k) for k in (1, 2, 3)},
        {
            fraction: evaluate_knapsack(
                game, estimated_scores, owner_costs, budget_fraction=fraction
            )
            for fraction in (0.25, 0.5, 0.75)
        },
        {
            fraction: evaluate_sequential(
                game, estimated_scores, exact_scores, target_fraction=fraction
            )
            for fraction in (0.5, 0.8)
        },
        abs(sum(predicted) - _utility(game, game.owner_ids)),
        float(spearmanr(predicted, exact).statistic),
    )


__all__ = [
    "AcquisitionOutcome",
    "MarketConsequences",
    "SequentialOutcome",
    "build_owner_costs",
    "evaluate_knapsack",
    "evaluate_market_consequences",
    "evaluate_sequential",
    "evaluate_top_k",
]
