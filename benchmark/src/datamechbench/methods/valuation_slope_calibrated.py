"""Slope-calibrated multi-fidelity estimation for ordinary Data Shapley."""

from __future__ import annotations

import importlib.util
import math
import warnings
from dataclasses import dataclass
from typing import Sequence

import numpy as np

from ..coalition_games import CoalitionGameTable
from ..models import ValuationOutput
from .valuation_multifidelity import InapplicableBudgetError
from .valuation_sota import evaluate_sota

_COUPLED_SVARM_CACHE: dict[
    tuple[str, str, int, int],
    tuple[
        dict[str, float],
        dict[str, float],
        tuple[int, ...],
        tuple[float, ...],
        tuple[float, ...],
    ],
] = {}


@dataclass(frozen=True)
class SlopeCalibratedConfig:
    """Global finite-sample settings for slope-calibrated residualization.

    ``folds`` remains pinned at two for evidence-schema compatibility with the
    first development iteration; the coupled estimator fits one plug-in slope.
    """

    ridge_relative: float
    folds: int = 2

    def __post_init__(self) -> None:
        if not math.isfinite(self.ridge_relative) or self.ridge_relative < 0:
            raise ValueError("ridge_relative must be finite and non-negative")
        if self.folds != 2:
            raise ValueError("folds must equal two for the frozen evidence schema")


def optimal_residual_slope(
    high_marginals: Sequence[float],
    low_marginals: Sequence[float],
    *,
    ridge: float,
) -> float:
    """Return the ridge-stabilized control-variate slope for paired samples."""

    high = np.asarray(tuple(high_marginals), dtype=float)
    low = np.asarray(tuple(low_marginals), dtype=float)
    if high.ndim != 1 or low.ndim != 1 or len(high) != len(low):
        raise ValueError("high and low marginals must have the same length")
    if len(high) < 2:
        raise ValueError("at least two paired marginals are required")
    if not np.all(np.isfinite(high)) or not np.all(np.isfinite(low)):
        raise ValueError("paired marginals must be finite")
    if not math.isfinite(ridge) or ridge < 0:
        raise ValueError("ridge must be finite and non-negative")
    centered_high = high - float(np.mean(high))
    centered_low = low - float(np.mean(low))
    covariance = float(np.mean(centered_high * centered_low))
    low_variance = float(np.mean(centered_low**2))
    denominator = low_variance + float(ridge)
    return 0.0 if denominator <= 0 else covariance / denominator


def _coupled_svarm_estimates(
    high: CoalitionGameTable,
    low: CoalitionGameTable,
    *,
    budget: int,
    seed: int,
) -> tuple[
    dict[str, float],
    dict[str, float],
    tuple[int, ...],
    tuple[float, ...],
    tuple[float, ...],
]:
    """Evaluate high and low games on one deterministic SVARM sample plan."""

    cache_key = (high.content_hash, low.content_hash, budget, seed)
    cached = _COUPLED_SVARM_CACHE.get(cache_key)
    if cached is not None:
        return cached
    if importlib.util.find_spec("shapiq") is None:
        raise RuntimeError("SCR-Shapley requires shapiq==1.7.0")
    import shapiq

    if shapiq.__version__ != "1.7.0":
        raise RuntimeError(f"SCR-Shapley requires shapiq==1.7.0, got {shapiq.__version__}")
    owner_count = len(high.owner_ids)

    def evaluate(
        table: CoalitionGameTable,
    ) -> tuple[dict[str, float], tuple[int, ...], tuple[float, ...]]:
        observed_masks: list[int] = []
        observed_values: list[float] = []

        def game(coalitions: np.ndarray) -> np.ndarray:
            matrix = np.atleast_2d(np.asarray(coalitions, dtype=bool))
            masks = tuple(
                sum(
                    (1 << index)
                    for index, included in enumerate(row)
                    if included
                )
                for row in matrix
            )
            observed_masks.extend(masks)
            values = tuple(float(table.values[mask]) for mask in masks)
            observed_values.extend(values)
            return np.asarray(values, dtype=float)

        approximator = shapiq.SVARM(
            n=owner_count,
            random_state=seed,
            pairing_trick=True,
        )
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore", message="Not all budget is required due to the border-trick"
            )
            result = approximator.approximate(budget=budget, game=game)
        values = np.asarray(result.get_n_order_values(1), dtype=float)
        if values.shape != (owner_count,) or not np.all(np.isfinite(values)):
            raise RuntimeError("SVARM returned invalid first-order Shapley values")
        return (
            dict(zip(table.owner_ids, map(float, values), strict=True)),
            tuple(observed_masks),
            tuple(observed_values),
        )

    high_scores, high_masks, high_values = evaluate(high)
    low_scores, low_masks, low_values = evaluate(low)
    if high_masks != low_masks:
        raise RuntimeError("coupled SVARM high and low sample plans diverged")
    result = high_scores, low_scores, high_masks, high_values, low_values
    if len(_COUPLED_SVARM_CACHE) >= 2048:
        _COUPLED_SVARM_CACHE.pop(next(iter(_COUPLED_SVARM_CACHE)))
    _COUPLED_SVARM_CACHE[cache_key] = result
    return result


