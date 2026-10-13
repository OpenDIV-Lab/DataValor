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


@dataclass(frozen=True)
class RiskEnvelopeSelection:
    """Exact minimizer of a finite normalized excess-risk envelope."""

    beta: float
    worst_normalized_excess: float
    active_indices: tuple[int, ...]
    per_game_normalized_excess: tuple[float, ...]


@dataclass(frozen=True)
class AnchorOrthogonalityAudit:
    """Same-history decomposition of direct and independence-specialized slopes."""

    direct_risk: float
    deployed_cross: float
    deployed_energy: float
    paired_cross: float
    paired_low_energy: float
    anchor_energy: float
    high_anchor_cross: float
    low_anchor_cross: float
    direct_beta: float
    anchor_energy_beta: float
    paired_only_beta: float
    beta_gap: float
    anchor_energy_excess: float


@dataclass(frozen=True)
class DeletionRobustRiskEnvelopeSelection:
    """Risk-envelope selection certified after any one trace deletion."""

    beta: float
    worst_deleted_normalized_excess: float
    deleted_scenarios: tuple[tuple[int, int], ...]
    active_scenarios: tuple[tuple[int, int], ...]
    per_deleted_normalized_excess: tuple[float, ...]
    full_sample_normalized_excess: tuple[float, ...]


@dataclass(frozen=True)
class ConfidenceRiskEnvelopeSelection:
    """Coefficient with a simultaneous asymptotic risk upper certificate."""

    beta: float
    worst_upper_normalized_excess: float
    per_game_upper_normalized_excess: tuple[float, ...]
    simultaneous_confidence: float
    pair_counts: tuple[int, ...]
    abstained: bool
    preferred_beta_clipped: bool
    calibration: str
    critical_value: float
    certificate_geometry: str


@dataclass(frozen=True)
class FiniteSampleContrastSelection:
    """Grid coefficient with a simultaneous finite-sample contrast bound."""

    beta: float
    worst_upper_contrast: float
    per_game_upper_contrast: tuple[float, ...]
    simultaneous_confidence: float
    pair_counts: tuple[int, ...]
    candidate_count: int
    abstained: bool
    preferred_beta_clipped: bool
    bound_type: str = "bernstein_grid"


def finite_sample_contrast_grid_beta(
    high_histories: Sequence[Sequence[Sequence[float]]],
    control_histories: Sequence[Sequence[Sequence[float]]],
    *,
    candidate_betas: Sequence[float],
    contrast_variance_bounds: Sequence[Sequence[float]],
    contrast_range_bounds: Sequence[Sequence[float]],
    confidence: float = 0.95,
    preferred_beta: float | None = None,
) -> FiniteSampleContrastSelection:
    """Certify a data-selected coefficient by finite-sample Bernstein bounds.

    For every predeclared candidate ``beta`` and source game, a disjoint trace
    pair produces the scalar excess-risk contrast
    ``X = D_pair * beta**2 - 2 * C_pair * beta``.  The caller supplies
    deterministic upper bounds on ``Var(X)`` and on the almost-sure range of
    ``X``.  A one-sided Bernstein inequality followed by one union bound over
    all game--candidate cells therefore covers even a coefficient selected
    from the same histories.  Zero must be on the grid and is always exactly
    safe, so an uninformative audit contract causes abstention rather than an
    uncertified correction.
    """

    if len(high_histories) == 0 or len(high_histories) != len(control_histories):
        raise ValueError("high and control histories must have matching non-zero length")
    if not math.isfinite(confidence) or not 0.0 < confidence < 1.0:
        raise ValueError("confidence must lie strictly between zero and one")

    candidates = np.asarray(candidate_betas, dtype=float)
    if candidates.ndim != 1 or len(candidates) == 0 or not np.all(np.isfinite(candidates)):
        raise ValueError("candidate_betas must be a non-empty finite vector")
    if len(np.unique(candidates)) != len(candidates):
        raise ValueError("candidate_betas must be distinct")
    zero_indices = np.flatnonzero(np.isclose(candidates, 0.0, atol=1e-15, rtol=0.0))
    if len(zero_indices) != 1:
        raise ValueError("candidate_betas must include zero exactly once")
    if preferred_beta is not None and not math.isfinite(preferred_beta):
        raise ValueError("preferred_beta must be finite")

    game_count = len(high_histories)
    expected_shape = (game_count, len(candidates))
    variance_bounds = np.asarray(contrast_variance_bounds, dtype=float)
    range_bounds = np.asarray(contrast_range_bounds, dtype=float)
    if variance_bounds.shape != expected_shape or range_bounds.shape != expected_shape:
        raise ValueError(
            "contrast variance and range bounds must have shape "
            f"{expected_shape}"
        )
    if (
        not np.all(np.isfinite(variance_bounds))
        or not np.all(np.isfinite(range_bounds))
        or np.any(variance_bounds < 0.0)
        or np.any(range_bounds < 0.0)
    ):
        raise ValueError("contrast variance and range bounds must be finite and non-negative")

    pair_contrasts: list[np.ndarray] = []
    pair_counts: list[int] = []
    for raw_high, raw_control in zip(high_histories, control_histories, strict=True):
        high = np.asarray(raw_high, dtype=float)
        control = np.asarray(raw_control, dtype=float)
        if high.ndim != 2 or high.shape != control.shape or high.shape[1] < 1:
            raise ValueError("each high/control history pair must have matching 2D shapes")
        if high.shape[0] < 4 or high.shape[0] % 2:
            raise ValueError("each finite-sample history needs at least four, evenly paired traces")
        if not np.all(np.isfinite(high)) or not np.all(np.isfinite(control)):
            raise ValueError("history matrices must be finite")
        delta_high = high[0::2] - high[1::2]
        delta_control = control[0::2] - control[1::2]
        cross = 0.5 * np.mean(delta_high * delta_control, axis=1)
        energy = 0.5 * np.mean(delta_control**2, axis=1)
        pair_contrasts.append(
            energy[:, None] * candidates[None, :] ** 2
            - 2.0 * cross[:, None] * candidates[None, :]
        )
        pair_counts.append(len(cross))

    log_factor = math.log(game_count * len(candidates) / (1.0 - confidence))
    upper = np.empty(expected_shape, dtype=float)
    for game, (contrasts, pairs) in enumerate(
        zip(pair_contrasts, pair_counts, strict=True)
    ):
        upper[game] = (
            contrasts.mean(axis=0)
            + np.sqrt(2.0 * variance_bounds[game] * log_factor / pairs)
            + range_bounds[game] * log_factor / (3.0 * pairs)
        )
    # The direct coefficient has identically zero contrast, irrespective of
    # any loose user-supplied bounds for that grid cell.
    upper[:, zero_indices[0]] = 0.0
    worst_by_candidate = np.max(upper, axis=0)
    safe_indices = np.flatnonzero(worst_by_candidate <= 1e-12)
    target = 0.0 if preferred_beta is None else float(preferred_beta)
    chosen = min(
        safe_indices,
        key=lambda index: (
            abs(float(candidates[index]) - target),
            abs(float(candidates[index])),
            float(candidates[index]),
        ),
    )
    beta = float(candidates[chosen])
    return FiniteSampleContrastSelection(
        beta=beta,
        worst_upper_contrast=float(worst_by_candidate[chosen]),
        per_game_upper_contrast=tuple(map(float, upper[:, chosen])),
        simultaneous_confidence=confidence,
        pair_counts=tuple(pair_counts),
        candidate_count=len(candidates),
        abstained=chosen == zero_indices[0],
        preferred_beta_clipped=(
            preferred_beta is not None and not math.isclose(beta, target, abs_tol=1e-15)
        ),
    )


