"""Practical valuation extensions for risk, counterfactuals and portfolios.

The implementations use only the existing ``ValuationRequest`` and
``ValueEstimate`` models.  They are intentionally transparent so a research
run can inspect every adjustment before a pricing module consumes the result.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import mean
from typing import Any, Sequence

from datavalor.core import ComponentSpec, RunContext

from .interfaces import DataValuator
from .models import ValuationMode, ValuationReport, ValuationRequest, ValueEstimate


def _number(value: Any, default: float = 0.0) -> float:
    try:
        converted = float(value)
    except (TypeError, ValueError):
        return default
    return converted if math.isfinite(converted) else default


def _costs(request: ValuationRequest) -> float:
    costs = request.costs
    if not costs:
        return 0.0
    return sum(_number(getattr(costs, name)) for name in ("acquisition", "preparation", "adoption", "operation"))


class RiskAdjustedValuator(DataValuator):
    """Subtract uncertainty and rights-risk penalties from task value."""

    def __init__(self, base_value: float = 1000.0, risk_aversion: float = 0.5, currency: str = "CNY"):
        if risk_aversion < 0:
            raise ValueError("risk_aversion must be non-negative")
        self.base_value, self.risk_aversion, self.currency = float(base_value), float(risk_aversion), currency

    @property
    def spec(self) -> ComponentSpec:
        return ComponentSpec("valuation.risk_adjusted", "1.0.0", "data_value", "valuator", capabilities=("risk", "uncertainty", "cost_adjusted"))

    def value(self, request: ValuationRequest, context: RunContext) -> ValuationReport:
        vector = request.options.get("evaluation_vector", {})
        quality = _number(vector.get("quality", vector.get("utility", 0.0)))
        quality = max(0.0, min(1.0, quality))
        uncertainty = request.options.get("uncertainty", {})
        std_error = max(0.0, _number(uncertainty.get("std_error", vector.get("std_error", 0.0))))
        rights_multiplier = _number((request.rights.constraints if request.rights else {}).get("multiplier", 1.0), 1.0)
        raw = self.base_value * quality * rights_multiplier
        monetary_std_error = self.base_value * abs(rights_multiplier) * std_error
        lower = uncertainty.get("lower_95", raw - 1.96 * monetary_std_error)
        upper = uncertainty.get("upper_95", raw + 1.96 * monetary_std_error)
        risk_penalty = self.risk_aversion * 1.96 * monetary_std_error
        value = max(0.0, raw - risk_penalty - _costs(request))
        components = {"quality": quality, "raw_value": raw, "risk_penalty": risk_penalty, "rights_multiplier": rights_multiplier, "total_cost": _costs(request)}
        def estimate(target):
            return ValueEstimate(target.target_id, round(value, 6), "monetary", self.currency, components=components, uncertainty={"quality_std_error": std_error, "monetary_std_error": monetary_std_error, "lower_95": _number(lower), "upper_95": _number(upper)}, explanation={"risk_aversion": self.risk_aversion, "confidence_level": 0.95})

        return ValuationReport(request.product.product_id, self.spec.name, ValuationMode.TASK_SPECIFIC, tuple(estimate(target) for target in request.targets), buyer_id=request.buyer.actor_id if request.buyer else None, task_id=request.task.task_id if request.task else context.task_id, diagnostics={"run_id": context.run_id, "uncertainty_source": "request.options.uncertainty"})


class CounterfactualValuator(DataValuator):
    """Value the observed improvement over an explicit baseline vector."""

    def __init__(self, value_per_unit: float = 1000.0, currency: str = "CNY"):
        self.value_per_unit, self.currency = float(value_per_unit), currency

    @property
    def spec(self) -> ComponentSpec:
        return ComponentSpec("valuation.counterfactual", "1.0.0", "data_value", "valuator", capabilities=("counterfactual", "incremental"))

    def value(self, request: ValuationRequest, context: RunContext) -> ValuationReport:
        observed = {str(k): _number(v) for k, v in request.options.get("evaluation_vector", {}).items()}
        baseline = {str(k): _number(v) for k, v in request.options.get("baseline_vector", {}).items()}
        weights = request.options.get("metric_weights", {})
        keys = set(observed) | set(baseline)
        delta = sum(_number(weights.get(key), 1.0) * (observed.get(key, 0.0) - baseline.get(key, 0.0)) for key in keys)
        value = max(0.0, self.value_per_unit * delta - _costs(request))
        components = {"incremental_score": delta, "value_per_unit": self.value_per_unit, "total_cost": _costs(request)}
        estimates = tuple(ValueEstimate(target.target_id, round(value, 6), "monetary", self.currency, components=components, explanation={"observed_vector": observed, "baseline_vector": baseline, "metric_weights": dict(weights)}) for target in request.targets)
        return ValuationReport(request.product.product_id, self.spec.name, ValuationMode.TASK_SPECIFIC, estimates, buyer_id=request.buyer.actor_id if request.buyer else None, task_id=request.task.task_id if request.task else context.task_id, diagnostics={"run_id": context.run_id, "metric_count": len(keys)})


class PortfolioValuator(DataValuator):
    """Aggregate product values with explicit pairwise synergy and risk penalty."""

    def __init__(self, risk_weight: float = 0.1, currency: str = "CNY"):
        self.risk_weight, self.currency = max(0.0, float(risk_weight)), currency

    @property
    def spec(self) -> ComponentSpec:
        return ComponentSpec("valuation.portfolio", "1.0.0", "data_value", "valuator", capabilities=("portfolio", "synergy", "diversification"))

    def value(self, request: ValuationRequest, context: RunContext) -> ValuationReport:
        items = request.options.get("portfolio_items")
        if items is None:
            items = [{"target_id": target.target_id, "value": target.metadata.get("value", 0.0), "uncertainty": target.metadata.get("std_error", 0.0)} for target in request.targets]
        normalized = [{"target_id": str(item.get("target_id", index)), "value": _number(item.get("value")), "uncertainty": abs(_number(item.get("uncertainty"))), "group": str(item.get("group", "default"))} for index, item in enumerate(items)]
        standalone = sum(item["value"] for item in normalized)
        uncertainty = math.sqrt(sum(item["uncertainty"] ** 2 for item in normalized))
        synergies = request.options.get("synergies", {})
        synergy_total = sum(_number(value) for value in synergies.values())
        concentration = 1.0 - max((item["value"] / standalone for item in normalized), default=0.0) if standalone > 0 else 0.0
        value = max(0.0, standalone + synergy_total - self.risk_weight * uncertainty)
        components = {"standalone_value": standalone, "synergy_value": synergy_total, "uncertainty": uncertainty, "risk_penalty": self.risk_weight * uncertainty, "diversification_factor": concentration}
        target_id = request.options.get("portfolio_id", "portfolio")
        estimate = ValueEstimate(str(target_id), round(value, 6), "monetary", self.currency, components=components, uncertainty={"std_error": uncertainty}, explanation={"items": normalized, "synergies": dict(synergies)})
        return ValuationReport(request.product.product_id, self.spec.name, ValuationMode.TASK_SPECIFIC, (estimate,), buyer_id=request.buyer.actor_id if request.buyer else None, task_id=request.task.task_id if request.task else context.task_id, diagnostics={"run_id": context.run_id, "item_count": len(normalized), "group_count": len({item["group"] for item in normalized})})


@dataclass(frozen=True)
class CalibrationReport:
    observations: int
    mae: float
    rmse: float
    bias: float
    mape: float | None
    correlation: float | None


@dataclass(frozen=True)
class ValueCurvePoint:
    size: int
    utility: float
    marginal_utility: float
    cumulative_value: float
    marginal_value: float


def calibrate_values(predicted: Sequence[float], observed: Sequence[float]) -> CalibrationReport:
    """Summarize ex-ante estimates against realized values."""
    if len(predicted) != len(observed) or not predicted:
        raise ValueError("predicted and observed must be non-empty and equally sized")
    pairs = []
    for predicted_value, observed_value in zip(predicted, observed):
        try:
            pair = (float(predicted_value), float(observed_value))
        except (TypeError, ValueError) as exc:
            raise ValueError("calibration values must be finite numbers") from exc
        if not all(math.isfinite(value) for value in pair):
            raise ValueError("calibration values must be finite numbers")
        pairs.append(pair)
    errors = [a - b for a, b in pairs]
    mae = sum(abs(error) for error in errors) / len(errors)
    rmse = math.sqrt(sum(error * error for error in errors) / len(errors))
    mape_values = [abs(error / actual) for error, (_, actual) in zip(errors, pairs) if actual != 0]
    x_mean, y_mean = mean(item[0] for item in pairs), mean(item[1] for item in pairs)
    cross = sum((x - x_mean) * (y - y_mean) for x, y in pairs); var_x = sum((x - x_mean) ** 2 for x, _ in pairs); var_y = sum((y - y_mean) ** 2 for _, y in pairs)
    return CalibrationReport(len(pairs), mae, rmse, sum(errors) / len(errors), sum(mape_values) / len(mape_values) if mape_values else None, cross / math.sqrt(var_x * var_y) if var_x and var_y else None)


def build_value_curve(sizes: Sequence[int], utilities: Sequence[float], total_value: float) -> tuple[ValueCurvePoint, ...]:
    """Build a monotone empirical utility/value curve with marginal values."""
    if len(sizes) != len(utilities) or not sizes:
        raise ValueError("sizes and utilities must be non-empty and equally sized")
    grouped: dict[int, list[float]] = {}
    for raw_size, raw_utility in zip(sizes, utilities):
        size, utility = int(raw_size), float(raw_utility)
        if size < 0 or not math.isfinite(utility):
            raise ValueError("curve sizes must be non-negative and utilities finite")
        grouped.setdefault(size, []).append(utility)
    observations = [(size, sum(values) / len(values), len(values)) for size, values in sorted(grouped.items())]
    blocks: list[dict[str, Any]] = []
    for size, utility, weight in observations:
        blocks.append({"sizes": [size], "value": utility, "weight": weight})
        while len(blocks) >= 2 and blocks[-2]["value"] > blocks[-1]["value"]:
            right, left = blocks.pop(), blocks.pop()
            weight_sum = left["weight"] + right["weight"]
            blocks.append({"sizes": left["sizes"] + right["sizes"], "value": (left["value"] * left["weight"] + right["value"] * right["weight"]) / weight_sum, "weight": weight_sum})
    fitted = {size: block["value"] for block in blocks for size in block["sizes"]}
    maximum = max(fitted.values()) if fitted else 0.0
    scale = float(total_value) / maximum if maximum > 0 else 0.0
    points: list[ValueCurvePoint] = []
    previous_utility = previous_value = 0.0
    for size in sorted(fitted):
        utility, value = fitted[size], max(0.0, fitted[size] * scale)
        points.append(ValueCurvePoint(size, utility, utility - previous_utility, value, value - previous_value))
        previous_utility, previous_value = utility, value
    return tuple(points)


__all__ = ["RiskAdjustedValuator", "CounterfactualValuator", "PortfolioValuator", "CalibrationReport", "ValueCurvePoint", "calibrate_values", "build_value_curve"]
