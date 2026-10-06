from __future__ import annotations

import datamechbench.methods.valuation_multifidelity as multifidelity
import pytest
from datamechbench.coalition_games import CoalitionGameTable
from datamechbench.elr_study import StudyGame
from datamechbench.methods.valuation_multifidelity import (
    BudgetDebitedConfig,
    InapplicableBudgetError,
    ProbeRisk,
    build_probe_games,
    calibrate_probe_risks,
    complementary_probe_plan,
    make_budget_ledger,
    resolve_probe_risks,
    run_exact_low_residual,
    select_budget_debited_method,
)
from datamechbench.methods.valuation_slope_calibrated import (
    SlopeCalibratedConfig,
    optimal_residual_slope,
    run_slope_calibrated_residual,
)


def test_optimal_residual_slope_recovers_known_linear_scale() -> None:
    assert optimal_residual_slope(
        (2.0, 4.0, 6.0),
        (1.0, 2.0, 3.0),
        ridge=0.0,
    ) == pytest.approx(2.0)


def test_optimal_residual_slope_ridge_shrinks_toward_direct_estimation() -> None:
    assert optimal_residual_slope(
        (2.0, 4.0, 6.0),
        (1.0, 2.0, 3.0),
        ridge=2.0 / 3.0,
    ) == pytest.approx(1.0)


def test_optimal_residual_slope_constant_low_marginals_fall_back_to_zero() -> None:
    assert optimal_residual_slope(
        (1.0, 2.0, 4.0),
        (3.0, 3.0, 3.0),
        ridge=0.0,
    ) == 0.0


@pytest.mark.parametrize(
    ("high", "low", "ridge", "match"),
    (
        ((1.0,), (1.0, 2.0), 0.0, "same length"),
        ((1.0, float("nan")), (1.0, 2.0), 0.0, "finite"),
        ((1.0, 2.0), (1.0, 2.0), -0.1, "ridge"),
    ),
)
def test_optimal_residual_slope_rejects_invalid_samples(
    high: tuple[float, ...],
    low: tuple[float, ...],
    ridge: float,
    match: str,
) -> None:
    with pytest.raises(ValueError, match=match):
        optimal_residual_slope(high, low, ridge=ridge)


def test_slope_calibrated_config_requires_two_folds_and_finite_ridge() -> None:
    with pytest.raises(ValueError, match="folds"):
        SlopeCalibratedConfig(ridge_relative=0.1, folds=1)
    with pytest.raises(ValueError, match="ridge_relative"):
        SlopeCalibratedConfig(ridge_relative=float("inf"))


def _linear_slope_tables(owner_count: int = 6) -> tuple[CoalitionGameTable, CoalitionGameTable]:
    owners = tuple(f"o{index}" for index in range(owner_count))
    weights = tuple(float(index + 1) / 10.0 for index in range(owner_count))
    low_values = {
        mask: float(mask.bit_count() ** 2)
        for mask in range(1 << owner_count)
    }
    high_values = {
        mask: 2.0 * low_values[mask]
        + sum(weight for index, weight in enumerate(weights) if mask & (1 << index))
        for mask in range(1 << owner_count)
    }
    return (
        CoalitionGameTable(owners, high_values, "high"),
        CoalitionGameTable(owners, low_values, "low"),
    )


def _interaction_slope_tables() -> tuple[CoalitionGameTable, CoalitionGameTable]:
    owner_count = 6
    owners = tuple(f"o{index}" for index in range(owner_count))
    weights = tuple(float(index + 1) / 10.0 for index in range(owner_count))
    low_values = {}
    for mask in range(1 << owner_count):
        present = [index for index in range(owner_count) if mask & (1 << index)]
        pair_utility = sum(
            0.07 * (left + 1) * (right + 1)
            for offset, left in enumerate(present)
            for right in present[offset + 1 :]
        )
        low_values[mask] = float(len(present) ** 2 + pair_utility)
    high_values = {
        mask: 2.0 * low_values[mask]
        + sum(
            weights[index]
            for index in range(owner_count)
            if mask & (1 << index)
        )
        for mask in low_values
    }
    return (
        CoalitionGameTable(owners, high_values, "high"),
        CoalitionGameTable(owners, low_values, "low"),
    )


