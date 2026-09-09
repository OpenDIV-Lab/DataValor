"""Mechanism-design utilities that sit *around* DataPrice mechanisms.

The pricing package computes a quote, allocation and payment.  A market still
needs a matching/admission step and a way to check whether the resulting
mechanism has the properties expected by a data marketplace.  The functions
in this module are deliberately side-effect free: they do not change bids,
asks or prices and therefore can be used in experiments, pre-trade controls
and audit reports.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from decimal import Decimal
from itertools import combinations
from typing import Any, Mapping, Sequence

from datavalor.core import ActorProfile, ComponentSpec, RunContext
from datavalor.data_price import Allocation, Ask, Bid, Money, Payment, PricingOutcome

from .interfaces import RevenueAllocator
from .models import Listing, ListingStatus, RevenueAllocation, RevenueShare


@dataclass(frozen=True)
class MarketMatch:
    """A feasible buyer--seller match before a price is cleared."""

    bid_id: str
    ask_id: str
    buyer_id: str
    seller_id: str
    product_ids: tuple[str, ...]
    quantity: Decimal
    surplus: Money
    diagnostics: Mapping[str, Any] = field(default_factory=dict)


def match_orders(
    bids: Sequence[Bid],
    asks: Sequence[Ask],
    listings: Sequence[Listing] = (),
    *,
    min_quality: Decimal | float = Decimal("0"),
) -> tuple[MarketMatch, ...]:
    """Match compatible orders using price-time priority.

    This is an order-book operation, not a pricing mechanism: it only decides
    which active products can trade.  Bids are ordered by reported willingness
    to pay (descending) and asks by reserve (ascending).  A seller ask can be
    split across buyers until its quantity is exhausted.  Product quality and
    listing status are checked when listings are supplied.
    """

    quality_by_product = {
        listing.product.product_id: Decimal(
            str(listing.metadata.get("quality", listing.product.metadata.get("quality", 1)))
        )
        for listing in listings
    }
    active_products = {
        listing.product.product_id
        for listing in listings
        if listing.status is ListingStatus.ACTIVE
        and Decimal(str(listing.metadata.get("quality", listing.product.metadata.get("quality", 1))))
        >= Decimal(str(min_quality))
    }
    use_filter = bool(listings)
    remaining = {ask.ask_id: max(Decimal("0"), ask.quantity) for ask in asks}
    result: list[MarketMatch] = []
    ordered_bids = sorted(bids, key=lambda item: (-item.amount.amount, item.bid_id))
    ordered_asks = sorted(asks, key=lambda item: (item.reserve.amount, item.ask_id))
    for bid in ordered_bids:
        if bid.quantity <= 0 or not bid.product_ids:
            continue
        for ask in ordered_asks:
            if remaining[ask.ask_id] <= 0 or ask.quantity <= 0:
                continue
            products = tuple(sorted(set(bid.product_ids).intersection(ask.product_ids)))
            if use_filter:
                products = tuple(product for product in products if product in active_products)
            if not products or bid.amount.currency != ask.reserve.currency:
                continue
            required_quality = Decimal(str(bid.constraints.get("min_quality", min_quality)))
            if listings and any(quality_by_product.get(product, Decimal("0")) < required_quality for product in products):
                continue
            quantity = min(max(Decimal("0"), bid.quantity), remaining[ask.ask_id])
            if quantity <= 0 or bid.amount.amount < ask.reserve.amount:
                continue
            surplus = (bid.amount.amount - ask.reserve.amount) * quantity
            result.append(
                MarketMatch(
                    bid.bid_id,
                    ask.ask_id,
                    bid.buyer_id,
                    ask.seller_id,
                    products,
                    quantity,
                    Money(surplus, bid.amount.currency),
                    {"bid_amount": str(bid.amount.amount), "reserve": str(ask.reserve.amount)},
                )
            )
            remaining[ask.ask_id] -= quantity
            break  # one bid is matched to one seller in this clearing pass
    return tuple(result)


@dataclass(frozen=True)
class MechanismAuditReport:
    """Observable mechanism properties and the evidence behind them."""

    properties: Mapping[str, bool | None]
    metrics: Mapping[str, Any]
    violations: tuple[str, ...]


def audit_market_mechanism(
    bids: Sequence[Bid],
    asks: Sequence[Ask],
    outcome: PricingOutcome,
    *,
    efficiency_threshold: Decimal | float = Decimal("0.95"),
) -> MechanismAuditReport:
    """Check IR, budget balance and allocative efficiency of an outcome.

    The report is intentionally empirical: truthfulness cannot be proven from
    one trace, but individual rationality, no-deficit and welfare loss can be
    checked exactly against the submitted orders.  It is suitable as a gate
    in mechanism experiments and stores enough metrics to reproduce a result.
    """

    bid_by_key = {(bid.buyer_id, product): bid for bid in bids for product in bid.product_ids}
    ask_by_key = {(ask.seller_id, product): ask for ask in asks for product in ask.product_ids}
    buyer_paid: dict[str, Decimal] = {}
    seller_received: dict[str, Decimal] = {}
    payments = outcome.payments if isinstance(outcome.payments, tuple) else (outcome.payments,)
    allocations = outcome.allocations if isinstance(outcome.allocations, tuple) else (outcome.allocations,)
    for payment in payments:
        buyer_paid[payment.payer_id] = buyer_paid.get(payment.payer_id, Decimal("0")) + payment.amount.amount
        seller_received[payment.payee_id] = seller_received.get(payment.payee_id, Decimal("0")) + payment.amount.amount
    buyer_reported: dict[str, Decimal] = {}
    for allocation in allocations:
        reported = sum(
            (bid_by_key.get((allocation.buyer_id, product), Bid("", allocation.buyer_id, (), Money(0))).amount.amount for product in allocation.product_ids),
            Decimal("0"),
        ) * allocation.quantity
        buyer_reported[allocation.buyer_id] = buyer_reported.get(allocation.buyer_id, Decimal("0")) + reported
    buyer_ir = all(buyer_paid.get(actor, Decimal("0")) <= value for actor, value in buyer_reported.items())
    seller_reserve: dict[str, Decimal] = {}
    for payment in payments:
        quantity = Decimal(str(payment.metadata.get("quantity", "1")))
        seller_reserve[payment.payee_id] = seller_reserve.get(payment.payee_id, Decimal("0")) + sum(
            (ask_by_key[(payment.payee_id, product)].reserve.amount * quantity for product in payment.product_ids if (payment.payee_id, product) in ask_by_key),
            Decimal("0"),
        )
    seller_ir = all(seller_received.get(actor, Decimal("0")) >= value for actor, value in seller_reserve.items())
    buyer_total = sum(buyer_paid.values(), Decimal("0"))
    seller_total = sum(seller_received.values(), Decimal("0"))
    feasible = match_orders(bids, asks)
    efficient_welfare = sum((match.surplus.amount for match in feasible), Decimal("0"))
    realized_welfare = outcome.welfare if outcome.welfare is not None else Decimal("0")
    efficiency = realized_welfare / efficient_welfare if efficient_welfare > 0 else Decimal("1")
    threshold = Decimal(str(efficiency_threshold))
    properties = {
        "buyer_individual_rationality": buyer_ir,
        "seller_individual_rationality": seller_ir,
        "weak_budget_balance": buyer_total >= seller_total,
        "no_deficit": buyer_total - seller_total >= 0,
        "allocative_efficiency_target": efficiency >= threshold,
    }
    violations = tuple(name for name, passed in properties.items() if passed is False)
    return MechanismAuditReport(
        properties,
        {
            "buyer_payments": str(buyer_total),
            "seller_payments": str(seller_total),
            "platform_surplus": str(buyer_total - seller_total),
            "efficient_welfare": str(efficient_welfare),
            "realized_welfare": str(realized_welfare),
            "efficiency_ratio": str(efficiency),
            "matched_order_count": len(feasible),
        },
        violations,
    )


@dataclass(frozen=True)
class QuotaDecision:
    allocations: tuple[Allocation, ...]
    payments: tuple[Payment, ...]
    denied: Mapping[str, Decimal]
    diagnostics: Mapping[str, Any]


class QuotaAdmissionController:
    """Enforce buyer/product usage quotas after pricing and before delivery."""

    def admit(
        self,
        outcome: PricingOutcome,
        quotas: Mapping[str, Mapping[str, Decimal]],
        usage: Mapping[tuple[str, str], Decimal] | None = None,
    ) -> QuotaDecision:
        usage = usage or {}
        usage_left = {(buyer, product): Decimal(str(limit)) - Decimal(str(usage.get((buyer, product), 0))) for buyer, products in quotas.items() for product, limit in products.items()}
        accepted: list[Allocation] = []
        denied: dict[str, Decimal] = {}
        ratios: dict[tuple[str, tuple[str, ...]], Decimal] = {}
        allocations = outcome.allocations if isinstance(outcome.allocations, tuple) else (outcome.allocations,)
        payments_in = outcome.payments if isinstance(outcome.payments, tuple) else (outcome.payments,)
        for allocation in allocations:
            allowed = min((usage_left.get((allocation.buyer_id, product), allocation.quantity) for product in allocation.product_ids), default=allocation.quantity)
            allowed = max(Decimal("0"), min(allocation.quantity, allowed))
            if allowed > 0:
                accepted.append(Allocation(allocation.buyer_id, allocation.product_ids, allowed, allocation.reported_value, allocation.metadata))
                ratios[(allocation.buyer_id, allocation.product_ids)] = allowed / allocation.quantity if allocation.quantity else Decimal("0")
                for product in allocation.product_ids:
                    if (allocation.buyer_id, product) in usage_left:
                        usage_left[(allocation.buyer_id, product)] -= allowed
            if allowed < allocation.quantity:
                denied[f"{allocation.buyer_id}:{','.join(allocation.product_ids)}"] = allocation.quantity - allowed
        payments: list[Payment] = []
        for payment in payments_in:
            ratio = ratios.get((payment.payer_id, payment.product_ids), Decimal("1"))
            if ratio > 0:
                payments.append(Payment(payment.payer_id, payment.payee_id, Money(payment.amount.amount * ratio, payment.amount.currency), payment.reason, payment.product_ids, {**payment.metadata, "quota_ratio": str(ratio)}))
        return QuotaDecision(tuple(accepted), tuple(payments), denied, {"denied_count": len(denied), "remaining_quota": {f"{b}:{p}": str(v) for (b, p), v in usage_left.items()}})


class ShapleyRevenueAllocator(RevenueAllocator):
    """Allocate revenue by marginal contribution in a cooperative game.

    ``context.metadata['coalition_values']`` may provide values keyed by
    ``"actor-a|actor-b"``.  Missing coalitions use additive contributions.
    Exact Shapley values are used up to ``max_exact_players``; larger markets
    use deterministic permutation sampling controlled by ``RunContext.seed``.
    """

    def __init__(self, max_exact_players: int = 10, samples: int = 2048) -> None:
        self.max_exact_players, self.samples = max_exact_players, samples

    @property
    def spec(self) -> ComponentSpec:
        return ComponentSpec("revenue.shapley", "1.0.0", "data_market", "revenue_allocator", capabilities=("shapley", "cooperative_game", "exact_reconciliation"))

    def allocate(self, total: Money, participants: tuple[ActorProfile, ...], contributions: Mapping[str, Decimal], context: RunContext) -> RevenueAllocation:
        actors = tuple(dict.fromkeys(profile.actor_id for profile in participants))
        if not actors:
            if total.amount != 0:
                raise ValueError("cannot allocate non-zero revenue without participants")
            return RevenueAllocation(total, (), self.spec.name)
        values = context.metadata.get("coalition_values", {})
        weights = {actor: Decimal(str(contributions.get(actor, 0))) for actor in actors}

        def coalition(group: frozenset[str]) -> Decimal:
            key = "|".join(sorted(group))
            if key in values:
                return Decimal(str(values[key]))
            return sum((max(Decimal("0"), weights[a]) for a in group), Decimal("0"))

        shapley = {actor: Decimal("0") for actor in actors}
        exact = len(actors) <= self.max_exact_players
        if exact:
            n = len(actors)
            for actor in actors:
                others = [a for a in actors if a != actor]
                for size in range(len(others) + 1):
                    coeff = Decimal(math.factorial(size) * math.factorial(n - size - 1)) / Decimal(math.factorial(n))
                    for subset in combinations(others, size):
                        group = frozenset(subset)
                        shapley[actor] += coeff * (coalition(group | {actor}) - coalition(group))
        else:
            rng = random.Random(context.seed)
            for _ in range(max(1, self.samples)):
                permutation = list(actors); rng.shuffle(permutation); before = frozenset()
                previous = coalition(before)
                for actor in permutation:
                    after = coalition(before | {actor}); shapley[actor] += after - previous; before, previous = before | {actor}, after
            shapley = {actor: value / Decimal(max(1, self.samples)) for actor, value in shapley.items()}
        positive = {actor: max(Decimal("0"), value) for actor, value in shapley.items()}
        total_weight = sum(positive.values(), Decimal("0"))
        if total_weight == 0:
            positive = {actor: Decimal("1") for actor in actors}; total_weight = Decimal(len(actors))
        shares = tuple(RevenueShare(actor, Money((total.amount * positive[actor] / total_weight).quantize(Decimal("0.01")), total.currency), "shapley_marginal_contribution", float(positive[actor] / total_weight), {"raw_shapley": str(shapley[actor])}) for actor in actors)
        residual = total.amount - sum((share.amount.amount for share in shares), Decimal("0"))
        if residual:
            first = shares[0]; shares = (RevenueShare(first.actor_id, Money(first.amount.amount + residual, total.currency), first.basis, first.weight, first.metadata),) + shares[1:]
        return RevenueAllocation(total, shares, self.spec.name, {"exact": exact, "player_count": len(actors), "coalition_value_count": len(values), "reconciled": sum((s.amount.amount for s in shares), Decimal("0")) == total.amount})


__all__ = ["MarketMatch", "match_orders", "MechanismAuditReport", "audit_market_mechanism", "QuotaDecision", "QuotaAdmissionController", "ShapleyRevenueAllocator"]
