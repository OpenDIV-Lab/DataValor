import numpy as np
import pytest

from datamechbench.methods.valuation_multifidelity_cv import (
    estimate_cv_coefficients,
    run_anchor_aware_cv_oracle,
    run_multifidelity_cv_oracle,
)
from datamechbench.methods.valuation_slope_calibrated_plus import (
    estimate_leverage_oracle,
)


def _oracles(n: int = 6):
    owners = tuple(f"o{i}" for i in range(n))

    def low(mask: int) -> float:
        linear = sum((i + 1) * 0.03 for i in range(n) if mask & (1 << i))
        return linear + 0.04 * ((mask & 3) == 3)

    def high(mask: int) -> float:
        return 0.65 * low(mask) + 0.02 * ((mask & 12) == 12)

    return owners, high, low


def test_unit_mode_matches_manual_residual_on_the_same_trace() -> None:
    owners, high, low = _oracles()
    anchor = estimate_leverage_oracle(owners, low, budget=64, seed=991)
    direct = estimate_leverage_oracle(owners, high, budget=64, seed=17)
    paired_low = estimate_leverage_oracle(owners, low, budget=64, seed=17)

    result = run_multifidelity_cv_oracle(
        owners,
        high,
        low,
        budget=64,
        seed=17,
        low_anchor=anchor.scores,
        low_anchor_calls=anchor.utility_calls,
        low_anchor_seed=991,
        mode="unit",
    )

    expected = {
        owner: direct.scores[owner] - (paired_low.scores[owner] - anchor.scores[owner])
        for owner in owners
    }
    assert result.scores == pytest.approx(expected, abs=1e-12)
    assert result.diagnostics["coefficient_mode"] == "unit"
    assert result.diagnostics["paired_trace_seed"] == 17


def test_pilot_mode_requires_and_records_a_disjoint_seed() -> None:
    owners, high, low = _oracles()
    anchor = estimate_leverage_oracle(owners, low, budget=64, seed=991)

    with pytest.raises(ValueError, match="pilot_seed"):
        run_multifidelity_cv_oracle(
            owners,
            high,
            low,
            budget=64,
            seed=17,
            low_anchor=anchor.scores,
            low_anchor_calls=anchor.utility_calls,
            low_anchor_seed=991,
            mode="pilot",
            pilot_budget=32,
            pilot_seed=17,
        )

    result = run_multifidelity_cv_oracle(
        owners,
        high,
        low,
        budget=64,
        seed=17,
        low_anchor=anchor.scores,
        low_anchor_calls=anchor.utility_calls,
        low_anchor_seed=991,
        mode="pilot",
        pilot_budget=32,
        pilot_seed=313,
    )
    assert result.diagnostics["coefficient_source"] == "independent_pilot_influence"
    assert result.diagnostics["pilot_seed"] == 313
    assert result.diagnostics["pilot_high_calls"] <= 32
    assert result.utility_calls <= 96


def test_crossfit_records_excluded_folds_and_finite_global_coefficient() -> None:
    rng = np.random.default_rng(4)
    low = rng.normal(size=(20, 5))
    high = 0.7 * low + rng.normal(scale=0.03, size=(20, 5))

    estimate = estimate_cv_coefficients(high, low, mode="crossfit", folds=5)

    assert np.isfinite(estimate.global_beta)
    assert len(estimate.fold_records) == 5
    all_scored = set()
    for record in estimate.fold_records:
        assert set(record.train_indices).isdisjoint(record.score_indices)
        all_scored.update(record.score_indices)
    assert all_scored == set(range(20))


def test_provider_ridge_degenerate_low_influence_falls_back_to_unit() -> None:
    high = np.arange(24, dtype=float).reshape(6, 4)
    low = np.zeros((6, 4), dtype=float)

    estimate = estimate_cv_coefficients(
        high, low, mode="provider_ridge", ridge_relative=0.2
    )

    assert estimate.provider_betas == pytest.approx((1.0, 1.0, 1.0, 1.0))
    assert estimate.degenerate is True


def test_runner_queries_only_declared_traces_and_never_exact_high_truth() -> None:
    owners, raw_high, raw_low = _oracles(n=10)
    high_masks: list[int] = []
    low_masks: list[int] = []

    def high(mask: int) -> float:
        high_masks.append(mask)
        return raw_high(mask)

    def low(mask: int) -> float:
        low_masks.append(mask)
        return raw_low(mask)

    anchor = estimate_leverage_oracle(owners, raw_low, budget=80, seed=991)
    result = run_multifidelity_cv_oracle(
        owners,
        high,
        low,
        budget=80,
        seed=17,
        low_anchor=anchor.scores,
        low_anchor_calls=anchor.utility_calls,
        low_anchor_seed=991,
        mode="acv_shrinkage",
        ridge_relative=0.25,
    )

    assert len(high_masks) == result.diagnostics["paired_high_calls"]
    assert high_masks == low_masks
    assert len(set(high_masks)) < 1 << len(owners)
    assert result.diagnostics["uses_exact_high_target"] is False


def test_utility_projection_uses_the_same_trace_without_extra_calls() -> None:
    owners, high, low = _oracles()
    anchor = estimate_leverage_oracle(owners, low, budget=64, seed=991)
    result = run_multifidelity_cv_oracle(
        owners,
        high,
        low,
        budget=64,
        seed=17,
        low_anchor=anchor.scores,
        low_anchor_calls=anchor.utility_calls,
        low_anchor_seed=991,
        mode="utility_projection",
    )
    assert result.diagnostics["coefficient_source"] == "coalition_utility_projection"
    assert np.isfinite(result.diagnostics["beta"])
    assert result.utility_calls <= 64


def test_anchor_aware_coefficient_charges_and_shrinks_for_anchor_noise() -> None:
    owners, high, low = _oracles(n=10)
    result = run_anchor_aware_cv_oracle(
        owners,
        high,
        low,
        budget=80,
        seed=17,
        anchor_budget=40,
        anchor_seed=991,
    )
    diagnostics = result.diagnostics
    assert diagnostics["coefficient_source"] == "paired_plus_anchor_influence"
    assert diagnostics["anchor_variance_energy"] > 0.0
    assert abs(diagnostics["beta"]) <= abs(diagnostics["paired_only_beta"]) + 1e-12
    assert diagnostics["low_anchor_calls"] <= 40
    assert diagnostics["uses_exact_high_target"] is False
