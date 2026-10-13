"""Slope-calibrated residualization on the official Stratified SVARM+ sampler."""

from __future__ import annotations

import importlib
import math
import random
import subprocess
import sys
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence

import numpy as np

from ..coalition_games import CoalitionGameTable
from ..models import ValuationOutput
from .valuation_shapley import OptionalMethodUnavailable
from .valuation_slope_calibrated import (
    SlopeCalibratedConfig,
    _coalition_value_confidence_slope,
    _coalition_value_slope,
)
from .valuation_sota import evaluate_sota

_OFFICIAL_SVARM_COMMIT = "c4e30395b14b8bf9a8687d839d5b406f825bb23d"


@dataclass(frozen=True)
class InfluenceCalibration:
    """Delete-block estimate of the global Shapley-error transfer scale."""

    raw_beta: float
    safe_beta: float
    lower: float
    upper: float
    standard_error: float
    block_count: int
    provider_betas: tuple[float, ...]
    degenerate: bool


def leverage_scores_from_trace(
    values: Sequence[float],
    masks: Sequence[int],
    *,
    owner_count: int,
) -> np.ndarray:
    """Refit LeverageSHAP on a fixed trace without new game evaluations."""

    value_array = np.asarray(tuple(values), dtype=float)
    mask_tuple = tuple(map(int, masks))
    if owner_count < 2:
        raise ValueError("owner_count must be at least two")
    if value_array.ndim != 1 or len(value_array) != len(mask_tuple):
        raise ValueError("values and masks must be equal-length vectors")
    if not np.all(np.isfinite(value_array)):
        raise ValueError("trace values must be finite")
    full_mask = (1 << owner_count) - 1
    if mask_tuple.count(0) != 1 or mask_tuple.count(full_mask) != 1:
        raise ValueError("trace must contain exactly one empty and grand coalition")
    if any(mask < 0 or mask > full_mask for mask in mask_tuple):
        raise ValueError("trace mask lies outside the owner domain")

    empty_index = mask_tuple.index(0)
    grand_index = mask_tuple.index(full_mask)
    v0 = float(value_array[empty_index])
    v_grand = float(value_array[grand_index])
    efficiency_shift = (v_grand - v0) / owner_count
    interior_indices = [
        index for index, mask in enumerate(mask_tuple) if mask not in {0, full_mask}
    ]
    if not interior_indices:
        return np.full(owner_count, efficiency_shift, dtype=float)

    size_counts: dict[int, int] = {}
    for index in interior_indices:
        size = mask_tuple[index].bit_count()
        size_counts[size] = size_counts.get(size, 0) + 1
    design_rows: list[list[float]] = []
    responses: list[float] = []
    weights: list[float] = []
    for index in interior_indices:
        mask = mask_tuple[index]
        size = mask.bit_count()
        row = [
            float(bool(mask & (1 << owner))) - size / owner_count
            for owner in range(owner_count)
        ]
        design_rows.append(row)
        responses.append(float(value_array[index]) - v0 - efficiency_shift * size)
        weights.append(1.0 / (size * (owner_count - size) * size_counts[size]))
    design = np.asarray(design_rows, dtype=float)
    response = np.asarray(responses, dtype=float)
    root_weight = np.sqrt(np.asarray(weights, dtype=float))
    perpendicular = np.linalg.lstsq(
        design * root_weight[:, None], response * root_weight, rcond=None
    )[0]
    return np.asarray(perpendicular + efficiency_shift, dtype=float)


def _complement_deletion_blocks(
    masks: Sequence[int], *, owner_count: int
) -> tuple[tuple[int, ...], ...]:
    full_mask = (1 << owner_count) - 1
    groups: dict[int, list[int]] = {}
    for index, raw_mask in enumerate(masks):
        mask = int(raw_mask)
        if mask in {0, full_mask}:
            continue
        key = min(mask, full_mask ^ mask)
        groups.setdefault(key, []).append(index)
    return tuple(tuple(groups[key]) for key in sorted(groups))


