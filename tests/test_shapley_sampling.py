from __future__ import annotations

import pytest

from datavalor.data_value import (
    antithetic_shapley_values,
    owen_shapley_values,
    stratified_shapley_values,
    truncated_monte_carlo_shapley_values,
)


def _additive(selection, context=None):
    del context
    weights = {"a": 1.0, "b": 2.0, "c": 3.0}
    return sum(weights[item] for item in selection)


def _interaction(selection, context=None):
    del context
    members = set(selection)
    return (
        sum({"a": 1.0, "b": 2.0, "c": 3.0}[item] for item in members)
        + 1.2 * {"a", "b"}.issubset(members)
        - 0.6 * {"b", "c"}.issubset(members)
    )


@pytest.mark.parametrize(
    "estimator,options",
    [
        (antithetic_shapley_values, {"permutations": 6}),
        (owen_shapley_values, {"samples": 64}),
        (truncated_monte_carlo_shapley_values, {"high_call_budget": 32, "tolerance": 0}),
        (stratified_shapley_values, {"high_call_budget": 40}),
    ],
)
def test_native_sampling_estimators_are_exact_on_additive_game(estimator, options):
    report = estimator(("a", "b", "c"), _additive, seed=4, **options)

    assert [item.value for item in report.contributions] == pytest.approx([1.0, 2.0, 3.0])
    assert report.utility_calls > 0


def test_antithetic_is_deterministic_and_records_reverse_pairing():
    first = antithetic_shapley_values(
        ("a", "b", "c"), _interaction, permutations=7, seed=12
    )
    second = antithetic_shapley_values(
        ("a", "b", "c"), _interaction, permutations=7, seed=12
    )

    assert first == second
    assert first.diagnostics["paired_permutations"] == 3
    assert first.diagnostics["unpaired_permutations"] == 1
    assert first.utility_calls == 1 + 7 * 3


def test_tmc_accounts_for_actual_calls_and_truncation():
    report = truncated_monte_carlo_shapley_values(
        ("a", "b", "c"),
        _interaction,
        high_call_budget=41,
        tolerance=2.5,
        seed=8,
    )

    assert report.utility_calls <= 41
    assert report.diagnostics["truncated_paths"] > 0
    assert report.diagnostics["completed_paths"] > 0


def test_stratified_covers_every_player_size_stratum_without_overspending():
    report = stratified_shapley_values(
        ("a", "b", "c"), _interaction, high_call_budget=40, seed=9
    )

    counts = report.diagnostics["stratum_counts"]
    assert set(counts) == {f"{owner}:{size}" for owner in ("a", "b", "c") for size in range(3)}
    assert min(counts.values()) >= 1
    assert report.utility_calls <= 40


def test_sampling_estimators_reject_duplicate_ids_and_small_budgets():
    with pytest.raises(ValueError, match="unique"):
        antithetic_shapley_values(("a", "a"), _additive, permutations=2, seed=0)
    with pytest.raises(ValueError, match="at least"):
        truncated_monte_carlo_shapley_values(
            ("a", "b", "c"), _additive, high_call_budget=4, tolerance=0, seed=0
        )
    with pytest.raises(ValueError, match="at least"):
        stratified_shapley_values(
            ("a", "b", "c"), _additive, high_call_budget=17, seed=0
        )


def test_sampling_estimators_are_unbiased_in_repeated_mean():
    estimates = [
        stratified_shapley_values(
            ("a", "b", "c"), _interaction, high_call_budget=24, seed=seed
        ).contributions
        for seed in range(300)
    ]
    means = [sum(run[index].value for run in estimates) / len(estimates) for index in range(3)]

    assert means == pytest.approx([1.6, 2.3, 2.7], abs=0.08)
