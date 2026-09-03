"""DataEval: reproducible data-quality evaluation."""

from .builtins import (
    CompletenessMetric,
    CompositeEvaluator,
    DuplicateRateMetric,
    FieldValidityMetric,
)
from .interfaces import DataEvaluator, QualityMetric, TaskUtilityEvaluator
from .models import (
    EvaluationReport,
    EvaluationRequest,
    MetricResult,
    ScoreDirection,
    TaskUtilityResult,
)
from .operators import FieldSummaryMetric, LexicalDiversityMetric, lexical_diversity
from .registry import EVALUATORS, QUALITY_METRICS, TASK_UTILITY_EVALUATORS
from .task_utility import CallableTaskUtility, RecordCountUtility

for _component, _registry in (
    (CompletenessMetric, QUALITY_METRICS),
    (DuplicateRateMetric, QUALITY_METRICS),
    (FieldValidityMetric, QUALITY_METRICS),
    (CompositeEvaluator, EVALUATORS),
):
    if _component().spec.name not in _registry:
        _registry.register(_component().spec, _component)

# Optional backends are imported lazily by users from ``data_eval.backends``;
# these names are intentionally not imported here to keep the core import
# dependency-free.

__all__ = [
    "EVALUATORS",
    "QUALITY_METRICS",
    "TASK_UTILITY_EVALUATORS",
    "DataEvaluator",
    "EvaluationReport",
    "EvaluationRequest",
    "MetricResult",
    "QualityMetric",
    "ScoreDirection",
    "TaskUtilityEvaluator",
    "TaskUtilityResult",
    "FieldSummaryMetric",
    "LexicalDiversityMetric",
    "lexical_diversity",
    "CallableTaskUtility",
    "RecordCountUtility",
    "CompletenessMetric",
    "CompositeEvaluator",
    "DuplicateRateMetric",
    "FieldValidityMetric",
]