def influence_calibrated_slope(
    high_values: Sequence[float],
    low_values: Sequence[float],
    masks: Sequence[int],
    *,
    owner_count: int,
    z_value: float = 1.96,
) -> InfluenceCalibration:
    """Estimate global and provider-wise control slopes from delete-block influences."""

    high = np.asarray(tuple(high_values), dtype=float)
    low = np.asarray(tuple(low_values), dtype=float)
    mask_tuple = tuple(map(int, masks))
    if high.shape != low.shape or high.ndim != 1 or len(high) != len(mask_tuple):
        raise ValueError("paired traces must have equal one-dimensional shape")
    if not math.isfinite(z_value) or z_value < 0.0:
        raise ValueError("z_value must be finite and non-negative")
    full_high = leverage_scores_from_trace(high, mask_tuple, owner_count=owner_count)
    full_low = leverage_scores_from_trace(low, mask_tuple, owner_count=owner_count)
    blocks = _complement_deletion_blocks(mask_tuple, owner_count=owner_count)
    high_changes: list[np.ndarray] = []
    low_changes: list[np.ndarray] = []
    all_indices = np.arange(len(mask_tuple))
    for block in blocks:
        keep = np.ones(len(mask_tuple), dtype=bool)
        keep[np.asarray(block, dtype=int)] = False
        kept_indices = all_indices[keep]
        try:
            deleted_high = leverage_scores_from_trace(
                high[kept_indices],
                tuple(mask_tuple[index] for index in kept_indices),
                owner_count=owner_count,
            )
            deleted_low = leverage_scores_from_trace(
                low[kept_indices],
                tuple(mask_tuple[index] for index in kept_indices),
                owner_count=owner_count,
            )
        except (ValueError, np.linalg.LinAlgError):
            continue
        high_changes.append(full_high - deleted_high)
        low_changes.append(full_low - deleted_low)
    if len(high_changes) < 2:
        return InfluenceCalibration(
            raw_beta=1.0,
            safe_beta=1.0,
            lower=1.0,
            upper=1.0,
            standard_error=0.0,
            block_count=len(high_changes),
            provider_betas=(1.0,) * owner_count,
            degenerate=True,
        )
    high_influence = np.asarray(high_changes, dtype=float)
    low_influence = np.asarray(low_changes, dtype=float)
    high_influence -= np.mean(high_influence, axis=0, keepdims=True)
    low_influence -= np.mean(low_influence, axis=0, keepdims=True)
    block_cross = np.sum(high_influence * low_influence, axis=1)
    block_low = np.sum(low_influence**2, axis=1)
    mean_low = float(np.mean(block_low))
    floor = 100.0 * np.finfo(float).eps * max(
        1.0, float(np.mean(high_influence**2))
    )
    if mean_low <= floor:
        return InfluenceCalibration(
            raw_beta=1.0,
            safe_beta=1.0,
            lower=1.0,
            upper=1.0,
            standard_error=0.0,
            block_count=len(high_changes),
            provider_betas=(1.0,) * owner_count,
            degenerate=True,
        )
    raw_beta = float(np.mean(block_cross) / mean_low)
    score = block_cross - raw_beta * block_low
    standard_error = float(
        np.sqrt(np.var(score, ddof=1) / len(score)) / mean_low
    )
    lower = raw_beta - z_value * standard_error
    upper = raw_beta + z_value * standard_error
    safe_beta = min(max(1.0, lower), upper)
    provider_betas: list[float] = []
    for owner in range(owner_count):
        denominator = float(np.sum(low_influence[:, owner] ** 2))
        if denominator <= floor:
            provider_betas.append(1.0)
        else:
            provider_betas.append(
                float(
                    np.sum(high_influence[:, owner] * low_influence[:, owner])
                    / denominator
                )
            )
    return InfluenceCalibration(
        raw_beta=raw_beta,
        safe_beta=float(safe_beta),
        lower=float(lower),
        upper=float(upper),
        standard_error=standard_error,
        block_count=len(high_changes),
        provider_betas=tuple(provider_betas),
        degenerate=False,
    )


