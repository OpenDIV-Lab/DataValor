"""Benchmark method adapters."""

from .procurement import register_procurement_methods
from .trading import register_trading_methods
from .valuation import OptionalMethodUnavailable, register_valuation_methods
from .valuation_anytime_gate import (
    AnytimeContrastSelection,
    AnytimeRoutedSelection,
    anytime_contrast_grid_beta,
    anytime_routed_contrast_beta,
)
from .valuation_multifidelity_cv import (
    AnchorOrthogonalityAudit,
    DeletionRobustRiskEnvelopeSelection,
    RiskEnvelopeSelection,
    anchor_orthogonality_audit,
    deletion_robust_minimax_normalized_excess_beta,
    estimate_cv_coefficients,
    minimax_normalized_excess_beta,
    history_deployed_control_moments,
    pool_history_anchor_aware_moments,
    pool_history_anchor_energy_moments,
    run_anchor_aware_cv_oracle,
    run_multifidelity_cv_oracle,
)
from .valuation_hierarchical_risk_sketch import (
    EmpiricalBreakEven,
    HierarchicalMomentErrorBound,
    HierarchicalRiskFit,
    NormalizedRiskSketch,
    empirical_break_even,
    fit_hierarchical_risk_sketch,
    hierarchical_moment_error_bound,
    normalize_risk_sketch,
)

__all__ = [
    "AnchorOrthogonalityAudit",
    "EmpiricalBreakEven",
    "HierarchicalMomentErrorBound",
    "HierarchicalRiskFit",
    "NormalizedRiskSketch",
    "DeletionRobustRiskEnvelopeSelection",
    "AnytimeContrastSelection",
    "AnytimeRoutedSelection",
    "OptionalMethodUnavailable",
    "anchor_orthogonality_audit",
    "register_procurement_methods",
    "register_trading_methods",
    "register_valuation_methods",
    "deletion_robust_minimax_normalized_excess_beta",
    "anytime_contrast_grid_beta",
    "anytime_routed_contrast_beta",
    "estimate_cv_coefficients",
    "history_deployed_control_moments",
    "pool_history_anchor_aware_moments",
    "pool_history_anchor_energy_moments",
    "RiskEnvelopeSelection",
    "minimax_normalized_excess_beta",
    "run_anchor_aware_cv_oracle",
    "run_multifidelity_cv_oracle",
    "empirical_break_even",
    "fit_hierarchical_risk_sketch",
    "hierarchical_moment_error_bound",
    "normalize_risk_sketch",
]
