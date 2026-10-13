from __future__ import annotations

import importlib.util
import math
from pathlib import Path

import pytest
from datamechbench.coalition_games import CoalitionGameTable
from datamechbench.data import make_analytic_valuation_cases
from datamechbench.methods.valuation import (
    OptionalMethodUnavailable,
    register_valuation_methods,
)
from datamechbench.methods.valuation_sota import evaluate_sota, sota_minimum_budget
from datamechbench.registry import MethodRegistry

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("shapiq") is None, reason="optional shapiq dependency"
)


def _game(kind: str, n: int = 6) -> CoalitionGameTable:
    owners = tuple(f"o{i}" for i in range(n))
    values = {}
    for mask in range(1 << n):
        if kind == "additive":
            value = sum(index + 1 for index in range(n) if mask & (1 << index))
        elif kind == "unanimity":
            value = float(mask & 0b111 == 0b111)
        else:
            value = math.sin(mask * 1.7) + 0.1 * mask.bit_count()
        values[mask] = value
    return CoalitionGameTable(owners, values, fidelity="high")


@pytest.mark.parametrize(
    "method_id",
    [
        "shapiq_svarm",
        "shapiq_stratified_sampling",
        "shapiq_kernel_shap",
        "shapiq_unbiased_kernel_shap",
        "shapiq_owen",
        "shapiq_leverage_shap",
        "shapiq_regression_msr",
    ],
)
def test_shapiq_adapters_preserve_owner_order_and_budget(method_id: str) -> None:
    table = _game("additive")
    output = evaluate_sota(method_id, table, budget=64, seed=3)

    assert tuple(output.scores) == table.owner_ids
    assert list(output.scores.values()) == pytest.approx(range(1, 7), abs=1e-5)
    assert 0 < output.utility_calls <= 64
    assert output.diagnostics["logical_calls"] == output.utility_calls
    assert output.diagnostics["estimand"] == "ordinary_shapley"
    assert output.diagnostics["backend_version"] == "1.7.0"


@pytest.mark.parametrize("kind", ["unanimity", "random"])
def test_sota_adapters_agree_with_exact_when_full_game_is_consumed(kind: str) -> None:
    table = _game(kind)
    exact = evaluate_sota("exact_table", table, budget=64, seed=0)
    for method_id in (
        "shapiq_svarm",
        "shapiq_kernel_shap",
        "shapiq_unbiased_kernel_shap",
        "shapiq_leverage_shap",
        "shapiq_regression_msr",
    ):
        estimate = evaluate_sota(method_id, table, budget=64, seed=0)
        assert estimate.scores == pytest.approx(exact.scores, abs=1e-5)


def test_sota_adapter_is_seed_deterministic_under_partial_budget() -> None:
    table = _game("random")
    first = evaluate_sota("shapiq_svarm", table, budget=36, seed=17)
    second = evaluate_sota("shapiq_svarm", table, budget=36, seed=17)
    assert first.scores == second.scores
    assert first.utility_calls == second.utility_calls


def test_regression_msr_exposes_a_replayable_paired_sampling_plan() -> None:
    high = _game("random")
    low = CoalitionGameTable(
        high.owner_ids,
        {mask: 0.7 * value + 0.1 * mask.bit_count() for mask, value in high.values.items()},
        fidelity="low",
    )

    high_output = evaluate_sota("shapiq_regression_msr", high, budget=36, seed=23)
    low_output = evaluate_sota("shapiq_regression_msr", low, budget=36, seed=23)

    assert high_output.diagnostics["sampled_mask_sequence"]
    assert high_output.diagnostics["sampled_mask_sequence"] == low_output.diagnostics[
        "sampled_mask_sequence"
    ]


