from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from datavalor.core import DataProduct, DataReference, RightsBundle, RunContext
from datavalor.data_price import (
    BundleDiscountConstraint,
    ComparablePricingModel,
    ComparableSelector,
    FreshnessTierPricingModel,
    Money,
    PriceQuote,
    PriceRangePricingModel,
    QuoteRequest,
    RightsDifferentiatedPricingModel,
    VersionDeltaPricingModel,
    audit_price_quotes,
)

NOW = datetime(2026, 9, 12, tzinfo=timezone.utc)


def _product(version="1", rights=None):
    return DataProduct("p", "p", DataReference("memory://p", "json"), "owner", version=version, rights=rights or RightsBundle())


def _request(rights=None, **context):
    product = _product(rights=rights)
    return QuoteRequest(product, rights=rights, market_context=context)


def _context(name="price", **config):
    return RunContext(name, config=config, started_at=NOW)


def test_price_range_preserves_floor_target_ceiling():
    quote = PriceRangePricingModel().quote(_request(estimated_value=1000, value_std_error=100, seller_share=0.5, confidence=0.8, cost_floor=300, comparable_price=500, comparable_weight=0.25), _context())
    assert quote.price.amount == Decimal("425.00")
    assert quote.components["floor"] == Decimal("327.00")
    assert quote.components["target"] == Decimal("425.000")
    assert quote.components["ceiling"] == Decimal("523.00")


def test_comparable_selector_and_adjusted_pricing():
    candidates = (
        {"comparable_id": "same", "kind": "stream", "quality": 0.9, "price": 100},
        {"comparable_id": "other", "kind": "snapshot", "quality": 0.4, "price": 50},
        {"comparable_id": "usd", "kind": "stream", "quality": 0.9, "price": 999, "currency": "USD"},
    )
    selected = ComparableSelector().select({"kind": "stream", "quality": 0.8}, candidates, currency="CNY")
    assert selected[0].comparable_id == "same"
    assert all(item.comparable_id != "usd" for item in selected)
    quote = ComparablePricingModel().quote(_request(target_attributes={"kind": "stream", "quality": 0.8}, comparables=candidates, quality_ratio=1.1, freshness_ratio=0.9), _context())
    assert quote.price.amount > Decimal("0")
    assert quote.diagnostics["comparables"][0]["id"] == "same"


def test_comparable_pricing_requires_positive_match():
    with pytest.raises(ValueError, match="comparable"):
        ComparablePricingModel().quote(_request(target_attributes={"kind": "stream"}, comparables=({"kind": "snapshot", "price": 10},)), _context())


def test_broader_rights_have_monotone_premium():
    narrow = RightsBundle(("analysis",), commercial_use=False, redistribution=False, valid_until=NOW + timedelta(days=30), jurisdictions=("CN",))
    broad = RightsBundle(("analysis",), commercial_use=True, redistribution=True, exclusivity="exclusive", valid_until=None, jurisdictions=("CN", "SG"))
    model = RightsDifferentiatedPricingModel()
    narrow_quote = model.quote(_request(narrow, base_price=100), _context("narrow"))
    broad_quote = model.quote(_request(broad, base_price=100), _context("broad"))
    assert broad_quote.price.amount > narrow_quote.price.amount
    assert broad_quote.components["commercial_premium"] == Decimal("0.20")


def test_freshness_tiers_and_version_delta():
    model = FreshnessTierPricingModel(((1, 1.2), (7, 1), (30, 0.8)))
    assert model.quote(_request(base_price=100, age_days=1), _context()).price.amount == Decimal("120.00")
    assert model.quote(_request(base_price=100, age_days=20), _context()).price.amount == Decimal("80.00")
    version_request = QuoteRequest(_product(version="2"), market_context={"previous_price": 100, "incremental_coverage": 0.4, "quality_gain": 0.1, "volume_growth": 0.5})
    version = VersionDeltaPricingModel().quote(version_request, _context())
    assert version.price.amount == Decimal("133.00")
    assert version.diagnostics["product_version"] == "2"


def test_bundle_projection_accounts_for_overlap_and_complementarity():
    quotes = (
        PriceQuote("a", "a", Money(Decimal("100")), "m"),
        PriceQuote("b", "b", Money(Decimal("200")), "m"),
    )
    projected = BundleDiscountConstraint().project(quotes, _context(overlap_ratio=0.2, overlap_discount_weight=0.5, complementarity=0.1, complementarity_premium_weight=0.2))
    assert sum(item.price.amount for item in projected) == Decimal("276.00")
    assert projected[0].components["bundle_factor"] == Decimal("0.92")
    with pytest.raises(ValueError, match="currency"):
        BundleDiscountConstraint().project((quotes[0], PriceQuote("usd", "b", Money(Decimal("1"), "USD"), "m")), _context())


def test_quote_audit_detects_cost_expiry_jump_and_rights_monotonicity():
    narrow = RightsBundle(("analysis",), commercial_use=False, valid_until=NOW + timedelta(days=30), jurisdictions=("CN",))
    broad = RightsBundle(("analysis",), commercial_use=True, redistribution=True, valid_until=None, jurisdictions=("CN", "SG"))
    quotes = (
        PriceQuote("broad", "p", Money(Decimal("80")), "m", rights=broad),
        PriceQuote("narrow", "p", Money(Decimal("100")), "m", rights=narrow),
        PriceQuote("expired", "x", Money(Decimal("20")), "m", valid_until=NOW - timedelta(seconds=1)),
    )
    report = audit_price_quotes(
        quotes,
        {"broad": {"cost_floor": 90, "estimated_value": 70, "previous_price": 200}},
        evaluated_at=NOW,
    )
    codes = {finding.code for finding in report.findings}
    assert report.status == "invalid"
    assert codes >= {"price.below_cost", "price.above_value_ratio", "price.jump", "quote.expired", "rights.non_monotone_price"}


def test_validation_boundaries():
    with pytest.raises(ValueError):
        FreshnessTierPricingModel(((7, 1), (1, 0.8)))
    with pytest.raises(ValueError):
        ComparableSelector().select({}, (), limit=-1)