def _coalition_value_slope(
    high_values: Sequence[float],
    low_values: Sequence[float],
    masks: Sequence[int],
    *,
    ridge_relative: float,
) -> tuple[float, int]:
    """Fit one scale after projecting out size and additive-owner effects."""

    beta, _, observations, _ = _coalition_value_slope_statistics(
        high_values,
        low_values,
        masks,
        ridge_relative=ridge_relative,
    )
    return beta, observations


def _coalition_value_slope_statistics(
    high_values: Sequence[float],
    low_values: Sequence[float],
    masks: Sequence[int],
    *,
    ridge_relative: float,
) -> tuple[float, float, int, bool]:
    """Return projected slope, standard error, observations, and degeneracy."""

    if len(masks) < 2:
        return 0.0, math.inf, len(masks), True
    owner_count = max((mask.bit_length() for mask in masks), default=0)
    sizes = tuple(sorted({mask.bit_count() for mask in masks}))
    design = np.asarray(
        [
            [float(mask.bit_count() == size) for size in sizes]
            + [float(bool(mask & (1 << owner))) for owner in range(owner_count)]
            for mask in masks
        ],
        dtype=float,
    )
    high_array = np.asarray(high_values, dtype=float)
    low_array = np.asarray(low_values, dtype=float)
    high_residual = high_array - design @ np.linalg.lstsq(
        design, high_array, rcond=None
    )[0]
    low_residual = low_array - design @ np.linalg.lstsq(
        design, low_array, rcond=None
    )[0]
    control_variance = float(np.var(low_residual))
    numerical_floor = (
        100.0
        * np.finfo(float).eps
        * max(1.0, float(np.mean(np.square(low_array))))
    )
    if control_variance <= numerical_floor:
        return 0.0, math.inf, len(low_residual), True
    beta = optimal_residual_slope(
        high_residual,
        low_residual,
        ridge=ridge_relative * control_variance,
    )
    regression_residual = high_residual - beta * low_residual
    degrees_of_freedom = max(1, len(low_residual) - int(np.linalg.matrix_rank(design)) - 1)
    residual_variance = float(np.sum(regression_residual**2) / degrees_of_freedom)
    standard_error = math.sqrt(
        max(0.0, residual_variance) / float(np.sum(low_residual**2))
    )
    return beta, standard_error, len(low_residual), False


def _coalition_value_confidence_slope(
    high_values: Sequence[float],
    low_values: Sequence[float],
    masks: Sequence[int],
    *,
    ridge_relative: float,
    z_value: float = 1.96,
) -> tuple[float, int, float, float, bool]:
    """Shrink the fitted deviation from unit by its confidence radius.

    The output moves away from the conventional unit coefficient only by the
    portion of ``beta - 1`` that exceeds ``z_value`` estimated standard errors.
    It uses paired coalition utilities only, never exact high-game Shapley truth.
    """

    if not math.isfinite(z_value) or z_value < 0.0:
        raise ValueError("z_value must be finite and non-negative")
    raw_beta, standard_error, observations, degenerate = _coalition_value_slope_statistics(
        high_values,
        low_values,
        masks,
        ridge_relative=ridge_relative,
    )
    if degenerate:
        return 1.0, observations, raw_beta, standard_error, False
    deviation = raw_beta - 1.0
    retained = max(0.0, abs(deviation) - z_value * standard_error)
    beta = 1.0 + math.copysign(retained, deviation) if retained else 1.0
    return beta, observations, raw_beta, standard_error, retained > 0.0


