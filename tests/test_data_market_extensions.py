from decimal import Decimal

from datavalor.core import ActorProfile, ActorRole, DataProduct, DataReference, RunContext
from datavalor.data_market import (
    ContributionIncentivePolicy,
    IdempotentTransactionProcessor,
    Listing,
    ListingStatus,
    MarketMatch,
    MarketSnapshot,
    QuotaAdmissionController,
    ReputationScore,
    ShapleyRevenueAllocator,
    TransactionRecord,
    audit_market_mechanism,
    market_statistics,
    match_orders,
    rank_listings,
    score_reputation,
)
from datavalor.data_price import Allocation, Ask, Bid, Money, Payment, PricingOutcome


def _product(pid: str, title: str = "Demand"):
    return DataProduct(pid, title, DataReference(f"memory://{pid}", "json"), "seller")


def test_rank_listings_filters_active_and_scores_relevance():
    listings = (
        Listing("l1", _product("p1", "Retail demand"), "s1", ListingStatus.ACTIVE, metadata={"quality": 0.9}),
        Listing("l2", _product("p2", "Weather archive"), "s2", ListingStatus.CLOSED, metadata={"quality": 1.0}),
    )
    ranked = rank_listings(listings, "retail", tags=("valuation",), preferences={"seller_id": "s1"})
    assert [listing.listing_id for listing in ranked] == ["l1"]


def test_reputation_and_market_statistics():
    outcome = PricingOutcome("test", (), ())
    records = (
        TransactionRecord("tx1", outcome, "succeeded", diagnostics={"seller_id": "s1"}),
        TransactionRecord("tx2", outcome, "failed", diagnostics={"seller_id": "s1"}),
    )
    reputation = score_reputation("s1", records, ("tx2",))
    assert isinstance(reputation, ReputationScore)
    assert reputation.completed == 1 and reputation.failed == 1
    participants = (ActorProfile("s1", ActorRole.SUPPLIER), ActorProfile("b1", ActorRole.BUYER))
    snapshot = MarketSnapshot((Listing("l1", _product("p1"), "s1", ListingStatus.ACTIVE),), participants, outcome)
    assert market_statistics(snapshot)["seller_hhi"] == 1.0


def test_contribution_incentive_budget_reconciles():
    outcome = PricingOutcome("auction", (), ())
    market = MarketSnapshot((), (ActorProfile("a", ActorRole.SUPPLIER), ActorProfile("b", ActorRole.SUPPLIER)))
    incentives = ContributionIncentivePolicy(Decimal("10")).compute(market, outcome, RunContext("r", config={"contributions": {"a": 3, "b": 1}}))
    assert sum(item.amount.amount for item in incentives) == Decimal("10.00")
    assert incentives[0].amount.amount > incentives[1].amount.amount


def test_idempotent_transaction_processor_and_partial_delivery():
    outcome = PricingOutcome("auction", (Allocation("b", ("p1",), Decimal("1")),), (Payment("b", "s", Money(Decimal("5")), "sale", ("p1",)),))
    processor = IdempotentTransactionProcessor(lambda product_id: product_id != "p1")
    first = processor.execute(outcome, RunContext("r1"))
    second = processor.execute(outcome, RunContext("r2"))
    assert first.status == "failed"
    assert first.transaction_id == second.transaction_id
    assert second.diagnostics["idempotent"] is False


def test_market_order_matching_respects_active_quality_and_split_quantity():
    product = _product("p1")
    listings = (Listing("l1", product, "s1", ListingStatus.ACTIVE, metadata={"quality": 0.9}),)
    bids = (
        Bid("b1", "buyer-1", ("p1",), Money(Decimal("12")), Decimal("1"), constraints={"min_quality": "0.8"}),
        Bid("b2", "buyer-2", ("p1",), Money(Decimal("11")), Decimal("1")),
    )
    asks = (Ask("a1", "s1", ("p1",), Money(Decimal("10")), Decimal("1.5")),)
    matches = match_orders(bids, asks, listings)
    assert all(isinstance(item, MarketMatch) for item in matches)
    assert matches[0].buyer_id == "buyer-1" and matches[0].quantity == Decimal("1")
    assert matches[0].surplus.amount == Decimal("2")


def test_mechanism_audit_reports_ir_budget_and_efficiency():
    bids = (Bid("b1", "buyer", ("p1",), Money(Decimal("10"))),)
    asks = (Ask("a1", "seller", ("p1",), Money(Decimal("4"))),)
    outcome = PricingOutcome("test", (Allocation("buyer", ("p1",), reported_value=Money(Decimal("10"))),), (Payment("buyer", "seller", Money(Decimal("6")), "sale", ("p1",))), welfare=Decimal("6"))
    report = audit_market_mechanism(bids, asks, outcome)
    assert report.properties["buyer_individual_rationality"]
    assert report.properties["seller_individual_rationality"]
    assert report.properties["weak_budget_balance"]
    assert report.metrics["efficiency_ratio"] == "1"


def test_quota_admission_clips_allocation_and_payment():
    outcome = PricingOutcome("test", (Allocation("buyer", ("p1",), Decimal("3")),), (Payment("buyer", "seller", Money(Decimal("30")), "sale", ("p1",)),))
    decision = QuotaAdmissionController().admit(outcome, {"buyer": {"p1": Decimal("2")}})
    assert decision.allocations[0].quantity == Decimal("2")
    assert decision.payments[0].amount.amount == Decimal("20")
    assert decision.denied["buyer:p1"] == Decimal("1")


def test_shapley_allocator_uses_coalition_synergy_and_reconciles():
    allocator = ShapleyRevenueAllocator()
    participants = (ActorProfile("a", ActorRole.SUPPLIER), ActorProfile("b", ActorRole.SUPPLIER))
    context = RunContext("shapley", metadata={"coalition_values": {"a": "2", "b": "2", "a|b": "10"}})
    allocation = allocator.allocate(Money(Decimal("10")), participants, {"a": 1, "b": 1}, context)
    assert sum(share.amount.amount for share in allocation.shares) == Decimal("10.00")
    assert allocation.shares[0].amount.amount == allocation.shares[1].amount.amount
    assert allocation.diagnostics["exact"] is True
