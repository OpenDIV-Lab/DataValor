"""Reusable auction and pricing mechanisms adapted to DataValor models."""

from __future__ import annotations

from decimal import Decimal

from datavalor.core import ComponentSpec

from .interfaces import PriceConstraint, PricingMechanism
from .models import (
    Allocation,
    Money,
    Payment,
    PriceQuote,
    PricingOutcome,
)


def _money(value, currency="CNY") -> Money:
    return Money(value if isinstance(value, Decimal) else Decimal(str(value)), currency)


def _outcome(name, allocations=(), payments=(), *, welfare=None, diagnostics=None):
    revenue = {}
    for payment in payments:
        previous = revenue.get(payment.payee_id)
        if previous is not None and previous.currency != payment.amount.currency:
            raise ValueError(f"mixed currencies for seller {payment.payee_id}")
        revenue[payment.payee_id] = Money((previous.amount if previous else Decimal("0")) + payment.amount.amount, payment.amount.currency)
    return PricingOutcome(name, tuple(allocations), tuple(payments), welfare, revenue, diagnostics=diagnostics or {})


class _SingleItem(PricingMechanism):
    @property
    def spec(self):
        return ComponentSpec(self.name, "1.0", "data_price", "pricing_mechanism")

    def _winner(self, request):
        return max(request.bids, key=lambda bid: bid.amount.amount, default=None)


class FirstPriceAuction(_SingleItem):
    name = "first_price_auction"

    def price(self, request, context):
        winner = self._winner(request)
        if not winner: return _outcome(self.name)
        seller = request.asks[0].seller_id if request.asks else "platform"
        allocation = Allocation(winner.buyer_id, winner.product_ids, winner.quantity, winner.amount)
        payment = Payment(winner.buyer_id, seller, winner.amount, "first_price", winner.product_ids)
        return _outcome(self.name, [allocation], [payment], welfare=winner.amount.amount)


class SecondPriceAuction(_SingleItem):
    name = "second_price_auction"

    def price(self, request, context):
        bids = sorted(request.bids, key=lambda bid: bid.amount.amount, reverse=True)
        if not bids: return _outcome(self.name)
        winner = bids[0]; amount = bids[1].amount if len(bids) > 1 else (request.asks[0].reserve if request.asks else _money(0, winner.amount.currency))
        seller = request.asks[0].seller_id if request.asks else "platform"
        return _outcome(self.name, [Allocation(winner.buyer_id, winner.product_ids, winner.quantity, winner.amount)], [Payment(winner.buyer_id, seller, amount, "second_price", winner.product_ids)], welfare=winner.amount.amount)


class PostedPriceMechanism(_SingleItem):
    name = "posted_price"

    def __init__(self, price=0, currency="CNY"): self.price_value, self.currency = _money(price, currency), currency

    def price(self, request, context):
        if not request.bids: return _outcome(self.name)
        bid = max(request.bids, key=lambda item: item.amount.amount)
        if bid.amount.amount < self.price_value.amount: return _outcome(self.name, diagnostics={"accepted": False})
        seller = request.asks[0].seller_id if request.asks else "platform"
        return _outcome(self.name, [Allocation(bid.buyer_id, bid.product_ids, bid.quantity, bid.amount)], [Payment(bid.buyer_id, seller, self.price_value, "posted_price", bid.product_ids)], welfare=bid.amount.amount, diagnostics={"accepted": True})


class FreshnessAdjustedPostedPrice(PostedPriceMechanism):
    name = "freshness_adjusted_posted_price"

    def price(self, request, context):
        freshness = Decimal(str(request.market_context.get("freshness", 1.0)))
        original = self.price_value
        self.price_value = _money(original.amount * max(Decimal("0"), freshness), self.currency)
        try:
            return super().price(request, context)
        finally:
            # A mechanism instance may be reused across requests; freshness
            # is request-local and must not compound over repeated calls.
            self.price_value = original


class MenuPricingMechanism(PostedPriceMechanism):
    name = "menu_pricing"

    def __init__(self, menu=None, currency="CNY"): self.menu, self.currency = menu or {}, currency

    def price(self, request, context):
        product_id = request.bids[0].product_ids[0] if request.bids else ""
        self.price_value = _money(self.menu.get(product_id, 0), self.currency)
        return super().price(request, context)


class VCGMechanism(_SingleItem):
    name = "vcg"

    def price(self, request, context):
        bids = sorted(request.bids, key=lambda bid: bid.amount.amount, reverse=True)
        if not bids: return _outcome(self.name)
        winner = bids[0]; second = bids[1].amount if len(bids) > 1 else _money(0, winner.amount.currency); seller = request.asks[0].seller_id if request.asks else "platform"
        return _outcome(self.name, [Allocation(winner.buyer_id, winner.product_ids, winner.quantity, winner.amount)], [Payment(winner.buyer_id, seller, second, "vcg", winner.product_ids)], welfare=winner.amount.amount)


