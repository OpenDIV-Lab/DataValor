from __future__ import annotations

import importlib.util

import pytest
from datamechbench.data import make_analytic_valuation_cases, make_real_valuation_cases
from datamechbench.methods.valuation import (
    OptionalMethodUnavailable,
    register_valuation_methods,
)
from datamechbench.metrics import evaluate_valuation_metrics
from datamechbench.models import ValuationOutput
from datamechbench.registry import MethodRegistry, validate_output


@pytest.fixture
def valuation_registry():
    registry = MethodRegistry()
    register_valuation_methods(registry)
    return registry


def test_all_valuation_methods_are_explicitly_registered(valuation_registry):
    assert {spec.method_id for spec in valuation_registry.specs("valuation")} == {
        "random",
        "leave_one_out",
        "shapley_exact",
        "shapley_mc",
        "owen_shapley",
        "shapley_antithetic",
        "shapley_stratified",
        "shapley_exact_low_residual",
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
        "banzhaf_exact",
        "tmc_shapley",
        "beta_shapley",
        "ame",
        "least_core_exact",
        "least_core_mc",
        "knn_shapley",
        "data_oob",
        "influence_function",
        "pydvl_tmc_shapley",
        "tracin_cp",
        "gradient_cosine",
        "datainf",
        "volume_shapley",
        "robust_volume_shapley",
    }


@pytest.mark.parametrize(
    "method_id,params",
    [
        ("random", {}),
        ("leave_one_out", {}),
        ("shapley_exact", {}),
        ("shapley_mc", {"samples": 32}),
        ("banzhaf_exact", {}),
    ],
)
def test_core_adapters_return_complete_valid_scores(valuation_registry, method_id, params):
    case = make_analytic_valuation_cases()[0]
    method = valuation_registry.create(method_id, params)
    output = method.evaluate(case, seed=7)

    validate_output(method.spec, case, output)
    assert set(output.scores) == set(case.owner_ids)
    if method_id in {"shapley_exact", "shapley_mc", "banzhaf_exact"}:
        assert list(output.scores.values()) == pytest.approx([1, 2, 3, 4, 5, 6])


def test_random_is_seed_reproducible(valuation_registry):
    case = make_analytic_valuation_cases()[0]
    method = valuation_registry.create("random")
    assert method.evaluate(case, 19).scores == method.evaluate(case, 19).scores
    assert method.evaluate(case, 19).scores != method.evaluate(case, 20).scores


def test_pydvl_missing_dependency_is_a_typed_skip(valuation_registry):
    if importlib.util.find_spec("pydvl") is not None:
        pytest.skip("pyDVL is installed; optional integration is exercised by root tests")
    method = valuation_registry.create("pydvl_tmc_shapley")
    with pytest.raises(OptionalMethodUnavailable) as error:
        method.evaluate(make_analytic_valuation_cases()[0], seed=0)
    assert error.value.reason == "optional_dependency_missing:pydvl"


def test_valuation_metrics_route_accuracy_cost_and_na_reasons(valuation_registry):
    case = make_analytic_valuation_cases()[0]
    exact = valuation_registry.create("shapley_exact").evaluate(case, 0)
    approximate = valuation_registry.create("shapley_mc", {"samples": 16}).evaluate(case, 3)
    metrics = evaluate_valuation_metrics(case, approximate, oracle_output=exact)

    assert metrics["score_mae"].value == pytest.approx(0.0)
    assert metrics["score_spearman"].value == pytest.approx(1.0)
    assert metrics["utility_calls"].applicable
    assert metrics["runtime_seconds"].value >= 0
    assert not metrics["topk_test_utility"].applicable
    assert metrics["topk_test_utility"].reason == "missing_test_dataset"
    assert metrics["bad_owner_rank"].reason == "missing_bad_owner"
    assert metrics["replication_gain"].reason == "not_replication_case"
    assert metrics["kendall_stability"].reason == "missing_peer_outputs"


def test_real_case_metrics_include_topk_bad_rank_replication_and_stability():
    real = {case.case_id: case for case in make_real_valuation_cases(seed=42)}
    clean_scores = {owner: float(index + 1) for index, owner in enumerate(real["C-real-clean"].owner_ids)}
    noisy_scores = dict(clean_scores, o7=-1.0)
    noisy_output = ValuationOutput(
        noisy_scores,
        diagnostics={"runtime_seconds": 0.01, "top_k": 3},
        utility_calls=10,
    )
    peer = ValuationOutput(
        {owner: score + 0.01 for owner, score in noisy_scores.items()},
        diagnostics={"runtime_seconds": 0.02},
    )
    noisy_metrics = evaluate_valuation_metrics(real["C-real-noise"], noisy_output, peer_outputs=(peer,))
    assert noisy_metrics["topk_test_utility"].applicable
    assert 0 <= noisy_metrics["topk_test_utility"].value <= 1
    assert noisy_metrics["bad_owner_rank"].value == pytest.approx(1.0)
    assert noisy_metrics["kendall_stability"].value == pytest.approx(1.0)

    duplicate_scores = {**clean_scores, "o8": clean_scores["o0"] / 2}
    duplicate_scores["o0"] /= 2
    duplicate_output = ValuationOutput(duplicate_scores)
    clean_output = ValuationOutput(clean_scores)
    duplicate_metrics = evaluate_valuation_metrics(
        real["C-real-dup"],
        duplicate_output,
        peer_outputs=((real["C-real-clean"], clean_output),),
    )
    assert duplicate_metrics["replication_gain"].value == pytest.approx(0.0)