def test_slope_modes_share_masks_and_high_call_budget() -> None:
    high, low = _linear_slope_tables()
    outputs = {
        mode: run_slope_calibrated_residual(
            high,
            low,
            budget=48,
            seed=19,
            config=SlopeCalibratedConfig(ridge_relative=0.0),
            accounting="cached",
            low_cost_ratio=0.5,
            beta_mode=mode,
        )
        for mode in ("zero", "one", "learned")
    }

    assert len({tuple(value.diagnostics["sampled_high_masks"]) for value in outputs.values()}) == 1
    assert {value.utility_calls for value in outputs.values()} == {
        outputs["zero"].utility_calls
    }
    assert outputs["zero"].diagnostics["beta_mode"] == "zero"
    assert outputs["one"].diagnostics["beta_mode"] == "one"


def test_beta_zero_is_exactly_the_same_seeded_svarm_estimator() -> None:
    import numpy as np
    import shapiq

    high, low = _interaction_slope_tables()

    output = run_slope_calibrated_residual(
        high,
        low,
        budget=48,
        seed=31,
        config=SlopeCalibratedConfig(ridge_relative=0.1),
        accounting="cached",
        low_cost_ratio=0.5,
        beta_mode="zero",
    )
    def game(coalitions: np.ndarray) -> np.ndarray:
        return np.asarray(
            [
                high.values[
                    sum(
                        1 << index
                        for index, included in enumerate(row)
                        if included
                    )
                ]
                for row in np.atleast_2d(coalitions).astype(bool)
            ]
        )

    result = shapiq.SVARM(
        n=len(high.owner_ids), random_state=31, pairing_trick=True
    ).approximate(budget=48, game=game)
    direct = dict(
        zip(high.owner_ids, result.get_n_order_values(1), strict=True)
    )

    assert output.scores == pytest.approx(direct)
    assert output.diagnostics["backend"] == "slope_calibrated_coupled_svarm"
    assert output.diagnostics["pairing_trick"] is True


def test_coupled_svarm_plugin_is_deterministic_and_auditable() -> None:
    high, low = _linear_slope_tables()
    kwargs = {
        "budget": 48,
        "seed": 23,
        "config": SlopeCalibratedConfig(ridge_relative=0.1),
        "accounting": "cached",
        "low_cost_ratio": 0.5,
    }

    first = run_slope_calibrated_residual(high, low, **kwargs)
    second = run_slope_calibrated_residual(high, low, **kwargs)

    assert first == second
    assert first.diagnostics["fold_count"] == 2
    assert first.diagnostics["base_estimator"] == "shapiq_svarm"
    assert first.diagnostics["coefficient_fit"] == "same_sample_plugin"
    assert first.diagnostics["slope_records"][0]["centering"] == (
        "coalition_size_and_owner_fixed_effects"
    )


def test_stratified_slope_removes_between_stratum_mean_confounding() -> None:
    high, low = _interaction_slope_tables()

    output = run_slope_calibrated_residual(
        high,
        low,
        budget=48,
        seed=0,
        config=SlopeCalibratedConfig(ridge_relative=0.0),
        accounting="cached",
        low_cost_ratio=0.5,
    )

    assert output.diagnostics["beta"] == pytest.approx(2.0)
    expected = {
        f"o{index}": 2.0
        * (
            6.0
            + 0.5
            * sum(
                0.07 * (index + 1) * (other + 1)
                for other in range(6)
                if other != index
            )
        )
        + (index + 1) / 10.0
        for index in range(6)
    }
    direct = run_slope_calibrated_residual(
        high,
        low,
        budget=48,
        seed=0,
        config=SlopeCalibratedConfig(ridge_relative=0.0),
        accounting="cached",
        low_cost_ratio=0.5,
        beta_mode="zero",
    )
    learned_mae = sum(abs(output.scores[key] - value) for key, value in expected.items())
    direct_mae = sum(abs(direct.scores[key] - value) for key, value in expected.items())
    assert learned_mae < direct_mae * 0.1


@pytest.mark.parametrize("mode", ("zero", "one", "learned"))
def test_full_high_table_budget_recovers_exact_shapley_for_every_slope_mode(
    mode: str,
) -> None:
    high, low = _linear_slope_tables(owner_count=4)
    output = run_slope_calibrated_residual(
        high,
        low,
        budget=16,
        seed=3,
        config=SlopeCalibratedConfig(ridge_relative=0.1),
        accounting="cached",
        low_cost_ratio=0.5,
        beta_mode=mode,
    )

    assert output.scores == pytest.approx(
        {"o0": 8.1, "o1": 8.2, "o2": 8.3, "o3": 8.4}
    )
    assert output.utility_calls == 16


