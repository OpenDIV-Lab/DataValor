"""Representative synthetic scenarios for the local DataValor workbench."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .workspace import Workspace


def _product(
    product_id: str,
    title: str,
    owner: str,
    records: list[dict[str, Any]],
    *,
    purposes: list[str],
    commercial_use: bool,
    quality: float,
    freshness: float,
    asking_price: float,
    description: str,
    tags: list[str],
    jurisdiction: str = "CN",
) -> dict[str, Any]:
    return {
        "product_id": product_id,
        "title": title,
        "owner_id": owner,
        "version": "2026.10",
        "description": description,
        "data": {
            "uri": f"memory://scenario/{product_id}",
            "format": "records",
            "record_count": len(records),
            "media_type": "application/json",
        },
        "rights": {
            "purposes": purposes,
            "commercial_use": commercial_use,
            "redistribution": False,
            "exclusivity": False,
            "jurisdictions": [jurisdiction],
            "constraints": {"synthetic_demo_only": True},
        },
        "metadata": {
            "quality": quality,
            "freshness": freshness,
            "asking_price": asking_price,
            "currency": "CNY",
            "synthetic": True,
            "record_count": len(records),
        },
        "tags": tags,
        "records": records,
    }


_SCENARIOS: tuple[dict[str, Any], ...] = (
    {
        "scenario_id": "ai-training",
        "name": "AI 训练数据采购",
        "domain": "人工智能",
        "icon": "spark",
        "summary": "比较多源训练语料的任务效用、贡献价值、许可报价与预算采购结果。",
        "decision": "在 30 万元预算内选择可用于商业模型训练的数据组合。",
        "buyer": "基础模型团队",
        "currency": "CNY",
        "data_notice": "Synthetic records for workflow testing; not production training data.",
        "default_operations": ["governance", "evaluation", "valuation", "pricing", "market"],
        "operation_parameters": {
            "governance": {"operation": "model_training"},
            "evaluation": {"required_fields": ["prompt", "response"]},
            "valuation": {"base_value": 140000, "evaluation_vector": {"task_utility": 0.88, "quality": 0.91}, "product_signals": ["quality", "freshness"]},
            "pricing": {"model": "pricing.rights_differentiated", "base_price": 90000},
            "market": {
                "mechanism": "bundle_matching",
                "budget": 300000,
                "bids": [{"buyer_id": "foundation-model-team", "product_ids": ["ai-legal-qa", "ai-code-reasoning"], "amount": 245000, "budget": 300000, "constraints": {"bundle_mode": "and"}}],
                "asks": [
                    {"seller_id": "legal-publisher", "product_ids": ["ai-legal-qa"], "reserve": 98000, "metadata": {"quality": 0.93}},
                    {"seller_id": "code-community", "product_ids": ["ai-code-reasoning"], "reserve": 105000, "metadata": {"quality": 0.89}},
                    {"seller_id": "vision-studio", "product_ids": ["ai-vision-instruction"], "reserve": 76000, "metadata": {"quality": 0.84}},
                ],
            },
        },
        "products": [
            _product("ai-legal-qa", "中文法律问答语料", "legal-publisher", [{"prompt": "合同解除条件", "response": "示例答复", "domain": "contract"}, {"prompt": "数据许可范围", "response": "示例答复", "domain": "data-law"}], purposes=["model_training", "evaluation"], commercial_use=True, quality=0.93, freshness=0.82, asking_price=98000, description="经编辑审核的中文法律问答对。", tags=["text", "legal", "instruction"]),
            _product("ai-code-reasoning", "代码推理与单元测试集", "code-community", [{"prompt": "修复边界条件", "response": "assert result == 0", "language": "python"}, {"prompt": "解释复杂度", "response": "O(n log n)", "language": "python"}], purposes=["model_training", "evaluation"], commercial_use=True, quality=0.89, freshness=0.94, asking_price=105000, description="带测试反馈的代码推理样本。", tags=["code", "reasoning", "tests"]),
            _product("ai-vision-instruction", "工业视觉指令对", "vision-studio", [{"prompt": "定位表面裂纹", "response": "bbox: 18,42,66,91", "modality": "image"}, {"prompt": "判断焊点质量", "response": "pass", "modality": "image"}], purposes=["model_training"], commercial_use=True, quality=0.84, freshness=0.76, asking_price=76000, description="合成工业图像描述与定位标注。", tags=["vision", "industrial", "multimodal"]),
        ],
    },
    {
        "scenario_id": "retail-demand",
        "name": "零售需求数据订阅",
        "domain": "零售与供应链",
        "icon": "pulse",
        "summary": "联合门店销量、促销和天气信号，比较新鲜度调整后的价值与订阅报价。",
        "decision": "为区域补货模型选择季度数据订阅组合。",
        "buyer": "连锁零售分析中心",
        "currency": "CNY",
        "data_notice": "Synthetic records for workflow testing; not observed customer transactions.",
        "default_operations": ["governance", "profile", "evaluation", "valuation", "pricing", "market"],
        "operation_parameters": {
            "governance": {"operation": "analytics"},
            "evaluation": {"required_fields": ["region", "date"]},
            "valuation": {"base_value": 110000, "evaluation_vector": {"forecast_gain": 0.84, "coverage": 0.9}, "product_signals": ["quality", "freshness"]},
            "pricing": {"model": "pricing.subscription", "period_fee": 52000, "included_usage": 1000, "usage": 1250, "overage_unit_price": 18},
            "market": {
                "mechanism": "bundle_matching",
                "budget": 210000,
                "bids": [{"buyer_id": "retail-analytics", "product_ids": ["retail-pos-demand", "retail-promotion-calendar", "retail-local-weather"], "amount": 192000, "budget": 210000, "constraints": {"bundle_mode": "and"}}],
                "asks": [
                    {"seller_id": "store-network", "product_ids": ["retail-pos-demand"], "reserve": 72000},
                    {"seller_id": "campaign-platform", "product_ids": ["retail-promotion-calendar"], "reserve": 43000},
                    {"seller_id": "weather-provider", "product_ids": ["retail-local-weather"], "reserve": 36000},
                ],
            },
        },
        "products": [
            _product("retail-pos-demand", "门店 SKU 日销量", "store-network", [{"region": "华东", "date": "2026-10-18", "sku": "A-104", "units": 128}, {"region": "华南", "date": "2026-10-18", "sku": "B-220", "units": 94}, {"region": "华北", "date": "2026-10-18", "sku": "A-104", "units": 81}], purposes=["analytics", "forecasting"], commercial_use=True, quality=0.96, freshness=0.98, asking_price=72000, description="聚合到门店与 SKU 的日级需求信号。", tags=["tabular", "demand", "daily"]),
            _product("retail-promotion-calendar", "渠道促销活动日历", "campaign-platform", [{"region": "华东", "date": "2026-10-18", "campaign": "会员日", "discount": 0.15}, {"region": "华南", "date": "2026-10-20", "campaign": "新品周", "discount": 0.1}], purposes=["analytics", "forecasting"], commercial_use=True, quality=0.88, freshness=0.91, asking_price=43000, description="跨渠道促销窗口及力度。", tags=["events", "promotion", "calendar"]),
            _product("retail-local-weather", "商圈小时级天气", "weather-provider", [{"region": "华东", "date": "2026-10-18", "temperature": 22.1, "rain_mm": 3.2}, {"region": "华南", "date": "2026-10-18", "temperature": 28.4, "rain_mm": 0.0}], purposes=["analytics", "forecasting"], commercial_use=True, quality=0.91, freshness=0.99, asking_price=36000, description="面向商圈聚合的短时天气观测。", tags=["stream", "weather", "hourly"]),
            _product("retail-footfall-index", "匿名客流指数", "mall-consortium", [{"region": "华东", "date": "2026-10-18", "footfall_index": 112.4}, {"region": "华南", "date": "2026-10-18", "footfall_index": 97.8}], purposes=["analytics"], commercial_use=True, quality=0.79, freshness=0.87, asking_price=31000, description="经匿名化处理的商圈相对客流指数。", tags=["mobility", "index", "privacy"]),
        ],
    },
    {
        "scenario_id": "industrial-sensor",
        "name": "工业传感数据采购",
        "domain": "工业制造",
        "icon": "gear",
        "summary": "按可靠性、采样延迟和维护覆盖比较设备信号，并执行质量感知采购。",
        "decision": "为预测性维护服务选择质量成本比最优的数据源。",
        "buyer": "设备健康平台",
        "currency": "CNY",
        "data_notice": "Synthetic records for workflow testing; not measurements from operating equipment.",
        "default_operations": ["governance", "profile", "evaluation", "valuation", "pricing", "market"],
        "operation_parameters": {
            "governance": {"operation": "predictive_maintenance"},
            "evaluation": {"required_fields": ["machine_id", "timestamp"]},
            "valuation": {"base_value": 180000, "evaluation_vector": {"downtime_avoidance": 0.86, "reliability": 0.92}, "product_signals": ["quality", "freshness"]},
            "pricing": {"model": "pricing.quality_freshness", "base_price": 125000, "quality": 0.91, "freshness": 0.96},
            "market": {
                "mechanism": "quality_aware_procurement",
                "budget": 240000,
                "buyer_id": "equipment-health-platform",
                "asks": [
                    {"seller_id": "plant-a", "product_ids": ["industry-vibration"], "reserve": 92000, "metadata": {"quality": 0.95}},
                    {"seller_id": "maintenance-vendor", "product_ids": ["industry-maintenance-log"], "reserve": 68000, "metadata": {"quality": 0.86}},
                    {"seller_id": "energy-operator", "product_ids": ["industry-energy-signals"], "reserve": 57000, "metadata": {"quality": 0.89}},
                ],
            },
        },
        "products": [
            _product("industry-vibration", "产线振动时序", "plant-a", [{"machine_id": "M-07", "timestamp": "2026-10-20T08:00:00Z", "rms": 2.41, "kurtosis": 3.8}, {"machine_id": "M-11", "timestamp": "2026-10-20T08:00:00Z", "rms": 1.72, "kurtosis": 2.9}], purposes=["predictive_maintenance", "analytics"], commercial_use=True, quality=0.95, freshness=0.99, asking_price=92000, description="轴承与电机振动统计特征流。", tags=["timeseries", "vibration", "high-frequency"]),
            _product("industry-maintenance-log", "设备维修工单", "maintenance-vendor", [{"machine_id": "M-07", "timestamp": "2026-10-02T09:30:00Z", "fault": "bearing", "downtime_h": 3.4}, {"machine_id": "M-11", "timestamp": "2026-09-19T14:00:00Z", "fault": "alignment", "downtime_h": 1.2}], purposes=["predictive_maintenance"], commercial_use=True, quality=0.86, freshness=0.72, asking_price=68000, description="标准化维修原因与停机时长。", tags=["events", "maintenance", "labels"]),
            _product("industry-energy-signals", "设备能耗与负载", "energy-operator", [{"machine_id": "M-07", "timestamp": "2026-10-20T08:00:00Z", "kw": 42.8, "load": 0.82}, {"machine_id": "M-11", "timestamp": "2026-10-20T08:00:00Z", "kw": 31.5, "load": 0.68}], purposes=["predictive_maintenance", "energy_optimization"], commercial_use=True, quality=0.89, freshness=0.97, asking_price=57000, description="设备级电力和负载曲线。", tags=["timeseries", "energy", "load"]),
        ],
    },
    {
        "scenario_id": "clinical-research",
        "name": "临床研究数据许可",
        "domain": "医疗健康",
        "icon": "cross",
        "summary": "在用途、地域和去标识约束下评估多中心研究数据的效用、风险与许可价格。",
        "decision": "选择满足研究方案且可审计的数据许可组合。",
        "buyer": "多中心研究协作组",
        "currency": "CNY",
        "data_notice": "Synthetic records for workflow testing; no patient or protected health information.",
        "default_operations": ["governance", "profile", "evaluation", "valuation", "pricing"],
        "operation_parameters": {
            "governance": {"operation": "clinical_research"},
            "evaluation": {"required_fields": ["cohort_id", "visit"]},
            "valuation": {"base_value": 220000, "evaluation_vector": {"endpoint_coverage": 0.83, "quality": 0.94}, "product_signals": ["quality", "freshness"]},
            "pricing": {"model": "pricing.risk_adjusted", "estimated_value": 220000, "std_error": 18000, "buyer_share": 0.5, "rights_factor": 0.82, "ceiling": 180000},
        },
        "products": [
            _product("clinical-lab-panel", "纵向实验室指标", "hospital-consortium", [{"cohort_id": "SYN-101", "visit": "baseline", "marker_a": 4.2, "marker_b": 12.1}, {"cohort_id": "SYN-102", "visit": "month-3", "marker_a": 4.8, "marker_b": 10.9}], purposes=["clinical_research"], commercial_use=False, quality=0.97, freshness=0.78, asking_price=128000, description="去标识化的纵向实验室指标样例。", tags=["tabular", "longitudinal", "controlled"]),
            _product("clinical-image-labels", "影像发现结构化标注", "radiology-network", [{"cohort_id": "SYN-201", "visit": "baseline", "finding": "synthetic-nodule", "confidence": 0.91}, {"cohort_id": "SYN-202", "visit": "follow-up", "finding": "no-change", "confidence": 0.94}], purposes=["clinical_research", "model_evaluation"], commercial_use=False, quality=0.92, freshness=0.75, asking_price=146000, description="合成影像发现及复核置信度。", tags=["imaging", "labels", "controlled"]),
            _product("clinical-outcomes", "随访结局数据", "research-registry", [{"cohort_id": "SYN-101", "visit": "month-6", "endpoint": "stable", "adverse_event": False}, {"cohort_id": "SYN-102", "visit": "month-6", "endpoint": "improved", "adverse_event": False}], purposes=["clinical_research"], commercial_use=False, quality=0.9, freshness=0.68, asking_price=118000, description="合成随访终点与安全性事件。", tags=["outcomes", "registry", "controlled"]),
        ],
    },
)


def scenario_catalog() -> list[dict[str, Any]]:
    """Return an isolated copy so UI callers cannot mutate the built-ins."""
    return deepcopy(list(_SCENARIOS))


def scenario_by_id(scenario_id: str) -> dict[str, Any]:
    for scenario in _SCENARIOS:
        if scenario["scenario_id"] == scenario_id:
            return deepcopy(scenario)
    raise ValueError(f"unknown workbench scenario: {scenario_id}")


def load_scenario(workspace: Workspace, scenario_id: str) -> dict[str, Any]:
    """Idempotently install or refresh the products for one scenario."""
    scenario = scenario_by_id(scenario_id)
    loaded = 0
    updated = 0
    for product in scenario["products"]:
        if workspace.get("products", product["product_id"]) is None:
            loaded += 1
        else:
            updated += 1
        workspace.put("products", product["product_id"], product)
    return {
        "scenario_id": scenario_id,
        "loaded": loaded,
        "updated": updated,
        "product_ids": [product["product_id"] for product in scenario["products"]],
        "scenario": scenario,
    }


__all__ = ["load_scenario", "scenario_by_id", "scenario_catalog"]