def _official_plus_trace(
    table: CoalitionGameTable,
    *,
    budget: int,
    seed: int,
    official_repo: str | Path,
) -> tuple[dict[str, float], tuple[int, ...], tuple[float, ...], int]:
    root = Path(official_repo).resolve()
    if not (root / "ApproxMethods/SVARM").is_dir():
        raise OptionalMethodUnavailable("invalid_official_repository:svarm")
    commit = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if commit != _OFFICIAL_SVARM_COMMIT:
        raise OptionalMethodUnavailable(f"unsupported_official_commit:svarm:{commit}")
    if budget < 2 * len(table.owner_ids) + 1:
        raise ValueError("official Stratified SVARM+ budget is below initialization cost")

    sys.path.insert(0, str(root))
    try:
        module = importlib.import_module("ApproxMethods.SVARM.StratifiedSVARMnoReplacement")
        estimator = module.StratifiedSVARMnoReplacement()
    finally:
        sys.path.remove(str(root))

    masks: list[int] = []
    raw_values: list[float] = []
    baseline = float(table.values[0])

    class TracedTableGame:
        def get_player_number(self):
            return len(table.owner_ids)

        def get_value(self, coalition):
            mask = sum(1 << int(index) for index in coalition)
            masks.append(mask)
            raw_values.append(float(table.values[mask]))
            return float(table.values[mask] - baseline)

        def get_shapley_values(self):
            return np.zeros(len(table.owner_ids), dtype=float)

        def get_name(self):
            return table.content_hash

        def get_game_information(self):
            return {"name": self.get_name(), "number_of_players": self.get_player_number()}

    numpy_state = np.random.get_state()
    python_state = random.getstate()
    try:
        np.random.seed(seed)
        random.seed(seed)
        estimator.reset(TracedTableGame(), budget, evaluation_penalty=0, step_size=budget)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            estimator.approximate_shapley_values()
        values = np.asarray(estimator.get_estimates(), dtype=float)
    finally:
        np.random.set_state(numpy_state)
        random.setstate(python_state)
    calls = int(estimator.initial_budget - estimator.budget)
    # ``ExperimentStorage.to_json`` performs one uncharged grand-coalition
    # read after estimation.  It is provenance output, not a sampler draw.
    if len(masks) == calls + 1:
        masks.pop()
        raw_values.pop()
    if len(masks) != calls or calls > budget:
        raise RuntimeError(
            f"official SVARM+ trace disagrees with its budget ledger: "
            f"charged={calls}, traced={len(masks)}"
        )
    return (
        dict(zip(table.owner_ids, map(float, values), strict=True)),
        tuple(masks),
        tuple(raw_values),
        calls,
    )


