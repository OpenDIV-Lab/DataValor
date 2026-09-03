"""Transparent task-aware valuators migrated to DataValor models."""

from __future__ import annotations

from datavalor.core import ComponentSpec

from .interfaces import DataValuator
from .models import ValuationMode, ValuationReport, ValuationRequest, ValueEstimate


class WeightedUserTaskValuator(DataValuator):
    """Estimate value from metric weights, buyer multiplier, rights and costs."""

    def __init__(self, base_value: float = 1000.0, currency: str = "CNY"):
        self.base_value, self.currency = float(base_value), currency

    @property
    def spec(self) -> ComponentSpec:
        return ComponentSpec("valuation.weighted_user_task", "1.0", "data_value", "valuator")

    def value(self, request: ValuationRequest, context) -> ValuationReport:
        metrics = request.options.get("evaluation_vector", {})
        weights = (request.task.metadata.get("metric_weights", {}) if request.task else {})
        if weights:
            denominator = sum(abs(float(weight)) for weight in weights.values())
            quality = sum(float(weight) * float(metrics.get(name, 0.0)) for name, weight in weights.items()) / denominator if denominator else 0.0
        else:
            quality = sum(float(value) for value in metrics.values()) / max(1, len(metrics))
        user_multiplier = float((request.buyer.preferences if request.buyer else {}).get("value_multiplier", 1.0))
        rights_multiplier = float((request.rights.constraints if request.rights else {}).get("multiplier", 1.0))
        adoption_cost = float(request.costs.adoption or 0.0) if request.costs and request.costs.adoption is not None else 0.0
        raw = self.base_value * quality * user_multiplier * rights_multiplier
        value = max(0.0, raw - adoption_cost)
        estimates = tuple(ValueEstimate(target.target_id, round(value, 6), "monetary", self.currency,
                                        components={"weighted_quality": quality, "base_value": self.base_value, "raw_value": raw, "adoption_cost": adoption_cost},
                                        explanation={"metric_weights": weights}) for target in request.targets)
        return ValuationReport(request.product.product_id, self.spec.name, ValuationMode.TASK_SPECIFIC, estimates,
                               request.buyer.actor_id if request.buyer else None, request.task.task_id if request.task else None,
                               diagnostics={"run_id": context.run_id})


__all__ = ["WeightedUserTaskValuator"]
