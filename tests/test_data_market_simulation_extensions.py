from decimal import Decimal

from datavalor.core import ActorProfile, ActorRole, DataProduct, DataReference
from datavalor.data_market import Listing, ListingStatus, MarketSnapshot
from datavalor.data_market.simulation import (
    PrivacyBudgetLedger,
    apply_participation_shock,
    decay_market_freshness,
    summarize_simulation,
)
from datavalor.data_market.simulation.models import (
    SimulationReport,
    SimulationStep,
    StrategyDecision,
)
from datavalor.data_price import Allocation, Money, Payment, PricingOutcome


def _market():
    product = DataProduct("p1", "P1", DataReference("memory://p1", "json"), "s1", metadata={"freshness": "0.3"})
    listing = Listing("l1", product, "s1", ListingStatus.ACTIVE, metadata={"freshness": "0.3"})
    return MarketSnapshot((listing,), (ActorProfile("s1", ActorRole.SUPPLIER),), state={"round": 0})


def test_freshness_decay_suspends_stale_listing_and_records_state():
    updated = decay_market_freshness(_market(), Decimal("0.15"), suspend_below=Decimal("0.2"))
    assert updated.listings[0].status is ListingStatus.SUSPENDED
    assert updated.state["freshness"]["l1"] == "0.15"


def test_participation_shock_replaces_exits_and_suspends_their_listings():
    entrant = ActorProfile("s2", ActorRole.SUPPLIER)
    updated = apply_participation_shock(_market(), entrants=(entrant,), exits=("s1",), demand_multiplier="1.5")
    assert [profile.actor_id for profile in updated.participants] == ["s2"]
    assert updated.listings[0].status is ListingStatus.SUSPENDED
    assert updated.state["demand_multiplier"] == "1.5"


def test_privacy_ledger_is_atomic_and_strategy_consumes_cost_on_win():
    ledger = PrivacyBudgetLedger({"buyer": 2})
    assert ledger.consume("buyer", 1.5)
    assert not ledger.consume("buyer", 1)
    assert ledger.remaining("buyer") == Decimal("0.5")


def test_simulation_summary_reports_concentration_and_coverage():
    outcome = PricingOutcome("test", (Allocation("buyer", ("p1",)),), (Payment("buyer", "seller", Money(Decimal("10")), "sale", ("p1",))), welfare=Decimal("8"))
    step = SimulationStep(0, (StrategyDecision("buyer"),), outcome, _market())
    metrics = summarize_simulation(SimulationReport("run", (step,)))
    assert metrics.trade_rounds == 1
    assert metrics.total_revenue == Decimal("10")
    assert metrics.seller_hhi == 1.0
    assert metrics.buyer_coverage == 1.0