def test_strict_slope_accounting_rejects_budget_consumed_by_low_table() -> None:
    high, low = _linear_slope_tables(owner_count=4)

    with pytest.raises(InapplicableBudgetError) as caught:
        run_slope_calibrated_residual(
            high,
            low,
            budget=8,
            seed=0,
            config=SlopeCalibratedConfig(ridge_relative=0.1),
            accounting="strict",
            low_cost_ratio=0.5,
        )

    assert caught.value.reason == "low_table_consumes_budget"


def test_complementary_six_owner_probes_have_112_unique_high_masks() -> None:
    owners = tuple(f"o{index}" for index in range(8))

    plan = complementary_probe_plan(owners, k=6)

    assert plan.owner_subsets == ((0, 1, 2, 3, 4, 5), (2, 3, 4, 5, 6, 7))
    assert plan.local_to_global_masks[0][0b100001] == 0b100001
    assert plan.local_to_global_masks[1][0b100001] == 0b10000100
    assert len(plan.unique_high_masks) == 112


def test_budget_ledger_charges_overlapping_probe_masks_and_medium_once() -> None:
    ledger = make_budget_ledger(
        declared_budget=20,
        low_cost_ratio=0.25,
        probe_high_masks=(0, 1, 2, 2),
        probe_medium_masks=(0, 1, 2, 2),
        additional_medium_masks=(2, 3, 3, 4),
        additional_high_calls=7,
    )

    assert ledger.probe_high_masks == frozenset({0, 1, 2})
    assert ledger.probe_medium_masks == frozenset({0, 1, 2})
    assert ledger.additional_medium_masks == frozenset({3, 4})
    assert ledger.additional_high_calls == 7
    assert ledger.equivalent_high_cost == pytest.approx(10.5)


@pytest.mark.parametrize("k", (1, 9))
def test_probe_plan_rejects_invalid_probe_size(k: int) -> None:
    with pytest.raises(ValueError, match="probe size"):
        complementary_probe_plan(tuple(f"o{i}" for i in range(8)), k=k)


def test_probe_plan_rejects_duplicate_owner_ids() -> None:
    with pytest.raises(ValueError, match="unique"):
        complementary_probe_plan(("o0", "o0", "o2"), k=2)


def test_probe_games_preserve_induced_coalition_values() -> None:
    owners = ("o0", "o1", "o2", "o3")
    high = CoalitionGameTable(
        owners, {mask: float(mask) for mask in range(16)}, "high"
    )
    medium = CoalitionGameTable(
        owners, {mask: -float(mask) for mask in range(16)}, "medium"
    )
    game = StudyGame("s", "tabular", "rf", "trees", high, medium)

    first, second = build_probe_games(
        game, complementary_probe_plan(owners, k=2)
    )

    assert first.high.owner_ids == ("o0", "o1")
    assert dict(first.high.values) == {0: 0.0, 1: 1.0, 2: 2.0, 3: 3.0}
    assert second.high.owner_ids == ("o2", "o3")
    assert dict(second.high.values) == {0: 0.0, 1: 4.0, 2: 8.0, 3: 12.0}
    assert dict(second.low.values) == {0: -0.0, 1: -4.0, 2: -8.0, 3: -12.0}


def test_probe_risk_resolution_requires_unanimity() -> None:
    agreeing = (
        ProbeRisk(0, {"elr": 0.1, "svarm": 0.2}, "elr"),
        ProbeRisk(1, {"elr": 0.2, "svarm": 0.3}, "elr"),
    )
    disagreeing = (
        agreeing[0],
        ProbeRisk(1, {"elr": 0.3, "svarm": 0.2}, "svarm"),
    )

    assert resolve_probe_risks(agreeing, fallback_method="svarm").selected_method == "elr"
    fallback = resolve_probe_risks(disagreeing, fallback_method="svarm")
    assert fallback.selected_method == "svarm"
    assert fallback.fallback_used is True


def test_budget_ledger_rejects_overspend() -> None:
    with pytest.raises(ValueError, match="exceeds"):
        make_budget_ledger(
            declared_budget=2,
            low_cost_ratio=0.5,
            probe_high_masks=(0, 1, 2),
        )


