from __future__ import annotations

import math

import pytest

from datamechbench.methods.valuation_hierarchical_risk_sketch import (
    empirical_break_even,
    fit_hierarchical_risk_sketch,
    hierarchical_moment_error_bound,
    normalize_risk_sketch,
)


def test_normalized_sketch_uses_hand_derived_quadratic_coefficients() -> None:
    sketch = normalize_risk_sketch(4.0, 1.5, 3.0, relative_tolerance=1e-10)

    assert sketch.normalized_control_energy == pytest.approx(0.75)
    assert sketch.normalized_cross_moment == pytest.approx(0.375)
    assert not sketch.degenerate


def test_zero_prior_weight_exactly_recovers_local_slope() -> None:
    local = normalize_risk_sketch(2.0, 0.6, 0.8)
    prior = normalize_risk_sketch(10.0, 0.5, 5.0)

    fit = fit_hierarchical_risk_sketch(
        local,
        prior,
        local_dof=7.0,
        prior_weight=0.0,
        beta_bounds=(-2.0, 2.0),
    )

    assert fit.beta == pytest.approx(0.6 / 0.8)
    assert fit.blended_control_energy == pytest.approx(0.8 / 2.0)
    assert fit.blended_cross_moment == pytest.approx(0.6 / 2.0)
    assert fit.mode == "local"


def test_infinite_prior_weight_is_explicit_pure_transfer() -> None:
    local = normalize_risk_sketch(2.0, 0.6, 0.8)
    prior = normalize_risk_sketch(5.0, 1.0, 4.0)

    fit = fit_hierarchical_risk_sketch(
        local,
        prior,
        local_dof=3.0,
        prior_weight=math.inf,
        beta_bounds=(-2.0, 2.0),
    )

    assert fit.beta == pytest.approx(0.25)
    assert fit.mode == "transfer"


def test_finite_prior_weight_blends_curves_before_minimizing() -> None:
    local = normalize_risk_sketch(1.0, 0.8, 1.0)
    prior = normalize_risk_sketch(2.0, 0.2, 1.0)

    fit = fit_hierarchical_risk_sketch(
        local,
        prior,
        local_dof=3.0,
        prior_weight=1.0,
        beta_bounds=(-2.0, 2.0),
    )

    # local (a,b)=(1,.8), prior=(.5,.1): blend=(.875,.625)
    assert fit.blended_control_energy == pytest.approx(0.875)
    assert fit.blended_cross_moment == pytest.approx(0.625)
    assert fit.beta == pytest.approx(5.0 / 7.0)
    assert fit.mode == "hierarchical"


def test_fit_clips_and_near_zero_control_fails_closed() -> None:
    clipped = fit_hierarchical_risk_sketch(
        normalize_risk_sketch(1.0, 3.0, 1.0),
        normalize_risk_sketch(1.0, 0.0, 1.0),
        local_dof=2.0,
        prior_weight=0.0,
        beta_bounds=(0.0, 2.0),
    )
    degenerate = fit_hierarchical_risk_sketch(
        normalize_risk_sketch(10.0, 1e-12, 1e-14, relative_tolerance=1e-12),
        normalize_risk_sketch(1.0, 0.2, 1.0),
        local_dof=2.0,
        prior_weight=0.0,
        beta_bounds=(0.0, 2.0),
    )

    assert clipped.beta == 2.0
    assert clipped.clipped
    assert degenerate.beta == 0.0
    assert degenerate.degenerate


def test_hierarchical_error_bound_separates_sampling_and_prior_drift() -> None:
    bound = hierarchical_moment_error_bound(
        local_dof=3.0,
        prior_weight=1.0,
        local_control_error=0.2,
        local_cross_error=0.1,
        prior_control_drift=0.6,
        prior_cross_drift=0.5,
    )

    assert bound.control_error == pytest.approx(0.3)
    assert bound.cross_error == pytest.approx(0.2)


def test_empirical_break_even_uses_first_observed_direct_budget_that_matches() -> None:
    result = empirical_break_even(
        commissioning_cost=100.0,
        aar_deployment_cost=77.0,
        direct_budget_risks={64: 2.0, 96: 1.1, 128: 0.8},
        aar_risk=1.0,
    )

    assert result.matched_direct_budget == 128
    assert result.saved_cost_per_settlement == pytest.approx(51.0)
    assert result.break_even_settlements == 2
    assert not result.infinite


@pytest.mark.parametrize(
    "curve, aar_risk",
    [({64: 2.0, 96: 1.5}, 1.0), ({64: 0.9, 96: 0.8}, 1.0)],
)
def test_empirical_break_even_is_infinite_without_positive_observed_saving(
    curve: dict[int, float], aar_risk: float
) -> None:
    result = empirical_break_even(
        commissioning_cost=100.0,
        aar_deployment_cost=77.0,
        direct_budget_risks=curve,
        aar_risk=aar_risk,
    )

    assert result.break_even_settlements is None
    assert result.infinite
