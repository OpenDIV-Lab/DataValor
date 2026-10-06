from pathlib import Path

import pytest
from datamechbench.coalition_games import CoalitionGameTable
from datamechbench.methods.valuation_regression_msr import run_regression_msr
from datamechbench.methods.valuation_sota import evaluate_sota, sota_minimum_budget

OFFICIAL = Path(__file__).parents[1] / "external/regression_msr_official"


def _additive_game(owner_count: int = 8) -> CoalitionGameTable:
    owners = tuple(f"o{i}" for i in range(owner_count))
    return CoalitionGameTable(
        owners,
        {
            mask: float(
                sum(index + 1 for index in range(owner_count) if mask & (1 << index))
            )
            for mask in range(1 << owner_count)
        },
        "high",
    )


@pytest.mark.skipif(not OFFICIAL.is_dir(), reason="official Regression MSR checkout absent")
def test_linear_msr_recovers_additive_game_with_strict_call_accounting() -> None:
    """Catches adapters that misencode coalition masks or hide endpoint calls."""

    output = run_regression_msr(
        _additive_game(),
        budget=102,
        seed=7,
        official_repo=OFFICIAL,
        variant="linear",
    )

    assert output.scores == pytest.approx(
        {f"o{index}": float(index + 1) for index in range(8)}, abs=1e-10
    )
    assert output.utility_calls <= 102
    assert output.diagnostics["source_commit"] == (
        "77525daf334aadffa8157b6d2693dc34ce33ecf6"
    )


@pytest.mark.skipif(not OFFICIAL.is_dir(), reason="official Regression MSR checkout absent")
def test_linear_msr_is_available_through_the_common_sota_registry() -> None:
    output = evaluate_sota(
        "official_linear_regression_msr",
        _additive_game(),
        budget=102,
        seed=7,
        regression_msr_repo=OFFICIAL,
    )

    assert output.scores == pytest.approx(
        {f"o{index}": float(index + 1) for index in range(8)}, abs=1e-10
    )
    assert output.diagnostics["backend"] == "official_linear_regression_msr"
    assert sota_minimum_budget("official_linear_regression_msr", 8) == 22


@pytest.mark.skipif(not OFFICIAL.is_dir(), reason="official Regression MSR checkout absent")
def test_tree_msr_returns_one_finite_value_per_owner() -> None:
    """Catches an official TreeMSR adapter that returns malformed attributions."""

    output = run_regression_msr(
        _additive_game(owner_count=4),
        budget=16,
        seed=3,
        official_repo=OFFICIAL,
        variant="tree",
    )

    assert set(output.scores) == {f"o{index}" for index in range(4)}
    assert all(abs(value) < 100 for value in output.scores.values())
    assert output.utility_calls <= 16


@pytest.mark.skipif(not OFFICIAL.is_dir(), reason="official Regression MSR checkout absent")
def test_practical_tree_msr_runs_one_surrogate_within_budget() -> None:
    """Catches omitting the paper-recommended all-samples TreeMSR variant."""

    output = run_regression_msr(
        _additive_game(owner_count=6),
        budget=62,
        seed=5,
        official_repo=OFFICIAL,
        variant="tree_all",
    )

    assert set(output.scores) == {f"o{index}" for index in range(6)}
    assert output.utility_calls <= 62
    assert output.diagnostics["folds"] == 1