def contrast_range_bounds_from_output_spans(
    *,
    candidate_betas: Sequence[float],
    high_coordinate_spans: Sequence[Sequence[float]],
    control_coordinate_spans: Sequence[Sequence[float]],
) -> tuple[tuple[float, ...], ...]:
    """Derive valid contrast ranges from enforceable output intervals.

    ``high_coordinate_spans[g][i]`` and ``control_coordinate_spans[g][i]``
    are widths of intervals that contain every high and deployed-control trace
    at coordinate ``i`` of game ``g``.  Games may have different dimensions.
    The returned game--coefficient bounds are deterministic, so they can be
    passed directly to :func:`finite_sample_empirical_bernstein_grid_beta`.
    """

    candidates = np.asarray(candidate_betas, dtype=float)
    if candidates.ndim != 1 or len(candidates) == 0 or not np.all(np.isfinite(candidates)):
        raise ValueError("candidate_betas must be a non-empty finite vector")
    if len(high_coordinate_spans) == 0 or len(high_coordinate_spans) != len(
        control_coordinate_spans
    ):
        raise ValueError("high and control span collections must have matching non-zero length")

    result = []
    for raw_high, raw_control in zip(
        high_coordinate_spans, control_coordinate_spans, strict=True
    ):
        high = np.asarray(raw_high, dtype=float)
        control = np.asarray(raw_control, dtype=float)
        if high.ndim != 1 or high.shape != control.shape or len(high) == 0:
            raise ValueError("each high/control span pair must have matching non-empty vectors")
        if (
            not np.all(np.isfinite(high))
            or not np.all(np.isfinite(control))
            or np.any(high < 0.0)
            or np.any(control < 0.0)
        ):
            raise ValueError("coordinate spans must be finite and non-negative")
        dimension = len(high)
        control_square = float(np.sum(control**2))
        cross_rectangle = float(np.sum(high * control))
        bounds = (
            candidates**2 * control_square / (2.0 * dimension)
            + 2.0 * np.abs(candidates) * cross_rectangle / dimension
        )
        result.append(tuple(map(float, bounds)))
    return tuple(result)


def finite_sample_empirical_bernstein_grid_beta(
    high_histories: Sequence[Sequence[Sequence[float]]],
    control_histories: Sequence[Sequence[Sequence[float]]],
    *,
    candidate_betas: Sequence[float],
    contrast_range_bounds: Sequence[Sequence[float]],
    confidence: float = 0.95,
    preferred_beta: float | None = None,
) -> FiniteSampleContrastSelection:
    """Certify a grid coefficient without a population-variance oracle.

    The only audit contract is a deterministic almost-sure range bound for
    each game--coefficient contrast.  Sample variances are inserted into the
    finite-sample empirical-Bernstein inequality and one union bound covers
    the complete predeclared grid.  Consequently the preferred coefficient
    may be learned from these same histories.  A platform can enforce the
    range contract with bounded estimator outputs or a declared payout cap;
    zero remains an exact fallback.
    """

    if len(high_histories) == 0 or len(high_histories) != len(control_histories):
        raise ValueError("high and control histories must have matching non-zero length")
    if not math.isfinite(confidence) or not 0.0 < confidence < 1.0:
        raise ValueError("confidence must lie strictly between zero and one")

    candidates = np.asarray(candidate_betas, dtype=float)
    if candidates.ndim != 1 or len(candidates) == 0 or not np.all(np.isfinite(candidates)):
        raise ValueError("candidate_betas must be a non-empty finite vector")
    if len(np.unique(candidates)) != len(candidates):
        raise ValueError("candidate_betas must be distinct")
    zero_indices = np.flatnonzero(np.isclose(candidates, 0.0, atol=1e-15, rtol=0.0))
    if len(zero_indices) != 1:
        raise ValueError("candidate_betas must include zero exactly once")
    if preferred_beta is not None and not math.isfinite(preferred_beta):
        raise ValueError("preferred_beta must be finite")

    expected_shape = (len(high_histories), len(candidates))
    range_bounds = np.asarray(contrast_range_bounds, dtype=float)
    if range_bounds.shape != expected_shape:
        raise ValueError(f"contrast range bounds must have shape {expected_shape}")
    if not np.all(np.isfinite(range_bounds)) or np.any(range_bounds < 0.0):
        raise ValueError("contrast range bounds must be finite and non-negative")

    pair_contrasts: list[np.ndarray] = []
    pair_counts: list[int] = []
    for raw_high, raw_control in zip(high_histories, control_histories, strict=True):
        high = np.asarray(raw_high, dtype=float)
        control = np.asarray(raw_control, dtype=float)
        if high.ndim != 2 or high.shape != control.shape or high.shape[1] < 1:
            raise ValueError("each high/control history pair must have matching 2D shapes")
        if high.shape[0] < 4 or high.shape[0] % 2:
            raise ValueError("each finite-sample history needs at least four, evenly paired traces")
        if not np.all(np.isfinite(high)) or not np.all(np.isfinite(control)):
            raise ValueError("history matrices must be finite")
        delta_high = high[0::2] - high[1::2]
        delta_control = control[0::2] - control[1::2]
        cross = 0.5 * np.mean(delta_high * delta_control, axis=1)
        energy = 0.5 * np.mean(delta_control**2, axis=1)
        pair_contrasts.append(
            energy[:, None] * candidates[None, :] ** 2
            - 2.0 * cross[:, None] * candidates[None, :]
        )
        pair_counts.append(len(cross))

    log_factor = math.log(
        2.0 * len(high_histories) * len(candidates) / (1.0 - confidence)
    )
    upper = np.empty(expected_shape, dtype=float)
    for game, (contrasts, pairs) in enumerate(
        zip(pair_contrasts, pair_counts, strict=True)
    ):
        sample_variance = np.var(contrasts, axis=0, ddof=1)
        upper[game] = (
            contrasts.mean(axis=0)
            + np.sqrt(2.0 * sample_variance * log_factor / pairs)
            + 7.0 * range_bounds[game] * log_factor / (3.0 * (pairs - 1))
        )
    upper[:, zero_indices[0]] = 0.0
    worst_by_candidate = np.max(upper, axis=0)
    safe_indices = np.flatnonzero(worst_by_candidate <= 1e-12)
    target = 0.0 if preferred_beta is None else float(preferred_beta)
    chosen = min(
        safe_indices,
        key=lambda index: (
            abs(float(candidates[index]) - target),
            abs(float(candidates[index])),
            float(candidates[index]),
        ),
    )
    beta = float(candidates[chosen])
    return FiniteSampleContrastSelection(
        beta=beta,
        worst_upper_contrast=float(worst_by_candidate[chosen]),
        per_game_upper_contrast=tuple(map(float, upper[:, chosen])),
        simultaneous_confidence=confidence,
        pair_counts=tuple(pair_counts),
        candidate_count=len(candidates),
        abstained=chosen == zero_indices[0],
        preferred_beta_clipped=(
            preferred_beta is not None and not math.isclose(beta, target, abs_tol=1e-15)
        ),
        bound_type="empirical_bernstein_grid",
    )