def run_slope_calibrated_residual(
    high: CoalitionGameTable,
    low: CoalitionGameTable,
    *,
    budget: int,
    seed: int,
    config: SlopeCalibratedConfig,
    accounting: str,
    low_cost_ratio: float,
    beta_mode: str = "learned",
) -> ValuationOutput:
    """Estimate high-fidelity Shapley with a learned residual slope."""

    if high.owner_ids != low.owner_ids or set(high.values) != set(low.values):
        raise ValueError("high and low games must have identical owners and masks")
    if not isinstance(budget, int) or budget < 0:
        raise ValueError("budget must be a non-negative integer")
    if accounting not in {"cached", "strict"}:
        raise ValueError("accounting must be 'cached' or 'strict'")
    if beta_mode not in {"zero", "one", "learned"}:
        raise ValueError("beta_mode must be zero, one, or learned")
    if not math.isfinite(low_cost_ratio) or low_cost_ratio < 0:
        raise ValueError("low_cost_ratio must be finite and non-negative")

    low_equivalent_cost = (
        len(low.values) * float(low_cost_ratio) if accounting == "strict" else 0.0
    )
    high_budget = math.floor(budget - low_equivalent_cost + 1e-12)
    if high_budget < 2:
        raise InapplicableBudgetError(
            required_calls=2,
            available_calls=max(0, high_budget),
            reason="low_table_consumes_budget",
            diagnostics={
                "declared_budget": budget,
                "low_equivalent_cost": low_equivalent_cost,
            },
        )

    if high_budget >= len(high.values):
        exact = evaluate_sota(
            "exact_table", high, budget=len(high.values), seed=seed
        )
        sampled_masks = frozenset(high.values)
        return ValuationOutput(
            exact.scores,
            diagnostics={
                "backend": "slope_calibrated_coupled_svarm",
                "beta_mode": beta_mode,
                "ridge_relative": config.ridge_relative,
                "fold_count": config.folds,
                "slope_records": (),
                "sampled_high_masks": tuple(sorted(sampled_masks)),
                "paired_high_calls": len(sampled_masks),
                "low_table_calls": len(low.values),
                "accounting": accounting,
                "low_equivalent_cost": low_equivalent_cost,
                "realized_equivalent_cost": len(sampled_masks)
                + low_equivalent_cost,
                "exact_high_table": True,
            },
            utility_calls=len(sampled_masks),
        )

    high_scores, sampled_low_scores, sampled_mask_sequence, high_values, low_values = (
        _coupled_svarm_estimates(
            high,
            low,
            budget=high_budget,
            seed=seed,
        )
    )
    sampled_masks = frozenset(sampled_mask_sequence)
    exact_low = evaluate_sota(
        "exact_table", low, budget=len(low.values), seed=0
    ).scores
    if beta_mode == "zero":
        beta = 0.0
        slope_observations = 0
    elif beta_mode == "one":
        beta = 1.0
        slope_observations = 0
    else:
        beta, slope_observations = _coalition_value_slope(
            high_values,
            low_values,
            sampled_mask_sequence,
            ridge_relative=config.ridge_relative,
        )
    scores = {
        owner: float(
            high_scores[owner]
            - beta * (sampled_low_scores[owner] - exact_low[owner])
        )
        for owner in high.owner_ids
    }
    realized_cost = len(sampled_mask_sequence) + low_equivalent_cost
    return ValuationOutput(
        scores,
        diagnostics={
            "backend": "slope_calibrated_coupled_svarm",
            "base_estimator": "shapiq_svarm",
            "pairing_trick": True,
            "beta_mode": beta_mode,
            "beta": float(beta),
            "ridge_relative": config.ridge_relative,
            "fold_count": config.folds,
            "slope_records": (
                {
                    "beta": float(beta),
                    "training_observations": slope_observations,
                    "centering": "coalition_size_and_owner_fixed_effects",
                },
            ),
            "slope_fallback_count": int(
                beta_mode == "learned" and slope_observations < 2
            ),
            "sampled_high_masks": tuple(sorted(sampled_masks)),
            "sampled_high_mask_sequence": sampled_mask_sequence,
            "paired_high_calls": len(sampled_mask_sequence),
            "low_table_calls": len(low.values),
            "accounting": accounting,
            "low_equivalent_cost": low_equivalent_cost,
            "realized_equivalent_cost": realized_cost,
            "coefficient_fit": "same_sample_plugin",
            "exact_high_table": False,
        },
        utility_calls=len(sampled_mask_sequence),
    )

__all__ = [
    "SlopeCalibratedConfig",
    "optimal_residual_slope",
    "run_slope_calibrated_residual",
]