def run_slope_calibrated_svarm_plus(
    high: CoalitionGameTable,
    low: CoalitionGameTable,
    *,
    budget: int,
    seed: int,
    config: SlopeCalibratedConfig,
    official_repo: str | Path,
    beta_mode: str = "learned",
) -> ValuationOutput:
    """Replace SVARM+'s direct output by one calibrated low-fidelity correction."""

    if high.owner_ids != low.owner_ids or set(high.values) != set(low.values):
        raise ValueError("high and low games must have identical owners and masks")
    if beta_mode not in {"zero", "one", "learned", "confidence"}:
        raise ValueError("beta_mode must be zero, one, learned, or confidence")
    high_scores, high_masks, high_values, calls = _official_plus_trace(
        high, budget=budget, seed=seed, official_repo=official_repo
    )
    low_scores, low_masks, low_values, low_calls = _official_plus_trace(
        low, budget=budget, seed=seed, official_repo=official_repo
    )
    if high_masks != low_masks or calls != low_calls:
        raise RuntimeError("official SVARM+ high/low sample plans diverged")
    exact_low = evaluate_sota("exact_table", low, budget=len(low.values), seed=0).scores
    if beta_mode == "zero":
        beta, observations = 0.0, 0
    elif beta_mode == "one":
        beta, observations = 1.0, 0
    elif beta_mode == "learned":
        beta, observations = _coalition_value_slope(
            high_values,
            low_values,
            high_masks,
            ridge_relative=config.ridge_relative,
        )
    else:
        beta, observations, raw_beta, beta_standard_error, shrinkage_active = (
            _coalition_value_confidence_slope(
                high_values,
                low_values,
                high_masks,
                ridge_relative=config.ridge_relative,
            )
        )
    scores = {
        owner: float(high_scores[owner] - beta * (low_scores[owner] - exact_low[owner]))
        for owner in high.owner_ids
    }
    return ValuationOutput(
        scores,
        diagnostics={
            "backend": "slope_calibrated_official_stratified_svarm_plus",
            "base_estimator": "official_stratified_svarm_plus",
            "source_commit": _OFFICIAL_SVARM_COMMIT,
            "sample_plans_coupled": True,
            "beta_mode": beta_mode,
            "beta": float(beta),
            "raw_beta": float(raw_beta) if beta_mode == "confidence" else float(beta),
            "beta_standard_error": (
                float(beta_standard_error) if beta_mode == "confidence" else None
            ),
            "confidence_shrinkage_active": (
                bool(shrinkage_active) if beta_mode == "confidence" else None
            ),
            "ridge_relative": config.ridge_relative,
            "slope_records": (
                {
                    "beta": float(beta),
                    "training_observations": observations,
                    "centering": "coalition_size_and_owner_fixed_effects",
                },
            ),
            "paired_high_calls": calls,
            "sampled_high_mask_sequence": high_masks,
            "low_table_calls": len(low.values),
            "accounting": "cached",
            "realized_equivalent_cost": calls,
            "coefficient_fit": (
                "same_sample_confidence_shrinkage"
                if beta_mode == "confidence"
                else "same_sample_plugin"
            ),
        },
        utility_calls=calls,
    )


def run_influence_calibrated_leverage_shap(
    high: CoalitionGameTable,
    low: CoalitionGameTable,
    *,
    budget: int,
    seed: int,
    beta_mode: str = "influence_safe",
    z_value: float = 1.96,
    low_anchor: Mapping[str, float] | None = None,
    low_anchor_calls: int | None = None,
    low_anchor_seed: int | None = None,
) -> ValuationOutput:
    """Correct LeverageSHAP with a coefficient aligned to Shapley influences."""

    if high.owner_ids != low.owner_ids or set(high.values) != set(low.values):
        raise ValueError("high and low games must have identical owners and masks")
    if beta_mode not in {"influence_raw", "influence_safe", "provider"}:
        raise ValueError(
            "beta_mode must be influence_raw, influence_safe, or provider"
        )
    high_scores, high_masks, high_values, calls = _leverage_trace(
        high, budget=budget, seed=seed
    )
    low_scores, low_masks, low_values, low_calls = _leverage_trace(
        low, budget=budget, seed=seed
    )
    if high_masks != low_masks or calls != low_calls:
        raise RuntimeError("LeverageSHAP high/low sample plans diverged")
    calibration = influence_calibrated_slope(
        high_values,
        low_values,
        high_masks,
        owner_count=len(high.owner_ids),
        z_value=z_value,
    )
    if low_anchor is None:
        if low_anchor_calls is not None or low_anchor_seed is not None:
            raise ValueError("low anchor metadata requires an approximate low anchor")
        anchor = evaluate_sota(
            "exact_table", low, budget=len(low.values), seed=0
        ).scores
        anchor_mode = "exact_table"
        anchor_calls = len(low.values)
    else:
        if set(low_anchor) != set(low.owner_ids):
            raise ValueError("low anchor must contain exactly one value per owner")
        if low_anchor_calls is None or low_anchor_calls <= 0:
            raise ValueError("approximate low anchor requires positive low_anchor_calls")
        if low_anchor_seed is None or low_anchor_seed == seed:
            raise ValueError("approximate low anchor must use an independent seed")
        anchor = {owner: float(low_anchor[owner]) for owner in low.owner_ids}
        if not all(math.isfinite(value) for value in anchor.values()):
            raise ValueError("low anchor values must be finite")
        anchor_mode = "independent_approximate"
        anchor_calls = int(low_anchor_calls)
    if beta_mode == "provider":
        coefficients = dict(
            zip(high.owner_ids, calibration.provider_betas, strict=True)
        )
    else:
        beta = (
            calibration.raw_beta
            if beta_mode == "influence_raw"
            else calibration.safe_beta
        )
        coefficients = {owner: beta for owner in high.owner_ids}
    scores = {
        owner: float(
            high_scores[owner]
            - coefficients[owner] * (low_scores[owner] - anchor[owner])
        )
        for owner in high.owner_ids
    }
    return ValuationOutput(
        scores,
        diagnostics={
            "backend": "influence_calibrated_shapiq_leverage_shap",
            "backend_version": "1.7.0",
            "base_estimator": "shapiq_leverage_shap",
            "sample_plans_coupled": True,
            "beta_mode": beta_mode,
            "beta": (
                list(map(float, calibration.provider_betas))
                if beta_mode == "provider"
                else float(coefficients[high.owner_ids[0]])
            ),
            "raw_beta": float(calibration.raw_beta),
            "safe_beta": float(calibration.safe_beta),
            "beta_interval": [float(calibration.lower), float(calibration.upper)],
            "beta_standard_error": float(calibration.standard_error),
            "influence_block_count": int(calibration.block_count),
            "influence_degenerate": bool(calibration.degenerate),
            "provider_betas": list(map(float, calibration.provider_betas)),
            "coefficient_source": "paired_delete_block_influence",
            "uses_exact_high_target": False,
            "sampled_high_mask_sequence": high_masks,
            "paired_high_calls": calls,
            "low_table_calls": anchor_calls,
            "low_anchor_mode": anchor_mode,
            "low_anchor_calls": anchor_calls,
            "low_anchor_seed": low_anchor_seed,
            "accounting": "cached",
            "realized_equivalent_cost": calls,
        },
        utility_calls=calls,
    )


