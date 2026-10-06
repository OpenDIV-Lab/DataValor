from pathlib import Path

import numpy as np
import pytest
from datamechbench.coalition_games import CoalitionGameTable
from datamechbench.methods.valuation_slope_calibrated import SlopeCalibratedConfig
from datamechbench.methods.valuation_slope_calibrated_plus import (
    estimate_leverage_oracle,
    influence_calibrated_slope,
    leverage_scores_from_trace,
    run_influence_calibrated_leverage_shap,
    run_influence_calibrated_oracle,
    run_slope_calibrated_leverage_shap,
    run_slope_calibrated_svarm_plus,
    run_split_calibrated_leverage_shap,
)
from datamechbench.methods.valuation_sota import evaluate_sota

OFFICIAL = Path(__file__).parents[1] / "external/svarm_official"


def _games() -> tuple[CoalitionGameTable, CoalitionGameTable]:
    owners = tuple(f"o{i}" for i in range(8))
    low = {
        mask: float(sum((i + 1) for i in range(8) if mask & (1 << i)))
        for mask in range(256)
    }
    high = {
        mask: value * 1.7 + (0.3 if mask & 3 == 3 else 0.0)
        for mask, value in low.items()
    }
    return (
        CoalitionGameTable(owners, high, "high"),
        CoalitionGameTable(owners, low, "low"),
    )


@pytest.mark.skipif(not OFFICIAL.is_dir(), reason="official SVARM checkout absent")
def test_beta_zero_is_exactly_official_svarm_plus() -> None:
    high, low = _games()
    expected = evaluate_sota(
        "official_stratified_svarm_plus",
        high,
        budget=100,
        seed=5,
        official_repo=OFFICIAL,
    )
    actual = run_slope_calibrated_svarm_plus(
        high,
        low,
        budget=100,
        seed=5,
        config=SlopeCalibratedConfig(0.0),
        official_repo=OFFICIAL,
        beta_mode="zero",
    )

    assert actual.scores == pytest.approx(expected.scores, abs=1e-14)
    assert actual.diagnostics["sample_plans_coupled"] is True
    assert actual.utility_calls <= 100


@pytest.mark.skipif(not OFFICIAL.is_dir(), reason="official SVARM checkout absent")
def test_learned_plus_is_finite_and_records_one_slope() -> None:
    high, low = _games()
    output = run_slope_calibrated_svarm_plus(
        high,
        low,
        budget=100,
        seed=7,
        config=SlopeCalibratedConfig(0.0),
        official_repo=OFFICIAL,
    )

    assert set(output.scores) == set(high.owner_ids)
    assert len(output.diagnostics["slope_records"]) == 1


def test_leverage_beta_zero_is_exactly_direct_leverage_shap() -> None:
    high, low = _games()
    expected = evaluate_sota("shapiq_leverage_shap", high, budget=100, seed=5)
    actual = run_slope_calibrated_leverage_shap(
        high,
        low,
        budget=100,
        seed=5,
        config=SlopeCalibratedConfig(0.0),
        beta_mode="zero",
    )

    assert actual.scores == pytest.approx(expected.scores, abs=1e-14)
    assert actual.diagnostics["sample_plans_coupled"] is True
    assert actual.utility_calls <= 100


def test_learned_leverage_is_finite_and_records_one_slope() -> None:
    high, low = _games()
    output = run_slope_calibrated_leverage_shap(
        high,
        low,
        budget=100,
        seed=7,
        config=SlopeCalibratedConfig(0.0),
    )

    assert set(output.scores) == set(high.owner_ids)
    assert len(output.diagnostics["slope_records"]) == 1
    assert output.diagnostics["base_estimator"] == "shapiq_leverage_shap"


def test_confidence_slope_is_conservative_toward_unit_without_truth() -> None:
    high, low = _games()
    learned = run_slope_calibrated_leverage_shap(
        high,
        low,
        budget=100,
        seed=7,
        config=SlopeCalibratedConfig(0.0),
        beta_mode="learned",
    )
    confidence = run_slope_calibrated_leverage_shap(
        high,
        low,
        budget=100,
        seed=7,
        config=SlopeCalibratedConfig(0.0),
        beta_mode="confidence",
    )

    raw = learned.diagnostics["beta"]
    safe = confidence.diagnostics["beta"]
    assert min(1.0, raw) <= safe <= max(1.0, raw)
    assert confidence.diagnostics["raw_beta"] == pytest.approx(raw)
    assert confidence.diagnostics["beta_standard_error"] >= 0.0
    assert confidence.diagnostics["coefficient_fit"] == "same_sample_confidence_shrinkage"


