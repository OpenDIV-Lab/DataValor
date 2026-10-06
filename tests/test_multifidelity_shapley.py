from __future__ import annotations

import math

import pytest

from datavalor.core import DataProduct, DataReference, RunContext, TaskContext
from datavalor.data_value import (
    ContributionRequest,
    ExactLowResidualShapleyValuator,
    ValuationTarget,
    exact_low_residual_shapley,
)


def _additive(weights):
    def utility(selection, context=None):
        del context
        return float(sum(weights[item] for item in selection))

    return utility


def _nonadditive(selection, context=None):
    del context
    members = set(selection)
    value = sum({"a": 1.0, "b": 2.0, "c": 3.0}[item] for item in members)
    if {"a", "b"}.issubset(members):
        value += 1.5
    if {"b", "c"}.issubset(members):
        value -= 0.75
    return value


def test_exact_low_residual_is_exact_and_efficient_on_additive_game():
    ids = ("a", "b", "c")
    high = _additive({"a": 1.0, "b": 2.0, "c": 3.0})
    low = _additive({"a": 0.4, "b": 1.4, "c": 2.4})

    result = exact_low_residual_shapley(
        ids,
        high,
        low,
        equivalent_budget=80.0,
        low_cost_ratio=0.2,
        seed=7,
    )

    assert result.values == pytest.approx((1.0, 2.0, 3.0))
    assert sum(result.values) == pytest.approx(high(ids) - high(()))
    assert result.cost.low_calls == 2 ** len(ids)
    assert result.cost.equivalent_high_calls <= 80.0
    assert all(error == pytest.approx(0.0) for error in result.standard_errors)


def test_exact_low_residual_rejects_invalid_ids_cost_and_budget():
    utility = _additive({"a": 1.0, "b": 2.0})

    with pytest.raises(ValueError, match="unique"):
        exact_low_residual_shapley(
            ("a", "a"),
            utility,
            utility,
            equivalent_budget=20,
            low_cost_ratio=0.1,
            seed=0,
        )
    with pytest.raises(ValueError, match="low_cost_ratio"):
        exact_low_residual_shapley(
            ("a", "b"),
            utility,
            utility,
            equivalent_budget=20,
            low_cost_ratio=1.0,
            seed=0,
        )
    with pytest.raises(ValueError, match="at least"):
        exact_low_residual_shapley(
            ("a", "b"),
            utility,
            utility,
            equivalent_budget=8.3,
            low_cost_ratio=0.1,
            seed=0,
        )


def test_exact_low_residual_is_deterministic_and_never_overspends():
    kwargs = {
        "ids": ("a", "b", "c"),
        "high_utility": _nonadditive,
        "low_utility": lambda selection, context=None: 0.8 * _nonadditive(selection),
        "equivalent_budget": 43.7,
        "low_cost_ratio": 0.17,
        "seed": 91,
    }

    first = exact_low_residual_shapley(**kwargs)
    second = exact_low_residual_shapley(**kwargs)

    assert first == second
    assert first.cost.equivalent_high_calls <= kwargs["equivalent_budget"]
    assert set(first.stratum_counts) == {
        (player, size) for player in kwargs["ids"] for size in range(len(kwargs["ids"]))
    }
    assert min(first.stratum_counts.values()) >= 1
    assert all(math.isfinite(error) and error >= 0 for error in first.standard_errors)


def test_exact_low_residual_rejects_nonfinite_and_labels_failed_fidelity():
    def bad_low(selection, context=None):
        del context
        if set(selection) == {"a"}:
            return float("nan")
        return 0.0

    with pytest.raises(ValueError, match="low-fidelity.*finite"):
        exact_low_residual_shapley(
            ("a", "b"),
            _additive({"a": 1.0, "b": 2.0}),
            bad_low,
            equivalent_budget=20,
            low_cost_ratio=0.1,
            seed=0,
        )

    def bad_high(selection, context=None):
        del context
        if set(selection) == {"a"}:
            raise RuntimeError("training failed")
        return 0.0

    with pytest.raises(RuntimeError, match="high-fidelity.*training failed"):
        exact_low_residual_shapley(
            ("a", "b"),
            bad_high,
            _additive({"a": 0.5, "b": 1.0}),
            equivalent_budget=20,
            low_cost_ratio=0.1,
            seed=0,
        )


def test_exact_low_residual_agrees_with_exact_shapley_in_repeated_mean():
    ids = ("a", "b", "c")

    def low(selection, context=None):
        del context
        return 0.75 * _nonadditive(selection)

    estimates = [
        exact_low_residual_shapley(
            ids,
            _nonadditive,
            low,
            equivalent_budget=28.0,
            low_cost_ratio=0.1,
            seed=seed,
        ).values
        for seed in range(300)
    ]
    means = tuple(sum(row[index] for row in estimates) / len(estimates) for index in range(3))

    assert means == pytest.approx((1.75, 2.375, 2.625), abs=0.035)


def test_valuator_reads_low_utility_and_returns_native_report():
    product = DataProduct("p", "demo", DataReference("memory://demo", "records"), "owner")
    ids = ("a", "b")
    request = ContributionRequest(
        product,
        tuple(ValuationTarget(owner, "p", "owner") for owner in ids),
        TaskContext("task", "classification"),
        {
            "low_utility": _additive({"a": 0.5, "b": 1.0}),
            "equivalent_budget": 20.0,
            "low_cost_ratio": 0.1,
            "seed": 13,
        },
    )

    report = ExactLowResidualShapleyValuator().value_contributions(
        request,
        _additive({"a": 1.0, "b": 2.0}),
        RunContext("run", seed=99),
    )

    assert report.method == "shapley_exact_low_residual"
    assert [item.target_id for item in report.contributions] == ["a", "b"]
    assert [item.value for item in report.contributions] == pytest.approx([1.0, 2.0])
    assert all("std_error" in item.uncertainty for item in report.contributions)
    assert report.diagnostics["equivalent_high_calls"] <= 20.0