def finite_sample_empirical_bernstein_fixed_beta(
    high_histories: Sequence[Sequence[Sequence[float]]],
    control_histories: Sequence[Sequence[Sequence[float]]],
    *,
    beta: float,
    contrast_range_bounds: Sequence[float],
    confidence: float = 0.95,
) -> FiniteSampleContrastSelection:
    """Certify one independently fixed coefficient with finite-sample bounds.

    The coefficient and deterministic range contract must be frozen before
    these certification histories are observed.  Unlike grid selection, the
    union bound therefore covers only the source games.  If any source upper
    bound is positive, the method returns the exact direct-estimation fallback
    ``beta=0``.
    """

    if len(high_histories) == 0 or len(high_histories) != len(control_histories):
        raise ValueError("high and control histories must have matching non-zero length")
    if not math.isfinite(beta):
        raise ValueError("beta must be finite")
    if not math.isfinite(confidence) or not 0.0 < confidence < 1.0:
        raise ValueError("confidence must lie strictly between zero and one")
    ranges = np.asarray(contrast_range_bounds, dtype=float)
    if ranges.shape != (len(high_histories),):
        raise ValueError(
            "contrast range bounds must have one entry per source game"
        )
    if not np.all(np.isfinite(ranges)) or np.any(ranges < 0.0):
        raise ValueError("contrast range bounds must be finite and non-negative")

    contrasts = []
    pair_counts = []
    for raw_high, raw_control in zip(
        high_histories, control_histories, strict=True
    ):
        high = np.asarray(raw_high, dtype=float)
        control = np.asarray(raw_control, dtype=float)
        if high.ndim != 2 or high.shape != control.shape or high.shape[1] < 1:
            raise ValueError("each high/control history pair must have matching 2D shapes")
        if high.shape[0] < 4 or high.shape[0] % 2:
            raise ValueError(
                "each finite-sample history needs at least four, evenly paired traces"
            )
        if not np.all(np.isfinite(high)) or not np.all(np.isfinite(control)):
            raise ValueError("history matrices must be finite")
        delta_high = high[0::2] - high[1::2]
        delta_control = control[0::2] - control[1::2]
        cross = 0.5 * np.mean(delta_high * delta_control, axis=1)
        energy = 0.5 * np.mean(delta_control**2, axis=1)
        contrasts.append(energy * beta**2 - 2.0 * cross * beta)
        pair_counts.append(len(cross))

    if math.isclose(beta, 0.0, abs_tol=1e-15):
        upper = np.zeros(len(contrasts), dtype=float)
    else:
        log_factor = math.log(
            2.0 * len(high_histories) / (1.0 - confidence)
        )
        upper = np.asarray(
            [
                values.mean()
                + math.sqrt(
                    2.0
                    * float(np.var(values, ddof=1))
                    * log_factor
                    / pairs
                )
                + 7.0 * current_range * log_factor / (3.0 * (pairs - 1))
                for values, pairs, current_range in zip(
                    contrasts, pair_counts, ranges, strict=True
                )
            ],
            dtype=float,
        )
    certified = bool(np.max(upper) <= 1e-12)
    selected_beta = float(beta) if certified else 0.0
    selected_upper = upper if certified else np.zeros_like(upper)
    return FiniteSampleContrastSelection(
        beta=selected_beta,
        worst_upper_contrast=float(np.max(selected_upper)),
        per_game_upper_contrast=tuple(map(float, selected_upper)),
        simultaneous_confidence=confidence,
        pair_counts=tuple(pair_counts),
        candidate_count=1,
        abstained=not certified or math.isclose(beta, 0.0, abs_tol=1e-15),
        preferred_beta_clipped=not certified,
        bound_type="empirical_bernstein_fixed",
    )


