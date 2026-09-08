"""DataValue: task-aware and user-aware data valuation."""

from .advanced_valuation import QualityAdjustedValuator, ScenarioValuator
from .contribution import (
    BanzhafValuator,
    ExactShapleyValuator,
    LeaveOneOutValuator,
    MonteCarloShapleyValuator,
    allocate_value_by_contribution,
    exact_shapley_values,
    leave_one_out_values,
    monte_carlo_shapley_values,
)
from .contribution_advanced import (
    GroupShapleyValuator,
    bootstrap_loo_values,
    group_shapley_values,
    pairwise_interactions,
)
from .extensions import (
    CalibrationReport,
    CounterfactualValuator,
    PortfolioValuator,
    RiskAdjustedValuator,
    ValueCurvePoint,
    build_value_curve,
    calibrate_values,
)
from .interfaces import ContributionValuator, DataValuator, TrainableValuator, UtilityFunction
from .models import (
    ContributionReport,
    ContributionRequest,
    TrainingReport,
    ValuationMode,
    ValuationReport,
    ValuationRequest,
    ValuationTarget,
    ValueEstimate,
)
from .registry import (
    CONTRIBUTION_VALUATORS,
    TRAINABLE_VALUATORS,
    UTILITY_FUNCTIONS,
    VALUATORS,
)
from .requirements import load_requirements, merge_requirement_bundles
from .task_metrics import (
    binary_roc_auc,
    classification_scores,
    incremental_gain,
    ranking_scores,
    regression_scores,
)
from .utilities import TabularTaskUtility
from .valuators import WeightedUserTaskValuator
from .value_functions import LearnedLinearValuator, SymbolicValuator

for _component, _registry in (
    (WeightedUserTaskValuator(), VALUATORS),
    (TabularTaskUtility({},), UTILITY_FUNCTIONS),
    (LeaveOneOutValuator(), CONTRIBUTION_VALUATORS),
    (ExactShapleyValuator(), CONTRIBUTION_VALUATORS),
    (MonteCarloShapleyValuator(), CONTRIBUTION_VALUATORS),
    (BanzhafValuator(), CONTRIBUTION_VALUATORS),
    (SymbolicValuator(), VALUATORS),
    (LearnedLinearValuator(), TRAINABLE_VALUATORS),
    (GroupShapleyValuator(), CONTRIBUTION_VALUATORS),
    (QualityAdjustedValuator(), VALUATORS),
    (ScenarioValuator(), VALUATORS),
    (RiskAdjustedValuator(), VALUATORS),
    (CounterfactualValuator(), VALUATORS),
    (PortfolioValuator(), VALUATORS),
):
    if _component.spec.name not in _registry:
        _registry.register(_component.spec, type(_component))

__all__ = [
    "CONTRIBUTION_VALUATORS",
    "TRAINABLE_VALUATORS",
    "UTILITY_FUNCTIONS",
    "VALUATORS",
    "ContributionReport",
    "ContributionRequest",
    "ContributionValuator",
    "DataValuator",
    "TrainableValuator",
    "TrainingReport",
    "UtilityFunction",
    "ValuationMode",
    "ValuationReport",
    "ValuationRequest",
    "ValuationTarget",
    "ValueEstimate",
    "BanzhafValuator",
    "ExactShapleyValuator",
    "LeaveOneOutValuator",
    "MonteCarloShapleyValuator",
    "WeightedUserTaskValuator",
    "exact_shapley_values",
    "leave_one_out_values",
    "load_requirements",
    "merge_requirement_bundles",
    "monte_carlo_shapley_values",
    "allocate_value_by_contribution",
    "TabularTaskUtility",
    "LearnedLinearValuator",
    "SymbolicValuator",
    "GroupShapleyValuator",
    "QualityAdjustedValuator",
    "ScenarioValuator",
    "bootstrap_loo_values",
    "group_shapley_values",
    "pairwise_interactions",
    "binary_roc_auc",
    "classification_scores",
    "incremental_gain",
    "ranking_scores",
    "regression_scores",
    "RiskAdjustedValuator",
    "CounterfactualValuator",
    "PortfolioValuator",
    "CalibrationReport",
    "calibrate_values",
    "ValueCurvePoint",
    "build_value_curve",
]