def test_exact_low_plus_exact_residual_equals_exact_high_shapley() -> None:
    owners = ("o0", "o1", "o2", "o3")
    medium = CoalitionGameTable(
        owners,
        {mask: 0.7 * mask.bit_count() for mask in range(16)},
        "medium",
    )
    high = CoalitionGameTable(
        owners,
        {
            mask: 0.7 * mask.bit_count()
            + 0.2 * bool(mask & 1)
            + 0.4 * bool(mask & 2)
            + 0.1 * bool(mask & 4)
            + 0.3 * bool(mask & 8)
            + 0.8 * float(mask == 15)
            for mask in range(16)
        },
        "high",
    )
    ledger = make_budget_ledger(
        declared_budget=20,
        low_cost_ratio=0.25,
        additional_medium_masks=range(16),
        additional_high_calls=16,
    )

    output = run_exact_low_residual(
        high,
        medium,
        residual_method="exact_table",
        residual_budget=16,
        seed=7,
        ledger=ledger,
    )

    assert output.scores == pytest.approx(
        {"o0": 1.1, "o1": 1.3, "o2": 1.0, "o3": 1.2}
    )
    assert output.diagnostics["equivalent_high_calls"] == pytest.approx(20.0)
    assert output.diagnostics["base_estimator"] == "exact_table"


def test_exact_low_residual_returns_typed_inapplicability_below_minimum() -> None:
    owners = ("o0", "o1")
    high = CoalitionGameTable(
        owners, {mask: float(mask.bit_count()) for mask in range(4)}, "high"
    )
    medium = CoalitionGameTable(
        owners, {mask: 0.5 * mask.bit_count() for mask in range(4)}, "medium"
    )
    ledger = make_budget_ledger(
        declared_budget=1,
        low_cost_ratio=0.25,
        additional_medium_masks=range(4),
    )

    with pytest.raises(InapplicableBudgetError) as caught:
        run_exact_low_residual(
            high,
            medium,
            residual_method="shapiq_leverage_shap",
            residual_budget=1,
            seed=0,
            ledger=ledger,
        )

    assert caught.value.status == "inapplicable_budget"
    assert caught.value.required_calls == 2
    assert caught.value.available_calls == 1


def _eight_owner_game() -> StudyGame:
    owners = tuple(f"o{index}" for index in range(8))
    high_values = {
        mask: float(mask.bit_count() ** 2 + 0.03 * ((mask * 17) % 13))
        for mask in range(256)
    }
    medium_values = {mask: 0.9 * value for mask, value in high_values.items()}
    return StudyGame(
        "strict-budget-fixture",
        "tabular",
        "boosting",
        "stage_prefix",
        CoalitionGameTable(owners, high_values, "high"),
        CoalitionGameTable(owners, medium_values, "medium"),
    )


def _probe_risks(winner_a: str, winner_b: str) -> tuple[ProbeRisk, ...]:
    candidates = {
        "elr_residual_leverage": 0.1,
        "shapiq_svarm": 0.2,
        "shapiq_leverage_shap": 0.3,
    }
    return (
        ProbeRisk(0, candidates, winner_a),
        ProbeRisk(1, candidates, winner_b),
    )


def test_probe_risk_calibration_is_deterministic_on_real_estimators() -> None:
    owners = ("o0", "o1", "o2", "o3")
    high_values = {
        mask: float(mask.bit_count() ** 2 + 0.07 * ((mask * 5) % 3))
        for mask in range(16)
    }
    game = StudyGame(
        "calibration-fixture",
        "tabular",
        "rf",
        "trees",
        CoalitionGameTable(owners, high_values, "high"),
        CoalitionGameTable(
            owners,
            {mask: 0.9 * value for mask, value in high_values.items()},
            "medium",
        ),
    )
    config = BudgetDebitedConfig(3, (0,), 8)

    first = calibrate_probe_risks(game, config=config, low_cost_ratio=0.1)
    second = calibrate_probe_risks(game, config=config, low_cost_ratio=0.1)

    assert first is second
    assert len(first) == 2
    assert all(set(risk.median_mae) == set(config.candidates) for risk in first)
    assert all(risk.winner in config.candidates for risk in first)