def run_influence_calibrated_oracle(
    owner_ids: Sequence[str],
    high_value: Callable[[int], float],
    low_value: Callable[[int], float],
    *,
    budget: int,
    seed: int,
    low_anchor: Mapping[str, float],
    low_anchor_calls: int,
    low_anchor_seed: int,
    beta_mode: str = "influence_safe",
    z_value: float = 1.96,
) -> ValuationOutput:
    """Run ICR against on-demand utility oracles without materializing a table."""

    owners = tuple(map(str, owner_ids))
    if len(owners) < 2 or len(set(owners)) != len(owners):
        raise ValueError("owner_ids must contain at least two unique owners")
    if beta_mode not in {"influence_raw", "influence_safe", "provider"}:
        raise ValueError(
            "beta_mode must be influence_raw, influence_safe, or provider"
        )
    if set(low_anchor) != set(owners):
        raise ValueError("low anchor must contain exactly one value per owner")
    if low_anchor_calls <= 0:
        raise ValueError("approximate low anchor requires positive low_anchor_calls")
    if low_anchor_seed == seed:
        raise ValueError("approximate low anchor must use an independent seed")
    anchor = {owner: float(low_anchor[owner]) for owner in owners}
    if not all(math.isfinite(value) for value in anchor.values()):
        raise ValueError("low anchor values must be finite")

    high_scores, high_masks, high_values, calls = _leverage_trace_oracle(
        owners, high_value, budget=budget, seed=seed
    )
    low_scores, low_masks, low_values, low_calls = _leverage_trace_oracle(
        owners, low_value, budget=budget, seed=seed
    )
    if high_masks != low_masks or calls != low_calls:
        raise RuntimeError("LeverageSHAP high/low sample plans diverged")
    calibration = influence_calibrated_slope(
        high_values,
        low_values,
        high_masks,
        owner_count=len(owners),
        z_value=z_value,
    )
    if beta_mode == "provider":
        coefficients = dict(zip(owners, calibration.provider_betas, strict=True))
    else:
        beta = (
            calibration.raw_beta
            if beta_mode == "influence_raw"
            else calibration.safe_beta
        )
        coefficients = {owner: beta for owner in owners}
    scores = {
        owner: float(
            high_scores[owner]
            - coefficients[owner] * (low_scores[owner] - anchor[owner])
        )
        for owner in owners
    }
    return ValuationOutput(
        scores,
        diagnostics={
            "backend": "influence_calibrated_oracle_leverage_shap",
            "backend_version": "1.7.0",
            "base_estimator": "shapiq_leverage_shap",
            "table_free": True,
            "sample_plans_coupled": True,
            "beta_mode": beta_mode,
            "beta": (
                list(map(float, calibration.provider_betas))
                if beta_mode == "provider"
                else float(coefficients[owners[0]])
            ),
            "raw_beta": float(calibration.raw_beta),
            "safe_beta": float(calibration.safe_beta),
            "beta_interval": [float(calibration.lower), float(calibration.upper)],
            "beta_standard_error": float(calibration.standard_error),
            "influence_block_count": int(calibration.block_count),
            "influence_degenerate": bool(calibration.degenerate),
            "provider_betas": list(map(float, calibration.provider_betas)),
            "coefficient_source": "paired_delete_block_influence",
            "uses_exact_high_target": False,
            "sampled_high_mask_sequence": high_masks,
            "paired_high_calls": calls,
            "low_anchor_mode": "independent_approximate",
            "low_anchor_calls": int(low_anchor_calls),
            "low_anchor_seed": int(low_anchor_seed),
            "accounting": "on_demand_oracle",
            "realized_equivalent_cost": calls,
        },
        utility_calls=calls,
    )