def test_split_calibration_is_disjoint_deterministic_and_budget_matched() -> None:
    high, low = _games()

    first = run_split_calibrated_leverage_shap(
        high,
        low,
        budget=100,
        seed=11,
        config=SlopeCalibratedConfig(0.0),
        calibration_fraction=0.25,
    )
    second = run_split_calibrated_leverage_shap(
        high,
        low,
        budget=100,
        seed=11,
        config=SlopeCalibratedConfig(0.0),
        calibration_fraction=0.25,
    )

    calibration = set(first.diagnostics["calibration_masks"])
    estimation = set(first.diagnostics["estimation_masks"])
    assert calibration.isdisjoint(estimation)
    assert first.utility_calls == 100
    assert first.diagnostics["calibration_high_calls"] + first.diagnostics[
        "estimation_high_calls"
    ] == 100
    assert first.scores == second.scores
    assert first.diagnostics == second.diagnostics
    assert first.diagnostics["coefficient_fit"] == "heldout_disjoint_masks"


def test_split_calibration_zero_variance_falls_back_to_zero_slope() -> None:
    high, low = _games()
    constant_low = CoalitionGameTable(
        low.owner_ids,
        {mask: 3.0 for mask in low.values},
        "constant-low",
    )

    output = run_split_calibrated_leverage_shap(
        high,
        constant_low,
        budget=80,
        seed=3,
        config=SlopeCalibratedConfig(0.0),
        calibration_fraction=0.25,
    )

    assert output.diagnostics["beta"] == 0.0
    assert output.utility_calls == 80
    assert all(np.isfinite(value) for value in output.scores.values())


def test_trace_refit_reproduces_direct_leverage_scores() -> None:
    high, low = _games()
    direct = run_slope_calibrated_leverage_shap(
        high,
        low,
        budget=100,
        seed=19,
        config=SlopeCalibratedConfig(0.0),
        beta_mode="zero",
    )
    masks = direct.diagnostics["sampled_high_mask_sequence"]
    values = [high.values[mask] for mask in masks]

    refit = leverage_scores_from_trace(values, masks, owner_count=8)

    assert refit == pytest.approx([direct.scores[owner] for owner in high.owner_ids])


def test_influence_interval_projects_unit_anchor_and_uses_complement_blocks() -> None:
    high, low = _games()
    direct = run_slope_calibrated_leverage_shap(
        high,
        low,
        budget=100,
        seed=23,
        config=SlopeCalibratedConfig(0.0),
        beta_mode="zero",
    )
    masks = tuple(direct.diagnostics["sampled_high_mask_sequence"])
    high_values = tuple(float(high.values[mask]) for mask in masks)
    low_values = tuple(float(low.values[mask]) for mask in masks)

    result = influence_calibrated_slope(
        high_values,
        low_values,
        masks,
        owner_count=8,
        z_value=1.96,
    )

    assert result.block_count == (len(masks) - 2) // 2
    assert result.lower <= result.safe_beta <= result.upper
    assert result.safe_beta == pytest.approx(
        min(max(1.0, result.lower), result.upper)
    )
    assert len(result.provider_betas) == 8
    assert np.isfinite(result.raw_beta)
    assert np.isfinite(result.standard_error)


def test_influence_calibration_degenerate_low_game_returns_unit_safely() -> None:
    masks = (0, 255, 1, 254, 2, 253, 4, 251, 8, 247)
    high_values = tuple(float(mask.bit_count()) for mask in masks)
    low_values = (3.0,) * len(masks)

    result = influence_calibrated_slope(
        high_values,
        low_values,
        masks,
        owner_count=8,
    )

    assert result.degenerate is True
    assert result.raw_beta == 1.0
    assert result.safe_beta == 1.0
    assert result.provider_betas == pytest.approx((1.0,) * 8)


@pytest.mark.parametrize("beta_mode", ["influence_raw", "influence_safe", "provider"])
def test_influence_runner_is_budget_matched_and_does_not_use_high_truth(
    beta_mode: str,
) -> None:
    high, low = _games()

    output = run_influence_calibrated_leverage_shap(
        high,
        low,
        budget=100,
        seed=29,
        beta_mode=beta_mode,
    )

    assert output.utility_calls <= 100
    assert output.diagnostics["coefficient_source"] == "paired_delete_block_influence"
    assert output.diagnostics["uses_exact_high_target"] is False
    assert output.diagnostics["sample_plans_coupled"] is True
    assert all(np.isfinite(value) for value in output.scores.values())


