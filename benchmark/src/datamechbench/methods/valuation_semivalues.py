"""Native cooperative-game valuation algorithms used by the V leaderboard."""

from __future__ import annotations

import itertools
import math
from collections.abc import Mapping
from typing import Any

import numpy as np
from scipy.optimize import linprog, minimize
from sklearn.linear_model import Lasso

from ..models import ValuationCase, ValuationOutput


class _Utility:
    def __init__(self, case: ValuationCase) -> None:
        self.case = case
        self.calls = 0
        self.cache: dict[tuple[str, ...], float] = {}

    def __call__(self, coalition) -> float:
        key = tuple(sorted(set(coalition)))
        if key not in self.cache:
            self.cache[key] = float(self.case.utility(key))
            self.calls += 1
        return self.cache[key]


def _coalitions(players: tuple[str, ...]):
    for size in range(len(players) + 1):
        yield from itertools.combinations(players, size)


def _beta_shapley(
    case: ValuationCase, params: Mapping[str, Any], seed: int
) -> ValuationOutput:
    del seed
    utility = _Utility(case)
    players = case.owner_ids
    alpha = float(params.get("alpha", 4.0))
    beta = float(params.get("beta", 1.0))
    if alpha <= 0 or beta <= 0:
        raise ValueError("Beta-Shapley alpha and beta must be positive")
    normalizer = math.gamma(alpha) * math.gamma(beta) / math.gamma(alpha + beta)
    scores: dict[str, float] = {}
    for owner in players:
        others = tuple(item for item in players if item != owner)
        score = 0.0
        for subset in _coalitions(others):
            size = len(subset)
            weight = (
                math.gamma(size + alpha)
                * math.gamma(len(others) - size + beta)
                / math.gamma(len(others) + alpha + beta)
                / normalizer
            )
            score += weight * (utility((*subset, owner)) - utility(subset))
        scores[owner] = score
    return ValuationOutput(
        scores,
        diagnostics={"alpha": alpha, "beta": beta},
        utility_calls=utility.calls,
    )


def _ame(case: ValuationCase, params: Mapping[str, Any], seed: int) -> ValuationOutput:
    utility = _Utility(case)
    players = case.owner_ids
    samples = max(int(params.get("samples", 512)), len(players) * 4)
    rng = np.random.default_rng(seed)
    design = rng.integers(0, 2, size=(samples, len(players)), endpoint=False)
    design[0, :] = 0
    design[1, :] = 1
    response = np.asarray(
        [utility(tuple(player for player, flag in zip(players, row) if flag)) for row in design],
        dtype=float,
    )
    model = Lasso(
        alpha=float(params.get("alpha", 1e-8)),
        fit_intercept=True,
        max_iter=20000,
        random_state=seed,
    )
    model.fit(design.astype(float), response)
    return ValuationOutput(
        dict(zip(players, (float(value) for value in model.coef_), strict=True)),
        diagnostics={
            "samples": samples,
            "regression": "lasso",
            "design": "bernoulli_randomized_experiment",
            "inclusion_probability": 0.5,
        },
        utility_calls=utility.calls,
    )


def _least_core(
    case: ValuationCase,
    params: Mapping[str, Any],
    seed: int,
    *,
    sampled: bool,
) -> ValuationOutput:
    utility = _Utility(case)
    players = case.owner_ids
    all_subsets = list(_coalitions(players))
    if sampled and int(params.get("samples", 128)) < len(all_subsets):
        rng = np.random.default_rng(seed)
        sample_count = max(int(params.get("samples", 128)), len(players) + 2)
        mandatory = [(), players, *((owner,) for owner in players)]
        remaining = [subset for subset in all_subsets if subset not in mandatory]
        chosen = rng.choice(len(remaining), size=min(sample_count - len(mandatory), len(remaining)), replace=False)
        subsets = [*mandatory, *(remaining[int(index)] for index in chosen)]
    else:
        subsets = all_subsets
    baseline = utility(())
    grand = utility(players) - baseline
    constraints = []
    bounds = []
    for subset in subsets:
        if not subset or subset == players:
            continue
        row = [-(1.0 if owner in subset else 0.0) for owner in players]
        row.append(-1.0)
        constraints.append(row)
        bounds.append(-(utility(subset) - baseline))
    objective = np.zeros(len(players) + 1)
    objective[-1] = 1.0
    equality = np.asarray([[1.0] * len(players) + [0.0]])
    solved = linprog(
        objective,
        A_ub=np.asarray(constraints) if constraints else None,
        b_ub=np.asarray(bounds) if bounds else None,
        A_eq=equality,
        b_eq=np.asarray([grand]),
        bounds=[(None, None)] * len(players) + [(0.0, None)],
        method="highs",
    )
    if not solved.success:
        raise RuntimeError(f"least-core optimization failed: {solved.message}")
    epsilon = float(solved.x[-1])
    # Select the egalitarian (minimum L2 norm) point from the optimal
    # least-core polytope.  The LP determines epsilon; this convex quadratic
    # tie-break determines a stable allocation without changing epsilon.
    coalition_constraints = []
    for subset in subsets:
        if not subset or subset == players:
            continue
        required = utility(subset) - baseline - epsilon
        indices = tuple(index for index, owner in enumerate(players) if owner in subset)
        coalition_constraints.append(
            {
                "type": "ineq",
                "fun": lambda values, indices=indices, required=required: (
                    sum(values[index] for index in indices) - required
                ),
            }
        )
    tie_break = minimize(
        lambda values: float(np.dot(values, values)),
        solved.x[:-1],
        method="SLSQP",
        constraints=[
            {"type": "eq", "fun": lambda values: float(np.sum(values) - grand)},
            *coalition_constraints,
        ],
        options={"ftol": 1e-12, "maxiter": 2000},
    )
    allocation = tie_break.x if tie_break.success else solved.x[:-1]
    return ValuationOutput(
        dict(zip(players, (float(value) for value in allocation), strict=True)),
        diagnostics={
            "epsilon": epsilon,
            "constraints": len(constraints),
            "sampled": sampled,
            "tie_break": "minimum_l2_norm",
            "tie_break_success": bool(tie_break.success),
        },
        utility_calls=utility.calls,
    )


def evaluate_semivalue(
    method_id: str,
    case: ValuationCase,
    params: Mapping[str, Any],
    seed: int,
) -> ValuationOutput:
    if method_id == "beta_shapley":
        return _beta_shapley(case, params, seed)
    if method_id == "ame":
        return _ame(case, params, seed)
    if method_id == "least_core_exact":
        return _least_core(case, params, seed, sampled=False)
    if method_id == "least_core_mc":
        return _least_core(case, params, seed, sampled=True)
    raise KeyError(f"unknown native semivalue method: {method_id}")


__all__ = ["evaluate_semivalue"]
