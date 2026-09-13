"""Run multi-attribute matching and market-structure analysis."""

from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal
from pathlib import Path

from datavalor.core import (
    ActorProfile,
    ActorRole,
    DataProduct,
    DataReference,
    write_json,
)
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


def product(product_id: str, seller_id: str) -> DataProduct:
    return DataProduct(
        product_id,
        product_id,
        DataReference(f"memory://{product_id}", "json", checksum=f"sha-{product_id}"),
        seller_id,
    )


def main() -> None:
    retail = product("retail-demand", "seller-a")
    weather = product("weather-stream", "seller-b")
    listings = (
        Listing("listing-retail", retail, "seller-a", ListingStatus.ACTIVE, metadata={"quality": 0.94, "freshness": 0.88, "reputation": 0.90, "rights_fit": 1.0, "group": "commercial"}),
        Listing("listing-weather", weather, "seller-b", ListingStatus.ACTIVE, metadata={"quality": 0.82, "freshness": 0.96, "reputation": 0.75, "rights_fit": 0.9, "group": "external"}),
    )
    bids = (
        Bid("forecast-and", "buyer-1", ("retail-demand", "weather-stream"), Money(Decimal("190")), constraints={"bundle_mode": "and", "min_quality": 0.8, "region": "CN"}, task_id="forecast"),
        Bid("alternative-xor", "buyer-2", ("retail-demand", "weather-stream"), Money(Decimal("110")), constraints={"bundle_mode": "xor", "min_freshness": 0.85, "region": "CN"}, task_id="planning"),
    )
    asks = (
        Ask("ask-retail", "seller-a", ("retail-demand",), Money(Decimal("90"))),
        Ask("ask-weather", "seller-b", ("weather-stream",), Money(Decimal("60"))),
    )
    matches = MultiAttributeMarketMatcher().match(bids, asks, listings)
    demand_segments = DemandClusterAnalyzer().analyze(bids)
    supply_segments = SupplySegmentAnalyzer().analyze(listings, asks)
    gaps = MarketGapAnalyzer().analyze(bids, asks, listings)
    bundles = BundleDemandMatcher().resolve(bids, asks, Money(Decimal("210")))

    # This is an already-cleared observation used only by market analysis;
    # DataPrice remains responsible for producing the real outcome.
    outcome = PricingOutcome(
        "observed",
        (Allocation("buyer-1", ("retail-demand", "weather-stream")),),
        (
            Payment("buyer-1", "seller-a", Money(Decimal("90")), "observed", ("retail-demand",)),
            Payment("buyer-1", "seller-b", Money(Decimal("60")), "observed", ("weather-stream",)),
        ),
    )
    participants = (
        ActorProfile("seller-a", ActorRole.SUPPLIER),
        ActorProfile("seller-b", ActorRole.SUPPLIER),
        ActorProfile("buyer-1", ActorRole.BUYER),
        ActorProfile("buyer-2", ActorRole.BUYER),
    )
    snapshot = MarketSnapshot(listings, participants, outcome)
    health = analyze_market_health(snapshot, bids, asks)
    anomalies = detect_market_anomalies(listings, bids, asks)
    output = {
        "multi_attribute_matches": [asdict(item) for item in matches],
        "demand_segments": [asdict(item) for item in demand_segments],
        "supply_segments": [asdict(item) for item in supply_segments],
        "market_gaps": [asdict(item) for item in gaps],
        "bundle_selection": asdict(bundles),
        "market_health": asdict(health),
        "anomaly_signals": [asdict(item) for item in anomalies],
    }
    target = Path("outputs/stage11-market-analysis/result.json")
    write_json(target, output)
    print(target)


if __name__ == "__main__":
    main()