def estimate_leverage_oracle(
    owner_ids: Sequence[str],
    value: Callable[[int], float],
    *,
    budget: int,
    seed: int,
) -> ValuationOutput:
    """Estimate Shapley values from an on-demand utility oracle."""

    scores, masks, _, calls = _leverage_trace_oracle(
        owner_ids, value, budget=budget, seed=seed
    )
    return ValuationOutput(
        scores,
        diagnostics={
            "backend": "oracle_shapiq_leverage_shap",
            "backend_version": "1.7.0",
            "table_free": True,
            "sampled_mask_sequence": masks,
            "logical_calls": calls,
        },
        utility_calls=calls,
    )


def _leverage_trace(
    table: CoalitionGameTable,
    *,
    budget: int,
    seed: int,
) -> tuple[dict[str, float], tuple[int, ...], tuple[float, ...], int]:
    return _leverage_trace_oracle(
        table.owner_ids, table.values.__getitem__, budget=budget, seed=seed
    )


def _leverage_trace_oracle(
    owner_ids: Sequence[str],
    value: Callable[[int], float],
    *,
    budget: int,
    seed: int,
) -> tuple[dict[str, float], tuple[int, ...], tuple[float, ...], int]:
    try:
        import shapiq
    except ImportError as exc:
        raise OptionalMethodUnavailable(
            "optional_dependency_missing:shapiq==1.7.0"
        ) from exc
    if shapiq.__version__ != "1.7.0":
        raise OptionalMethodUnavailable(
            f"unsupported_dependency_version:shapiq=={shapiq.__version__}"
        )
    if not isinstance(budget, int) or budget < 2:
        raise ValueError("budget must be an integer of at least two coalition calls")

    owners = tuple(map(str, owner_ids))
    if len(owners) < 2 or len(set(owners)) != len(owners):
        raise ValueError("owner_ids must contain at least two unique owners")
    n_players = len(owners)
    masks: list[int] = []
    raw_values: list[float] = []

    def game(coalitions: np.ndarray) -> np.ndarray:
        matrix = np.atleast_2d(np.asarray(coalitions, dtype=bool))
        if matrix.shape[1] != n_players:
            raise ValueError("LeverageSHAP supplied a coalition with wrong width")
        batch_masks = [
            sum((1 << index) for index, included in enumerate(row) if included)
            for row in matrix
        ]
        if len(masks) + len(batch_masks) > budget:
            raise RuntimeError("LeverageSHAP exceeded declared coalition budget")
        batch_values = [float(value(mask)) for mask in batch_masks]
        masks.extend(batch_masks)
        raw_values.extend(batch_values)
        return np.asarray(batch_values, dtype=float)

    approximator = shapiq.LeverageSHAP(n=n_players, random_state=seed)
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore", message="Not all budget is required due to the border-trick"
        )
        result = approximator.approximate(budget=budget, game=game)
    values = np.asarray(result.get_n_order_values(1), dtype=float)
    if values.shape != (n_players,) or not np.all(np.isfinite(values)):
        raise RuntimeError("LeverageSHAP returned invalid first-order values")
    return (
        dict(zip(owners, map(float, values), strict=True)),
        tuple(masks),
        tuple(raw_values),
        len(masks),
    )