class BilateralMidpointTrade(PricingMechanism):
    """The former single-pair midpoint behavior, retained under an accurate name."""

    name = "bilateral_midpoint_trade"

    @property
    def spec(self):
        return ComponentSpec(self.name, "1.0", "data_price", "pricing_mechanism")

    def price(self, request, context):
        del context
        bids = sorted(request.bids, key=lambda item: (-item.amount.amount, item.buyer_id))
        asks = sorted(request.asks, key=lambda item: (item.reserve.amount, item.seller_id))
        if not bids or not asks or bids[0].amount.amount < asks[0].reserve.amount:
            return _outcome(self.name)
        amount = _money(
            (bids[0].amount.amount + asks[0].reserve.amount) / 2,
            bids[0].amount.currency,
        )
        allocation = Allocation(
            bids[0].buyer_id,
            bids[0].product_ids,
            bids[0].quantity,
            bids[0].amount,
            {"seller_id": asks[0].seller_id},
        )
        return _outcome(
            self.name,
            [allocation],
            [Payment(bids[0].buyer_id, asks[0].seller_id, amount, "midpoint", bids[0].product_ids)],
            welfare=bids[0].amount.amount - asks[0].reserve.amount,
        )


class McAfeeDoubleAuction(PricingMechanism):
    """McAfee trade-reduction auction for homogeneous single-unit reports."""

    name = "mcafee_double_auction"

    @property
    def spec(self):
        return ComponentSpec(
            self.name,
            "2.0",
            "data_price",
            "pricing_mechanism",
            capabilities=("double_auction", "multi_party", "single_unit"),
        )

    def price(self, request, context):
        del context
        reports = (*request.bids, *request.asks)
        if any(report.quantity != Decimal("1") for report in reports):
            raise ValueError("McAfee requires unit quantity reports")
        currencies = {
            *(bid.amount.currency for bid in request.bids),
            *(ask.reserve.currency for ask in request.asks),
        }
        if len(currencies) > 1:
            raise ValueError("McAfee bid/ask currency mismatch")
        buyer_ids = [bid.buyer_id for bid in request.bids]
        seller_ids = [ask.seller_id for ask in request.asks]
        if len(set(buyer_ids)) != len(buyer_ids) or len(set(seller_ids)) != len(seller_ids):
            raise ValueError("McAfee actor IDs must be unique")

        bids = sorted(request.bids, key=lambda item: (-item.amount.amount, item.buyer_id))
        asks = sorted(request.asks, key=lambda item: (item.reserve.amount, item.seller_id))
        efficient_count = 0
        for bid, ask in zip(bids, asks):
            if bid.amount.amount < ask.reserve.amount:
                break
            efficient_count += 1
        if efficient_count == 0:
            return _outcome(
                self.name,
                diagnostics={"branch": "no_trade", "efficient_trade_count": 0, "trade_count": 0},
            )

        pair_limit = min(len(bids), len(asks))
        candidate_price = None
        if efficient_count < pair_limit:
            candidate_price = (
                bids[efficient_count].amount.amount + asks[efficient_count].reserve.amount
            ) / 2
        marginal_bid = bids[efficient_count - 1].amount.amount
        marginal_ask = asks[efficient_count - 1].reserve.amount
        if candidate_price is not None and marginal_ask <= candidate_price <= marginal_bid:
            trade_count = efficient_count
            buyer_price = seller_price = candidate_price
            branch = "candidate_price"
        else:
            trade_count = max(0, efficient_count - 1)
            buyer_price = marginal_bid
            seller_price = marginal_ask
            branch = "trade_reduction"

        allocations = []
        payments = []
        currency = next(iter(currencies), "CNY")
        for index in range(trade_count):
            bid, ask = bids[index], asks[index]
            allocations.append(
                Allocation(
                    bid.buyer_id,
                    bid.product_ids,
                    Decimal("1"),
                    bid.amount,
                    {
                        "seller_id": ask.seller_id,
                        "buyer_price": str(buyer_price),
                        "seller_price": str(seller_price),
                    },
                )
            )
            if buyer_price == seller_price:
                payments.append(
                    Payment(
                        bid.buyer_id,
                        ask.seller_id,
                        _money(buyer_price, currency),
                        "mcafee_uniform_price",
                        bid.product_ids,
                    )
                )
            else:
                payments.extend(
                    (
                        Payment(
                            bid.buyer_id,
                            "platform",
                            _money(buyer_price, currency),
                            "mcafee_buyer_payment",
                            bid.product_ids,
                            {"seller_id": ask.seller_id},
                        ),
                        Payment(
                            "platform",
                            ask.seller_id,
                            _money(seller_price, currency),
                            "mcafee_seller_payment",
                            bid.product_ids,
                            {"buyer_id": bid.buyer_id},
                        ),
                    )
                )
        welfare = sum(
            (
                bids[index].amount.amount - asks[index].reserve.amount
                for index in range(trade_count)
            ),
            Decimal("0"),
        )
        surplus = (buyer_price - seller_price) * trade_count
        return _outcome(
            self.name,
            allocations,
            payments,
            welfare=welfare,
            diagnostics={
                "branch": branch,
                "efficient_trade_count": efficient_count,
                "trade_count": trade_count,
                "candidate_price": str(candidate_price) if candidate_price is not None else None,
                "buyer_price": str(buyer_price),
                "seller_price": str(seller_price),
                "auctioneer_surplus": str(surplus),
            },
        )