def test_budget_debited_direct_route_receives_only_post_probe_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        multifidelity,
        "calibrate_probe_risks",
        lambda *args, **kwargs: _probe_risks("shapiq_svarm", "shapiq_svarm"),
    )

    output = select_budget_debited_method(
        _eight_owner_game(),
        budget=224,
        config=BudgetDebitedConfig(6, (0,), 56),
        low_cost_ratio=0.1,
        seed=9,
    )

    assert output.diagnostics["selected_method"] == "shapiq_svarm"
    assert output.diagnostics["probe_high_calls"] == 112
    assert output.diagnostics["production_high_budget"] == 112
    assert output.diagnostics["production_warm_start_reused"] is False
    assert output.diagnostics["realized_equivalent_cost"] <= 224
    assert output.utility_calls == (
        output.diagnostics["probe_high_calls"]
        + output.diagnostics["production_high_calls"]
    )


def test_budget_debited_elr_route_debits_unobserved_medium_table(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        multifidelity,
        "calibrate_probe_risks",
        lambda *args, **kwargs: _probe_risks(
            "elr_residual_leverage", "elr_residual_leverage"
        ),
    )

    output = select_budget_debited_method(
        _eight_owner_game(),
        budget=224,
        config=BudgetDebitedConfig(6, (0,), 56),
        low_cost_ratio=0.1,
        seed=11,
    )

    assert output.diagnostics["selected_method"] == "elr_residual_leverage"
    assert output.diagnostics["probe_medium_values"] == 112
    assert output.diagnostics["additional_medium_calls"] == 144
    assert output.diagnostics["production_high_budget"] == 97
    assert output.diagnostics["realized_equivalent_cost"] <= 224
    assert output.utility_calls == (
        112 + 144 + output.diagnostics["production_high_calls"]
    )


def test_budget_debited_disagreement_routes_to_svarm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        multifidelity,
        "calibrate_probe_risks",
        lambda *args, **kwargs: _probe_risks(
            "elr_residual_leverage", "shapiq_leverage_shap"
        ),
    )

    output = select_budget_debited_method(
        _eight_owner_game(),
        budget=224,
        config=BudgetDebitedConfig(6, (0,), 56),
        low_cost_ratio=0.1,
        seed=13,
    )

    assert output.diagnostics["selected_method"] == "shapiq_svarm"
    assert output.diagnostics["fallback_used"] is True


@pytest.mark.parametrize(
    ("ratio", "expected"),
    ((0.0, 5.0), (0.1, 5.2), (0.25, 5.5), (0.4, 5.8)),
)
def test_budget_ledger_cost_ratio_sensitivity_is_explicit(
    ratio: float, expected: float
) -> None:
    ledger = make_budget_ledger(
        declared_budget=10,
        low_cost_ratio=ratio,
        probe_high_masks=(0, 1),
        probe_medium_masks=(0, 1),
        additional_medium_masks=(0, 1, 2, 3),
        additional_high_calls=3,
    )

    assert ledger.equivalent_high_cost == pytest.approx(expected)


def test_budget_debited_full_owner_probes_charge_union_once() -> None:
    plan = complementary_probe_plan(tuple(f"o{i}" for i in range(8)), k=8)

    assert len(plan.unique_high_masks) == 256
    assert plan.local_to_global_masks[0] == plan.local_to_global_masks[1]


def test_budget_debited_rejects_probe_cost_above_total_budget() -> None:
    with pytest.raises(InapplicableBudgetError) as caught:
        select_budget_debited_method(
            _eight_owner_game(),
            budget=111,
            config=BudgetDebitedConfig(6, (0,), 56),
            low_cost_ratio=0.1,
            seed=0,
        )

    assert caught.value.reason == "probe_cost_exceeds_budget"
    assert caught.value.diagnostics["probe_high_calls"] == 112
    assert caught.value.diagnostics["declared_budget"] == 111


def test_budget_debited_rejects_one_call_left_after_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        multifidelity,
        "calibrate_probe_risks",
        lambda *args, **kwargs: _probe_risks("shapiq_svarm", "shapiq_svarm"),
    )

    with pytest.raises(InapplicableBudgetError) as caught:
        select_budget_debited_method(
            _eight_owner_game(),
            budget=113,
            config=BudgetDebitedConfig(6, (0,), 56),
            low_cost_ratio=0.1,
            seed=0,
        )

    assert caught.value.reason == "direct_initialization_after_probe"
    assert caught.value.available_calls == 1
