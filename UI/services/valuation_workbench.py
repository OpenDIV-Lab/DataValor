"""Workbench adapter for directly executable DataValor valuators."""

from __future__ import annotations

from typing import Any

from datavalor.core import DataProduct, DataScope, RunContext
from datavalor.data_value import (
    CounterfactualValuator,
    IncrementalCoverageValuator,
    MarketContextValuator,
    QualityAdjustedValuator,
    RiskAdjustedValuator,
    ScarcityAdjustedValuator,
    ScenarioValuator,
    SubstitutionAdjustedValuator,
    SymbolicValuator,
    TimeDecayValuator,
    UpdateStreamValuator,
    ValuationRequest,
    ValuationTarget,
    WeightedUserTaskValuator,
)


def _field(key: str, label: str, kind: str, default: Any, **extra: Any) -> dict[str, Any]:
    return {"key": key, "label": label, "type": kind, "default": default, **extra}


_BASE_FIELDS = [
    _field("base_value", "价值基数", "number", 100000, min=0),
    _field("currency", "估值币种", "select", "CNY", options=["CNY", "USD", "EUR"]),
]


def _method(label: str, description: str, class_name: str, fields: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "label": label,
        "description": description,
        "implementation": f"datavalor.data_value.{class_name}",
        "fields": _BASE_FIELDS + fields,
    }


_METHODS = {
    "valuation.weighted_user_task": _method(
        "自定义效用向量（任务加权）", "对质量或任务效用向量做透明聚合，再映射为货币价值。", "WeightedUserTaskValuator",
        [_field("evaluation_vector", "效用 / 评估向量", "json", {"quality": 0.9, "task_utility": 0.85})],
    ),
    "valuation.quality_adjusted": _method(
        "质量与新鲜度修正", "以质量、独特性和新鲜度修正价值基数。", "QualityAdjustedValuator",
        [_field("evaluation_vector", "质量信号", "json", {"quality": 0.9, "uniqueness": 0.8, "freshness": 0.9}), _field("quality_floor", "质量因子下限", "number", 0.5, min=0), _field("freshness_weight", "新鲜度权重", "number", 0.2, min=0)],
    ),
    "valuation.scenario": _method(
        "情景估值", "在基准、保守和乐观等假设下输出价值区间。", "ScenarioValuator",
        [_field("evaluation_vector", "基准质量信号", "json", {"quality": 0.85, "freshness": 0.9}), _field("scenarios", "情景覆盖", "json", {"base": {}, "conservative": {"quality": 0.7}, "optimistic": {"quality": 1.0}})],
    ),
    "valuation.risk_adjusted": _method(
        "风险调整估值", "基于估值不确定性、权利风险和成本扣减风险溢价。", "RiskAdjustedValuator",
        [_field("evaluation_vector", "质量信号", "json", {"quality": 0.85}), _field("uncertainty", "不确定性", "json", {"std_error": 0.05}), _field("risk_aversion", "风险厌恶系数", "number", 0.5, min=0)],
    ),
    "valuation.counterfactual": _method(
        "反事实增量估值", "按相对基线的任务指标增益估算增量价值。", "CounterfactualValuator",
        [_field("evaluation_vector", "使用数据后的指标", "json", {"accuracy": 0.9}), _field("baseline_vector", "不使用数据的基线指标", "json", {"accuracy": 0.75}), _field("metric_weights", "指标权重", "json", {"accuracy": 1})],
    ),
    "valuation.symbolic": _method(
        "符号价值函数", "使用受限安全表达式显式定义信号到价值的映射。", "SymbolicValuator",
        [_field("evaluation_vector", "表达式变量", "json", {"quality": 0.9, "freshness": 0.8}), _field("expression", "价值表达式", "text", "base_value * quality")],
    ),
    "valuation.market_context": _method(
        "市场环境估值", "联合需求匹配、质量、新鲜度、稀缺性、权利与供应稳定性。", "MarketContextValuator",
        [_field("market_factors", "市场因子", "json", {"demand_fit": 0.9, "quality": 0.9, "freshness": 0.85, "scarcity": 0.5, "rights": 1, "supply_stability": 0.9}), _field("factor_floor", "乘数下限", "number", 0, min=0, max=1), _field("scarcity_weight", "稀缺性权重", "number", 0.25, min=0), _field("risk_penalty", "风险扣减", "number", 0, min=0)],
    ),
    "valuation.scarcity_adjusted": _method(
        "稀缺性修正估值", "仅在与任务相关时赋予稀缺覆盖溢价。", "ScarcityAdjustedValuator",
        [_field("scarcity", "稀缺程度", "number", 0.5, min=0, max=1), _field("task_relevance", "任务相关度", "number", 0.9, min=0, max=1), _field("scarcity_weight", "稀缺性权重", "number", 0.5, min=0)],
    ),
    "valuation.incremental_coverage": _method(
        "增量覆盖估值", "只计量买方现有数据之外的新覆盖价值。", "IncrementalCoverageValuator",
        [_field("incremental_coverage", "新增覆盖率", "number", 0.6, min=0, max=1), _field("quality", "覆盖质量", "number", 0.9, min=0, max=1), _field("task_relevance", "任务相关度", "number", 0.9, min=0, max=1), _field("coverage_dimensions", "分维度覆盖（可选）", "json", {})],
    ),
    "valuation.substitution_adjusted": _method(
        "替代品修正估值", "依据可用替代品覆盖与质量折减资产价值。", "SubstitutionAdjustedValuator",
        [_field("substitutes", "替代品列表", "json", [{"coverage": 0.2, "quality_ratio": 0.8, "task_relevance": 1, "available": True}]), _field("unique_fraction", "独有价值比例", "number", 0.8, min=0, max=1)],
    ),
    "valuation.time_decay": _method(
        "时间衰减估值", "使用任务半衰期对时效性价值做指数衰减。", "TimeDecayValuator",
        [_field("age_days", "数据年龄（天）", "number", 7, min=0), _field("half_life_days", "价值半衰期（天）", "number", 30, min=0.01), _field("time_sensitivity", "任务时效敏感度", "number", 1, min=0, max=1)],
    ),
    "valuation.update_stream": _method(
        "更新流估值", "折现有限更新流中每期数据增量的预期价值。", "UpdateStreamValuator",
        [_field("updates", "更新计划", "json", [{"period": 0, "marginal_value": 60000, "delivery_probability": 1, "quality": 0.9}, {"period": 1, "marginal_value": 40000, "delivery_probability": 0.9, "quality": 0.9}]), _field("discount_rate", "每期折现率", "number", 0.05, min=-0.99)],
    ),
}


