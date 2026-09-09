"""Additional, data-market-specific simulation primitives.

The finite runner deliberately stays small.  These helpers model the state
that makes a data market different from a static auction: products become
stale, participants enter and leave, buyers have privacy budgets, and a
simulation must report liquidity and concentration rather than only a
winner.  They are pure or explicitly stateful objects and can be composed
with :class:`FiniteMarketSimulator` without changing its runner contract.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Mapping, Sequence

from datavalor.core import ActorProfile, ComponentSpec
from datavalor.data_market.models import ListingStatus, MarketSnapshot

from .models import SimulationReport, SimulationStep
from .strategies import TruthfulStrategy, _won_and_paid


def decay_market_freshness(
    market: MarketSnapshot,
    decay_rate: Decimal | float = Decimal("0.05"),
    *,
    suspend_below: Decimal | float = Decimal("0.2"),
) -> MarketSnapshot:
    """Advance listing freshness by one round and suspend stale products.

    Freshness is read from listing metadata or product metadata and clamped to
    ``[0, 1]``.  The original snapshot is not mutated; the updated values and
    suspended listing IDs are recorded in ``state`` for downstream strategies.
    """

    decay = Decimal(str(decay_rate))
    threshold = Decimal(str(suspend_below))
    if decay < 0 or threshold < 0 or threshold > 1:
        raise ValueError("decay_rate must be non-negative and suspend_below in [0, 1]")
    updated = []
    suspended: list[str] = []
    freshness_values: dict[str, str] = {}
    for listing in market.listings:
        current = Decimal(str(listing.metadata.get("freshness", listing.product.metadata.get("freshness", 1))))
        freshness = max(Decimal("0"), min(Decimal("1"), current - decay))
        status = listing.status
        if status is ListingStatus.ACTIVE and freshness < threshold:
            status = ListingStatus.SUSPENDED
            suspended.append(listing.listing_id)
        updated.append(replace(listing, status=status, metadata={**listing.metadata, "freshness": str(freshness)}))
        freshness_values[listing.listing_id] = str(freshness)
    return replace(market, listings=tuple(updated), state={**market.state, "freshness": freshness_values, "suspended_for_staleness": tuple(suspended)})


def apply_participation_shock(
    market: MarketSnapshot,
    *,
    entrants: Sequence[ActorProfile] = (),
    exits: Sequence[str] = (),
    demand_multiplier: Decimal | float = Decimal("1"),
) -> MarketSnapshot:
    """Apply an entry/exit or demand shock at a simulation boundary."""

    multiplier = Decimal(str(demand_multiplier))
    if multiplier < 0:
        raise ValueError("demand_multiplier must be non-negative")
    exiting = set(exits)
    profiles = {profile.actor_id: profile for profile in market.participants if profile.actor_id not in exiting}
    for profile in entrants:
        profiles[profile.actor_id] = profile
    listings = tuple(
        replace(listing, status=ListingStatus.SUSPENDED)
        if listing.seller_id in exiting and listing.status is ListingStatus.ACTIVE
        else listing
        for listing in market.listings
    )
    return replace(
        market,
        participants=tuple(profiles[key] for key in sorted(profiles)),
        listings=listings,
        state={**market.state, "demand_multiplier": str(multiplier), "exited": tuple(sorted(exiting)), "entered": tuple(sorted(profile.actor_id for profile in entrants))},
    )


class PrivacyBudgetLedger:
    """Track buyer privacy/query budgets during a simulation.

    A ledger is intentionally independent of payment.  A successful query can
    consume privacy budget even when a transaction is free, while a failed
    delivery does not consume it.  ``consume`` returns ``False`` atomically
    when the requested cost would exceed the remaining budget.
    """

    def __init__(self, budgets: Mapping[str, Decimal | float]) -> None:
        self._budgets = {actor: max(Decimal("0"), Decimal(str(value))) for actor, value in budgets.items()}
        self._spent = {actor: Decimal("0") for actor in self._budgets}

    def remaining(self, actor_id: str) -> Decimal:
        return max(Decimal("0"), self._budgets.get(actor_id, Decimal("0")) - self._spent.get(actor_id, Decimal("0")))

    def consume(self, actor_id: str, cost: Decimal | float) -> bool:
        amount = Decimal(str(cost))
        if amount < 0:
            raise ValueError("privacy cost must be non-negative")
        if amount > self.remaining(actor_id):
            return False
        self._spent[actor_id] = self._spent.get(actor_id, Decimal("0")) + amount
        return True

    def snapshot(self) -> Mapping[str, str]:
        return {actor: str(self.remaining(actor)) for actor in sorted(self._budgets)}


class PrivacyAwareStrategy(TruthfulStrategy):
    """Truthful bidding adjusted for per-unit privacy cost and a finite budget."""

    name = "privacy_aware_truthful"

    def __init__(self, ledger: PrivacyBudgetLedger | None = None) -> None:
        super().__init__()
        self.ledger = ledger
        self._last_privacy_cost = Decimal("0")
        self._last_adjusted_bid = Decimal("0")

    @property
    def spec(self) -> ComponentSpec:
        return ComponentSpec(self.name, "1.0.0", "data_market", "participant_strategy", capabilities=("privacy_budget", "cost_aware"))

    def decide(self, observation, context):
        decision = super().decide(observation, context)
        if not decision.bids:
            return decision
        bid = decision.bids[0]
        cost = Decimal(str(observation.actor.preferences.get("privacy_cost", 0)))
        self._last_privacy_cost = max(Decimal("0"), cost)
        budget_left = self.ledger.remaining(observation.actor.actor_id) if self.ledger else Decimal("Infinity")
        net_value = max(Decimal("0"), bid.amount.amount - cost)
        if budget_left <= 0:
            net_value = Decimal("0")
        adjusted = type(bid)(bid.bid_id, bid.buyer_id, bid.product_ids, type(bid.amount)(net_value, bid.amount.currency), bid.quantity, bid.task_id, bid.constraints, {**bid.metadata, "privacy_cost": str(cost), "privacy_budget_remaining": str(budget_left)})
        self._last_adjusted_bid = net_value
        return type(decision)(decision.actor_id, bids=(adjusted,), state={**decision.state, "privacy_cost": str(cost), "privacy_budget_remaining": str(budget_left)})

    def observe(self, step: SimulationStep, context) -> None:
        super().observe(step, context)
        if self.ledger is None or self._last_actor_id is None:
            return
        won, _ = _won_and_paid(step, self._last_actor_id)
        if won and self._last_adjusted_bid > 0:
            quantity = next((allocation.quantity for allocation in step.outcome.allocations if allocation.buyer_id == self._last_actor_id), Decimal("0")) if step.outcome else Decimal("0")
            self.ledger.consume(self._last_actor_id, quantity * self._last_privacy_cost)


@dataclass(frozen=True)
class SimulationMetrics:
    """Market-health metrics derived from a simulation trace."""

    rounds: int
    trade_rounds: int
    conversion_rate: float
    total_revenue: Decimal
    mean_trade_price: Decimal
    price_volatility: Decimal
    seller_hhi: float
    seller_revenue_gini: float
    buyer_coverage: float
    welfare_per_trade: Decimal


def summarize_simulation(report: SimulationReport) -> SimulationMetrics:
    """Compute liquidity, concentration and volatility from a report."""

    steps = report.steps
    prices = [
        payment.amount.amount
        for step in steps
        if step.outcome
        for payment in (step.outcome.payments if isinstance(step.outcome.payments, tuple) else (step.outcome.payments,))
    ]
    revenues: dict[str, Decimal] = {}
    buyers: set[str] = set()
    traded_buyers: set[str] = set()
    for step in steps:
        buyers.update(decision.actor_id for decision in step.decisions)
        if not step.outcome:
            continue
        payments = step.outcome.payments if isinstance(step.outcome.payments, tuple) else (step.outcome.payments,)
        for payment in payments:
            revenues[payment.payee_id] = revenues.get(payment.payee_id, Decimal("0")) + payment.amount.amount
        allocations = step.outcome.allocations if isinstance(step.outcome.allocations, tuple) else (step.outcome.allocations,)
        traded_buyers.update(allocation.buyer_id for allocation in allocations)
    total = sum(prices, Decimal("0"))
    mean = total / Decimal(len(prices)) if prices else Decimal("0")
    variance = sum((price - mean) ** 2 for price in prices) / Decimal(len(prices)) if prices else Decimal("0")
    shares = [float(value / total) for value in revenues.values()] if total else []
    ordered = sorted(revenues.values())
    n = len(ordered)
    gini = float(
        2 * sum(index * value for index, value in enumerate(ordered, 1)) / (Decimal(n) * sum(ordered))
        - Decimal(n + 1) / Decimal(n)
    ) if n and sum(ordered) else 0.0
    welfare = sum((step.outcome.welfare or Decimal("0") for step in steps if step.outcome), Decimal("0"))
    trade_rounds = sum(bool(step.outcome and step.outcome.allocations) for step in steps)
    return SimulationMetrics(len(steps), trade_rounds, trade_rounds / len(steps) if steps else 0.0, total, mean, variance.sqrt() if variance else Decimal("0"), sum(share * share for share in shares), gini, len(traded_buyers) / len(buyers) if buyers else 0.0, welfare / Decimal(trade_rounds) if trade_rounds else Decimal("0"))


__all__ = ["decay_market_freshness", "apply_participation_shock", "PrivacyBudgetLedger", "PrivacyAwareStrategy", "SimulationMetrics", "summarize_simulation"]
