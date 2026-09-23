"""Model-aware pricing configuration and attributable execution traces."""

from __future__ import annotations

from typing import Any

from datavalor.data_price import PRICING_MODELS, QuoteRequest


def _field(key: str, label: str, field_type: str = "number", default: Any = 0, **extra: Any) -> dict[str, Any]:
    return {"key": key, "label": label, "type": field_type, "default": default, **extra}


_SCHEMAS: dict[str, dict[str, Any]] = {
    "pricing.cost_plus": {"label": "成本加成", "fields": [_field("preparation_cost", "准备成本", default=40000), _field("operation_cost", "运营成本", default=25000), _field("acquisition_cost", "获取成本"), _field("margin_rate", "利润率", default=0.2)]},
    "pricing.value_based": {"label": "价值分成", "fields": [_field("estimated_value", "估计价值", default=100000), _field("buyer_share", "买方价值分成", default=0.5), _field("floor", "价格下限"), _field("ceiling", "价格上限", default=100000)]},
    "pricing.usage_based": {"label": "按量计费", "fields": [_field("fixed_fee", "固定费用", default=1000), _field("records", "记录数"), _field("queries", "查询次数", default=100), _field("compute_seconds", "计算秒数"), _field("per_record", "每记录单价"), _field("per_query", "每查询单价", default=20), _field("per_compute_second", "每计算秒单价")]},
    "pricing.quality_freshness": {"label": "质量与新鲜度", "fields": [_field("base_price", "基础价格", default=100000), _field("quality", "质量", default=0.9, min=0, max=1), _field("freshness", "新鲜度", default=0.85, min=0, max=1), _field("quality_weight", "质量权重", default=0.7), _field("floor", "价格下限"), _field("ceiling", "价格上限", default=100000)]},
    "pricing.tiered_usage": {"label": "阶梯用量", "fields": [_field("usage", "使用量", default=500)]},
    "pricing.subscription": {"label": "订阅与超额", "fields": [_field("period_fee", "周期费用", default=50000), _field("included_usage", "包含用量", default=1000), _field("usage", "实际用量", default=1200), _field("overage_unit_price", "超额单价", default=20), _field("commitment_discount", "承诺折扣", default=0), _field("billing_period", "结算周期", "select", "month", options=["month", "quarter", "year"])]},
    "pricing.risk_adjusted": {"label": "风险调整", "fields": [_field("estimated_value", "估计价值", default=100000), _field("std_error", "标准误", default=5000), _field("buyer_share", "买方分成", default=0.5), _field("rights_factor", "权利系数", default=1), _field("floor", "下限"), _field("ceiling", "上限", default=100000)]},
    "pricing.price_range": {"label": "价格区间", "fields": [_field("estimated_value", "估计价值", default=100000), _field("value_std_error", "价值标准误", default=5000), _field("cost_floor", "成本下限", default=20000), _field("seller_share", "卖方分成", default=0.5), _field("confidence", "置信度", default=0.9), _field("comparable_price", "可比价格", default=80000), _field("comparable_weight", "可比权重", default=0.25)]},
    "pricing.comparable": {"label": "可比产品", "fields": [_field("target_attributes", "目标属性", "json", {"quality": 0.9}), _field("comparables", "可比产品", "json", [{"comparable_id": "c1", "quality": 0.9, "price": 80000}]), _field("feature_weights", "特征权重", "json", {"quality": 1}), _field("quality_ratio", "质量比", default=1), _field("freshness_ratio", "新鲜度比", default=1), _field("rights_ratio", "权利比", default=1)]},
    "pricing.rights_differentiated": {"label": "权利差异定价", "fields": [_field("base_price", "基础价格", default=100000), _field("commercial_premium", "商业使用溢价", default=0.2), _field("redistribution_premium", "再分发溢价", default=0.3), _field("exclusivity_premium", "独占溢价", default=0.5), _field("per_jurisdiction_premium", "地域溢价", default=0.02), _field("per_year_premium", "年限溢价", default=0.05)]},
    "pricing.freshness_tier": {"label": "新鲜度分层", "fields": [_field("base_price", "基础价格", default=100000), _field("age_days", "数据年龄（天）", default=1)]},
    "pricing.version_delta": {"label": "版本增量", "fields": [_field("previous_price", "上一版本价格", default=80000), _field("incremental_coverage", "增量覆盖", default=0.2), _field("quality_gain", "质量提升", default=0.1), _field("volume_growth", "数据量增长", default=0.1), _field("coverage_weight", "覆盖权重", default=0.5), _field("quality_weight", "质量权重", default=0.3), _field("volume_weight", "数据量权重", default=0.2)]},
    "pricing.expected_revenue": {"label": "期望收入优化", "fields": [_field("candidate_prices", "候选价格", "number_list", [50000, 75000, 100000, 125000]), _field("buyer_budget", "买方预算", default=120000), _field("quality", "质量", default=0.9), _field("freshness", "新鲜度", default=0.85)]},
}


def pricing_schema() -> dict[str, dict[str, Any]]:
    """Return UI-safe fields only for executable repository models."""
    return {name: {**schema, "name": name} for name, schema in _SCHEMAS.items() if name in PRICING_MODELS}


def normalize_pricing_parameters(parameters: dict[str, Any], record_count: int) -> dict[str, Any]:
    model_name = str(parameters.get("model", "pricing.quality_freshness"))
    if model_name not in pricing_schema():
        raise ValueError(f"pricing model is not supported by the workbench: {model_name}")
    fields = pricing_schema()[model_name]["fields"]
    normalized = {field["key"]: field.get("default") for field in fields}
    normalized.update({key: value for key, value in parameters.items() if key not in {"model", "seed"}})
    if "records" in normalized and not normalized["records"]:
        normalized["records"] = record_count
    normalized.setdefault("currency", "CNY")
    return normalized


def run_pricing(product, parameters: dict[str, Any], context, *, record_count: int = 0):
    model_name = str(parameters.get("model", "pricing.quality_freshness"))
    normalized = normalize_pricing_parameters(parameters, record_count)
    model = PRICING_MODELS.create(model_name)
    trace = [
        {"step": "normalize_parameters", "status": "succeeded", "model": model_name, "parameter_count": len(normalized)},
        {"step": "validate_rights", "status": "succeeded", "purposes": list(product.rights.purposes), "commercial_use": product.rights.commercial_use},
    ]
    quote = model.quote(QuoteRequest(product, rights=product.rights, market_context=normalized), context)
    trace.append({"step": "quote", "status": "succeeded", "model": model.spec.name, "component_count": len(quote.components), "amount": str(quote.price.amount), "currency": quote.price.currency})
    return quote, normalized, trace, model.spec.name


__all__ = ["normalize_pricing_parameters", "pricing_schema", "run_pricing"]
