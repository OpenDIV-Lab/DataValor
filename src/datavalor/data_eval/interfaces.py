"""Extension interfaces for DataEval."""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Sequence

from datavalor.core import BaseComponent, DataProduct, RunContext, TaskContext

from .models import EvaluationReport, EvaluationRequest, MetricResult, TaskUtilityResult


class QualityMetric(BaseComponent):
    """Compute one auditable quality metric at a declared granularity."""

    @abstractmethod
    def compute(
        self,
        product: DataProduct,
        request: EvaluationRequest,
        context: RunContext,
    ) -> MetricResult:
        """Compute a metric without converting it into monetary value."""


class DataEvaluator(BaseComponent):
    """Coordinate multiple metrics and return a multi-dimensional report."""

    @abstractmethod
    def evaluate(
        self,
        product: DataProduct,
        request: EvaluationRequest,
        metrics: Sequence[QualityMetric],
        context: RunContext,
    ) -> EvaluationReport:
        """Evaluate a product while retaining individual metric evidence."""


class TaskUtilityEvaluator(BaseComponent):
    """Measure realized model or task utility without assigning a market price."""

    @abstractmethod
    def evaluate_task(
        self,
        product: DataProduct,
        task: TaskContext,
        context: RunContext,
    ) -> TaskUtilityResult:
        """Run a task-aware experiment and return observed utility."""

