import numpy as np
import pytest
from datamechbench.methods.valuation_multifidelity_cv import (
    anchor_orthogonality_audit,
    confidence_minimax_normalized_excess_beta,
    contrast_range_bounds_from_output_spans,
    deletion_robust_minimax_normalized_excess_beta,
    estimate_cv_coefficients,
    finite_sample_contrast_grid_beta,
    finite_sample_empirical_bernstein_fixed_beta,
    finite_sample_empirical_bernstein_grid_beta,
    minimax_normalized_excess_beta,
    nested_cost_optimal_anchor_ratio,
    pool_anchor_aware_moments,
    pool_history_anchor_aware_moments,
    pool_history_anchor_energy_moments,
    pool_history_paired_only_moments,
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


def test_risk_envelope_recovers_single_game_vertex() -> None:
    result = minimax_normalized_excess_beta(
        direct_risks=[4.0],
        cross_moments=[2.0],
        control_energies=[4.0],
        beta_limit=2.0,
    )

    assert result.beta == pytest.approx(0.5)
    assert result.worst_normalized_excess == pytest.approx(-0.25)
    assert result.active_indices == (0,)


def test_risk_envelope_solves_conflicting_games_and_certifies_all() -> None:
    result = minimax_normalized_excess_beta(
        direct_risks=[1.0, 1.0],
        cross_moments=[0.8, 0.4],
        control_energies=[4.0, 1.0],
        beta_limit=2.0,
    )

    assert result.beta == pytest.approx(4.0 / 15.0)
    assert max(result.per_game_normalized_excess) <= 1e-12
    assert result.worst_normalized_excess == pytest.approx(-32.0 / 225.0)
    assert result.active_indices == (0, 1)


def test_risk_envelope_zero_energy_uses_safe_zero() -> None:
    result = minimax_normalized_excess_beta(
        direct_risks=[1.0, 2.0],
        cross_moments=[0.0, 0.0],
        control_energies=[0.0, 0.0],
        beta_limit=2.0,
    )

    assert result.beta == 0.0
    assert result.worst_normalized_excess == 0.0
    assert result.active_indices == (0, 1)


def test_deletion_robust_envelope_matches_explicit_leave_one_out_scenarios() -> None:
    high = [
        np.array(
            [
                [0.0, 1.0],
                [1.0, 0.0],
                [2.5, 1.5],
                [4.0, 1.0],
            ]
        )
    ]
    control = [
        np.array(
            [
                [0.0, 0.5],
                [0.5, 0.0],
                [1.0, 0.8],
                [1.8, 0.4],
            ]
        )
    ]

    robust = deletion_robust_minimax_normalized_excess_beta(high, control)
    manual_h, manual_c, manual_d = [], [], []
    for deleted in range(4):
        keep = np.arange(4) != deleted
        centered_h = high[0][keep] - high[0][keep].mean(axis=0, keepdims=True)
        centered_c = control[0][keep] - control[0][keep].mean(axis=0, keepdims=True)
        scale = 1.0 / ((keep.sum() - 1) * high[0].shape[1])
        manual_h.append(scale * np.sum(centered_h**2))
        manual_c.append(scale * np.sum(centered_h * centered_c))
        manual_d.append(scale * np.sum(centered_c**2))
    explicit = minimax_normalized_excess_beta(manual_h, manual_c, manual_d)

    assert robust.beta == pytest.approx(explicit.beta)
    assert robust.worst_deleted_normalized_excess == pytest.approx(
        explicit.worst_normalized_excess
    )
    assert robust.deleted_scenarios == tuple((0, index) for index in range(4))
    assert robust.active_scenarios == tuple(
        robust.deleted_scenarios[index] for index in explicit.active_indices
    )


def test_deletion_certificate_implies_full_history_noninferiority() -> None:
    high = [
        np.array([[0.0], [0.8], [1.9], [3.1], [4.2]]),
        np.array([[0.0], [1.1], [2.0], [2.7], [4.0]]),
    ]
    control = [
        np.array([[0.0], [0.3], [0.9], [1.4], [1.8]]),
        np.array([[0.0], [0.5], [1.0], [1.1], [1.9]]),
    ]

    robust = deletion_robust_minimax_normalized_excess_beta(high, control)

    assert robust.worst_deleted_normalized_excess <= 0.0
    assert max(robust.full_sample_normalized_excess) <= 0.0


def test_deletion_robust_envelope_rejects_too_short_or_unaligned_histories() -> None:
    with pytest.raises(ValueError, match="at least three"):
        deletion_robust_minimax_normalized_excess_beta(
            [np.ones((2, 1))], [np.ones((2, 1))]
        )


def test_confidence_envelope_certifies_a_stable_population_gain() -> None:
    rng = np.random.default_rng(91)
    high = rng.normal(size=(200, 3))
    control = 0.65 * high + rng.normal(scale=0.20, size=high.shape)

    result = confidence_minimax_normalized_excess_beta(
        [high], [control], confidence=0.95
    )

    assert result.beta > 0.0
    assert result.worst_upper_normalized_excess < 0.0
    assert result.simultaneous_confidence == pytest.approx(0.95)
    assert result.pair_counts == (100,)
    assert not result.abstained


def test_confidence_envelope_preserves_or_clips_a_preferred_empirical_beta() -> None:
    rng = np.random.default_rng(19)
    high = rng.normal(size=(200, 2))
    control = 0.75 * high + rng.normal(scale=0.15, size=high.shape)

    preserved = confidence_minimax_normalized_excess_beta(
        [high], [control], confidence=0.95, preferred_beta=0.5
    )
    clipped = confidence_minimax_normalized_excess_beta(
        [high], [control], confidence=0.95, preferred_beta=-2.0
    )

    assert preserved.beta == pytest.approx(0.5)
    assert preserved.worst_upper_normalized_excess <= 0.0
    assert not preserved.preferred_beta_clipped
    assert -2.0 < clipped.beta <= 0.0
    assert clipped.worst_upper_normalized_excess <= 1e-9
    assert clipped.preferred_beta_clipped


def test_joint_bootstrap_confidence_gate_is_reproducible_and_self_normalized() -> None:
    rng = np.random.default_rng(2027)
    high = rng.standard_t(df=5, size=(120, 3))
    control = 0.55 * high + rng.standard_t(df=5, size=high.shape) * 0.25

    first = confidence_minimax_normalized_excess_beta(
        [high],
        [control],
        confidence=0.95,
        preferred_beta=0.4,
        calibration="joint_pair_bootstrap",
        certificate_geometry="excess_contrast",
        bootstrap_iterations=499,
        random_seed=73,
    )
    second = confidence_minimax_normalized_excess_beta(
        [high],
        [control],
        confidence=0.95,
        preferred_beta=0.4,
        calibration="joint_pair_bootstrap",
        certificate_geometry="excess_contrast",
        bootstrap_iterations=499,
        random_seed=73,
    )

    assert first == second
    assert first.calibration == "joint_pair_bootstrap"
    assert first.certificate_geometry == "excess_contrast"
    assert first.critical_value > 0.0
    assert first.worst_upper_normalized_excess <= 1e-9


def test_joint_bootstrap_confidence_gate_rejects_too_few_draws() -> None:
    rng = np.random.default_rng(17)
    high = rng.normal(size=(40, 2))
    control = 0.4 * high + rng.normal(scale=0.2, size=high.shape)

    with pytest.raises(ValueError, match="bootstrap_iterations"):
        confidence_minimax_normalized_excess_beta(
            [high],
            [control],
            calibration="joint_pair_bootstrap",
            bootstrap_iterations=19,
        )


def test_finite_sample_contrast_grid_selects_only_jointly_certified_beta() -> None:
    rng = np.random.default_rng(8027)
    high = rng.normal(size=(240, 3))
    control = 0.55 * high + rng.normal(scale=0.18, size=high.shape)
    candidates = np.asarray([0.0, 0.25, 0.5, 0.75])
    delta_h = high[0::2] - high[1::2]
    delta_c = control[0::2] - control[1::2]
    cross = 0.5 * np.mean(delta_h * delta_c, axis=1)
    energy = 0.5 * np.mean(delta_c**2, axis=1)
    contrast = np.asarray(
        [energy * beta**2 - 2.0 * cross * beta for beta in candidates]
    ).T
    variance_bounds = [np.var(contrast, axis=0)]
    range_bounds = [np.ptp(contrast, axis=0)]

    result = finite_sample_contrast_grid_beta(
        [high],
        [control],
        candidate_betas=candidates,
        contrast_variance_bounds=variance_bounds,
        contrast_range_bounds=range_bounds,
        confidence=0.95,
        preferred_beta=0.5,
    )

    assert result.beta in candidates
    assert result.beta > 0.0
    assert result.worst_upper_contrast <= 1e-12
    assert result.candidate_count == len(candidates)
    assert result.bound_type == "bernstein_grid"


def test_empirical_bernstein_grid_uses_sample_variance_and_declared_range() -> None:
    # Every disjoint pair has the same negative harm contrast at beta=0.5.
    # A zero declared range is therefore valid and should yield an exact pass.
    high = np.tile(np.array([[1.0, -1.0], [-1.0, 1.0]]), (4, 1))
    control = 0.5 * high

    result = finite_sample_empirical_bernstein_grid_beta(
        [high],
        [control],
        candidate_betas=[0.0, 0.5],
        contrast_range_bounds=[[0.0, 0.0]],
        confidence=0.95,
        preferred_beta=0.5,
    )

    assert result.beta == pytest.approx(0.5)
    assert result.worst_upper_contrast < 0.0
    assert not result.abstained
    assert result.bound_type == "empirical_bernstein_grid"


def test_output_spans_imply_a_deterministic_contrast_range() -> None:
    bounds = contrast_range_bounds_from_output_spans(
        candidate_betas=[0.0, 0.5],
        high_coordinate_spans=[[2.0, 4.0]],
        control_coordinate_spans=[[1.0, 3.0]],
    )

    # beta^2 * sum(c_i^2)/(2n) + 2|beta| * sum(h_i c_i)/n
    np.testing.assert_allclose(bounds, [[0.0, 7.625]])


def test_empirical_bernstein_grid_abstains_under_a_loose_range_contract() -> None:
    rng = np.random.default_rng(1927)
    high = rng.normal(size=(40, 2))
    control = 0.5 * high + rng.normal(scale=0.2, size=high.shape)

    result = finite_sample_empirical_bernstein_grid_beta(
        [high],
        [control],
        candidate_betas=[0.0, 0.5],
        contrast_range_bounds=[[0.0, 100.0]],
        preferred_beta=0.5,
    )

    assert result.beta == 0.0
    assert result.abstained
    assert result.preferred_beta_clipped


def test_fixed_beta_gate_avoids_the_grid_selection_penalty() -> None:
    # The coefficient is fixed before these 200 certification pairs arrive.
    # Its constant negative contrast clears the one-decision bound but not an
    # otherwise unnecessary eleven-candidate simultaneous grid correction.
    scale = np.sqrt(0.06 / 0.875)
    high = np.tile(scale * np.array([[1.0, -1.0], [-1.0, 1.0]]), (200, 1))
    control = 0.5 * high
    candidates = np.linspace(0.0, 0.5, 11)

    fixed = finite_sample_empirical_bernstein_fixed_beta(
        [high],
        [control],
        beta=0.5,
        contrast_range_bounds=[1.0],
        confidence=0.95,
    )
    grid = finite_sample_empirical_bernstein_grid_beta(
        [high],
        [control],
        candidate_betas=candidates,
        contrast_range_bounds=[[0.0] + [1.0] * 10],
        confidence=0.95,
        preferred_beta=0.5,
    )

    assert fixed.beta == pytest.approx(0.5)
    assert fixed.worst_upper_contrast < 0.0
    assert fixed.bound_type == "empirical_bernstein_fixed"
    assert not fixed.abstained
    assert grid.beta == 0.0
    assert grid.abstained


def test_fixed_beta_gate_falls_back_to_direct_when_not_certified() -> None:
    rng = np.random.default_rng(2027)
    high = rng.normal(size=(40, 3))
    control = rng.normal(size=high.shape)

    result = finite_sample_empirical_bernstein_fixed_beta(
        [high],
        [control],
        beta=0.4,
        contrast_range_bounds=[10.0],
        confidence=0.95,
    )

    assert result.beta == 0.0
    assert result.abstained
    assert result.preferred_beta_clipped


def test_finite_sample_contrast_grid_abstains_when_bounds_are_uninformative() -> None:
    rng = np.random.default_rng(91)
    high = rng.normal(size=(40, 2))
    control = rng.normal(size=high.shape)

    result = finite_sample_contrast_grid_beta(
        [high],
        [control],
        candidate_betas=[0.0, 0.5, 1.0],
        contrast_variance_bounds=[[0.0, 100.0, 100.0]],
        contrast_range_bounds=[[0.0, 100.0, 100.0]],
        preferred_beta=1.0,
    )

    assert result.beta == 0.0
    assert result.abstained
    assert result.preferred_beta_clipped


def test_finite_sample_contrast_grid_validates_audit_contract() -> None:
    high = np.arange(32, dtype=float).reshape(16, 2)
    control = 0.5 * high

    with pytest.raises(ValueError, match="include zero"):
        finite_sample_contrast_grid_beta(
            [high],
            [control],
            candidate_betas=[0.5, 1.0],
            contrast_variance_bounds=[[1.0, 1.0]],
            contrast_range_bounds=[[1.0, 1.0]],
        )
    with pytest.raises(ValueError, match="shape"):
        finite_sample_contrast_grid_beta(
            [high],
            [control],
            candidate_betas=[0.0, 0.5],
            contrast_variance_bounds=[[0.0]],
            contrast_range_bounds=[[0.0, 1.0]],
        )


def test_confidence_envelope_abstains_when_history_cannot_bound_denominator() -> None:
    high = np.zeros((8, 2))
    control = np.arange(16, dtype=float).reshape(8, 2)

    result = confidence_minimax_normalized_excess_beta(
        [high], [control], confidence=0.95
    )

    assert result.beta == 0.0
    assert result.worst_upper_normalized_excess == 0.0
    assert result.abstained


def test_confidence_envelope_abstains_for_singular_three_moment_geometry() -> None:
    high = np.arange(40, dtype=float).reshape(20, 2)
    control = 0.5 * high

    result = confidence_minimax_normalized_excess_beta([high], [control])

    assert result.beta == 0.0
    assert result.abstained


def test_confidence_envelope_rejects_odd_or_too_short_histories() -> None:
    with pytest.raises(ValueError, match="even"):
        confidence_minimax_normalized_excess_beta(
            [np.ones((9, 2))], [np.ones((9, 2))]
        )
    with pytest.raises(ValueError, match="at least eight"):
        confidence_minimax_normalized_excess_beta(
            [np.ones((6, 2))], [np.ones((6, 2))]
        )
    with pytest.raises(ValueError, match="matching"):
        deletion_robust_minimax_normalized_excess_beta(
            [np.ones((3, 1))], [np.ones((4, 1))]
        )


@pytest.mark.parametrize(
    "direct,cross,energy,limit,match",
    [
        ([0.0], [1.0], [1.0], 2.0, "direct risks"),
        ([1.0], [1.0, 2.0], [1.0], 2.0, "same non-zero length"),
        ([1.0], [1.0], [-1.0], 2.0, "control energies"),
        ([1.0], [1.0], [1.0], 0.0, "beta_limit"),
    ],
)
def test_risk_envelope_rejects_invalid_geometry(
    direct, cross, energy, limit, match
) -> None:
    with pytest.raises(ValueError, match=match):
        minimax_normalized_excess_beta(
            direct_risks=direct,
            cross_moments=cross,
            control_energies=energy,
            beta_limit=limit,
        )


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


def test_pool_anchor_aware_moments_uses_no_truth_and_weights_trace_energy() -> None:
    diagnostics = [
        {
            "paired_cross_energy": 2.0,
            "paired_low_variance_energy": 3.0,
            "anchor_variance_energy": 1.0,
        },
        {
            "paired_cross_energy": 1.0,
            "paired_low_variance_energy": 1.0,
            "anchor_variance_energy": 1.0,
        },
    ]

    result = pool_anchor_aware_moments(diagnostics)

    assert result == pytest.approx((2.0 + 1.0) / (3.0 + 1.0 + 1.0 + 1.0))


def test_history_moments_center_scores_so_truth_is_not_required() -> None:
    high_errors = np.asarray([[2.0], [-2.0], [1.0], [-1.0]])
    low_errors = np.asarray([[1.0], [-1.0], [0.5], [-0.5]])
    anchor_errors = np.asarray([[0.2], [-0.2], [-0.1], [0.1]])
    beta = pool_history_anchor_aware_moments(
        high_errors + 17.0,
        low_errors - 5.0,
        anchor_errors + 9.0,
    )
    deployed_control = low_errors - anchor_errors
    expected = np.sum(high_errors * deployed_control) / np.sum(deployed_control**2)
    assert beta == pytest.approx(expected)


def test_anchor_orthogonality_audit_exactly_isolates_denominator_approximation() -> None:
    high = np.asarray([[-1.0], [0.0], [1.0]])
    low = np.asarray([[-1.0], [1.0], [0.0]])
    anchor = np.asarray([[0.0], [-1.0], [1.0]])

    audit = anchor_orthogonality_audit(
        high + 10.0,
        low + 7.0,
        anchor + 7.0,
    )

    assert audit.direct_risk == pytest.approx(1.0)
    assert audit.deployed_cross == pytest.approx(0.0)
    assert audit.deployed_energy == pytest.approx(3.0)
    assert audit.paired_cross == pytest.approx(0.5)
    assert audit.paired_low_energy == pytest.approx(1.0)
    assert audit.anchor_energy == pytest.approx(1.0)
    assert audit.high_anchor_cross == pytest.approx(0.5)
    assert audit.low_anchor_cross == pytest.approx(-0.5)
    assert audit.direct_beta == pytest.approx(0.0)
    assert audit.anchor_energy_beta == pytest.approx(0.25)
    assert audit.paired_only_beta == pytest.approx(0.5)
    assert audit.beta_gap == pytest.approx(-0.25)
    assert audit.anchor_energy_excess == pytest.approx(0.1875)


def test_anchor_energy_diagnostic_retains_independence_specialized_formula() -> None:
    high = np.asarray([[-1.0], [0.0], [1.0]])
    low = np.asarray([[-1.0], [1.0], [0.0]])
    anchor = np.asarray([[0.0], [-1.0], [1.0]])

    beta = pool_history_anchor_energy_moments(high, low, anchor)

    assert beta == pytest.approx(0.25)


def test_history_paired_only_matches_same_histories_without_anchor_energy() -> None:
    high_errors = np.asarray([[2.0], [-2.0], [1.0], [-1.0]])
    low_errors = np.asarray([[1.0], [-1.0], [0.5], [-0.5]])

    beta = pool_history_paired_only_moments(
        high_errors + 17.0,
        low_errors - 5.0,
    )

    assert beta == pytest.approx(np.sum(high_errors * low_errors) / np.sum(low_errors**2))


def test_nested_cost_allocation_obeys_boundary_and_stationary_law() -> None:
    assert nested_cost_optimal_anchor_ratio(1.0, 0.2, 1.0, 2.0, 0.5) == 0.0

    ratio = nested_cost_optimal_anchor_ratio(1.0, 0.8, 1.0, 0.5, 0.2)
    assert ratio > 0.0
    derivative = 0.2 * (1.0 - 0.8**2 * ratio / (ratio + 0.5)) - (
        (1.0 + 0.2 * ratio) * 0.8**2 * 0.5 / (ratio + 0.5) ** 2
    )
    assert derivative == pytest.approx(0.0, abs=1e-10)


def test_anchor_aware_diagonal_has_one_finite_coefficient_per_owner() -> None:
    owners, high, low = _oracles(n=10)
    result = run_anchor_aware_cv_oracle(
        owners,
        high,
        low,
        budget=80,
        seed=17,
        anchor_budget=40,
        anchor_seed=991,
        coefficient_mode="diagonal",
    )
    beta = np.asarray(result.diagnostics["beta"])
    assert beta.shape == (len(owners),)
    assert np.all(np.isfinite(beta))
    assert result.diagnostics["coefficient_mode"] == "anchor_aware_diagonal"


def test_anchor_aware_matrix_is_finite_and_preserves_vector_width() -> None:
    owners, high, low = _oracles(n=10)
    result = run_anchor_aware_cv_oracle(
        owners,
        high,
        low,
        budget=80,
        seed=17,
        anchor_budget=40,
        anchor_seed=991,
        coefficient_mode="matrix",
        ridge_relative=0.1,
    )
    matrix = np.asarray(result.diagnostics["beta"])
    assert matrix.shape == (len(owners), len(owners))
    assert np.all(np.isfinite(matrix))
    assert result.diagnostics["coefficient_mode"] == "anchor_aware_matrix"


def test_anchor_aware_degenerate_control_falls_back_to_direct_not_unit() -> None:
    owners = tuple(f"o{i}" for i in range(6))

    def high(mask: int) -> float:
        return float(sum((i + 1) for i in range(6) if mask & (1 << i)))

    def constant_low(mask: int) -> float:
        return 0.0

    direct = estimate_leverage_oracle(owners, high, budget=64, seed=17)
    result = run_anchor_aware_cv_oracle(
        owners,
        high,
        constant_low,
        budget=64,
        seed=17,
        anchor_budget=40,
        anchor_seed=991,
    )

    assert result.scores == pytest.approx(direct.scores)
    assert result.diagnostics["beta"] == 0.0
    assert result.diagnostics["degenerate_fallback"] == "direct"
