from decimal import Decimal

from datavalor.core import DataProduct, DataReference, RunContext
from datavalor.data_price import (
    Ask,
    Bid,
    BudgetAwareProcurement,
    FreshnessAdjustedPostedPrice,
    Money,
    MultiUnitUniformPriceAuction,
    Payment,
    PricingOutcome,
    PricingRequest,
    QualityAwareProcurement,
    check_budget_feasibility,
    check_capacity_feasibility,
    check_individual_rationality,
    evaluate_pricing_properties,
)


def _product():
    return DataProduct("p1", "Retail", DataReference("memory://p1", "json"), "seller")


def _bid(buyer, amount, quantity, bid_id=None):
    return Bid(bid_id or buyer, buyer, ("p1",), Money(Decimal(str(amount))), Decimal(str(quantity)))


def _ask(seller, reserve, quantity, ask_id=None, quality=None):
    metadata = {} if quality is None else {"quality": quality}
    return Ask(ask_id or seller, seller, ("p1",), Money(Decimal(str(reserve))), Decimal(str(quantity)), metadata=metadata)


def test_uniform_price_partial_marginal_bid_and_welfare():
    request = PricingRequest((_product(),), bids=(_bid("b1", 12, 6), _bid("b2", 10, 8)), asks=(_ask("s", 4, 10),), supply={"p1": Decimal("10")})
    outcome = MultiUnitUniformPriceAuction().price(request, RunContext("r"))
    assert outcome.diagnostics["unit_price"] == "10"
    assert sum(a.quantity for a in outcome.allocations) == Decimal("10")
    assert [p.amount.amount for p in outcome.payments] == [Decimal("60"), Decimal("40")]
    assert outcome.welfare == Decimal("72")


def test_uniform_price_reserve_blocks_low_bids_and_zero_supply():
    request = PricingRequest((_product(),), bids=(_bid("b", 3, 2),), asks=(_ask("s", 5, 2),), supply={"p1": Decimal("2")})
    outcome = MultiUnitUniformPriceAuction().price(request, RunContext("r"))
    assert not outcome.allocations
    assert outcome.diagnostics["clearing"] is False
    zero = MultiUnitUniformPriceAuction().price(PricingRequest((_product(),), bids=(_bid("b", 8, 2),), supply={"p1": Decimal("0")}), RunContext("r"))
    assert not zero.allocations


def test_budget_aware_procurement_skips_unaffordable_ask_and_partially_fills():
    request = PricingRequest((_product(),), asks=(_ask("expensive", 90, 1), _ask("cheap", 30, 4)), market_context={"budget": "100", "buyer_id": "buyer"})
    outcome = BudgetAwareProcurement().price(request, RunContext("r"))
    assert Decimal(outcome.diagnostics["spent"]) <= Decimal("100")
    assert outcome.diagnostics["skipped_asks"] == ("expensive",)
    assert outcome.allocations[0].quantity == Decimal("3.333333333333333333333333333")


def test_budget_aware_procurement_ignores_nonpositive_asks():
    request = PricingRequest((_product(),), asks=(_ask("zero", 0, 2), _ask("negative", -1, 2)), market_context={"budget": "10", "buyer_id": "b"})
    outcome = BudgetAwareProcurement().price(request, RunContext("r"))
    assert not outcome.payments
    assert set(outcome.diagnostics["skipped_asks"]) == {"zero", "negative"}


def test_quality_aware_procurement_prefers_quality_per_cost():
    asks = (_ask("low", 10, 1, quality=0.5), _ask("high", 20, 1, quality=2.0))
    outcome = QualityAwareProcurement().price(PricingRequest((_product(),), asks=asks, market_context={"budget": "20", "buyer_id": "b"}), RunContext("r"))
    assert outcome.allocations[0].product_ids == ("p1",)
    assert outcome.payments[0].payee_id == "high"


def test_pricing_properties_report_witnesses():
    request = PricingRequest((_product(),), bids=(_bid("b", 10, 2),), supply={"p1": Decimal("1")})
    auction = MultiUnitUniformPriceAuction().price(request, RunContext("r"))
    assert check_capacity_feasibility(auction, {"p1": Decimal("1")})["holds"]
    assert check_budget_feasibility(auction, {"b": Decimal("100")})["holds"]
    assert check_individual_rationality(auction, request)["holds"]
    checks = evaluate_pricing_properties(auction, request, budgets={"b": Decimal("100")})
    assert set(checks) == {"individual_rationality", "capacity_feasibility", "budget_feasibility"}
    assert all(item["holds"] for item in checks.values())


def test_individual_rationality_reports_excess_payment_witness():
    request = PricingRequest((_product(),), bids=(_bid("b", 10, 2),))
    outcome = PricingOutcome("manual", (), (Payment("b", "s", Money(Decimal("25")), "manual", ("p1",)),))
    report = check_individual_rationality(outcome, request)
    assert not report["holds"]
    assert report["violations"]["b"] == {"bid": Decimal("20"), "paid": Decimal("25")}


def test_freshness_adjusted_posted_price_does_not_compound_state():
    mechanism = FreshnessAdjustedPostedPrice(100)
    request = PricingRequest((_product(),), bids=(_bid("b", 100, 1),), market_context={"freshness": "0.8"})
    first = mechanism.price(request, RunContext("r"))
    second = mechanism.price(request, RunContext("r2"))
    assert first.payments[0].amount.amount == Decimal("80")
    assert second.payments[0].amount.amount == Decimal("80")


def test_uniform_auction_rejects_mixed_seller_revenue_currency():
    bids = (_bid("b1", 12, 1), Bid("b2", "b2", ("p1",), Money(Decimal("11"), "USD"), Decimal("1")))
    request = PricingRequest((_product(),), bids=bids, asks=(_ask("s", 4, 2),), supply={"p1": Decimal("2")})
    try:
        MultiUnitUniformPriceAuction().price(request, RunContext("r"))
    except ValueError as exc:
        assert "mixed currencies" in str(exc)
    else:
        raise AssertionError("mixed revenue currencies must be rejected")
