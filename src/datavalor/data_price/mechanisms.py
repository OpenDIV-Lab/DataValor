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
        revenue[payment.payee_id] = Money(revenue.get(payment.payee_id, Money(Decimal("0"), payment.amount.currency)).amount + payment.amount.amount, payment.amount.currency)
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
        freshness = float(request.market_context.get("freshness", 1.0)); self.price_value = _money(self.price_value.amount * Decimal(str(freshness)), self.currency)
        return super().price(request, context)


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


class McAfeeDoubleAuction(PricingMechanism):
    name = "mcafee_double_auction"

    @property
    def spec(self): return ComponentSpec(self.name, "1.0", "data_price", "pricing_mechanism")

    def price(self, request, context):
        bids = sorted(request.bids, key=lambda item: item.amount.amount, reverse=True); asks = sorted(request.asks, key=lambda item: item.reserve.amount)
        if not bids or not asks or bids[0].amount.amount < asks[0].reserve.amount: return _outcome(self.name)
        amount = _money((bids[0].amount.amount + asks[0].reserve.amount) / 2, bids[0].amount.currency)
        allocation = Allocation(bids[0].buyer_id, bids[0].product_ids, bids[0].quantity, bids[0].amount)
        return _outcome(self.name, [allocation], [Payment(bids[0].buyer_id, asks[0].seller_id, amount, "mcafee", bids[0].product_ids)], welfare=bids[0].amount.amount - asks[0].reserve.amount)


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


class ProportionalShareProcurement(BudgetFeasibleProcurement): name = "proportional_share_procurement"
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