class BudgetFeasibleProcurement(PricingMechanism):
    name = "budget_feasible_procurement"

    @property
    def spec(self): return ComponentSpec(self.name, "1.0", "data_price", "pricing_mechanism")

    def price(self, request, context):
        budget = Decimal(str(request.market_context.get("budget", "0"))); allocations = []; payments = []; spent = Decimal("0")
        for ask in sorted(request.asks, key=lambda item: item.reserve.amount):
            if spent + ask.reserve.amount > budget: break
            allocations.append(Allocation(request.market_context.get("buyer_id", "buyer"), ask.product_ids, ask.quantity)); payments.append(Payment(request.market_context.get("buyer_id", "buyer"), ask.seller_id, ask.reserve, "procurement", ask.product_ids)); spent += ask.reserve.amount
        return _outcome(self.name, allocations, payments, diagnostics={"budget": str(budget), "spent": str(spent)})


class ProportionalShareProcurement(BudgetFeasibleProcurement):
    """Additive proportional-share procurement with critical payments.

    Public seller values are supplied separately from reported asks through
    ``market_context['seller_values']``.  The mechanism therefore never reads
    evaluator-side true costs.
    """

    name = "proportional_share_procurement"

    def price(self, request, context):
        del context
        budget = Decimal(str(request.market_context.get("budget", "0")))
        buyer = str(request.market_context.get("buyer_id", "buyer"))
        raw_values = request.market_context.get("seller_values", {})
        if budget < 0:
            raise ValueError("budget must be non-negative")
        seller_ids = [ask.seller_id for ask in request.asks]
        if len(set(seller_ids)) != len(seller_ids):
            raise ValueError("seller IDs must be unique")

        ranked = []
        for ask in request.asks:
            value = Decimal(str(raw_values.get(ask.seller_id, "0")))
            cost = ask.reserve.amount
            if value <= 0 or cost <= 0:
                raise ValueError("proportional share requires positive values and asks")
            ranked.append((ask, value))
        ranked.sort(key=lambda item: (-(item[1] / item[0].reserve.amount), item[0].seller_id))

        winners = []
        cumulative_value = Decimal("0")
        for ask, value in ranked:
            candidate_value = cumulative_value + value
            if ask.reserve.amount <= budget * value / candidate_value:
                winners.append((ask, value))
                cumulative_value = candidate_value
            else:
                break

        first_excluded = ranked[len(winners)] if len(winners) < len(ranked) else None
        allocations = []
        payments = []
        for ask, value in winners:
            proportional_cap = budget * value / cumulative_value
            if first_excluded is None:
                critical = proportional_cap
            else:
                excluded_ask, excluded_value = first_excluded
                replacement_threshold = value * excluded_ask.reserve.amount / excluded_value
                critical = min(proportional_cap, replacement_threshold)
            allocations.append(Allocation(buyer, ask.product_ids, ask.quantity))
            payments.append(
                Payment(
                    buyer,
                    ask.seller_id,
                    _money(critical, ask.reserve.currency),
                    "proportional_share_critical",
                    ask.product_ids,
                )
            )
        spent = sum((payment.amount.amount for payment in payments), Decimal("0"))
        return _outcome(
            self.name,
            allocations,
            payments,
            diagnostics={
                "budget": str(budget),
                "spent": str(spent),
                "assumption": "additive_public_values",
                "winner_ids": tuple(ask.seller_id for ask, _ in winners),
            },
        )
class ContributionFairShareMechanism(BudgetFeasibleProcurement): name = "contribution_fair_share"
class CoreSelectingAuction(BudgetFeasibleProcurement): name = "core_selecting_auction"
class ExternalityVCGMechanism(VCGMechanism): name = "externality_vcg"


class ContextualBanditPostedPrice(PostedPriceMechanism):
    name = "contextual_bandit_posted_price"

    def __init__(self, price=0, currency="CNY", learning_rate=.1): super().__init__(price, currency); self.learning_rate = float(learning_rate)


class NoArbitrageProjectionPricing(PriceConstraint):
    name = "no_arbitrage_projection"

    @property
    def spec(self): return ComponentSpec(self.name, "1.0", "data_price", "price_constraint")

    def project(self, quotes, context):
        floor = Decimal(str(context.config.get("minimum_price", 0)))
        return tuple(PriceQuote(q.quote_id, q.product_id, Money(max(q.price.amount, floor), q.price.currency), q.pricing_model, q.buyer_id, q.rights, q.valid_until, q.components, {**q.diagnostics, "projected": True}) for q in quotes)


__all__ = [name for name in globals() if name[0].isupper()]