def run_slope_calibrated_leverage_shap(
    high: CoalitionGameTable,
    low: CoalitionGameTable,
    *,
    budget: int,
    seed: int,
    config: SlopeCalibratedConfig,
    beta_mode: str = "learned",
) -> ValuationOutput:
    """Wrap LeverageSHAP with the same exact-low calibrated residual module."""

    if high.owner_ids != low.owner_ids or set(high.values) != set(low.values):
        raise ValueError("high and low games must have identical owners and masks")
    if beta_mode not in {"zero", "one", "learned", "confidence"}:
        raise ValueError("beta_mode must be zero, one, learned, or confidence")
    high_scores, high_masks, high_values, calls = _leverage_trace(
        high, budget=budget, seed=seed
    )
    low_scores, low_masks, low_values, low_calls = _leverage_trace(
        low, budget=budget, seed=seed
    )
    if high_masks != low_masks or calls != low_calls:
        raise RuntimeError("LeverageSHAP high/low sample plans diverged")
    exact_low = evaluate_sota("exact_table", low, budget=len(low.values), seed=0).scores
    if beta_mode == "zero":
        beta, observations = 0.0, 0
    elif beta_mode == "one":
        beta, observations = 1.0, 0
    elif beta_mode == "learned":
        beta, observations = _coalition_value_slope(
            high_values,
            low_values,
            high_masks,
            ridge_relative=config.ridge_relative,
        )
    else:
        beta, observations, raw_beta, beta_standard_error, shrinkage_active = (
            _coalition_value_confidence_slope(
                high_values,
                low_values,
                high_masks,
                ridge_relative=config.ridge_relative,
            )
        )
    scores = {
        owner: float(high_scores[owner] - beta * (low_scores[owner] - exact_low[owner]))
        for owner in high.owner_ids
    }
    return ValuationOutput(
        scores,
        diagnostics={
            "backend": "slope_calibrated_shapiq_leverage_shap",
            "backend_version": "1.7.0",
            "base_estimator": "shapiq_leverage_shap",
            "sample_plans_coupled": True,
            "beta_mode": beta_mode,
            "beta": float(beta),
            "raw_beta": float(raw_beta) if beta_mode == "confidence" else float(beta),
            "beta_standard_error": (
                float(beta_standard_error) if beta_mode == "confidence" else None
            ),
            "confidence_shrinkage_active": (
                bool(shrinkage_active) if beta_mode == "confidence" else None
            ),
            "ridge_relative": config.ridge_relative,
            "slope_records": (
                {
                    "beta": float(beta),
                    "training_observations": observations,
                    "centering": "coalition_size_and_owner_fixed_effects",
                },
            ),
            "paired_high_calls": calls,
            "sampled_high_mask_sequence": high_masks,
            "low_table_calls": len(low.values),
            "accounting": "cached",
            "realized_equivalent_cost": calls,
            "coefficient_fit": (
                "same_sample_confidence_shrinkage"
                if beta_mode == "confidence"
                else "same_sample_plugin"
            ),
        },
        utility_calls=calls,
    )


