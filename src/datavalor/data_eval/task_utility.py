"""Task utility evaluators for downstream valuation calls."""

from __future__ import annotations

from datavalor.core import ComponentSpec, DataProduct, RunContext, TaskContext

from .interfaces import TaskUtilityEvaluator
from .models import TaskUtilityResult


class RecordCountUtility(TaskUtilityEvaluator):
    """Simple deterministic utility useful as a baseline and test oracle."""

    @property
    def spec(self) -> ComponentSpec:
        return ComponentSpec("task.record_count", "1.0", "data_eval", "task_utility", capabilities=("deterministic",))

    def evaluate_task(self, product: DataProduct, task: TaskContext, context: RunContext) -> TaskUtilityResult:
        records = task.metadata.get("records", ())
        utility = float(len(records))
        return TaskUtilityResult(product.product_id, task.task_id, utility, "record_count",
                                 diagnostics={"run_id": context.run_id, "source": "task.metadata.records"})


class CallableTaskUtility(TaskUtilityEvaluator):
    """Adapter for a caller-provided utility callable without introducing a runner protocol."""

    def __init__(self, function): self.function = function

    @property
    def spec(self) -> ComponentSpec:
        return ComponentSpec("task.callable", "1.0", "data_eval", "task_utility")

    def evaluate_task(self, product: DataProduct, task: TaskContext, context: RunContext) -> TaskUtilityResult:
        records = task.metadata.get("records", ())
        value = float(self.function(list(records), task, context))
        return TaskUtilityResult(product.product_id, task.task_id, value, task.utility_metric or "utility")


__all__ = ["CallableTaskUtility", "RecordCountUtility"]