def valuation_schema() -> dict[str, Any]:
    return {"default_method": "valuation.weighted_user_task", "methods": _METHODS}


def run_valuation(product: DataProduct, parameters: dict[str, Any], context: RunContext):
    method = str(parameters.get("method", "valuation.weighted_user_task"))
    if method not in _METHODS:
        raise ValueError(f"unknown valuation method: {method}")
    base_value = float(parameters.get("base_value", 1000))
    currency = str(parameters.get("currency", "CNY"))

    if method == "valuation.weighted_user_task":
        valuator = WeightedUserTaskValuator(base_value, currency)
    elif method == "valuation.quality_adjusted":
        valuator = QualityAdjustedValuator(base_value, currency, quality_floor=float(parameters.get("quality_floor", 0.5)), freshness_weight=float(parameters.get("freshness_weight", 0.2)))
    elif method == "valuation.scenario":
        valuator = ScenarioValuator(parameters.get("scenarios"), base_value=base_value, currency=currency)
    elif method == "valuation.risk_adjusted":
        valuator = RiskAdjustedValuator(base_value, float(parameters.get("risk_aversion", 0.5)), currency)
    elif method == "valuation.counterfactual":
        valuator = CounterfactualValuator(base_value, currency)
    elif method == "valuation.symbolic":
        valuator = SymbolicValuator(str(parameters.get("expression", "base_value * quality")), base_value=base_value, currency=currency)
    elif method == "valuation.market_context":
        valuator = MarketContextValuator(base_value, currency, float(parameters.get("factor_floor", 0)))
    elif method == "valuation.scarcity_adjusted":
        valuator = ScarcityAdjustedValuator(base_value, float(parameters.get("scarcity_weight", 0.5)), currency)
    elif method == "valuation.incremental_coverage":
        valuator = IncrementalCoverageValuator(base_value, currency)
    elif method == "valuation.substitution_adjusted":
        valuator = SubstitutionAdjustedValuator(base_value, currency)
    elif method == "valuation.time_decay":
        valuator = TimeDecayValuator(base_value, float(parameters.get("half_life_days", 30)), currency)
    else:
        valuator = UpdateStreamValuator(currency)

    options = {key: value for key, value in parameters.items() if key not in {"method", "base_value", "currency"}}
    request = ValuationRequest(
        product,
        (ValuationTarget(product.product_id, product.product_id, DataScope.PRODUCT),),
        rights=product.rights,
        options=options,
    )
    report = valuator.value(request, context)
    return report, valuator.spec.name


__all__ = ["run_valuation", "valuation_schema"]
