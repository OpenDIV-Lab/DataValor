from __future__ import annotations

import math

import pytest
from datamechbench.data import make_analytic_valuation_cases, make_real_valuation_cases
from datamechbench.runner import build_registry

EXPECTED_NATIVE_FAMILIES = {
    "random",
    "leave_one_out",
    "shapley_exact",
    "shapley_mc",
    "owen_shapley",
    "shapley_antithetic",
    "shapley_stratified",
    "shapley_exact_low_residual",
    "tmc_shapley",
    "data_banzhaf",
    "beta_shapley",
    "ame",
    "least_core_exact",
    "least_core_mc",
    "knn_shapley",
    "data_oob",
    "influence_function",
    "tracin_cp",
    "gradient_cosine",
    "datainf",
    "volume_shapley",
    "robust_volume_shapley",
}


def test_valuation_has_eighteen_native_families_and_dense_settings():
    registry = build_registry()
    native = {
        spec.family_id
        for spec in registry.specs("valuation")
        if spec.implementation_kind == "native"
    }
    analytic = {
        spec.family_id
        for spec in registry.compatible("valuation", "analytic")
        if spec.implementation_kind == "native"
    }
    real = {
        spec.family_id
        for spec in registry.compatible("valuation", "real_owner_data")
        if spec.implementation_kind == "native"
    }

    assert native == EXPECTED_NATIVE_FAMILIES
    assert len(analytic) >= 10
    assert real == EXPECTED_NATIVE_FAMILIES


@pytest.mark.parametrize(
    "method_id,tolerance",
    [
        ("tmc_shapley", 0.35),
        ("beta_shapley", 1e-8),
        ("ame", 0.45),
        ("least_core_exact", 1e-8),
        ("least_core_mc", 1e-8),
    ],
)
def test_generic_valuation_methods_recover_additive_owner_order(method_id, tolerance):
    registry = build_registry()
    case = make_analytic_valuation_cases()[0]
    method = registry.create(method_id, {"samples": 2048})

    first = method.evaluate(case, seed=7)
    second = method.evaluate(case, seed=7)

    assert first.scores == second.scores
    assert set(first.scores) == set(case.owner_ids)
    expected = case.truth_scores
    for owner in case.owner_ids:
        assert first.scores[owner] == pytest.approx(expected[owner], abs=tolerance)
    assert first.utility_calls is not None
    assert first.utility_calls > 0


@pytest.mark.parametrize("method_id", ["knn_shapley", "data_oob", "influence_function"])
def test_model_based_methods_emit_finite_deterministic_owner_scores(method_id):
    registry = build_registry()
    case = make_real_valuation_cases(seed=42)[0]
    method = registry.create(method_id, {"n_estimators": 24, "k": 5})

    first = method.evaluate(case, seed=11)
    second = method.evaluate(case, seed=11)

    assert first.scores == second.scores
    assert set(first.scores) == set(case.owner_ids)
    assert all(math.isfinite(value) for value in first.scores.values())
    assert max(first.scores.values()) > min(first.scores.values())
