from __future__ import annotations

import pytest
from datamechbench.coalition_games import CoalitionGameTable
from datamechbench.methods.valuation import (
    OptionalMethodUnavailable,
    register_valuation_methods,
)
from datamechbench.methods.valuation_shapley import (
    native_shapley_minimum_budget,
    native_shapley_parameters,
)
from datamechbench.models import ValuationCase
from datamechbench.registry import MethodRegistry


@pytest.fixture
def registry() -> MethodRegistry:
    result = MethodRegistry()
    register_valuation_methods(result)
    return result


def _additive_case(*, with_low: bool = False) -> ValuationCase:
    owners = ("a", "b", "c")
    weights = {"a": 1.0, "b": 2.0, "c": 4.0}
    metadata = {}
    if with_low:
        values = {
            mask: 0.8
            * sum(weights[owner] for index, owner in enumerate(owners) if mask & (1 << index))
            for mask in range(1 << len(owners))
        }
        metadata = {
            "low_fidelity_game": CoalitionGameTable(owners, values, fidelity="low"),
            "low_cost_ratio": 0.05,
        }
    return ValuationCase(
        "additive",
        owners,
        lambda coalition: sum(weights[owner] for owner in coalition),
        "analytic",
        metadata=metadata,
        truth_scores=weights,
    )


def test_same_target_methods_are_explicitly_labelled(registry: MethodRegistry) -> None:
    specs = {spec.method_id: spec for spec in registry.specs("valuation")}
    same_target = {
        "shapley_mc",
        "tmc_shapley",
        "owen_shapley",
        "shapley_antithetic",
        "shapley_stratified",
        "shapley_exact_low_residual",
    }
    assert all(specs[method].estimand == "ordinary_shapley" for method in same_target)
    assert specs["banzhaf_exact"].estimand == "alternative_estimand"
    assert specs["beta_shapley"].estimand == "alternative_estimand"


@pytest.mark.parametrize(
    "method_id,params",
    [
        ("tmc_shapley", {"high_call_budget": 50, "tolerance": 0.0}),
        ("owen_shapley", {"samples": 128}),
        ("shapley_antithetic", {"permutations": 12}),
        ("shapley_stratified", {"high_call_budget": 36}),
    ],
)
def test_native_shapley_adapters_recover_additive_game(
    registry: MethodRegistry, method_id: str, params: dict[str, float]
) -> None:
    case = _additive_case()
    output = registry.create(method_id, params).evaluate(case, seed=9)

    assert output.scores == pytest.approx(case.truth_scores)
    assert output.utility_calls is not None and output.utility_calls > 0
    assert output.diagnostics["estimand"] == "ordinary_shapley"


def test_exact_low_residual_requires_a_low_fidelity_game(registry: MethodRegistry) -> None:
    method = registry.create(
        "shapley_exact_low_residual", {"equivalent_budget": 40.0}
    )
    with pytest.raises(OptionalMethodUnavailable) as error:
        method.evaluate(_additive_case(), seed=0)
    assert error.value.reason == "missing_low_fidelity_game"

    output = method.evaluate(_additive_case(with_low=True), seed=0)
    assert output.scores == pytest.approx({"a": 1.0, "b": 2.0, "c": 4.0})
    assert output.diagnostics["equivalent_high_calls"] <= 40.0
    assert output.diagnostics["estimand"] == "ordinary_shapley"


@pytest.mark.parametrize(
    ("method_id", "budget", "n_players", "expected"),
    [
        ("shapley_mc", 24, 3, {"samples": 7}),
        ("shapley_antithetic", 24, 3, {"permutations": 7}),
        ("owen_shapley", 24, 3, {"samples": 4}),
        ("tmc_shapley", 24, 3, {"high_call_budget": 24}),
        ("shapley_stratified", 24, 3, {"high_call_budget": 24}),
    ],
)
def test_native_budget_translation_is_centralized_and_exact(
    method_id: str,
    budget: int,
    n_players: int,
    expected: dict[str, int],
) -> None:
    assert native_shapley_parameters(method_id, budget, n_players) == expected
    assert native_shapley_minimum_budget(method_id, n_players) <= budget
