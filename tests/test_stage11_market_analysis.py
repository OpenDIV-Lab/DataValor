from decimal import Decimal

import pytest

from datavalor.core import ActorProfile, ActorRole, DataProduct, DataReference
from datavalor.data_market import (
    BundleDemandMatcher,
    DemandClusterAnalyzer,
    Listing,
    ListingStatus,
    MarketGapAnalyzer,
    MarketSnapshot,
    MultiAttributeMarketMatcher,
    SupplySegmentAnalyzer,
    analyze_market_health,
    detect_market_anomalies,
)
from datavalor.data_price import Allocation, Ask, Bid, Money, Payment, PricingOutcome


def _product(product_id, seller="seller"):
    return DataProduct(product_id, product_id, DataReference(f"memory://{product_id}", "json", checksum=f"sum-{product_id}"), seller)


def _listing(product_id, seller="seller", **metadata):
    return Listing(f"listing-{product_id}", _product(product_id, seller), seller, ListingStatus.ACTIVE, metadata=metadata)


def test_multi_attribute_match_filters_hard_constraints_and_ranks():
    listings = (
        _listing("premium", "s1", quality=0.95, freshness=0.9, reputation=0.8, rights_fit=1),
        _listing("cheap", "s2", quality=0.5, freshness=1, reputation=1, rights_fit=1),
    )
    bids = (Bid("b1", "buyer", ("premium", "cheap"), Money(Decimal("100")), constraints={"min_quality": 0.8}),)
    asks = (
        Ask("a1", "s1", ("premium",), Money(Decimal("80"))),
        Ask("a2", "s2", ("cheap",), Money(Decimal("20"))),
    )
    matches = MultiAttributeMarketMatcher().match(bids, asks, listings)
    assert len(matches) == 1
    assert matches[0].product_id == "premium"
    assert matches[0].score_components["quality"] == Decimal("0.95")


def test_demand_and_supply_segments_are_deterministic_and_currency_safe():
    bids = (
        Bid("b2", "buyer-2", ("p",), Money(Decimal("20"), "CNY"), task_id="forecast", constraints={"region": "CN"}),
        Bid("b1", "buyer-1", ("p",), Money(Decimal("10"), "CNY"), task_id="forecast", constraints={"region": "CN"}),
        Bid("usd", "buyer-3", ("p",), Money(Decimal("10"), "USD"), task_id="forecast", constraints={"region": "CN"}),
    )
    demand = DemandClusterAnalyzer().analyze(bids)
    assert len(demand) == 2
    assert next(item for item in demand if item.attributes["currency"] == "CNY").member_ids == ("b1", "b2")
    listings = (_listing("p1", quality=0.9, freshness=0.9), _listing("p2", quality=0.5, freshness=0.4))
    supply = SupplySegmentAnalyzer().analyze(listings, (Ask("a1", "seller", ("p1",), Money(Decimal("600"))), Ask("a2", "seller", ("p2",), Money(Decimal("50")))))
    assert len(supply) == 2
    with pytest.raises(ValueError, match="cuts"):
        SupplySegmentAnalyzer().analyze(listings, quality_cuts=(0.9, 0.5))


def test_market_gap_distinguishes_shortage_and_price_gap():
    bids = (
        Bid("bp", "b", ("p",), Money(Decimal("8")), Decimal("3")),
        Bid("bq", "b", ("q",), Money(Decimal("20")), Decimal("2")),
    )
    asks = (
        Ask("ap", "s", ("p",), Money(Decimal("10")), Decimal("3")),
        Ask("aq", "s", ("q",), Money(Decimal("10")), Decimal("1")),
    )
    gaps = {item.product_id: item for item in MarketGapAnalyzer().analyze(bids, asks)}
    assert gaps["p"].status == "price_gap"
    assert gaps["q"].status == "undersupplied"
    assert gaps["q"].unmet_quantity == Decimal("1")


