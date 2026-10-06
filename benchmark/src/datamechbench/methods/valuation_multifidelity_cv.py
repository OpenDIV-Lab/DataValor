"""Same-information multi-fidelity control baselines for provider Shapley."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Mapping, Sequence

import numpy as np

from ..models import ValuationOutput
from .valuation_slope_calibrated import _coalition_value_slope
from .valuation_slope_calibrated_plus import (
    _complement_deletion_blocks,
    _leverage_trace_oracle,
    leverage_scores_from_trace,
)


@dataclass(frozen=True)
class CrossFitFold:
    train_indices: tuple[int, ...]
    score_indices: tuple[int, ...]
    beta: float


@dataclass(frozen=True)
class CoefficientEstimate:
    mode: str
    global_beta: float
    provider_betas: tuple[float, ...]
    raw_beta: float
    standard_error: float
    degenerate: bool
    fold_records: tuple[CrossFitFold, ...] = ()


def _global_ratio(high: np.ndarray, low: np.ndarray) -> tuple[float, float, bool]:
    block_cross = np.sum(high * low, axis=1)
    block_low = np.sum(low * low, axis=1)
    denominator = float(np.sum(block_low))
    floor = 100.0 * np.finfo(float).eps * max(1.0, float(np.sum(high * high)))
    if denominator <= floor or len(block_low) < 2:
        return 1.0, 0.0, True
    beta = float(np.sum(block_cross) / denominator)
    score = block_cross - beta * block_low
    mean_low = denominator / len(block_low)
    standard_error = float(
        np.sqrt(np.var(score, ddof=1) / len(score)) / mean_low
    )
    return beta, standard_error, False


def estimate_cv_coefficients(
    high_influence: Sequence[Sequence[float]],
    low_influence: Sequence[Sequence[float]],
    *,
    mode: str,
    ridge_relative: float = 0.1,
    folds: int = 5,
    z_value: float = 1.96,
) -> CoefficientEstimate:
    """Estimate comparable scalar/vector coefficients from paired influences."""

    high = np.asarray(high_influence, dtype=float)
    low = np.asarray(low_influence, dtype=float)
    allowed = {
        "unit",
        "influence_raw",
        "influence_safe",
        "crossfit",
        "acv_shrinkage",
        "provider_ridge",
    }
    if mode not in allowed:
        raise ValueError(f"unknown coefficient mode: {mode}")
    if high.shape != low.shape or high.ndim != 2 or high.shape[1] < 1:
        raise ValueError("paired influence arrays must have equal two-dimensional shape")
    if not np.all(np.isfinite(high)) or not np.all(np.isfinite(low)):
        raise ValueError("paired influences must be finite")
    if not math.isfinite(ridge_relative) or ridge_relative < 0.0:
        raise ValueError("ridge_relative must be finite and non-negative")
    if not math.isfinite(z_value) or z_value < 0.0:
        raise ValueError("z_value must be finite and non-negative")
    owner_count = high.shape[1]
    if mode == "unit":
        return CoefficientEstimate(mode, 1.0, (1.0,) * owner_count, 1.0, 0.0, False)

    high = high - np.mean(high, axis=0, keepdims=True)
    low = low - np.mean(low, axis=0, keepdims=True)
    raw_beta, standard_error, degenerate = _global_ratio(high, low)
    if degenerate:
        return CoefficientEstimate(mode, 1.0, (1.0,) * owner_count, 1.0, 0.0, True)

    if mode == "influence_safe":
        lower = raw_beta - z_value * standard_error
        upper = raw_beta + z_value * standard_error
        beta = float(min(max(1.0, lower), upper))
    elif mode == "acv_shrinkage":
        beta = float((raw_beta + ridge_relative) / (1.0 + ridge_relative))
    else:
        beta = raw_beta

    fold_records: tuple[CrossFitFold, ...] = ()
    if mode == "crossfit":
        if not isinstance(folds, int) or folds < 2 or folds > len(high):
            raise ValueError("folds must be between two and the block count")
        records: list[CrossFitFold] = []
        all_indices = np.arange(len(high))
        for score_array in np.array_split(all_indices, folds):
            score_indices = tuple(map(int, score_array))
            train_indices = tuple(
                int(index) for index in all_indices if index not in set(score_indices)
            )
            fold_beta, _, fold_degenerate = _global_ratio(
                high[list(train_indices)], low[list(train_indices)]
            )
            records.append(
                CrossFitFold(
                    train_indices=train_indices,
                    score_indices=score_indices,
                    beta=1.0 if fold_degenerate else fold_beta,
                )
            )
        beta = float(np.mean([record.beta for record in records]))
        fold_records = tuple(records)

    denominator = np.sum(low * low, axis=0)
    cross = np.sum(high * low, axis=0)
    scale = float(np.mean(denominator))
    floor = 100.0 * np.finfo(float).eps * max(1.0, scale)
    ridge = ridge_relative * scale
    provider = []
    for owner in range(owner_count):
        if denominator[owner] <= floor:
            provider.append(1.0)
        elif mode == "provider_ridge":
            provider.append(float((cross[owner] + ridge) / (denominator[owner] + ridge)))
        else:
            provider.append(beta)
    if mode == "provider_ridge":
        beta = float(np.mean(provider))
    return CoefficientEstimate(
        mode=mode,
        global_beta=beta,
        provider_betas=tuple(provider),
        raw_beta=raw_beta,
        standard_error=standard_error,
        degenerate=False,
        fold_records=fold_records,
    )


def _delete_block_influences(
    high_values: Sequence[float],
    low_values: Sequence[float],
    masks: Sequence[int],
    *,
    owner_count: int,
) -> tuple[np.ndarray, np.ndarray]:
    high = np.asarray(high_values, dtype=float)
    low = np.asarray(low_values, dtype=float)
    mask_tuple = tuple(map(int, masks))
    full_high = leverage_scores_from_trace(high, mask_tuple, owner_count=owner_count)
    full_low = leverage_scores_from_trace(low, mask_tuple, owner_count=owner_count)
    changes_high: list[np.ndarray] = []
    changes_low: list[np.ndarray] = []
    for block in _complement_deletion_blocks(mask_tuple, owner_count=owner_count):
        keep = np.ones(len(mask_tuple), dtype=bool)
        keep[np.asarray(block, dtype=int)] = False
        kept_masks = tuple(mask for index, mask in enumerate(mask_tuple) if keep[index])
        try:
            deleted_high = leverage_scores_from_trace(
                high[keep], kept_masks, owner_count=owner_count
            )
            deleted_low = leverage_scores_from_trace(
                low[keep], kept_masks, owner_count=owner_count
            )
        except (ValueError, np.linalg.LinAlgError):
            continue
        changes_high.append(full_high - deleted_high)
        changes_low.append(full_low - deleted_low)
    if not changes_high:
        return np.zeros((0, owner_count)), np.zeros((0, owner_count))
    return np.asarray(changes_high), np.asarray(changes_low)


def run_multifidelity_cv_oracle(
    owner_ids: Sequence[str],
    high_value: Callable[[int], float],
    low_value: Callable[[int], float],
    *,
    budget: int,
    seed: int,
    low_anchor: Mapping[str, float],
    low_anchor_calls: int,
    low_anchor_seed: int,
    mode: str,
    pilot_budget: int = 0,
    pilot_seed: int | None = None,
    ridge_relative: float = 0.1,
    folds: int = 5,
    z_value: float = 1.96,
) -> ValuationOutput:
    """Run one same-information control method against on-demand utilities."""

    owners = tuple(map(str, owner_ids))
    if len(owners) < 2 or len(set(owners)) != len(owners):
        raise ValueError("owner_ids must contain at least two unique owners")
    if set(low_anchor) != set(owners):
        raise ValueError("low anchor must contain exactly one value per owner")
    if low_anchor_calls <= 0 or low_anchor_seed == seed:
        raise ValueError("low anchor must use positive calls and an independent seed")
    if mode == "pilot":
        if pilot_budget < 2 or pilot_seed is None or pilot_seed in {seed, low_anchor_seed}:
            raise ValueError("pilot mode requires a positive, disjoint pilot_seed")
    elif pilot_budget or pilot_seed is not None:
        raise ValueError("pilot metadata is valid only in pilot mode")

    high_scores, masks, high_values, high_calls = _leverage_trace_oracle(
        owners, high_value, budget=budget, seed=seed
    )
    low_scores, low_masks, low_values, low_calls = _leverage_trace_oracle(
        owners, low_value, budget=budget, seed=seed
    )
    if masks != low_masks or high_calls != low_calls:
        raise RuntimeError("paired high/low sample plans diverged")

    coefficient_mode = mode
    coefficient_source = "paired_delete_block_influence"
    pilot_high_calls = 0
    if mode == "utility_projection":
        beta, observations = _coalition_value_slope(
            high_values,
            low_values,
            masks,
            ridge_relative=ridge_relative,
        )
        estimate = CoefficientEstimate(
            mode=mode,
            global_beta=float(beta),
            provider_betas=(float(beta),) * len(owners),
            raw_beta=float(beta),
            standard_error=0.0,
            degenerate=observations < 2,
        )
        coefficient_source = "coalition_utility_projection"
    elif mode == "pilot":
        _, pilot_masks, pilot_high, pilot_high_calls = _leverage_trace_oracle(
            owners, high_value, budget=pilot_budget, seed=int(pilot_seed)
        )
        _, pilot_low_masks, pilot_low, pilot_low_calls = _leverage_trace_oracle(
            owners, low_value, budget=pilot_budget, seed=int(pilot_seed)
        )
        if pilot_masks != pilot_low_masks or pilot_high_calls != pilot_low_calls:
            raise RuntimeError("pilot high/low sample plans diverged")
        influence_high, influence_low = _delete_block_influences(
            pilot_high, pilot_low, pilot_masks, owner_count=len(owners)
        )
        estimate = estimate_cv_coefficients(
            influence_high, influence_low, mode="influence_raw"
        )
        coefficient_source = "independent_pilot_influence"
    else:
        influence_high, influence_low = _delete_block_influences(
            high_values, low_values, masks, owner_count=len(owners)
        )
        estimate = estimate_cv_coefficients(
            influence_high,
            influence_low,
            mode=mode,
            ridge_relative=ridge_relative,
            folds=folds,
            z_value=z_value,
        )

    if mode == "provider_ridge":
        coefficients = dict(zip(owners, estimate.provider_betas, strict=True))
    else:
        coefficients = {owner: estimate.global_beta for owner in owners}
    scores = {
        owner: float(
            high_scores[owner]
            - coefficients[owner] * (low_scores[owner] - float(low_anchor[owner]))
        )
        for owner in owners
    }
    return ValuationOutput(
        scores,
        diagnostics={
            "backend": "same_information_multifidelity_cv_oracle",
            "table_free": True,
            "coefficient_mode": coefficient_mode,
            "coefficient_source": coefficient_source,
            "beta": (
                list(map(float, estimate.provider_betas))
                if mode == "provider_ridge"
                else float(estimate.global_beta)
            ),
            "raw_beta": float(estimate.raw_beta),
            "beta_standard_error": float(estimate.standard_error),
            "coefficient_degenerate": bool(estimate.degenerate),
            "paired_trace_seed": int(seed),
            "sampled_high_mask_sequence": masks,
            "paired_high_calls": int(high_calls),
            "low_anchor_calls": int(low_anchor_calls),
            "low_anchor_seed": int(low_anchor_seed),
            "pilot_seed": pilot_seed,
            "pilot_high_calls": int(pilot_high_calls),
            "crossfit_folds": len(estimate.fold_records),
            "uses_exact_high_target": False,
        },
        utility_calls=int(high_calls + pilot_high_calls),
    )


def _centered_jackknife_energy(values: np.ndarray) -> float:
    if len(values) < 2:
        return 0.0
    centered = values - np.mean(values, axis=0, keepdims=True)
    return float((len(values) - 1) / len(values) * np.sum(centered * centered))


def run_anchor_aware_cv_oracle(
    owner_ids: Sequence[str],
    high_value: Callable[[int], float],
    low_value: Callable[[int], float],
    *,
    budget: int,
    seed: int,
    anchor_budget: int,
    anchor_seed: int,
) -> ValuationOutput:
    """Fit the deployed-risk optimum including independent anchor noise."""
    owners = tuple(map(str, owner_ids))
    if len(owners) < 2 or len(set(owners)) != len(owners):
        raise ValueError("owner_ids must contain at least two unique owners")
    if anchor_seed == seed:
        raise ValueError("anchor and paired traces require independent seeds")
    if budget < 2 or anchor_budget < 2:
        raise ValueError("budgets must be at least two")

    high_scores, masks, high_values, high_calls = _leverage_trace_oracle(
        owners, high_value, budget=budget, seed=seed
    )
    low_scores, low_masks, low_values, low_calls = _leverage_trace_oracle(
        owners, low_value, budget=budget, seed=seed
    )
    anchor_scores, anchor_masks, anchor_values, anchor_calls = _leverage_trace_oracle(
        owners, low_value, budget=anchor_budget, seed=anchor_seed
    )
    if masks != low_masks or high_calls != low_calls:
        raise RuntimeError("paired high/low sample plans diverged")

    high_influence, low_influence = _delete_block_influences(
        high_values, low_values, masks, owner_count=len(owners)
    )
    anchor_influence, _ = _delete_block_influences(
        anchor_values, anchor_values, anchor_masks, owner_count=len(owners)
    )
    if len(high_influence) < 2 or len(anchor_influence) < 2:
        beta = paired_beta = 1.0
        high_low_cross = low_energy = anchor_energy = 0.0
        degenerate = True
    else:
        centered_high = high_influence - np.mean(
            high_influence, axis=0, keepdims=True
        )
        centered_low = low_influence - np.mean(low_influence, axis=0, keepdims=True)
        paired_factor = (len(centered_low) - 1) / len(centered_low)
        high_low_cross = float(paired_factor * np.sum(centered_high * centered_low))
        low_energy = _centered_jackknife_energy(low_influence)
        anchor_energy = _centered_jackknife_energy(anchor_influence)
        floor = 100.0 * np.finfo(float).eps * max(
            1.0, _centered_jackknife_energy(high_influence)
        )
        if low_energy <= floor:
            beta = paired_beta = 1.0
            degenerate = True
        else:
            paired_beta = high_low_cross / low_energy
            beta = high_low_cross / (low_energy + anchor_energy)
            degenerate = False

    scores = {
        owner: float(
            high_scores[owner] - beta * (low_scores[owner] - anchor_scores[owner])
        )
        for owner in owners
    }
    return ValuationOutput(
        scores,
        diagnostics={
            "backend": "anchor_aware_multifidelity_cv_oracle",
            "table_free": True,
            "coefficient_mode": "anchor_aware",
            "coefficient_source": "paired_plus_anchor_influence",
            "beta": float(beta),
            "paired_only_beta": float(paired_beta),
            "paired_cross_energy": float(high_low_cross),
            "paired_low_variance_energy": float(low_energy),
            "anchor_variance_energy": float(anchor_energy),
            "coefficient_degenerate": bool(degenerate),
            "paired_trace_seed": int(seed),
            "low_anchor_seed": int(anchor_seed),
            "sampled_high_mask_sequence": masks,
            "sampled_anchor_mask_sequence": anchor_masks,
            "paired_high_calls": int(high_calls),
            "low_anchor_calls": int(anchor_calls),
            "uses_exact_high_target": False,
        },
        utility_calls=int(high_calls),
    )


__all__ = [
    "CoefficientEstimate",
    "CrossFitFold",
    "estimate_cv_coefficients",
    "run_anchor_aware_cv_oracle",
    "run_multifidelity_cv_oracle",
]
