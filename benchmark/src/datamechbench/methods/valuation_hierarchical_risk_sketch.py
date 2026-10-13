"""Truth-free hierarchical calibration of scalar Shapley risk sketches."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class NormalizedRiskSketch:
    high_energy: float
    cross_moment: float
    control_energy: float
    normalized_cross_moment: float
    normalized_control_energy: float
    relative_tolerance: float
    degenerate: bool


@dataclass(frozen=True)
class HierarchicalRiskFit:
    beta: float
    raw_beta: float
    blended_cross_moment: float
    blended_control_energy: float
    local_dof: float
    prior_weight: float
    mode: str
    clipped: bool
    degenerate: bool


@dataclass(frozen=True)
class HierarchicalMomentErrorBound:
    control_error: float
    cross_error: float


@dataclass(frozen=True)
class EmpiricalBreakEven:
    matched_direct_budget: int | None
    saved_cost_per_settlement: float
    break_even_settlements: int | None
    infinite: bool


def normalize_risk_sketch(
    high_energy: float,
    cross_moment: float,
    control_energy: float,
    relative_tolerance: float = 1e-10,
) -> NormalizedRiskSketch:
    """Normalize one centered quadratic by its direct-estimator energy."""

    values = (high_energy, cross_moment, control_energy, relative_tolerance)
    if not all(math.isfinite(value) for value in values):
        raise ValueError("risk-sketch inputs must be finite")
    if high_energy < 0.0 or control_energy < 0.0:
        raise ValueError("risk energies must be non-negative")
    if not 0.0 < relative_tolerance < 1.0:
        raise ValueError("relative_tolerance must lie strictly between zero and one")
    if high_energy == 0.0:
        return NormalizedRiskSketch(
            high_energy,
            cross_moment,
            control_energy,
            0.0,
            0.0,
            relative_tolerance,
            True,
        )
    normalized_cross = cross_moment / high_energy
    normalized_control = control_energy / high_energy
    return NormalizedRiskSketch(
        high_energy,
        cross_moment,
        control_energy,
        normalized_cross,
        normalized_control,
        relative_tolerance,
        normalized_control <= relative_tolerance,
    )


def fit_hierarchical_risk_sketch(
    local: NormalizedRiskSketch,
    prior: NormalizedRiskSketch,
    *,
    local_dof: float,
    prior_weight: float,
    beta_bounds: tuple[float, float],
) -> HierarchicalRiskFit:
    """Blend normalized risk curves, then minimize the resulting quadratic."""

    if not math.isfinite(local_dof) or local_dof <= 0.0:
        raise ValueError("local_dof must be positive and finite")
    if math.isnan(prior_weight) or prior_weight < 0.0:
        raise ValueError("prior_weight must be non-negative or infinity")
    lower, upper = map(float, beta_bounds)
    if not math.isfinite(lower) or not math.isfinite(upper) or lower >= upper:
        raise ValueError("beta_bounds must be finite and increasing")

    if prior_weight == 0.0:
        cross = local.normalized_cross_moment
        control = local.normalized_control_energy
        mode = "local"
        sole_degenerate = local.degenerate
    elif math.isinf(prior_weight):
        cross = prior.normalized_cross_moment
        control = prior.normalized_control_energy
        mode = "transfer"
        sole_degenerate = prior.degenerate
    else:
        denominator = local_dof + prior_weight
        cross = (
            local_dof * local.normalized_cross_moment
            + prior_weight * prior.normalized_cross_moment
        ) / denominator
        control = (
            local_dof * local.normalized_control_energy
            + prior_weight * prior.normalized_control_energy
        ) / denominator
        mode = "hierarchical"
        sole_degenerate = local.degenerate and prior.degenerate

    tolerance = max(local.relative_tolerance, prior.relative_tolerance)
    degenerate = sole_degenerate or control <= tolerance
    raw_beta = 0.0 if degenerate else cross / control
    beta = min(max(raw_beta, lower), upper)
    return HierarchicalRiskFit(
        beta=beta,
        raw_beta=raw_beta,
        blended_cross_moment=cross,
        blended_control_energy=control,
        local_dof=local_dof,
        prior_weight=prior_weight,
        mode=mode,
        clipped=not math.isclose(beta, raw_beta, rel_tol=0.0, abs_tol=1e-15),
        degenerate=degenerate,
    )


def hierarchical_moment_error_bound(
    *,
    local_dof: float,
    prior_weight: float,
    local_control_error: float,
    local_cross_error: float,
    prior_control_drift: float,
    prior_cross_drift: float,
) -> HierarchicalMomentErrorBound:
    """Convex-combination bound for local noise and source-prior drift."""

    errors = (
        local_control_error,
        local_cross_error,
        prior_control_drift,
        prior_cross_drift,
    )
    if not math.isfinite(local_dof) or local_dof <= 0.0:
        raise ValueError("local_dof must be positive and finite")
    if math.isnan(prior_weight) or prior_weight < 0.0:
        raise ValueError("prior_weight must be non-negative or infinity")
    if any(not math.isfinite(value) or value < 0.0 for value in errors):
        raise ValueError("error and drift bounds must be finite and non-negative")
    if math.isinf(prior_weight):
        return HierarchicalMomentErrorBound(
            prior_control_drift, prior_cross_drift
        )
    denominator = local_dof + prior_weight
    return HierarchicalMomentErrorBound(
        control_error=(
            local_dof * local_control_error
            + prior_weight * prior_control_drift
        )
        / denominator,
        cross_error=(
            local_dof * local_cross_error + prior_weight * prior_cross_drift
        )
        / denominator,
    )


def empirical_break_even(
    *,
    commissioning_cost: float,
    aar_deployment_cost: float,
    direct_budget_risks: Mapping[int, float],
    aar_risk: float,
) -> EmpiricalBreakEven:
    """Use an observed direct-budget curve; never extrapolate a scaling law."""

    scalar_values = (commissioning_cost, aar_deployment_cost, aar_risk)
    if any(not math.isfinite(value) or value < 0.0 for value in scalar_values):
        raise ValueError("costs and risks must be finite and non-negative")
    if not direct_budget_risks:
        raise ValueError("direct_budget_risks must be non-empty")
    curve: list[tuple[int, float]] = []
    for budget, risk in direct_budget_risks.items():
        if not isinstance(budget, int) or budget <= 0:
            raise ValueError("direct budgets must be positive integers")
        if not math.isfinite(risk) or risk < 0.0:
            raise ValueError("direct risks must be finite and non-negative")
        curve.append((budget, float(risk)))
    matching = [budget for budget, risk in sorted(curve) if risk <= aar_risk]
    matched = matching[0] if matching else None
    saving = 0.0 if matched is None else float(matched) - aar_deployment_cost
    if matched is None or saving <= 0.0:
        return EmpiricalBreakEven(matched, saving, None, True)
    return EmpiricalBreakEven(
        matched,
        saving,
        math.ceil(commissioning_cost / saving),
        False,
    )


__all__ = [
    "EmpiricalBreakEven",
    "HierarchicalMomentErrorBound",
    "HierarchicalRiskFit",
    "NormalizedRiskSketch",
    "empirical_break_even",
    "fit_hierarchical_risk_sketch",
    "hierarchical_moment_error_bound",
    "normalize_risk_sketch",
]