def confidence_minimax_normalized_excess_beta(
    high_histories: Sequence[Sequence[Sequence[float]]],
    control_histories: Sequence[Sequence[Sequence[float]]],
    *,
    confidence: float = 0.95,
    beta_limit: float = 2.0,
    preferred_beta: float | None = None,
    calibration: str = "bonferroni_wald",
    certificate_geometry: str = "full_ratio",
    bootstrap_iterations: int = 1999,
    random_seed: int = 0,
) -> ConfidenceRiskEnvelopeSelection:
    """Minimize a simultaneous Wald upper envelope of population risk.

    Adjacent, disjoint trace pairs yield independent unbiased observations of
    the three centered moments ``(H,C,D)``.  Under i.i.d. sampling, finite
    second moments of these pair statistics, and nonsingular covariance, a
    Bonferroni collection of studentized ellipsoids has simultaneous
    asymptotic coverage ``confidence`` by the multivariate CLT and Slutsky's
    theorem.  Alternatively, ``joint_pair_bootstrap`` uses the conditional
    quantile of the maximum studentized pair-bootstrap statistic across games.
    Under the same fixed-game CLT conditions plus a finite fourth moment, this
    jointly calibrated critical value is consistent and adapts to finite-history
    skew and the number of markets.  No Gaussian model is imposed on the
    nonnegative square terms.  ``excess_contrast`` drops the direct-risk
    coordinate from the confidence geometry: because ``H>0``, non-inferiority
    is equivalent to ``D beta^2 - 2 C beta <= 0``.  It therefore certifies the
    same sign decision in two rather than three uncertain dimensions.
    The returned curve value is the exact worst normalized excess over each
    ellipsoid.  If an ellipsoid cannot certify positive ``H`` and ``D``, the
    safe coefficient zero is returned instead of extrapolating.
    """

    from scipy.optimize import minimize_scalar
    from scipy.stats import f

    if len(high_histories) == 0 or len(high_histories) != len(control_histories):
        raise ValueError("high and control histories must have matching non-zero length")
    if not math.isfinite(confidence) or not 0.0 < confidence < 1.0:
        raise ValueError("confidence must lie strictly between zero and one")
    if not math.isfinite(beta_limit) or beta_limit <= 0.0:
        raise ValueError("beta_limit must be finite and positive")
    if preferred_beta is not None and (
        not math.isfinite(preferred_beta) or abs(preferred_beta) > beta_limit
    ):
        raise ValueError("preferred_beta must be finite and within beta_limit")
    if calibration not in {"bonferroni_wald", "joint_pair_bootstrap"}:
        raise ValueError("calibration must be bonferroni_wald or joint_pair_bootstrap")
    if certificate_geometry not in {"full_ratio", "excess_contrast"}:
        raise ValueError("certificate_geometry must be full_ratio or excess_contrast")
    if calibration == "joint_pair_bootstrap" and bootstrap_iterations < 99:
        raise ValueError("bootstrap_iterations must be at least 99")

    moment_samples: list[np.ndarray] = []
    centers: list[np.ndarray] = []
    covariances: list[np.ndarray] = []
    pair_counts: list[int] = []
    nonsingular = True
    game_alpha = (1.0 - confidence) / len(high_histories)
    dimension = 3 if certificate_geometry == "full_ratio" else 2
    high_centers: list[float] = []
    for raw_high, raw_control in zip(
        high_histories, control_histories, strict=True
    ):
        high = np.asarray(raw_high, dtype=float)
        control = np.asarray(raw_control, dtype=float)
        if high.ndim != 2 or high.shape != control.shape or high.shape[1] < 1:
            raise ValueError("each high/control history pair must have matching 2D shapes")
        if high.shape[0] < 8:
            raise ValueError("each confidence history needs at least eight traces")
        if high.shape[0] % 2:
            raise ValueError("each confidence history needs an even trace count")
        if not np.all(np.isfinite(high)) or not np.all(np.isfinite(control)):
            raise ValueError("history matrices must be finite")
        delta_high = high[0::2] - high[1::2]
        delta_control = control[0::2] - control[1::2]
        full_observations = np.column_stack(
            (
                0.5 * np.mean(delta_high**2, axis=1),
                0.5 * np.mean(delta_high * delta_control, axis=1),
                0.5 * np.mean(delta_control**2, axis=1),
            )
        )
        high_centers.append(float(full_observations[:, 0].mean()))
        observations = (
            full_observations
            if certificate_geometry == "full_ratio"
            else full_observations[:, 1:]
        )
        pairs = observations.shape[0]
        center = observations.mean(axis=0)
        covariance = np.cov(observations, rowvar=False, ddof=1)
        nonsingular = nonsingular and np.linalg.matrix_rank(covariance) == dimension
        moment_samples.append(observations)
        centers.append(center)
        covariances.append(covariance)
        pair_counts.append(pairs)

    if calibration == "joint_pair_bootstrap":
        generator = np.random.default_rng(random_seed)
        maximum_statistics = np.zeros(bootstrap_iterations, dtype=float)
        for observations, center, covariance in zip(
            moment_samples, centers, covariances, strict=True
        ):
            pairs = observations.shape[0]
            indices = generator.integers(
                0, pairs, size=(bootstrap_iterations, pairs)
            )
            draws = observations[indices]
            bootstrap_means = draws.mean(axis=1)
            centered_draws = draws - bootstrap_means[:, None, :]
            bootstrap_covariances = np.einsum(
                "bki,bkj->bij", centered_draws, centered_draws
            ) / (pairs - 1)
            differences = bootstrap_means - center
            solutions = np.linalg.pinv(bootstrap_covariances) @ differences[..., None]
            statistics = pairs * np.sum(differences * solutions[..., 0], axis=1)
            ranks = np.linalg.matrix_rank(bootstrap_covariances)
            statistics[ranks < dimension] = np.inf
            maximum_statistics = np.maximum(maximum_statistics, statistics)
        critical_value = float(
            np.quantile(maximum_statistics, confidence, method="higher")
        )
        if not math.isfinite(critical_value):
            nonsingular = False
        critical_values = [critical_value] * len(moment_samples)
    else:
        critical_values = []
        for pairs in pair_counts:
            quantile = float(
                f.ppf(1.0 - game_alpha, dimension, pairs - dimension)
            )
            critical_values.append(
                dimension * (pairs - 1) / (pairs - dimension) * quantile
            )
        critical_value = max(critical_values)

    ellipsoids = [
        (center, critical * covariance / pairs)
        for center, covariance, pairs, critical in zip(
            centers, covariances, pair_counts, critical_values, strict=True
        )
    ]

    # Every point in the ellipsoid then has positive H and D, making each
    # upper risk curve finite and convex in beta.
    for center, shape in ellipsoids:
        positive_geometry = (
            center[0] - math.sqrt(max(0.0, float(shape[0, 0]))) > 0.0
            and center[2] - math.sqrt(max(0.0, float(shape[2, 2]))) > 0.0
            if certificate_geometry == "full_ratio"
            else center[1] - math.sqrt(max(0.0, float(shape[1, 1]))) > 0.0
        )
        if not nonsingular or not positive_geometry:
            return ConfidenceRiskEnvelopeSelection(
                beta=0.0,
                worst_upper_normalized_excess=0.0,
                per_game_upper_normalized_excess=tuple(0.0 for _ in ellipsoids),
                simultaneous_confidence=confidence,
                pair_counts=tuple(pair_counts),
                abstained=True,
                preferred_beta_clipped=preferred_beta not in (None, 0.0),
                calibration=calibration,
                critical_value=critical_value,
                certificate_geometry=certificate_geometry,
            )

    def upper_ratio(
        beta: float, center: np.ndarray, shape: np.ndarray, high_center: float
    ) -> float:
        if certificate_geometry == "excess_contrast":
            direction = np.asarray((-2.0 * beta, beta * beta))
            spread = math.sqrt(max(0.0, float(direction @ shape @ direction)))
            # Positive scaling preserves the certified sign.  It also keeps
            # the diagnostic on the normalized-excess scale without spending
            # confidence radius on H, which is irrelevant to non-inferiority.
            return float((direction @ center + spread) / high_center)
        numerator = np.asarray((0.0, -2.0 * beta, beta * beta))

        def support(level: float) -> float:
            direction = numerator - np.asarray((level, 0.0, 0.0))
            spread = math.sqrt(max(0.0, float(direction @ shape @ direction)))
            return float(direction @ center + spread)

        lower, upper = -1.0, 1.0
        while support(lower) < 0.0:
            lower *= 2.0
        while support(upper) > 0.0:
            upper *= 2.0
        for _ in range(100):
            midpoint = 0.5 * (lower + upper)
            if support(midpoint) > 0.0:
                lower = midpoint
            else:
                upper = midpoint
        return 0.5 * (lower + upper)

    def evaluate(beta: float) -> tuple[float, tuple[float, ...]]:
        values = tuple(
            upper_ratio(beta, center, shape, high_center)
            for (center, shape), high_center in zip(
                ellipsoids, high_centers, strict=True
            )
        )
        return max(values), values

    clipped = False
    if preferred_beta is not None:
        beta = float(preferred_beta)
        if evaluate(beta)[0] > 0.0:
            clipped = True
            safe, unsafe = 0.0, beta
            for _ in range(100):
                midpoint = 0.5 * (safe + unsafe)
                if evaluate(midpoint)[0] <= 0.0:
                    safe = midpoint
                else:
                    unsafe = midpoint
            beta = safe
    else:
        optimum = minimize_scalar(
            lambda candidate: evaluate(float(candidate))[0],
            bounds=(-beta_limit, beta_limit),
            method="bounded",
            options={"xatol": 1e-12},
        )
        candidates = (0.0, -beta_limit, beta_limit, float(optimum.x))
        beta = min(candidates, key=lambda value: (evaluate(value)[0], abs(value), value))
    worst, values = evaluate(beta)
    # Numerical minimization must never make the certificate weaker than the
    # exact safe fallback beta=0.
    if worst > 1e-10:
        beta, worst, values = 0.0, 0.0, tuple(0.0 for _ in ellipsoids)
    return ConfidenceRiskEnvelopeSelection(
        beta=float(beta),
        worst_upper_normalized_excess=float(worst),
        per_game_upper_normalized_excess=tuple(map(float, values)),
        simultaneous_confidence=confidence,
        pair_counts=tuple(pair_counts),
        abstained=False,
        preferred_beta_clipped=clipped,
        calibration=calibration,
        critical_value=critical_value,
        certificate_geometry=certificate_geometry,
    )


