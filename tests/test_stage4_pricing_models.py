from datetime import datetime, timezone
from decimal import Decimal

import pytest

from datavalor.core import DataProduct, DataReference, RunContext
from datavalor.data_price import (
    AdaptiveDemandPricingModel,
    CostPlusPricingModel,
    Money,
    PriceBandConstraint,
    PriceQuote,
    PricingObservation,
    QualityFreshnessPricingModel,
    QuoteRequest,
    UsageBasedPricingModel,
    ValueBasedPricingModel,
    VolumeDiscountConstraint,
)


def _product():
    return DataProduct("p1", "Retail", DataReference("memory://p1", "json"), "owner")


def _request(**context):
    return QuoteRequest(_product(), market_context=context)


def _ctx():
    return RunContext("stage4-test", started_at=datetime(2025, 1, 1, tzinfo=timezone.utc))


def test_cost_plus_components_and_expiry():
    quote = CostPlusPricingModel().quote(
        _request(acquisition_cost="10", preparation_cost="5", operation_cost="2", margin_rate="0.2", valid_seconds=60),
        _ctx(),
    )
    assert quote.price.amount == Decimal("20.40")
    assert quote.components["margin"] == Decimal("3.4")
    assert quote.valid_until.isoformat() == "2025-01-01T00:01:00+00:00"


def test_value_based_floor_and_ceiling_are_applied():
    quote = ValueBasedPricingModel().quote(_request(estimated_value=100, buyer_share="0.8", floor=90, ceiling=95), _ctx())
    assert quote.price.amount == Decimal("90.00")
    assert quote.components["buyer_share"] == Decimal("0.8")


def test_usage_based_formula():
    quote = UsageBasedPricingModel().quote(
        _request(fixed_fee=10, records=1000, per_record="0.01", queries=3, per_query=2, compute_seconds=5, per_compute_second="0.5"),
        _ctx(),
    )
    assert quote.price.amount == Decimal("28.50")


def test_quality_freshness_factor_and_bounds():
    quote = QualityFreshnessPricingModel().quote(_request(base_price=100, quality="0.8", freshness="0.4", quality_weight="0.5", floor=30, ceiling=70), _ctx())
    assert quote.components["factor"] == Decimal("0.6")
    assert quote.price.amount == Decimal("60.00")


def test_adaptive_demand_increases_on_acceptance_and_decreases_on_rejection():
    model = AdaptiveDemandPricingModel(100, learning_rate=0.1, target_acceptance=0.5)
    request = _request()
    first = model.quote(request, _ctx())
    model.observe(PricingObservation(first, accepted=True, realized_revenue=first.price), _ctx())
    assert model.price == Decimal("105.0")
    model.observe(PricingObservation(first, accepted=False), _ctx())
    assert model.price == Decimal("99.75")
    assert model.observations == 2


def test_adaptive_demand_rejects_currency_mismatch():
    model = AdaptiveDemandPricingModel(100, currency="CNY")
    quote = model.quote(_request(), _ctx())
    with pytest.raises(ValueError, match="currency"):
        model.observe(PricingObservation(quote, accepted=True, realized_revenue=Money(Decimal("1"), "USD")), _ctx())


def test_price_band_projection_preserves_provenance_and_checks_currency():
    quote = PriceQuote("q", "p1", Money(Decimal("5"), "CNY"), "x")
    projected = PriceBandConstraint(floor=10, ceiling=20).project((quote,), _ctx())[0]
    assert projected.price.amount == Decimal("10")
    assert projected.diagnostics["price_band_projected"] is True
    with pytest.raises(ValueError, match="currency"):
        PriceBandConstraint(currency="USD").project((quote,), _ctx())
    with pytest.raises(ValueError, match="ceiling"):
        PriceBandConstraint(floor=20, ceiling=10)


def test_volume_discount_uses_highest_matching_tier():
    quote = CostPlusPricingModel().quote(_request(acquisition_cost=100), _ctx())
    discounted = VolumeDiscountConstraint(((1, 0), (10, "0.05"), (100, "0.15"))).project((quote,), RunContext("r", config={"quantity": 100}))[0]
    assert discounted.price.amount == Decimal("102.00")
    assert discounted.components["volume_discount"] == Decimal("0.15")


def test_volume_discount_quantity_below_first_tier_has_no_discount():
    quote = CostPlusPricingModel().quote(_request(acquisition_cost=10), _ctx())
    projected = VolumeDiscountConstraint(((10, "0.05"),)).project((quote,), RunContext("r", config={"quantity": 1}))[0]
    assert projected.price.amount == quote.price.amount


def test_volume_discount_rejects_invalid_tiers():
    with pytest.raises(ValueError, match="thresholds"):
        VolumeDiscountConstraint(((0, 0.1),))
    with pytest.raises(ValueError, match="between"):
        VolumeDiscountConstraint(((1, 1.1),))
