import numpy as np
import pytest
from datamechbench.methods.valuation_anytime_gate import (
    anytime_contrast_grid_beta,
    anytime_routed_contrast_beta,
)


def test_anytime_gate_stops_at_hand_computed_e_process_crossing() -> None:
    # One source, one nonzero coefficient, X_t=-1, range width r=2.
    # With eta=lambda*r=1, log E_t=t(1/2-1/8)=3t/8 and the
    # cell threshold is log(1/0.05), first crossed at t=8.
    contrasts = np.zeros((1, 12, 2))
    contrasts[:, :, 1] = -1.0

    result = anytime_contrast_grid_beta(
        contrasts,
        candidate_betas=[0.0, 0.5],
        contrast_range_bounds=[[0.0, 2.0]],
        confidence=0.95,
        preferred_beta=0.5,
        eta_grid=[1.0],
    )

    assert result.beta == pytest.approx(0.5)
    assert result.stopping_pair == 8
    assert result.abstained is False
    assert result.bound_type == "mixture_e_process"


def test_anytime_gate_never_certifies_a_null_or_harmful_contrast() -> None:
    contrasts = np.zeros((2, 200, 2))
    contrasts[1, :, 1] = 0.2

    result = anytime_contrast_grid_beta(
        contrasts,
        candidate_betas=[0.0, 0.5],
        contrast_range_bounds=[[0.0, 1.0], [0.0, 1.0]],
        confidence=0.95,
        preferred_beta=0.5,
        eta_grid=[0.5, 1.0],
    )

    assert result.beta == 0.0
    assert result.stopping_pair is None
    assert result.abstained is True


def test_anytime_gate_selects_only_a_coefficient_safe_for_every_source() -> None:
    contrasts = np.zeros((2, 160, 3))
    contrasts[:, :, 1] = -0.8
    contrasts[0, :, 2] = -1.0
    contrasts[1, :, 2] = 0.1

    result = anytime_contrast_grid_beta(
        contrasts,
        candidate_betas=[0.0, 0.25, 0.5],
        contrast_range_bounds=[[0.0, 2.0, 2.0], [0.0, 2.0, 2.0]],
        confidence=0.95,
        preferred_beta=0.5,
        eta_grid=[0.5, 1.0, 2.0],
    )

    assert result.beta == pytest.approx(0.25)
    assert result.stopping_pair is not None
    assert all(value >= result.log_rejection_threshold for value in result.per_game_log_e_values)


def test_anytime_gate_rejects_misaligned_contracts() -> None:
    with pytest.raises(ValueError, match="shape"):
        anytime_contrast_grid_beta(
            np.zeros((1, 10, 2)),
            candidate_betas=[0.0, 0.5],
            contrast_range_bounds=[[0.0]],
        )


def test_routed_gate_freezes_crossed_sources_and_reduces_pair_cost() -> None:
    # At eta=1 and range width 2, X=-1 adds 3/8 log-e per pair and
    # X=-1/2 adds 1/8.  With two source nulls the threshold is
    # log(2/.05), so the local first crossings are 10 and 30 pairs.
    contrasts = np.vstack((np.full(40, -1.0), np.full(40, -0.5)))

    result = anytime_routed_contrast_beta(
        contrasts,
        beta=0.5,
        contrast_range_bounds=[2.0, 2.0],
        confidence=0.95,
        eta_grid=[1.0],
    )

    assert result.beta == pytest.approx(0.5)
    assert result.per_game_stopping_pairs == (10, 30)
    assert result.total_source_pairs == 40
    assert result.synchronous_source_pairs == 60
    assert result.cost_ratio_to_synchronous == pytest.approx(2.0 / 3.0)
    assert result.abstained is False


def test_routed_gate_abstains_when_any_source_is_not_certified() -> None:
    contrasts = np.vstack((np.full(80, -1.0), np.full(80, 0.2)))

    result = anytime_routed_contrast_beta(
        contrasts,
        beta=0.5,
        contrast_range_bounds=[2.0, 2.0],
        confidence=0.95,
        eta_grid=[1.0],
    )

    assert result.beta == 0.0
    assert result.per_game_stopping_pairs == (10, None)
    assert result.total_source_pairs == 90
    assert result.synchronous_source_pairs == 160
    assert result.abstained is True


def test_routed_gate_rejects_nonpositive_range_contract() -> None:
    with pytest.raises(ValueError, match="positive"):
        anytime_routed_contrast_beta(
            np.zeros((2, 10)),
            beta=0.5,
            contrast_range_bounds=[1.0, 0.0],
        )


def test_routed_gate_uses_the_full_mixture_not_the_best_component() -> None:
    # For X=-1 and r=2, eta=.5 and 1 have log components .21875t and
    # .375t.  Their equal mixture first exceeds log(20) at t=10; choosing
    # only the best component would incorrectly stop at t=8.
    result = anytime_routed_contrast_beta(
        np.full((1, 12), -1.0),
        beta=0.5,
        contrast_range_bounds=[2.0],
        confidence=0.95,
        eta_grid=[0.5, 1.0],
    )

    assert result.per_game_stopping_pairs == (10,)


def test_routed_gate_controls_boundary_null_crossings() -> None:
    generator = np.random.default_rng(4317)
    false_crossings = 0
    trials = 1_000
    for _ in range(trials):
        streams = generator.choice((-1.0, 1.0), size=(2, 120))
        result = anytime_routed_contrast_beta(
            streams,
            beta=0.5,
            contrast_range_bounds=[2.0, 2.0],
            confidence=0.90,
            eta_grid=[0.25, 0.5, 1.0, 2.0, 4.0],
        )
        false_crossings += any(
            value is not None for value in result.per_game_stopping_pairs
        )

    assert false_crossings / trials <= 0.10


def test_routed_gate_rejects_zero_coefficient_that_needs_no_audit() -> None:
    with pytest.raises(ValueError, match="nonzero"):
        anytime_routed_contrast_beta(
            np.zeros((1, 10)),
            beta=0.0,
            contrast_range_bounds=[1.0],
        )