def minimax_normalized_excess_beta(
    direct_risks: Sequence[float],
    cross_moments: Sequence[float],
    control_energies: Sequence[float],
    *,
    beta_limit: float = 2.0,
) -> RiskEnvelopeSelection:
    """Minimize worst historical excess risk using only scalar sketches.

    Game ``g`` contributes ``(D_g/H_g) beta^2 - 2(C_g/H_g) beta``.
    The upper envelope's minimum is attained at a boundary, an individual
    vertex, or a pairwise intersection, so finite candidate enumeration is
    exact and needs no numerical optimizer or target-game information.
    """

    direct = np.asarray(direct_risks, dtype=float)
    cross = np.asarray(cross_moments, dtype=float)
    energy = np.asarray(control_energies, dtype=float)
    if (
        direct.ndim != 1
        or cross.ndim != 1
        or energy.ndim != 1
        or len(direct) == 0
        or len(cross) != len(direct)
        or len(energy) != len(direct)
    ):
        raise ValueError("risk-sketch arrays must have the same non-zero length")
    if not all(np.all(np.isfinite(values)) for values in (direct, cross, energy)):
        raise ValueError("risk-sketch arrays must be finite")
    if np.any(direct <= 0.0):
        raise ValueError("direct risks must be positive")
    if np.any(energy < 0.0):
        raise ValueError("control energies must be non-negative")
    if not math.isfinite(beta_limit) or beta_limit <= 0.0:
        raise ValueError("beta_limit must be finite and positive")

    curvature = energy / direct
    slope = cross / direct
    candidates = {-float(beta_limit), 0.0, float(beta_limit)}
    for current_curvature, current_slope in zip(curvature, slope, strict=True):
        if current_curvature > 0.0:
            candidates.add(
                float(np.clip(current_slope / current_curvature, -beta_limit, beta_limit))
            )
    for left in range(len(curvature)):
        for right in range(left + 1, len(curvature)):
            difference = curvature[left] - curvature[right]
            tolerance = 100.0 * np.finfo(float).eps * max(
                1.0, abs(curvature[left]), abs(curvature[right])
            )
            if abs(difference) <= tolerance:
                continue
            intersection = 2.0 * (slope[left] - slope[right]) / difference
            if -beta_limit <= intersection <= beta_limit:
                candidates.add(float(intersection))

    def evaluate(beta: float) -> tuple[float, np.ndarray]:
        values = curvature * beta * beta - 2.0 * slope * beta
        return float(np.max(values)), values

    beta = min(
        candidates,
        key=lambda candidate: (evaluate(candidate)[0], abs(candidate), candidate),
    )
    worst, values = evaluate(beta)
    tolerance = 1e-12 * max(1.0, abs(worst))
    active = tuple(
        int(index)
        for index, value in enumerate(values)
        if abs(float(value) - worst) <= tolerance
    )
    return RiskEnvelopeSelection(
        beta=float(beta),
        worst_normalized_excess=worst,
        active_indices=active,
        per_game_normalized_excess=tuple(map(float, values)),
    )


