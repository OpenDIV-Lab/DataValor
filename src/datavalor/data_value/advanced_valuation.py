"""Scenario and quality-adjusted monetary valuators."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping

from datavalor.core import ComponentSpec, RunContext

from .interfaces import DataValuator
from .models import ValuationMode, ValuationReport, ValuationRequest, ValueEstimate
from .value_functions import _features


class QualityAdjustedValuator(DataValuator):
    """Apply explicit quality, freshness, rights and cost factors to task value."""

    def __init__(self, base_value: float = 1000.0, currency: str = "CNY", *, quality_floor: float = 0.5, freshness_weight: float = 0.2) -> None:
        self.base_value, self.currency = float(base_value), currency
        self.quality_floor, self.freshness_weight = max(0.0, float(quality_floor)), max(0.0, float(freshness_weight))

    @property
    def spec(self) -> ComponentSpec:
        return ComponentSpec("valuation.quality_adjusted", "1.0.0", "data_value", "valuator", capabilities=("quality", "freshness", "cost_adjusted"))

    def value(self, request: ValuationRequest, context: RunContext) -> ValuationReport:
        features = _features(request)
        quality = max(0.0, min(1.0, features.get("quality", 0.0)))
        uniqueness = max(0.0, min(1.0, features.get("uniqueness", 1.0)))
        freshness = max(0.0, min(1.0, features.get("freshness", 1.0)))
        task_factor = 0.7 * quality + 0.3 * uniqueness
        quality_factor = self.quality_floor + (1.0 - self.quality_floor) * task_factor
        freshness_factor = (1.0 - self.freshness_weight) + self.freshness_weight * freshness
        rights_factor = float((request.rights.constraints if request.rights else {}).get("multiplier", 1.0))
        buyer_factor = features.get("buyer_multiplier", 1.0)
        preparation = float(request.costs.preparation or 0.0) if request.costs and request.costs.preparation is not None else 0.0
        adoption = float(request.costs.adoption or 0.0) if request.costs and request.costs.adoption is not None else 0.0
        raw = self.base_value * quality_factor * freshness_factor * rights_factor * buyer_factor
        value = max(0.0, raw - preparation - adoption)
        components = {"task_factor": task_factor, "quality_factor": quality_factor, "freshness_factor": freshness_factor, "rights_factor": rights_factor, "buyer_factor": buyer_factor, "raw_value": raw, "preparation_cost": preparation, "adoption_cost": adoption}
        estimates = tuple(ValueEstimate(target.target_id, round(value, 6), "monetary", self.currency, components=components, explanation={"quality_floor": self.quality_floor, "freshness_weight": self.freshness_weight}) for target in request.targets)
        return ValuationReport(request.product.product_id, self.spec.name, ValuationMode.TASK_SPECIFIC, estimates, buyer_id=request.buyer.actor_id if request.buyer else None, task_id=request.task.task_id if request.task else context.task_id, diagnostics={"run_id": context.run_id})


class ScenarioValuator(DataValuator):
    """Evaluate one request under named assumptions and expose value ranges."""

    def __init__(self, scenarios: Mapping[str, Mapping[str, Any]] | None = None, *, base_value: float = 1000.0, currency: str = "CNY") -> None:
        self.scenarios = dict(scenarios or {"base": {}, "conservative": {"quality": 0.8}, "optimistic": {"quality": 1.0}})
        self.base_value, self.currency = float(base_value), currency

    @property
    def spec(self) -> ComponentSpec:
        return ComponentSpec("valuation.scenario", "1.0.0", "data_value", "valuator", capabilities=("scenario", "sensitivity", "range"))

    def value(self, request: ValuationRequest, context: RunContext) -> ValuationReport:
        estimates = []
        scenario_values: dict[str, float] = {}
        for name, overrides in self.scenarios.items():
            vector = dict(request.options.get("evaluation_vector", {})); vector.update({key: value for key, value in overrides.items() if key != "adoption_cost"})
            options = {**request.options, "evaluation_vector": vector}
            if "adoption_cost" in overrides:
                options["evaluation_vector"] = {**vector, "adoption_cost": overrides["adoption_cost"]}
            scenario_request = replace(request, options=options)
            result = QualityAdjustedValuator(self.base_value, self.currency).value(scenario_request, context)
            value = result.estimates[0].value if result.estimates else 0.0
            scenario_values[str(name)] = value
            for target in request.targets:
                estimates.append(ValueEstimate(f"{target.target_id}@{name}", value, "monetary", self.currency, components={"scenario_value": value}, explanation={"scenario": str(name), "assumptions": dict(overrides)}))
        values = list(scenario_values.values())
        return ValuationReport(request.product.product_id, self.spec.name, ValuationMode.TASK_SPECIFIC, tuple(estimates), buyer_id=request.buyer.actor_id if request.buyer else None, task_id=request.task.task_id if request.task else context.task_id, diagnostics={"run_id": context.run_id, "scenario_values": scenario_values, "lower_bound": min(values) if values else 0.0, "upper_bound": max(values) if values else 0.0})


__all__ = ["QualityAdjustedValuator", "ScenarioValuator"]
