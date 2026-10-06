"""Benchmark adapters for ordinary-Shapley estimators implemented in DataValor."""

from __future__ import annotations

from typing import Any, Mapping

from datavalor.data_value import (
    antithetic_shapley_values,
    exact_low_residual_shapley,
    monte_carlo_shapley_values,
    owen_shapley_values,
    stratified_shapley_values,
    truncated_monte_carlo_shapley_values,
)

from ..coalition_games import CoalitionGameTable
from ..models import ValuationCase, ValuationOutput


class OptionalMethodUnavailable(RuntimeError):
    """A runner-visible reason to record a method as skipped, not failed."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _utility(case: ValuationCase):
    return lambda coalition, context: case.utility(tuple(coalition))


def _output(report) -> ValuationOutput:
    return ValuationOutput(
        {item.target_id: float(item.value) for item in report.contributions},
        diagnostics=dict(report.diagnostics),
        utility_calls=report.utility_calls,
    )


def native_shapley_minimum_budget(method_id: str, n_players: int) -> int:
    """Return the smallest high-fidelity call budget accepted by an adapter."""

    if n_players < 1:
        raise ValueError("n_players must be positive")
    if method_id in {"shapley_mc", "shapley_antithetic"}:
        return n_players + 1
    if method_id == "owen_shapley":
        return 2 * n_players
    if method_id == "tmc_shapley":
        return n_players + 2
    if method_id == "shapley_stratified":
        return 2 * n_players * n_players
    raise KeyError(f"unsupported native Shapley budget adapter: {method_id}")


def native_shapley_parameters(
    method_id: str,
    budget: int,
    n_players: int,
) -> dict[str, int]:
    """Translate one high-call budget into an estimator's native parameters."""

    minimum = native_shapley_minimum_budget(method_id, n_players)
    if not isinstance(budget, int) or budget < minimum:
        raise ValueError(f"{method_id} budget must be at least {minimum}")
    if method_id == "shapley_mc":
        return {"samples": max(1, (budget - 1) // n_players)}
    if method_id == "shapley_antithetic":
        return {"permutations": max(1, (budget - 1) // n_players)}
    if method_id == "owen_shapley":
        return {"samples": max(1, budget // (2 * n_players))}
    return {"high_call_budget": budget}


def evaluate_shapley(
    method_id: str,
    case: ValuationCase,
    params: Mapping[str, Any],
    seed: int,
) -> ValuationOutput:
    """Route benchmark parameters to a reusable ordinary-Shapley estimator."""
    utility = _utility(case)
    n_players = len(case.owner_ids)
    samples = int(params.get("samples", 256))
    if method_id == "shapley_mc":
        return _output(
            monte_carlo_shapley_values(case.owner_ids, utility, samples=samples, seed=seed)
        )
    if method_id == "tmc_shapley":
        budget = int(params.get("high_call_budget", 2 + n_players * samples))
        return _output(
            truncated_monte_carlo_shapley_values(
                case.owner_ids,
                utility,
                high_call_budget=budget,
                tolerance=float(params.get("tolerance", 1e-6)),
                seed=seed,
            )
        )
    if method_id == "owen_shapley":
        return _output(
            owen_shapley_values(case.owner_ids, utility, samples=samples, seed=seed)
        )
    if method_id == "shapley_antithetic":
        return _output(
            antithetic_shapley_values(
                case.owner_ids,
                utility,
                permutations=int(params.get("permutations", samples)),
                seed=seed,
            )
        )
    if method_id == "shapley_stratified":
        budget = int(params.get("high_call_budget", max(2 * n_players * n_players, samples)))
        return _output(
            stratified_shapley_values(
                case.owner_ids, utility, high_call_budget=budget, seed=seed
            )
        )
    if method_id == "shapley_exact_low_residual":
        low_game = case.metadata.get("low_fidelity_game")
        if not isinstance(low_game, CoalitionGameTable):
            raise OptionalMethodUnavailable("missing_low_fidelity_game")
        if low_game.owner_ids != case.owner_ids:
            raise OptionalMethodUnavailable("low_fidelity_owner_mismatch")
        low_ratio = float(params.get("low_cost_ratio", case.metadata.get("low_cost_ratio", 0.0)))
        result = exact_low_residual_shapley(
            case.owner_ids,
            utility,
            lambda coalition, context: low_game.value(tuple(coalition)),
            equivalent_budget=float(params["equivalent_budget"]),
            low_cost_ratio=low_ratio,
            seed=seed,
        )
        return ValuationOutput(
            dict(zip(result.ids, result.values, strict=True)),
            diagnostics={
                "standard_errors": dict(
                    zip(result.ids, result.standard_errors, strict=True)
                ),
                "high_calls": result.cost.high_calls,
                "low_calls": result.cost.low_calls,
                "low_cost_ratio": result.cost.low_cost_ratio,
                "equivalent_high_calls": result.cost.equivalent_high_calls,
            },
            utility_calls=result.cost.high_calls + result.cost.low_calls,
        )
    raise KeyError(f"unsupported ordinary-Shapley method: {method_id}")


__all__ = [
    "OptionalMethodUnavailable",
    "evaluate_shapley",
    "native_shapley_minimum_budget",
    "native_shapley_parameters",
]