def _centered_risk_sketch(
    high: np.ndarray, control: np.ndarray
) -> tuple[float, float, float]:
    """Return unbiased per-coordinate centered moments ``(H, C, D)``."""

    high_centered = high - high.mean(axis=0, keepdims=True)
    control_centered = control - control.mean(axis=0, keepdims=True)
    scale = 1.0 / ((high.shape[0] - 1) * high.shape[1])
    return (
        float(scale * np.sum(high_centered**2)),
        float(scale * np.sum(high_centered * control_centered)),
        float(scale * np.sum(control_centered**2)),
    )


def deletion_robust_minimax_normalized_excess_beta(
    high_histories: Sequence[Sequence[Sequence[float]]],
    control_histories: Sequence[Sequence[Sequence[float]]],
    *,
    beta_limit: float = 2.0,
) -> DeletionRobustRiskEnvelopeSelection:
    """Minimize the worst excess after any single calibration-trace deletion.

    Each game supplies paired matrices whose rows are independent calibration
    traces and whose columns are provider scores.  The method forms every
    leave-one-trace-out centered risk sketch and applies the exact finite
    envelope solver.  Consequently the returned coefficient is audited on
    every observed game even if any one calibration trace is removed.
    """

    if len(high_histories) == 0 or len(high_histories) != len(control_histories):
        raise ValueError("high and control histories must have matching non-zero length")

    deleted_scenarios: list[tuple[int, int]] = []
    deleted_direct: list[float] = []
    deleted_cross: list[float] = []
    deleted_energy: list[float] = []
    full_sketches: list[tuple[float, float, float]] = []
    for game, (raw_high, raw_control) in enumerate(
        zip(high_histories, control_histories, strict=True)
    ):
        high = np.asarray(raw_high, dtype=float)
        control = np.asarray(raw_control, dtype=float)
        if high.ndim != 2 or control.shape != high.shape or high.shape[1] < 1:
            raise ValueError("each high/control history pair must have matching 2D shapes")
        if high.shape[0] < 3:
            raise ValueError("each history needs at least three calibration traces")
        if not np.all(np.isfinite(high)) or not np.all(np.isfinite(control)):
            raise ValueError("history matrices must be finite")
        full_sketches.append(_centered_risk_sketch(high, control))
        for deleted in range(high.shape[0]):
            keep = np.arange(high.shape[0]) != deleted
            direct, cross, energy = _centered_risk_sketch(high[keep], control[keep])
            deleted_scenarios.append((game, deleted))
            deleted_direct.append(direct)
            deleted_cross.append(cross)
            deleted_energy.append(energy)

    selection = minimax_normalized_excess_beta(
        deleted_direct,
        deleted_cross,
        deleted_energy,
        beta_limit=beta_limit,
    )
    full_excess = tuple(
        energy / direct * selection.beta**2
        - 2.0 * cross / direct * selection.beta
        for direct, cross, energy in full_sketches
    )
    return DeletionRobustRiskEnvelopeSelection(
        beta=selection.beta,
        worst_deleted_normalized_excess=selection.worst_normalized_excess,
        deleted_scenarios=tuple(deleted_scenarios),
        active_scenarios=tuple(
            deleted_scenarios[index] for index in selection.active_indices
        ),
        per_deleted_normalized_excess=selection.per_game_normalized_excess,
        full_sample_normalized_excess=tuple(map(float, full_excess)),
    )


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


def pool_anchor_aware_moments(
    diagnostics: Sequence[Mapping[str, object]],
) -> float:
    """Pool truth-free AA moment estimates across historical settlements.

    Pooling the moment numerators and denominators (rather than averaging
    per-trace ratios) preserves the deployed-risk estimating equation and
    naturally gives more weight to informative traces.
    """
    if not diagnostics:
        raise ValueError("at least one anchor-aware diagnostic is required")
    cross = 0.0
    energy = 0.0
    for record in diagnostics:
        current_cross = float(record["paired_cross_energy"])
        low = float(record["paired_low_variance_energy"])
        anchor = float(record["anchor_variance_energy"])
        if not all(math.isfinite(value) for value in (current_cross, low, anchor)):
            raise ValueError("anchor-aware moments must be finite")
        if low < 0.0 or anchor < 0.0:
            raise ValueError("anchor-aware energies must be non-negative")
        cross += current_cross
        energy += low + anchor
    if energy <= 0.0:
        return 0.0
    return float(cross / energy)


def pool_history_anchor_aware_moments(
    high_scores: Sequence[Sequence[float]],
    low_scores: Sequence[Sequence[float]],
    anchor_scores: Sequence[Sequence[float]],
) -> float:
    """Estimate the deployed-risk slope from repeated historical traces.

    Centering across repeated settlements removes each game's unknown target.
    The method then forms the *deployed* control ``G = L - A`` before taking
    moments, so no independence or orthogonality assumption between the paired
    low trace and the anchor trace is needed.
    """

    return anchor_orthogonality_audit(
        high_scores, low_scores, anchor_scores
    ).direct_beta