def test_bundle_matcher_resolves_and_xor_then_maximizes_surplus():
    asks = (
        Ask("a", "s1", ("a",), Money(Decimal("30"))),
        Ask("b", "s2", ("b",), Money(Decimal("40"))),
        Ask("c", "s3", ("c",), Money(Decimal("20"))),
    )
    bids = (
        Bid("and", "buyer-1", ("a", "b"), Money(Decimal("100")), constraints={"bundle_mode": "and"}),
        Bid("xor", "buyer-2", ("b", "c"), Money(Decimal("50")), constraints={"bundle_mode": "xor"}),
    )
    result = BundleDemandMatcher().resolve(bids, asks, Money(Decimal("90")))
    assert {item.bid_id for item in result.matches} == {"and", "xor"}
    assert next(item for item in result.matches if item.bid_id == "xor").product_ids == ("c",)
    assert result.total_cost.amount == Decimal("90")
    assert result.total_reported_value.amount == Decimal("150")


def test_bundle_ask_is_not_charged_twice_and_invalid_mode_fails():
    bundle_ask = Ask("bundle", "s", ("a", "b"), Money(Decimal("60")))
    bid = Bid("and", "buyer", ("a", "b"), Money(Decimal("80")), constraints={"bundle_mode": "and"})
    result = BundleDemandMatcher().resolve((bid,), (bundle_ask,), Money(Decimal("60")))
    assert result.total_cost.amount == Decimal("60")
    with pytest.raises(ValueError, match="bundle_mode"):
        BundleDemandMatcher().resolve((Bid("bad", "b", ("a",), Money(Decimal("1")), constraints={"bundle_mode": "or"}),), (bundle_ask,), Money(Decimal("10")))


def test_market_health_reports_competition_spread_and_group_trade_rate():
    listings = (
        _listing("p1", "s1", group="core"),
        _listing("p2", "s2", group="long_tail"),
    )
    participants = (ActorProfile("s1", ActorRole.SUPPLIER), ActorProfile("s2", ActorRole.SUPPLIER), ActorProfile("b1", ActorRole.BUYER))
    outcome = PricingOutcome("m", (Allocation("b1", ("p1",)),), (Payment("b1", "s1", Money(Decimal("8")), "trade", ("p1",)),))
    snapshot = MarketSnapshot(listings, participants, outcome)
    bids = (Bid("b1", "b1", ("p1",), Money(Decimal("10"))), Bid("b2", "b2", ("p2",), Money(Decimal("9"))))
    asks = (Ask("a1", "s1", ("p1",), Money(Decimal("7"))), Ask("a2", "s2", ("p2",), Money(Decimal("8"))))
    report = analyze_market_health(snapshot, bids, asks)
    assert report.metrics["seller_hhi"] == 0.5
    assert report.metrics["bid_ask_spread"] == Decimal("-3")
    assert report.by_group["core"]["trade_rate"] == 1
    assert report.by_group["long_tail"]["trade_rate"] == 0


def test_market_health_does_not_compute_cross_currency_spread():
    report = analyze_market_health(MarketSnapshot((), ()), (Bid("b", "buyer", ("p",), Money(Decimal("1"), "USD")),), (Ask("a", "seller", ("p",), Money(Decimal("1"), "CNY")),))
    assert report.metrics["bid_ask_spread"] is None
    assert not report.diagnostics["spread_available"]


def test_anomaly_detection_returns_review_signals():
    product = _product("same", "seller")
    listings = (
        Listing("l1", product, "seller", ListingStatus.ACTIVE, metadata={"quality": 0.1}),
        Listing("l2", product, "seller", ListingStatus.ACTIVE, metadata={"quality": 0.1}),
    )
    asks = (Ask("ask", "seller", ("same",), Money(Decimal("200"))),)
    anomalies = detect_market_anomalies(listings, (), asks, high_price_quality_ratio=1000)
    codes = {item.code for item in anomalies}
    assert codes == {"listing.duplicate", "listing.high_price_low_quality"}
    assert all(item.severity == "medium" for item in anomalies)