def test_sota_methods_are_registered_with_same_target_metadata() -> None:
    registry = MethodRegistry()
    register_valuation_methods(registry)
    specs = {spec.method_id: spec for spec in registry.specs("valuation")}
    expected = {
        "shapiq_svarm",
        "shapiq_stratified_sampling",
        "shapiq_kernel_shap",
        "shapiq_unbiased_kernel_shap",
        "shapiq_owen",
        "shapiq_leverage_shap",
        "shapiq_regression_msr",
        "official_stratified_svarm",
        "official_stratified_svarm_plus",
        "official_linear_regression_msr",
        "asss_a",
        "asss_b",
        "pydvl_vrds",
        "pydvl_owen",
        "pydvl_group_testing",
    }
    assert expected <= set(specs)
    assert all(specs[item].estimand == "ordinary_shapley" for item in expected)
    assert all(specs[item].implementation_kind == "external_adapter" for item in expected)

    with pytest.raises(OptionalMethodUnavailable) as error:
        registry.create("shapiq_svarm", {"budget": 32}).evaluate(
            make_analytic_valuation_cases()[0], seed=0
        )
    assert error.value.reason == "missing_high_fidelity_game"


def test_sota_minimum_budgets_are_explicit() -> None:
    assert sota_minimum_budget("exact_table", 6) == 64
    assert sota_minimum_budget("shapiq_svarm", 6) == 2
    assert sota_minimum_budget("shapiq_leverage_shap", 6) == 2
    assert sota_minimum_budget("shapiq_regression_msr", 6) == 2
    assert sota_minimum_budget("official_stratified_svarm", 6) == 13
    assert sota_minimum_budget("pydvl_vrds", 6) == 2


def test_missing_official_backends_return_structured_unavailability() -> None:
    table = _game("additive")
    with pytest.raises(OptionalMethodUnavailable) as official:
        evaluate_sota(
            "official_stratified_svarm",
            table,
            budget=64,
            seed=0,
            official_repo=None,
        )
    with pytest.raises(OptionalMethodUnavailable) as pydvl:
        evaluate_sota("pydvl_vrds", table, budget=64, seed=0, pydvl_python=None)

    assert official.value.reason == "official_repository_path_missing:svarm"
    assert pydvl.value.reason == "pydvl_python_missing"


@pytest.mark.skipif(
    not Path("/root/yusen/DataValor/.venv-pydvl/bin/python").exists(),
    reason="pinned pyDVL environment is not present",
)
@pytest.mark.parametrize(
    "method_id,budget,tolerance",
    [("pydvl_vrds", 240, 0.01), ("pydvl_owen", 72, 1e-8)],
)
def test_pydvl_exact_marginal_adapters_recover_additive_game(
    method_id: str, budget: int, tolerance: float
) -> None:
    output = evaluate_sota(
        method_id,
        _game("additive"),
        budget=budget,
        seed=4,
        pydvl_python="/root/yusen/DataValor/.venv-pydvl/bin/python",
    )
    assert list(output.scores.values()) == pytest.approx(range(1, 7), abs=tolerance)
    assert 0 < output.utility_calls <= budget
    assert output.diagnostics["backend_version"] == "0.10.0"


@pytest.mark.skipif(
    not Path("/root/yusen/DataValor/.venv-pydvl/bin/python").exists(),
    reason="pinned pyDVL environment is not present",
)
def test_pydvl_group_testing_is_finite_and_strictly_budgeted() -> None:
    output = evaluate_sota(
        "pydvl_group_testing",
        _game("unanimity"),
        budget=200,
        seed=7,
        pydvl_python="/root/yusen/DataValor/.venv-pydvl/bin/python",
    )
    assert tuple(output.scores) == tuple(f"o{i}" for i in range(6))
    assert all(math.isfinite(value) for value in output.scores.values())
    assert output.utility_calls <= 200


@pytest.mark.skipif(
    not Path("/tmp/svarm-official/.git").exists(),
    reason="frozen official SVARM checkout is not present",
)
@pytest.mark.parametrize(
    "method_id",
    ["official_stratified_svarm", "official_stratified_svarm_plus"],
)
def test_frozen_official_svarm_adapters_are_finite_and_budgeted(method_id: str) -> None:
    output = evaluate_sota(
        method_id,
        _game("additive"),
        budget=64,
        seed=5,
        official_repo="/tmp/svarm-official",
    )

    assert tuple(output.scores) == tuple(f"o{i}" for i in range(6))
    assert all(math.isfinite(value) for value in output.scores.values())
    assert output.utility_calls <= 64
    assert output.diagnostics["source_commit"] == (
        "c4e30395b14b8bf9a8687d839d5b406f825bb23d"
    )
    if method_id.endswith("plus"):
        assert list(output.scores.values()) == pytest.approx(range(1, 7))
