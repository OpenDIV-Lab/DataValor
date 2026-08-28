"""DataEval: reproducible data-quality evaluation."""

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
]
