"""阶段 4：从估值结果生成报价，并运行拍卖、预算采购与性质检查。

运行：``PYTHONPATH=src python examples/09_stage4_pricing_and_mechanisms.py``

脚本故意把“价值估计”和“市场价格”分开：估值结果只作为 value-based
模型的输入，买方支付仍由明确的报价模型和交易机制决定。
"""

from __future__ import annotations

import json
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path

from datavalor.core import DataProduct, DataReference, RunContext, load_workflow_config
from datavalor.data_price import (
    AdaptiveDemandPricingModel,
    Ask,
    Bid,
    CostPlusPricingModel,
    Money,
    MultiUnitUniformPriceAuction,
    PriceBandConstraint,
    PricingObservation,
    PricingRequest,
    QualityAwareProcurement,
    QualityFreshnessPricingModel,
    QuoteRequest,
    UsageBasedPricingModel,
    ValueBasedPricingModel,
    VolumeDiscountConstraint,
    evaluate_pricing_properties,
)

ROOT = Path(__file__).resolve().parents[1]


def _json(value):
    if isinstance(value, Decimal):
        return str(value)
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    return str(value)


def main() -> None:
    workflow = load_workflow_config(ROOT / "configs/workflows/stage4_pricing.json")
    product = DataProduct("stage4-mobility-v1", "城市出行样本", DataReference("memory://stage4", "jsonl", record_count=50000), "city-owner")
    run = RunContext("stage4-pricing-001", seed=41, config={"quantity": 100})
    quote_request = QuoteRequest(product, market_context={"currency": "CNY", "estimated_value": "980", "buyer_share": "0.7", "floor": "400", "ceiling": "800", "acquisition_cost": "120", "preparation_cost": "80", "operation_cost": "30", "margin_rate": "0.25", "base_price": "700", "quality": "0.92", "freshness": "0.75", "quality_weight": "0.7", "records": "50000", "per_record": "0.002", "queries": "20", "per_query": "3", "compute_seconds": "60", "per_compute_second": "0.1", "valid_seconds": 3600})

    raw_quotes = [
        CostPlusPricingModel().quote(quote_request, run),
        ValueBasedPricingModel().quote(quote_request, run),
        UsageBasedPricingModel().quote(quote_request, run),
        QualityFreshnessPricingModel().quote(quote_request, run),
    ]
    bounded = PriceBandConstraint(floor=300, ceiling=750).project(tuple(raw_quotes), run)
    discounted = VolumeDiscountConstraint(((1, 0), (10, "0.05"), (100, "0.15"))).project(bounded, run)

    adaptive = AdaptiveDemandPricingModel(initial_price=620, learning_rate=0.08, target_acceptance=0.5)
    adaptive_quote = adaptive.quote(quote_request, run)
    adaptive.observe(PricingObservation(adaptive_quote, accepted=True, realized_revenue=adaptive_quote.price), run)
    adaptive_quote_after_feedback = adaptive.quote(quote_request, run)

    bids = (Bid("b1", "buyer-a", (product.product_id,), Money(Decimal("680")), Decimal("60")), Bid("b2", "buyer-b", (product.product_id,), Money(Decimal("640")), Decimal("50")), Bid("b3", "buyer-c", (product.product_id,), Money(Decimal("590")), Decimal("40")))
    asks = (Ask("ask-1", "seller-a", (product.product_id,), Money(Decimal("420")), Decimal("100")),)
    market_request = PricingRequest((product,), bids=bids, asks=asks, supply={product.product_id: Decimal("100")})
    auction = MultiUnitUniformPriceAuction().price(market_request, run)
    auction_properties = evaluate_pricing_properties(auction, market_request, budgets={"buyer-a": Decimal("50000"), "buyer-b": Decimal("50000"), "buyer-c": Decimal("50000")})

    procurement_request = PricingRequest((product,), asks=(Ask("s-low", "seller-low", (product.product_id,), Money(Decimal("8")), Decimal("80"), metadata={"quality": 0.78}), Ask("s-high", "seller-high", (product.product_id,), Money(Decimal("12")), Decimal("80"), metadata={"quality": 1.45})), market_context={"buyer_id": "enterprise-buyer", "budget": "720"})
    procurement = QualityAwareProcurement().price(procurement_request, run)
    procurement_properties = evaluate_pricing_properties(procurement, procurement_request, budgets={"enterprise-buyer": Decimal("720")})

    output = {"workflow_id": workflow.workflow_id, "quotes": discounted, "adaptive_quote_before_feedback": adaptive_quote, "adaptive_quote_after_feedback": adaptive_quote_after_feedback, "auction": auction, "auction_properties": auction_properties, "quality_procurement": procurement, "procurement_properties": procurement_properties}
    out_dir = ROOT / "outputs/stage4-pricing"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "result.json").write_text(json.dumps(output, ensure_ascii=False, indent=2, default=_json), encoding="utf-8")
    print(json.dumps({"status": "succeeded", "output": str(out_dir / "result.json"), "auction_unit_price": auction.diagnostics.get("unit_price"), "auction_allocated": auction.diagnostics.get("allocated"), "procurement_spent": procurement.diagnostics.get("spent"), "properties": {"auction": auction_properties, "procurement": procurement_properties}}, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
