from decimal import Decimal

from datavalor.core import ActorProfile, ActorRole, RunContext
from datavalor.data_market.simulation import FixedShadingStrategy, TruthfulStrategy
from datavalor.data_price import (
    Bid,
    FirstPriceAuction,
    McAfeeDoubleAuction,
    Money,
    NoArbitrageProjectionPricing,
    PricingRequest,
)
from datavalor.toolkit.analysis import bootstrap_mean_interval, paired_difference, pareto_frontier


def _bid(buyer, amount):
    return Bid(f"b-{buyer}", buyer, ("p",), Money(Decimal(str(amount))))


def test_pricing_mechanisms_return_typed_outcomes():
    request = PricingRequest((), bids=(_bid("buyer", 10), _bid("buyer2", 8)))
    outcome = FirstPriceAuction().price(request, RunContext("r"))
    assert outcome.allocations[0].buyer_id == "buyer"
    assert outcome.payments[0].amount.amount == Decimal("10")
    assert McAfeeDoubleAuction().price(PricingRequest((), bids=(_bid("b", 10),), asks=()), RunContext("r")).mechanism == "mcafee_double_auction"


def test_price_constraint_and_strategies():
    quote = __import__("datavalor.data_price", fromlist=["PriceQuote"]).PriceQuote("q", "p", Money(Decimal("1")), "m")
    projected = NoArbitrageProjectionPricing().project((quote,), RunContext("r", config={"minimum_price": "2"}))
    assert projected[0].price.amount == Decimal("2")
    actor = ActorProfile("buyer", ActorRole.BUYER, preferences={"value": 5, "product_id": "p"})
    from datavalor.data_market.models import MarketSnapshot
    from datavalor.data_market.simulation import MarketObservation
    observation = MarketObservation(0, actor, MarketSnapshot((), (actor,)))
    assert TruthfulStrategy().decide(observation, RunContext("r")).bids[0].amount.amount == Decimal("5")
    assert FixedShadingStrategy(.5).decide(observation, RunContext("r")).bids[0].amount.amount == Decimal("2.5")


def test_analysis_helpers():
    interval = bootstrap_mean_interval([1, 2, 3], samples=100, seed=1)
    assert interval["lower"] <= interval["mean"] <= interval["upper"]
    assert paired_difference([1, 2], [2, 4])["mean_difference"] == 1.5
    assert len(pareto_frontier([{"a": 1, "b": 2}, {"a": 2, "b": 1}, {"a": 0, "b": 0}], ("a", "b"))) == 2
