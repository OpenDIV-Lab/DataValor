"""Market-oriented valuation methods using the stable DataValue contracts.

Inputs are supplied through ``ValuationRequest.options`` so the public request
and report schemas remain unchanged.  Every adjustment is exposed in
``ValueEstimate.components`` and no method produces a quote or payment.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from itertools import combinations
from statistics import median
from typing import Any, Mapping, Sequence

from datavalor.core import ComponentSpec, RunContext

from .interfaces import DataValuator
from .models import ValuationMode, ValuationReport, ValuationRequest, ValueEstimate


def _finite(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _unit(value: Any, default: float = 0.0) -> float:
    return min(1.0, max(0.0, _finite(value, default)))


def _costs(request: ValuationRequest) -> float:
    if request.costs is None:
        return 0.0
    return sum(max(0.0, _finite(getattr(request.costs, name))) for name in ("acquisition", "preparation", "adoption", "operation"))


def _report(
    valuator: DataValuator,
    request: ValuationRequest,
    context: RunContext,
    value: float,
    components: Mapping[str, float],
    explanation: Mapping[str, Any],
    *,
    currency: str,
    uncertainty: Mapping[str, float] | None = None,
    diagnostics: Mapping[str, Any] | None = None,
) -> ValuationReport:
    estimates = tuple(
        ValueEstimate(
            target.target_id,
            round(max(0.0, value), 6),
            "monetary",
            currency,
            components=dict(components),
            uncertainty=dict(uncertainty or {}),
            explanation=dict(explanation),
        )
        for target in request.targets
    )
    return ValuationReport(
        request.product.product_id,
        valuator.spec.name,
        ValuationMode.MARKET_ORIENTED,
        estimates,
        buyer_id=request.buyer.actor_id if request.buyer else None,
        task_id=request.task.task_id if request.task else context.task_id,
        diagnostics={"run_id": context.run_id, **dict(diagnostics or {})},
    )


class MarketContextValuator(DataValuator):
    """Combine explicit market-relevant factors without hiding their effects."""

    def __init__(self, base_value: float = 1000.0, currency: str = "CNY", factor_floor: float = 0.0):
        if base_value < 0 or not 0 <= factor_floor <= 1:
            raise ValueError("base_value must be non-negative and factor_floor in [0, 1]")
        self.base_value, self.currency, self.factor_floor = float(base_value), currency, float(factor_floor)

    @property
    def spec(self):
        return ComponentSpec("valuation.market_context", "1.0.0", "data_value", "valuator", capabilities=("demand_fit", "scarcity", "rights", "market"))

    def value(self, request, context):
        vector = request.options.get("market_factors", request.options.get("evaluation_vector", {}))
        names = ("demand_fit", "quality", "freshness", "scarcity", "rights", "supply_stability")
        defaults = {"demand_fit": 1.0, "quality": 1.0, "freshness": 1.0, "scarcity": 0.0, "rights": 1.0, "supply_stability": 1.0}
        factors = {name: _unit(vector.get(name, defaults[name]), defaults[name]) for name in names}
        scarcity_weight = max(0.0, _finite(request.options.get("scarcity_weight", 0.25), 0.25))
        scarcity_multiplier = 1.0 + scarcity_weight * factors["scarcity"] * factors["demand_fit"]
        multipliers = {name: max(self.factor_floor, factors[name]) for name in ("demand_fit", "quality", "freshness", "rights", "supply_stability")}
        gross = self.base_value * math.prod(multipliers.values()) * scarcity_multiplier
        risk_penalty = max(0.0, _finite(request.options.get("risk_penalty")))
        total_cost = _costs(request)
        value = gross - risk_penalty - total_cost
        components = {"base_value": self.base_value, **{f"{name}_factor": value for name, value in factors.items()}, "scarcity_multiplier": scarcity_multiplier, "gross_value": gross, "risk_penalty": risk_penalty, "total_cost": total_cost}
        return _report(self, request, context, value, components, {"factor_floor": self.factor_floor, "source": "request.options.market_factors"}, currency=self.currency)


class ScarcityAdjustedValuator(DataValuator):
    """Reward scarce coverage only to the extent that it fits the task."""

    def __init__(self, base_value: float = 1000.0, scarcity_weight: float = 0.5, currency: str = "CNY"):
        if scarcity_weight < 0:
            raise ValueError("scarcity_weight must be non-negative")
        self.base_value, self.scarcity_weight, self.currency = float(base_value), float(scarcity_weight), currency

    @property
    def spec(self):
        return ComponentSpec("valuation.scarcity_adjusted", "1.0.0", "data_value", "valuator", capabilities=("scarcity", "task_relevance", "market"))

    def value(self, request, context):
        scarcity = _unit(request.options.get("scarcity", 0.0))
        relevance = _unit(request.options.get("task_relevance", request.options.get("demand_fit", 1.0)), 1.0)
        multiplier = 1.0 + self.scarcity_weight * scarcity * relevance
        total_cost = _costs(request); value = self.base_value * relevance * multiplier - total_cost
        return _report(self, request, context, value, {"base_value": self.base_value, "scarcity": scarcity, "task_relevance": relevance, "scarcity_multiplier": multiplier, "total_cost": total_cost}, {"principle": "scarcity premium is gated by task relevance"}, currency=self.currency)


class IncrementalCoverageValuator(DataValuator):
    """Value only coverage not already available to the buyer."""

    def __init__(self, value_per_coverage_unit: float = 1000.0, currency: str = "CNY"):
        self.value_per_coverage_unit, self.currency = float(value_per_coverage_unit), currency

    @property
    def spec(self):
        return ComponentSpec("valuation.incremental_coverage", "1.0.0", "data_value", "valuator", capabilities=("incremental", "overlap", "coverage"))

    def value(self, request, context):
        dimensions = request.options.get("coverage_dimensions", {})
        if dimensions:
            weights = request.options.get("coverage_weights", {})
            total_weight = sum(max(0.0, _finite(weights.get(name), 1.0)) for name in dimensions)
            incremental = sum(_unit(value) * max(0.0, _finite(weights.get(name), 1.0)) for name, value in dimensions.items()) / total_weight if total_weight else 0.0
        else:
            incremental = _unit(request.options.get("incremental_coverage", 1.0 - _unit(request.options.get("overlap", 0.0))), 1.0)
            weights = {}
        quality = _unit(request.options.get("quality", 1.0), 1.0)
        relevance = _unit(request.options.get("task_relevance", 1.0), 1.0)
        gross = self.value_per_coverage_unit * incremental * quality * relevance
        total_cost = _costs(request)
        return _report(self, request, context, gross - total_cost, {"value_per_coverage_unit": self.value_per_coverage_unit, "incremental_coverage": incremental, "quality_factor": quality, "task_relevance": relevance, "gross_value": gross, "total_cost": total_cost}, {"coverage_dimensions": dict(dimensions), "coverage_weights": dict(weights)}, currency=self.currency)


class SubstitutionAdjustedValuator(DataValuator):
    """Discount value when a cheaper or already-owned substitute covers the task."""

    def __init__(self, base_value: float = 1000.0, currency: str = "CNY"):
        self.base_value, self.currency = float(base_value), currency

    @property
    def spec(self):
        return ComponentSpec("valuation.substitution_adjusted", "1.0.0", "data_value", "valuator", capabilities=("substitution", "alternatives", "market"))

    def value(self, request, context):
        substitutes = tuple(request.options.get("substitutes", ()))
        effective = [
            _unit(item.get("coverage", 0.0)) * _unit(item.get("quality_ratio", 1.0), 1.0) * _unit(item.get("task_relevance", 1.0), 1.0)
            for item in substitutes
            if item.get("available", True)
        ]
        best = max(effective, default=0.0)
        unique_fraction = _unit(request.options.get("unique_fraction", 1.0 - best), 1.0 - best)
        retention = max(unique_fraction, 1.0 - best)
        gross = self.base_value * retention; total_cost = _costs(request)
        return _report(self, request, context, gross - total_cost, {"base_value": self.base_value, "best_substitute_score": best, "unique_fraction": unique_fraction, "retention_factor": retention, "gross_value": gross, "total_cost": total_cost}, {"substitute_count": len(substitutes), "effective_substitute_scores": tuple(effective)}, currency=self.currency)


class TimeDecayValuator(DataValuator):
    """Apply exponential value decay using an explicit task half-life."""

    def __init__(self, base_value: float = 1000.0, half_life_days: float = 30.0, currency: str = "CNY"):
        if half_life_days <= 0:
            raise ValueError("half_life_days must be positive")
        self.base_value, self.half_life_days, self.currency = float(base_value), float(half_life_days), currency

    @property
    def spec(self):
        return ComponentSpec("valuation.time_decay", "1.0.0", "data_value", "valuator", capabilities=("time", "freshness", "decay"))

    def value(self, request, context):
        age = max(0.0, _finite(request.options.get("age_days")))
        half_life = _finite(request.options.get("half_life_days"), self.half_life_days)
        if half_life <= 0:
            raise ValueError("half_life_days must be positive")
        decay = 2.0 ** (-age / half_life)
        task_sensitivity = _unit(request.options.get("time_sensitivity", 1.0), 1.0)
        retention = (1.0 - task_sensitivity) + task_sensitivity * decay
        total_cost = _costs(request); gross = self.base_value * retention
        return _report(self, request, context, gross - total_cost, {"base_value": self.base_value, "age_days": age, "half_life_days": half_life, "time_sensitivity": task_sensitivity, "decay_factor": decay, "retention_factor": retention, "gross_value": gross, "total_cost": total_cost}, {"decay": "exponential_half_life"}, currency=self.currency)


class UpdateStreamValuator(DataValuator):
    """Discount and sum the marginal value of a finite update stream."""

    def __init__(self, currency: str = "CNY"):
        self.currency = currency

    @property
    def spec(self):
        return ComponentSpec("valuation.update_stream", "1.0.0", "data_value", "valuator", capabilities=("updates", "discounted_cash_flow", "marginal_value"))

    def value(self, request, context):
        updates = tuple(request.options.get("updates", ()))
        rate = _finite(request.options.get("discount_rate", 0.0))
        if rate <= -1:
            raise ValueError("discount_rate must be greater than -1")
        contributions = []
        for index, item in enumerate(updates):
            period = max(0, int(item.get("period", index)))
            gross = max(0.0, _finite(item.get("marginal_value"))) * _unit(item.get("delivery_probability", 1.0), 1.0) * _unit(item.get("quality", 1.0), 1.0)
            contributions.append({"period": period, "gross": gross, "present_value": gross / ((1.0 + rate) ** period)})
        gross = sum(item["present_value"] for item in contributions); total_cost = _costs(request)
        return _report(self, request, context, gross - total_cost, {"present_value": gross, "total_cost": total_cost, "discount_rate": rate, "update_count": float(len(updates))}, {"updates": tuple(contributions)}, currency=self.currency)


@dataclass(frozen=True)
class ConsensusValuation:
    value: float
    lower: float
    upper: float
    method_values: Mapping[str, float]
    dispersion: float
    diagnostics: Mapping[str, Any] = field(default_factory=dict)


class ValuationEnsemble:
    """Combine existing reports using robust median or explicit weights."""

    def combine(self, reports: Sequence[ValuationReport], target_id: str, weights: Mapping[str, float] | None = None) -> ConsensusValuation:
        values = {report.method: estimate.value for report in reports for estimate in report.estimates if estimate.target_id == target_id}
        if not values:
            raise ValueError("no estimates found for target_id")
        if weights:
            positive = {name: max(0.0, _finite(weights.get(name))) for name in values}
            denominator = sum(positive.values())
            if denominator <= 0:
                raise ValueError("ensemble weights must contain a positive weight")
            center = sum(values[name] * positive[name] for name in values) / denominator
            method = "weighted_mean"
        else:
            center = median(values.values()); method = "median"
        ordered = sorted(values.values())
        lower = ordered[max(0, math.floor((len(ordered) - 1) * 0.1))]
        upper = ordered[min(len(ordered) - 1, math.ceil((len(ordered) - 1) * 0.9))]
        dispersion = math.sqrt(sum((value - center) ** 2 for value in values.values()) / len(values))
        return ConsensusValuation(center, lower, upper, values, dispersion, {"combination": method, "method_count": len(values)})


@dataclass(frozen=True)
class SensitivityObservation:
    parameter: str
    input_value: float
    estimated_value: float
    delta: float


class ValuationSensitivityAnalyzer:
    """Revalue explicit option perturbations without mutating the request."""

    def analyze(self, valuator: DataValuator, request: ValuationRequest, context: RunContext, scenarios: Mapping[str, Sequence[float]]) -> tuple[SensitivityObservation, ...]:
        baseline_report = valuator.value(request, context)
        baseline = baseline_report.estimates[0].value if baseline_report.estimates else 0.0
        observations = []
        base_factors = dict(request.options.get("market_factors", {}))
        for parameter, values in scenarios.items():
            for input_value in values:
                factors = {**base_factors, parameter: float(input_value)}
                scenario_request = replace(request, options={**request.options, "market_factors": factors})
                report = valuator.value(scenario_request, context)
                estimate = report.estimates[0].value if report.estimates else 0.0
                observations.append(SensitivityObservation(parameter, float(input_value), estimate, estimate - baseline))
        return tuple(observations)


@dataclass(frozen=True)
class PortfolioSelection:
    selected_ids: tuple[str, ...]
    total_cost: float
    total_value: float
    unspent_budget: float
    method: str
    excluded: Mapping[str, str] = field(default_factory=dict)
    diagnostics: Mapping[str, Any] = field(default_factory=dict)


class BudgetConstrainedPortfolioSelector:
    """Select eligible items under a budget using exact enumeration or greedy fallback."""

    def __init__(self, max_exact_items: int = 20):
        if max_exact_items < 1:
            raise ValueError("max_exact_items must be positive")
        self.max_exact_items = max_exact_items

    def select(self, items: Sequence[Mapping[str, Any]], budget: float, *, required_groups: Sequence[str] = ()) -> PortfolioSelection:
        if budget < 0 or not math.isfinite(float(budget)):
            raise ValueError("budget must be finite and non-negative")
        normalized, excluded = [], {}
        for index, item in enumerate(items):
            item_id = str(item.get("item_id", index)); cost = _finite(item.get("cost"), float("nan")); value = _finite(item.get("value"), float("nan"))
            if not math.isfinite(cost) or not math.isfinite(value) or cost < 0 or value < 0:
                excluded[item_id] = "invalid_cost_or_value"
            elif not item.get("eligible", True):
                excluded[item_id] = "ineligible"
            else:
                normalized.append({"item_id": item_id, "cost": cost, "value": value, "group": str(item.get("group", "default"))})
        required = set(required_groups)
        def feasible(selection):
            return sum(item["cost"] for item in selection) <= budget + 1e-9 and required.issubset({item["group"] for item in selection})
        if len(normalized) <= self.max_exact_items:
            candidates = (combo for size in range(len(normalized) + 1) for combo in combinations(normalized, size))
            feasible_sets = [combo for combo in candidates if feasible(combo)]
            chosen = max(feasible_sets, key=lambda combo: (sum(item["value"] for item in combo), -sum(item["cost"] for item in combo), tuple(item["item_id"] for item in combo)), default=())
            method = "exact_enumeration"
        else:
            chosen_list = []
            ordered = sorted(normalized, key=lambda item: (-(item["value"] / item["cost"] if item["cost"] else float("inf")), item["item_id"]))
            for group in sorted(required):
                group_items = [item for item in ordered if item["group"] == group]
                if group_items and feasible((*chosen_list, group_items[0])):
                    chosen_list.append(group_items[0])
            for item in ordered:
                if item in chosen_list:
                    continue
                if feasible((*chosen_list, item)):
                    chosen_list.append(item)
            chosen = tuple(chosen_list); method = "greedy_value_cost"
        total_cost = sum(item["cost"] for item in chosen); total_value = sum(item["value"] for item in chosen)
        missing = sorted(required - {item["group"] for item in chosen})
        return PortfolioSelection(tuple(item["item_id"] for item in chosen), total_cost, total_value, budget - total_cost, method, excluded, {"candidate_count": len(normalized), "required_groups": tuple(required_groups), "missing_required_groups": tuple(missing), "feasible": not missing})


__all__ = [
    "BudgetConstrainedPortfolioSelector", "ConsensusValuation", "IncrementalCoverageValuator",
    "MarketContextValuator", "PortfolioSelection", "ScarcityAdjustedValuator",
    "SensitivityObservation", "SubstitutionAdjustedValuator", "TimeDecayValuator",
    "UpdateStreamValuator", "ValuationEnsemble", "ValuationSensitivityAnalyzer",
]
