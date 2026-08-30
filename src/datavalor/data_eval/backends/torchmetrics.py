"""Bridge the stateful TorchMetrics ``update/compute`` protocol to DataValor."""

from __future__ import annotations

from typing import Any, Callable

from datavalor.core import ComponentSpec, DataProduct, RunContext, require_capability

from ..interfaces import QualityMetric
from ..models import EvaluationRequest, MetricResult, ScoreDirection
from ._utils import first_number, records_for


class TorchMetricsAdapter(QualityMetric):
    def __init__(self, metric: Any = None, *, metric_factory: Callable[[], Any] | None = None,
                 target_field: str = "target", prediction_field: str = "prediction", name: str | None = None) -> None:
        self.metric, self.metric_factory = metric, metric_factory
        self.target_field, self.prediction_field, self.name = target_field, prediction_field, name

    @property
    def spec(self) -> ComponentSpec:
        return ComponentSpec("torchmetrics.metric", "0.1.0", "data_eval", "quality_metric",
                             capabilities=("stateful_metric", "aggregation"), requires=("torchmetrics>=1.0",))

    def _metric(self, request: EvaluationRequest) -> Any:
        if self.metric is not None:
            return self.metric
        if self.metric_factory is not None:
            return self.metric_factory()
        factory = request.options.get("metric_factory")
        if callable(factory):
            return factory()
        tm = require_capability("torchmetrics", "torchmetrics", distribution="torchmetrics", extra="torch")
        metric_name = request.options.get("metric")
        if not metric_name:
            raise ValueError("TorchMetricsAdapter needs metric, metric_factory, or metric instance")
        obj = tm
        for part in str(metric_name).split("."):
            obj = getattr(obj, part)
        return obj() if callable(obj) else obj

    def compute(self, product: DataProduct, request: EvaluationRequest, context: RunContext) -> MetricResult:
        metric = self._metric(request)
        rows = records_for(product, request.options)
        targets = request.options.get("targets", [r.get(self.target_field) for r in rows])
        predictions = request.options.get("predictions", [r.get(self.prediction_field) for r in rows])
        update = getattr(metric, "update", None)
        if not callable(update):
            raise TypeError("TorchMetrics object must expose update")
        # TorchMetrics follows the conventional ``update(preds, target)``
        # ordering even though DataValor names the fields target/prediction.
        update(predictions, targets)
        value = first_number(getattr(metric, "compute")())
        return MetricResult(self.name or metric.__class__.__name__.lower(), "task_metric", request.scope, value,
                            ScoreDirection.HIGHER_IS_BETTER, target_id=product.product_id,
                            statistics={"record_count": len(rows)}, diagnostics={"backend": "torchmetrics", "run_id": context.run_id})


TorchMetricAdapter = TorchMetricsAdapter

__all__ = ["TorchMetricsAdapter", "TorchMetricAdapter"]
