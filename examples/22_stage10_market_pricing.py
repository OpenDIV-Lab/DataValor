"""Run explainable market pricing over stage-nine style valuations."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from datavalor.core import DataProduct, DataReference, RightsBundle, RunContext, write_json
from datavalor.data_price import (
    BundleDiscountConstraint,
    ComparablePricingModel,
    FreshnessTierPricingModel,
    PriceRangePricingModel,
    QuoteRequest,
    RightsDifferentiatedPricingModel,
    VersionDeltaPricingModel,
    audit_price_quotes,
)


def main() -> None:
    now = datetime(2026, 9, 12, tzinfo=timezone.utc)
    product = DataProduct(
        "demand-signals",
        "Demand signals",
        DataReference("memory://signals", "json"),
        "supplier",
        version="2",
    )
    range_quote = PriceRangePricingModel().quote(
        QuoteRequest(
            product,
            market_context={
                "estimated_value": 1800,
                "value_std_error": 120,
                "seller_share": 0.55,
                "confidence": 0.86,
                "cost_floor": 650,
                "comparable_price": 900,
                "comparable_weight": 0.25,
                "valid_seconds": 3600,
            },
        ),
        RunContext("range", started_at=now),
    )
    comparable_quote = ComparablePricingModel().quote(
        QuoteRequest(
            product,
            market_context={
                "target_attributes": {"kind": "stream", "quality": 0.90, "freshness": 0.82},
                "feature_weights": {"kind": 2, "quality": 1, "freshness": 1},
                "comparables": (
                    {"comparable_id": "c1", "kind": "stream", "quality": 0.88, "freshness": 0.80, "price": 920},
                    {"comparable_id": "c2", "kind": "stream", "quality": 0.75, "freshness": 0.70, "price": 760},
                    {"comparable_id": "c3", "kind": "snapshot", "quality": 0.92, "freshness": 0.90, "price": 600},
                ),
                "quality_ratio": 1.03,
                "freshness_ratio": 1.01,
            },
        ),
        RunContext("comparable", started_at=now),
    )
    narrow = RightsBundle(
        ("forecasting",),
        commercial_use=False,
        redistribution=False,
        valid_until=now + timedelta(days=90),
        jurisdictions=("CN",),
    )
    broad = RightsBundle(
        ("forecasting",),
        commercial_use=True,
        redistribution=True,
        exclusivity="exclusive",
        jurisdictions=("CN", "SG"),
    )
    rights_model = RightsDifferentiatedPricingModel()
    narrow_quote = rights_model.quote(
        QuoteRequest(product, rights=narrow, market_context={"base_price": 700}),
        RunContext("rights-narrow", started_at=now),
    )
    broad_quote = rights_model.quote(
        QuoteRequest(product, rights=broad, market_context={"base_price": 700}),
        RunContext("rights-broad", started_at=now),
    )
    freshness_quote = FreshnessTierPricingModel().quote(
        QuoteRequest(product, market_context={"base_price": 800, "age_days": 4}),
        RunContext("freshness", started_at=now),
    )
    version_quote = VersionDeltaPricingModel().quote(
        QuoteRequest(
            product,
            market_context={
                "previous_price": 820,
                "incremental_coverage": 0.35,
                "quality_gain": 0.08,
                "volume_growth": 0.20,
            },
        ),
        RunContext("version", started_at=now),
    )
    bundle = BundleDiscountConstraint().project(
        (range_quote, comparable_quote),
        RunContext(
            "bundle",
            config={
                "overlap_ratio": 0.25,
                "overlap_discount_weight": 0.6,
                "complementarity": 0.20,
                "complementarity_premium_weight": 0.15,
            },
            started_at=now,
        ),
    )
    quotes = (
        range_quote,
        comparable_quote,
        narrow_quote,
        broad_quote,
        freshness_quote,
        version_quote,
    )
    audit = audit_price_quotes(
        quotes,
        {
            range_quote.quote_id: {"cost_floor": 650, "estimated_value": 1800},
            version_quote.quote_id: {"previous_price": 820, "estimated_value": 1800},
        },
        evaluated_at=now,
        max_value_ratio=Decimal("1"),
    )
    output = {
        "quotes": [asdict(item) for item in quotes],
        "bundle_projection": [asdict(item) for item in bundle],
        "audit": asdict(audit),
    }
    target = Path("outputs/stage10-market-pricing/result.json")
    write_json(target, output)
    print(target)


if __name__ == "__main__":
    main()
