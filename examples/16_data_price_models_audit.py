"""DataPrice 拓展示例：分段计费、订阅、风险折价、弹性调价和校准。"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from datavalor.core import DataProduct, DataReference, RunContext
from datavalor.data_price import (
    ElasticityPricingModel,
    Money,
    PricingObservation,
    QuoteRequest,
    RiskAdjustedPricingModel,
    SubscriptionPricingModel,
    TieredUsagePricingModel,
    audit_pricing_outcome,
    calibrate_quotes,
)

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    product = DataProduct("retail-demand", "Retail demand", DataReference("memory://retail-demand", "json"), "owner")
    request = QuoteRequest(product, market_context={"usage": 350, "currency": "CNY", "valid_seconds": 3600})
    tiered = TieredUsagePricingModel(((100, "1.2"), (500, "0.9"), (float("inf"), "0.6"))).quote(request, RunContext("tiered"))
    subscription = SubscriptionPricingModel().quote(QuoteRequest(product, market_context={"period_fee": 500, "included_usage": 1000, "usage": 1300, "overage_unit_price": 0.4, "commitment_discount": 0.1}), RunContext("subscription"))
    risk = RiskAdjustedPricingModel(risk_aversion=0.4).quote(QuoteRequest(product, market_context={"estimated_value": 1800, "std_error": 120, "buyer_share": 0.55, "rights_factor": 0.9}), RunContext("risk"))
    elastic = ElasticityPricingModel(initial_price=100, elasticity=0.8, learning_rate=0.15, target_quantity=10)
    before = elastic.quote(QuoteRequest(product), RunContext("elastic-before"))
    elastic.observe(PricingObservation(before, True, Decimal("16")), RunContext("elastic-observe"))
    after = elastic.quote(QuoteRequest(product), RunContext("elastic-after"))
    calibration = calibrate_quotes([tiered, subscription], [Money(tiered.price.amount - Decimal("5")), Money(subscription.price.amount + Decimal("10"))], [True, False])
    output = {"tiered": tiered.__dict__, "subscription": subscription.__dict__, "risk": risk.__dict__, "elasticity": {"before": before.__dict__, "after": after.__dict__}, "calibration": calibration.__dict__, "outcome_audit_example": audit_pricing_outcome(__import__("datavalor.data_price", fromlist=["PricingOutcome"]).PricingOutcome("empty", (), ())) }
    path = ROOT / "outputs/dataprice-extension/result.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"output": str(path), "tiered_price": str(tiered.price.amount), "subscription_price": str(subscription.price.amount), "risk_price": str(risk.price.amount), "elastic_before": str(before.price.amount), "elastic_after": str(after.price.amount)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

