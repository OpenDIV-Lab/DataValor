"""Typed extension registries for DataEval."""

from datavalor.core import Registry

from .interfaces import DataEvaluator, QualityMetric, TaskUtilityEvaluator

QUALITY_METRICS = Registry[QualityMetric]("data_eval.metrics")
EVALUATORS = Registry[DataEvaluator]("data_eval.evaluators")
TASK_UTILITY_EVALUATORS = Registry[TaskUtilityEvaluator]("data_eval.task_utility")