def _center_aligned_histories(
    high_scores: Sequence[Sequence[float]],
    low_scores: Sequence[Sequence[float]],
    anchor_scores: Sequence[Sequence[float]],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Validate and center aligned repeated score matrices."""

    high = np.asarray(high_scores, dtype=float)
    low = np.asarray(low_scores, dtype=float)
    anchor = np.asarray(anchor_scores, dtype=float)
    if (
        high.ndim != 2
        or low.shape != high.shape
        or anchor.shape != high.shape
        or len(high) < 2
    ):
        raise ValueError("historical score matrices must share shape and have repeats")
    if not all(np.all(np.isfinite(value)) for value in (high, low, anchor)):
        raise ValueError("historical scores must be finite")
    return tuple(
        value - np.mean(value, axis=0, keepdims=True)
        for value in (high, low, anchor)
    )


def history_deployed_control_moments(
    high_scores: Sequence[Sequence[float]],
    low_scores: Sequence[Sequence[float]],
    anchor_scores: Sequence[Sequence[float]],
) -> tuple[float, float, float]:
    """Return ``(H, C, D)`` for centered high error and ``G=L-A``.

    The common factor ``1/(M-1)`` is retained so the values are empirical
    risks, although it cancels in the coefficient ``C/D``.
    """

    high, low, anchor = _center_aligned_histories(
        high_scores, low_scores, anchor_scores
    )
    deployed = low - anchor
    scale = 1.0 / (len(high) - 1)
    direct_risk = float(scale * np.sum(high * high))
    deployed_cross = float(scale * np.sum(high * deployed))
    deployed_energy = float(scale * np.sum(deployed * deployed))
    return direct_risk, deployed_cross, deployed_energy


def anchor_orthogonality_audit(
    high_scores: Sequence[Sequence[float]],
    low_scores: Sequence[Sequence[float]],
    anchor_scores: Sequence[Sequence[float]],
) -> AnchorOrthogonalityAudit:
    """Decompose the exact effect of an anchor-orthogonality approximation.

    ``direct_beta`` minimizes empirical risk for the actual deployed control
    ``L-A``. ``anchor_energy_beta`` instead drops the two cross terms and is
    exposed only as a mechanism diagnostic. Both use the identical histories.
    """

    high, low, anchor = _center_aligned_histories(
        high_scores, low_scores, anchor_scores
    )
    scale = 1.0 / (len(high) - 1)
    direct_risk = float(scale * np.sum(high * high))
    paired_cross = float(scale * np.sum(high * low))
    paired_low_energy = float(scale * np.sum(low * low))
    anchor_energy = float(scale * np.sum(anchor * anchor))
    high_anchor_cross = float(scale * np.sum(high * anchor))
    low_anchor_cross = float(scale * np.sum(low * anchor))
    deployed_cross = paired_cross - high_anchor_cross
    deployed_energy = paired_low_energy + anchor_energy - 2.0 * low_anchor_cross
    floor = 100.0 * np.finfo(float).eps * max(1.0, direct_risk)
    direct_beta = (
        0.0 if deployed_energy <= floor else deployed_cross / deployed_energy
    )
    anchor_energy_denominator = paired_low_energy + anchor_energy
    anchor_energy_beta = (
        0.0
        if anchor_energy_denominator <= floor
        else paired_cross / anchor_energy_denominator
    )
    paired_only_beta = (
        0.0 if paired_low_energy <= floor else paired_cross / paired_low_energy
    )
    beta_gap = direct_beta - anchor_energy_beta
    return AnchorOrthogonalityAudit(
        direct_risk=direct_risk,
        deployed_cross=deployed_cross,
        deployed_energy=deployed_energy,
        paired_cross=paired_cross,
        paired_low_energy=paired_low_energy,
        anchor_energy=anchor_energy,
        high_anchor_cross=high_anchor_cross,
        low_anchor_cross=low_anchor_cross,
        direct_beta=float(direct_beta),
        anchor_energy_beta=float(anchor_energy_beta),
        paired_only_beta=float(paired_only_beta),
        beta_gap=float(beta_gap),
        anchor_energy_excess=float(deployed_energy * beta_gap * beta_gap),
    )


def pool_history_anchor_energy_moments(
    high_scores: Sequence[Sequence[float]],
    low_scores: Sequence[Sequence[float]],
    anchor_scores: Sequence[Sequence[float]],
) -> float:
    """Independence-specialized slope retained as a named diagnostic only."""

    return anchor_orthogonality_audit(
        high_scores, low_scores, anchor_scores
    ).anchor_energy_beta


def pool_history_paired_only_moments(
    high_scores: Sequence[Sequence[float]],
    low_scores: Sequence[Sequence[float]],
) -> float:
    """Historical paired-only slope, omitting sampled-anchor uncertainty.

    This is the history- and information-matched ablation of
    :func:`pool_history_anchor_aware_moments`: it uses the same centered high
    and paired-low traces but deliberately leaves anchor energy out of the
    normal equation.
    """

    high = np.asarray(high_scores, dtype=float)
    low = np.asarray(low_scores, dtype=float)
    if high.ndim != 2 or low.shape != high.shape or len(high) < 2:
        raise ValueError("historical high/low score matrices must share shape")
    if not np.all(np.isfinite(high)) or not np.all(np.isfinite(low)):
        raise ValueError("historical scores must be finite")
    high_centered = high - np.mean(high, axis=0, keepdims=True)
    low_centered = low - np.mean(low, axis=0, keepdims=True)
    cross = float(np.sum(high_centered * low_centered) / (len(high) - 1))
    low_risk = float(np.sum(low_centered**2) / (len(low) - 1))
    floor = 100.0 * np.finfo(float).eps * max(
        1.0, float(np.sum(high_centered**2) / (len(high) - 1))
    )
    return 0.0 if low_risk <= floor else float(cross / low_risk)


def nested_cost_optimal_anchor_ratio(
    high_risk_constant: float,
    cross_constant: float,
    paired_low_constant: float,
    anchor_constant: float,
    anchor_cost_ratio: float,
) -> float:
    """Continuous ``A/B`` allocation from the nested-checkpoint cost law.

    The paired low checkpoint is treated as a free output of each high
    trajectory; only independent anchor fits carry ``anchor_cost_ratio``.
    """

    h, c, low, anchor, rho = map(
        float,
        (
            high_risk_constant,
            cross_constant,
            paired_low_constant,
            anchor_constant,
            anchor_cost_ratio,
        ),
    )
    if not all(math.isfinite(value) for value in (h, c, low, anchor, rho)):
        raise ValueError("cost-law constants must be finite")
    if h <= 0.0 or low <= 0.0 or anchor <= 0.0 or rho <= 0.0:
        raise ValueError("risk, energy, and cost constants must be positive")
    if c * c <= rho * h * anchor:
        return 0.0
    gap = max(0.0, h * low - c * c)
    coefficients = np.asarray(
        [rho * low * gap, 2.0 * rho * anchor * gap, anchor * (rho * h * anchor - c * c)],
        dtype=float,
    )
    if coefficients[0] <= 100.0 * np.finfo(float).eps:
        return float("inf")
    roots = np.roots(coefficients)
    feasible = [float(root.real) for root in roots if abs(root.imag) < 1e-10 and root.real >= 0.0]
    return min(feasible) if feasible else float("inf")


def run_anchor_aware_cv_oracle(
    owner_ids: Sequence[str],
    high_value: Callable[[int], float],
    low_value: Callable[[int], float],
    *,
    budget: int,
    seed: int,
    anchor_budget: int,
    anchor_seed: int,
    coefficient_mode: str = "scalar",
    ridge_relative: float = 0.1,
) -> ValuationOutput:
    """Fit the deployed-risk optimum including independent anchor noise."""
    owners = tuple(map(str, owner_ids))
    if len(owners) < 2 or len(set(owners)) != len(owners):
        raise ValueError("owner_ids must contain at least two unique owners")
    if anchor_seed == seed:
        raise ValueError("anchor and paired traces require independent seeds")
    if budget < 2 or anchor_budget < 2:
        raise ValueError("budgets must be at least two")
    if coefficient_mode not in {"scalar", "diagonal", "matrix"}:
        raise ValueError("coefficient_mode must be scalar, diagonal, or matrix")
    if not math.isfinite(ridge_relative) or ridge_relative < 0.0:
        raise ValueError("ridge_relative must be finite and non-negative")

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
        beta = paired_beta = 0.0
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
            beta = paired_beta = 0.0
            degenerate = True
        else:
            paired_beta = high_low_cross / low_energy
            beta = high_low_cross / (low_energy + anchor_energy)
            degenerate = False

    coefficient_matrix: np.ndarray | None = None
    if coefficient_mode in {"diagonal", "matrix"} and not degenerate:
        paired_factor = (len(high_influence) - 1) / len(high_influence)
        anchor_factor = (len(anchor_influence) - 1) / len(anchor_influence)
        centered_anchor = anchor_influence - np.mean(
            anchor_influence, axis=0, keepdims=True
        )
        if coefficient_mode == "diagonal":
            cross_by_owner = paired_factor * np.sum(
                centered_high * centered_low, axis=0
            )
            low_by_owner = paired_factor * np.sum(centered_low**2, axis=0)
            anchor_by_owner = anchor_factor * np.sum(centered_anchor**2, axis=0)
            denominators = low_by_owner + anchor_by_owner
            coefficients_array = np.divide(
                cross_by_owner,
                denominators,
                out=np.full(len(owners), float(beta)),
                where=denominators > floor / len(owners),
            )
        else:
            cross_matrix = paired_factor * centered_high.T @ centered_low
            control_covariance = (
                paired_factor * centered_low.T @ centered_low
                + anchor_factor * centered_anchor.T @ centered_anchor
            )
            scale = float(np.trace(control_covariance) / len(owners))
            ridge = ridge_relative * max(scale, floor / len(owners))
            coefficient_matrix = cross_matrix @ np.linalg.pinv(
                control_covariance + ridge * np.eye(len(owners)),
                hermitian=True,
            )
            coefficients_array = np.diag(coefficient_matrix)
    else:
        coefficients_array = np.full(len(owners), float(beta))
        if coefficient_mode == "matrix":
            coefficient_matrix = np.eye(len(owners)) * float(beta)

    low_difference = np.asarray(
        [low_scores[owner] - anchor_scores[owner] for owner in owners]
    )
    direct_vector = np.asarray([high_scores[owner] for owner in owners])
    correction = (
        coefficient_matrix @ low_difference
        if coefficient_matrix is not None
        else coefficients_array * low_difference
    )
    scores = {
        owner: float(direct_vector[index] - correction[index])
        for index, owner in enumerate(owners)
    }
    return ValuationOutput(
        scores,
        diagnostics={
            "backend": "anchor_aware_multifidelity_cv_oracle",
            "table_free": True,
            "coefficient_mode": f"anchor_aware_{coefficient_mode}",
            "coefficient_source": "paired_plus_anchor_influence",
            "beta": (
                coefficient_matrix.tolist()
                if coefficient_matrix is not None
                else (
                    list(map(float, coefficients_array))
                    if coefficient_mode == "diagonal"
                    else float(beta)
                )
            ),
            "ridge_relative": float(ridge_relative),
            "paired_only_beta": float(paired_beta),
            "paired_cross_energy": float(high_low_cross),
            "paired_low_variance_energy": float(low_energy),
            "anchor_variance_energy": float(anchor_energy),
            "coefficient_degenerate": bool(degenerate),
            "degenerate_fallback": "direct" if degenerate else None,
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
    "AnchorOrthogonalityAudit",
    "CoefficientEstimate",
    "ConfidenceRiskEnvelopeSelection",
    "CrossFitFold",
    "DeletionRobustRiskEnvelopeSelection",
    "RiskEnvelopeSelection",
    "deletion_robust_minimax_normalized_excess_beta",
    "confidence_minimax_normalized_excess_beta",
    "estimate_cv_coefficients",
    "anchor_orthogonality_audit",
    "history_deployed_control_moments",
    "pool_anchor_aware_moments",
    "pool_history_anchor_aware_moments",
    "pool_history_anchor_energy_moments",
    "pool_history_paired_only_moments",
    "nested_cost_optimal_anchor_ratio",
    "minimax_normalized_excess_beta",
    "run_anchor_aware_cv_oracle",
    "run_multifidelity_cv_oracle",
]