def test_influence_runner_accepts_independent_approximate_low_anchor() -> None:
    high, low = _games()
    exact_anchor = evaluate_sota(
        "exact_table", low, budget=len(low.values), seed=0
    ).scores
    expected = run_influence_calibrated_leverage_shap(
        high, low, budget=100, seed=31
    )
    actual = run_influence_calibrated_leverage_shap(
        high,
        low,
        budget=100,
        seed=31,
        low_anchor=exact_anchor,
        low_anchor_calls=80,
        low_anchor_seed=991,
    )

    assert actual.scores == pytest.approx(expected.scores, abs=1e-14)
    assert actual.diagnostics["low_anchor_mode"] == "independent_approximate"
    assert actual.diagnostics["low_anchor_calls"] == 80
    assert actual.diagnostics["low_anchor_seed"] == 991
    assert actual.diagnostics["low_anchor_seed"] != 31


def test_influence_runner_rejects_nonindependent_or_incomplete_low_anchor() -> None:
    high, low = _games()
    anchor = {owner: 0.0 for owner in high.owner_ids}

    with pytest.raises(ValueError, match="independent"):
        run_influence_calibrated_leverage_shap(
            high,
            low,
            budget=100,
            seed=7,
            low_anchor=anchor,
            low_anchor_calls=64,
            low_anchor_seed=7,
        )
    anchor.pop(high.owner_ids[-1])
    with pytest.raises(ValueError, match="owner"):
        run_influence_calibrated_leverage_shap(
            high,
            low,
            budget=100,
            seed=7,
            low_anchor=anchor,
            low_anchor_calls=64,
            low_anchor_seed=8,
        )


def test_oracle_influence_runner_matches_complete_table_runner() -> None:
    high, low = _games()
    anchor = evaluate_sota("exact_table", low, budget=len(low.values), seed=0).scores
    expected = run_influence_calibrated_leverage_shap(
        high,
        low,
        budget=100,
        seed=37,
        low_anchor=anchor,
        low_anchor_calls=80,
        low_anchor_seed=991,
    )

    actual = run_influence_calibrated_oracle(
        high.owner_ids,
        high.values.__getitem__,
        low.values.__getitem__,
        budget=100,
        seed=37,
        low_anchor=anchor,
        low_anchor_calls=80,
        low_anchor_seed=991,
    )

    assert actual.scores == pytest.approx(expected.scores, abs=1e-14)
    assert actual.diagnostics["table_free"] is True
    assert actual.diagnostics["uses_exact_high_target"] is False


def test_oracle_influence_runner_does_not_enumerate_large_game() -> None:
    owners = tuple(f"o{i}" for i in range(10))
    high_calls: list[int] = []
    low_calls: list[int] = []

    def low_value(mask: int) -> float:
        low_calls.append(mask)
        return float(mask.bit_count() + 0.01 * (mask & 7))

    def high_value(mask: int) -> float:
        high_calls.append(mask)
        return float(1.4 * mask.bit_count() + 0.03 * (mask & 15))

    output = run_influence_calibrated_oracle(
        owners,
        high_value,
        low_value,
        budget=80,
        seed=41,
        low_anchor={owner: 1.0 for owner in owners},
        low_anchor_calls=64,
        low_anchor_seed=1041,
    )

    assert 0 < len(high_calls) <= 80
    assert 0 < len(low_calls) <= 80
    assert tuple(high_calls) == tuple(low_calls)
    assert len(set(high_calls)) < 2 ** len(owners)
    assert output.utility_calls == len(high_calls)
    assert output.diagnostics["sampled_high_mask_sequence"] == tuple(high_calls)


def test_leverage_oracle_exposes_scores_trace_and_exact_call_count() -> None:
    owners = tuple(f"o{i}" for i in range(10))
    calls: list[int] = []

    def value(mask: int) -> float:
        calls.append(mask)
        return float(mask.bit_count() + 0.02 * (mask & 31))

    output = estimate_leverage_oracle(owners, value, budget=80, seed=43)

    assert set(output.scores) == set(owners)
    assert output.utility_calls == len(calls)
    assert 0 < output.utility_calls <= 80
    assert output.diagnostics["sampled_mask_sequence"] == tuple(calls)
    assert output.diagnostics["table_free"] is True
