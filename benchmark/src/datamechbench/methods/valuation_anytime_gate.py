"""Anytime-valid certification for anchor-aware Shapley corrections."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

import numpy as np


@dataclass(frozen=True)
class AnytimeContrastSelection:
    """First nonzero grid decision certified by contrast e-processes."""

    beta: float
    stopping_pair: int | None
    per_game_log_e_values: tuple[float, ...]
    log_rejection_threshold: float
    simultaneous_confidence: float
    candidate_count: int
    abstained: bool
    preferred_beta_clipped: bool
    bound_type: str = "mixture_e_process"


@dataclass(frozen=True)
class AnytimeRoutedSelection:
    """Precommitted coefficient certified with source-wise early freezing."""

    beta: float
    proposed_beta: float
    per_game_stopping_pairs: tuple[int | None, ...]
    per_game_log_e_values: tuple[float, ...]
    total_source_pairs: int
    synchronous_source_pairs: int
    cost_ratio_to_synchronous: float
    log_rejection_threshold: float
    simultaneous_confidence: float
    abstained: bool
    bound_type: str = "routed_mixture_e_process"


def _log_mean_exp(values: np.ndarray, axis: int) -> np.ndarray:
    maximum = np.max(values, axis=axis, keepdims=True)
    return np.squeeze(
        maximum + np.log(np.mean(np.exp(values - maximum), axis=axis, keepdims=True)),
        axis=axis,
    )


def anytime_contrast_grid_beta(
    contrast_streams: Sequence[Sequence[Sequence[float]]],
    *,
    candidate_betas: Sequence[float],
    contrast_range_bounds: Sequence[Sequence[float]],
    confidence: float = 0.95,
    preferred_beta: float | None = None,
    eta_grid: Sequence[float] = (0.25, 0.5, 1.0, 2.0, 4.0),
    min_pairs: int = 1,
) -> AnytimeContrastSelection:
    """Certify a grid coefficient at an arbitrary data-dependent stopping time.

    ``contrast_streams[g, t, j]`` is the paired scalar harm contrast for source
    game ``g``, pair ``t``, and coefficient ``candidate_betas[j]``.  Under the
    harmful null ``E[X] >= 0`` and range width ``r``, each process
    ``exp(-lambda * sum(X) - t * lambda**2 * r**2 / 8)`` is a nonnegative
    supermartingale.  A finite mixture over ``eta=lambda*r`` remains one.
    Ville's inequality and a union bound over every nonzero game--coefficient
    cell therefore make the returned first crossing valid under optional
    stopping and post-selection.  The zero coefficient is safe by identity.
    """

    streams = np.asarray(contrast_streams, dtype=float)
    candidates = np.asarray(candidate_betas, dtype=float)
    ranges = np.asarray(contrast_range_bounds, dtype=float)
    etas = np.asarray(eta_grid, dtype=float)
    if streams.ndim != 3 or candidates.ndim != 1:
        raise ValueError("contrast streams and candidates must have compatible shape")
    games, pairs, candidate_count = streams.shape
    if games == 0 or pairs == 0 or candidate_count != len(candidates):
        raise ValueError("contrast streams and candidates must have compatible shape")
    if ranges.shape != (games, candidate_count):
        raise ValueError("contrast range bounds must match stream shape")
    if not np.all(np.isfinite(streams)) or not np.all(np.isfinite(candidates)):
        raise ValueError("contrasts and candidates must be finite")
    if not np.all(np.isfinite(ranges)) or np.any(ranges < 0.0):
        raise ValueError("range bounds must be finite and nonnegative")
    if not math.isfinite(confidence) or not 0.0 < confidence < 1.0:
        raise ValueError("confidence must lie strictly between zero and one")
    if min_pairs < 1 or min_pairs > pairs:
        raise ValueError("min_pairs must lie within the observed stream")
    if etas.ndim != 1 or len(etas) == 0 or np.any(~np.isfinite(etas)) or np.any(etas <= 0.0):
        raise ValueError("eta_grid must contain positive finite values")
    zero = np.flatnonzero(np.isclose(candidates, 0.0, atol=1e-15, rtol=0.0))
    if len(zero) != 1:
        raise ValueError("candidate_betas must contain zero exactly once")
    nonzero = np.flatnonzero(~np.isclose(candidates, 0.0, atol=1e-15, rtol=0.0))
    if np.any(ranges[:, nonzero] <= 0.0):
        raise ValueError("nonzero candidates require positive range bounds")
    if preferred_beta is None:
        preferred_beta = float(candidates[np.argmax(np.abs(candidates))])
    if not math.isfinite(preferred_beta):
        raise ValueError("preferred_beta must be finite")

    cell_count = games * max(1, len(nonzero))
    log_threshold = math.log(cell_count / (1.0 - confidence))
    cumulative = np.cumsum(streams, axis=1)
    selected_index = int(zero[0])
    selected_time: int | None = None
    selected_logs = np.zeros(games, dtype=float)

    for time in range(min_pairs, pairs + 1):
        safe = [int(zero[0])]
        log_e_by_candidate: dict[int, np.ndarray] = {}
        for index in nonzero:
            range_vector = ranges[:, index]
            lambdas = etas[None, :] / range_vector[:, None]
            log_components = (
                -lambdas * cumulative[:, time - 1, index, None]
                - time * (lambdas * range_vector[:, None]) ** 2 / 8.0
            )
            log_e = _log_mean_exp(log_components, axis=1)
            log_e_by_candidate[int(index)] = log_e
            if np.all(log_e >= log_threshold):
                safe.append(int(index))
        chosen = min(
            safe,
            key=lambda index: (
                abs(float(candidates[index]) - preferred_beta),
                abs(float(candidates[index])),
            ),
        )
        if chosen != int(zero[0]):
            selected_index = chosen
            selected_time = time
            selected_logs = log_e_by_candidate[chosen]
            break

    beta = float(candidates[selected_index])
    return AnytimeContrastSelection(
        beta=beta,
        stopping_pair=selected_time,
        per_game_log_e_values=tuple(map(float, selected_logs)),
        log_rejection_threshold=float(log_threshold),
        simultaneous_confidence=float(confidence),
        candidate_count=int(candidate_count),
        abstained=selected_time is None,
        preferred_beta_clipped=not math.isclose(beta, preferred_beta, abs_tol=1e-12),
    )


def anytime_routed_contrast_beta(
    contrast_streams: Sequence[Sequence[float]],
    *,
    beta: float,
    contrast_range_bounds: Sequence[float],
    confidence: float = 0.95,
    eta_grid: Sequence[float] = (0.25, 0.5, 1.0, 2.0, 4.0),
    min_pairs: int = 1,
) -> AnytimeRoutedSelection:
    """Certify one precommitted coefficient while freezing crossed sources.

    The coefficient must be fixed independently of ``contrast_streams``.  Each
    row is the successive harm-contrast stream for one source market.  Once a
    source e-process crosses its simultaneous threshold at or after
    ``min_pairs``, that source is frozen and incurs no further pair cost.
    Sampling unresolved sources in any
    predictable order gives the same local first-crossing times represented by
    this rectangular offline input.  The guarantee is time-uniform, because a
    stopped nonnegative supermartingale remains a nonnegative supermartingale.
    """

    streams = np.asarray(contrast_streams, dtype=float)
    ranges = np.asarray(contrast_range_bounds, dtype=float)
    etas = np.asarray(eta_grid, dtype=float)
    if streams.ndim != 2 or streams.shape[0] == 0 or streams.shape[1] == 0:
        raise ValueError("contrast streams must have shape (sources, pairs)")
    games, pairs = streams.shape
    if ranges.shape != (games,):
        raise ValueError("contrast range bounds must match the source count")
    if not np.all(np.isfinite(streams)) or not math.isfinite(beta):
        raise ValueError("contrasts and beta must be finite")
    if math.isclose(beta, 0.0, abs_tol=1e-15, rel_tol=0.0):
        raise ValueError("beta must be nonzero; direct estimation needs no audit")
    if not np.all(np.isfinite(ranges)) or np.any(ranges <= 0.0):
        raise ValueError("contrast range bounds must be positive and finite")
    if not math.isfinite(confidence) or not 0.0 < confidence < 1.0:
        raise ValueError("confidence must lie strictly between zero and one")
    if min_pairs < 1 or min_pairs > pairs:
        raise ValueError("min_pairs must lie within the observed stream")
    if etas.ndim != 1 or len(etas) == 0 or np.any(~np.isfinite(etas)) or np.any(etas <= 0.0):
        raise ValueError("eta_grid must contain positive finite values")

    log_threshold = math.log(games / (1.0 - confidence))
    stopping_pairs: list[int | None] = []
    final_logs: list[float] = []
    used_pairs: list[int] = []
    for game in range(games):
        cumulative = np.cumsum(streams[game])
        lambdas = etas / ranges[game]
        crossing: int | None = None
        final_log_e = 0.0
        for time in range(min_pairs, pairs + 1):
            components = (
                -lambdas * cumulative[time - 1]
                - time * (lambdas * ranges[game]) ** 2 / 8.0
            )
            final_log_e = float(_log_mean_exp(components, axis=0))
            if final_log_e >= log_threshold:
                crossing = time
                break
        stopping_pairs.append(crossing)
        final_logs.append(final_log_e)
        used_pairs.append(pairs if crossing is None else crossing)

    certified = all(value is not None for value in stopping_pairs)
    synchronous_horizon = max(used_pairs)
    synchronous_source_pairs = games * synchronous_horizon
    total_source_pairs = sum(used_pairs)
    return AnytimeRoutedSelection(
        beta=float(beta if certified else 0.0),
        proposed_beta=float(beta),
        per_game_stopping_pairs=tuple(stopping_pairs),
        per_game_log_e_values=tuple(final_logs),
        total_source_pairs=int(total_source_pairs),
        synchronous_source_pairs=int(synchronous_source_pairs),
        cost_ratio_to_synchronous=float(total_source_pairs / synchronous_source_pairs),
        log_rejection_threshold=float(log_threshold),
        simultaneous_confidence=float(confidence),
        abstained=not certified,
    )


__all__ = [
    "AnytimeContrastSelection",
    "AnytimeRoutedSelection",
    "anytime_contrast_grid_beta",
    "anytime_routed_contrast_beta",
]