def run_split_calibrated_leverage_shap(
    high: CoalitionGameTable,
    low: CoalitionGameTable,
    *,
    budget: int,
    seed: int,
    config: SlopeCalibratedConfig,
    calibration_fraction: float = 0.25,
) -> ValuationOutput:
    """Fit the slope on held-out masks at the same total high-call budget.

    The base LeverageSHAP estimate receives the non-calibration share of the
    budget.  Any calls left unused by its border trick are reassigned to the
    calibration set, whose masks are sampled without replacement and are
    disjoint from every estimation mask.  Exact high-game Shapley values are
    never evaluated or used to choose the coefficient.
    """

    if high.owner_ids != low.owner_ids or set(high.values) != set(low.values):
        raise ValueError("high and low games must have identical owners and masks")
    if not isinstance(budget, int) or budget < 4 or budget > len(high.values):
        raise ValueError("budget must be an integer in [4, number of coalitions]")
    if not np.isfinite(calibration_fraction) or not 0.0 < calibration_fraction < 1.0:
        raise ValueError("calibration_fraction must lie strictly between zero and one")
    calibration_target = max(2, int(np.floor(budget * calibration_fraction)))
    estimation_budget = budget - calibration_target
    if estimation_budget < 2:
        raise ValueError("calibration_fraction leaves fewer than two estimation calls")

    high_scores, high_masks, _, estimation_calls = _leverage_trace(
        high, budget=estimation_budget, seed=seed
    )
    low_scores, low_masks, _, low_estimation_calls = _leverage_trace(
        low, budget=estimation_budget, seed=seed
    )
    if high_masks != low_masks or estimation_calls != low_estimation_calls:
        raise RuntimeError("LeverageSHAP high/low estimation plans diverged")

    calibration_calls = budget - estimation_calls
    available_masks = np.asarray(
        sorted(set(high.values) - set(high_masks)), dtype=np.int64
    )
    if calibration_calls > len(available_masks):
        raise ValueError("budget leaves too few masks for disjoint calibration")
    generator = np.random.default_rng(seed ^ 0x5EEDC0DE)
    selected = generator.choice(
        available_masks, size=calibration_calls, replace=False
    )
    calibration_masks = tuple(sorted(map(int, selected)))
    high_calibration = tuple(float(high.values[mask]) for mask in calibration_masks)
    low_calibration = tuple(float(low.values[mask]) for mask in calibration_masks)
    beta, observations = _coalition_value_slope(
        high_calibration,
        low_calibration,
        calibration_masks,
        ridge_relative=config.ridge_relative,
    )

    exact_low = evaluate_sota("exact_table", low, budget=len(low.values), seed=0).scores
    scores = {
        owner: float(high_scores[owner] - beta * (low_scores[owner] - exact_low[owner]))
        for owner in high.owner_ids
    }
    return ValuationOutput(
        scores,
        diagnostics={
            "backend": "split_calibrated_shapiq_leverage_shap",
            "backend_version": "1.7.0",
            "base_estimator": "shapiq_leverage_shap",
            "sample_plans_coupled": True,
            "beta_mode": "heldout",
            "beta": float(beta),
            "ridge_relative": config.ridge_relative,
            "calibration_fraction": float(calibration_fraction),
            "calibration_target_calls": calibration_target,
            "calibration_high_calls": calibration_calls,
            "estimation_high_calls": estimation_calls,
            "calibration_masks": calibration_masks,
            "estimation_masks": high_masks,
            "masks_disjoint": set(calibration_masks).isdisjoint(high_masks),
            "slope_records": (
                {
                    "beta": float(beta),
                    "training_observations": observations,
                    "centering": "coalition_size_and_owner_fixed_effects",
                },
            ),
            "paired_high_calls": budget,
            "low_table_calls": len(low.values),
            "accounting": "cached",
            "realized_equivalent_cost": budget,
            "coefficient_fit": "heldout_disjoint_masks",
        },
        utility_calls=budget,
    )


__all__ = [
    "InfluenceCalibration",
    "influence_calibrated_slope",
    "leverage_scores_from_trace",
    "run_influence_calibrated_leverage_shap",
    "run_slope_calibrated_leverage_shap",
    "run_split_calibrated_leverage_shap",
    "run_slope_calibrated_svarm_plus",
]
