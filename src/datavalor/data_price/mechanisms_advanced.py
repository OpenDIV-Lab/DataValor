"""Multi-unit and constraint-aware pricing mechanisms."""

from __future__ import annotations

from decimal import Decimal

from datavalor.core import ComponentSpec

from .interfaces import PricingMechanism
from .mechanisms import _money, _outcome
from .models import Allocation, Payment


class MultiUnitUniformPriceAuction(PricingMechanism):
    """Uniform-price auction with quantity bids and explicit supply."""

    @property
    def spec(self) -> ComponentSpec:
        return ComponentSpec("multi_unit_uniform_price", "1.0.0", "data_price", "pricing_mechanism", capabilities=("multi_unit", "uniform_price"))

    def price(self, request, context):
        bids = sorted(request.bids, key=lambda item: item.amount.amount, reverse=True)
        if not bids:
            return _outcome(self.spec.name, diagnostics={"clearing": False})
        product_id = bids[0].product_ids[0] if bids[0].product_ids else ""
        supply = Decimal(str(request.supply.get(product_id, request.asks[0].quantity if request.asks else 1)))
        reserve = request.asks[0].reserve.amount if request.asks else Decimal("0")
        accepted = []
        remaining = max(Decimal("0"), supply)
        for bid in bids:
            quantity = min(max(Decimal("0"), bid.quantity), remaining)
            if quantity <= 0:
                continue
            if bid.amount.amount < reserve:
                continue
            accepted.append((bid, quantity)); remaining -= quantity
            if remaining <= 0:
                break
        if not accepted:
            return _outcome(self.spec.name, diagnostics={"clearing": False, "supply": str(supply)})
        # Uniform-price auctions charge all winners the marginal accepted bid
        # when supply binds; if supply is slack, the seller reserve is the
        # market-clearing floor.  This also handles a partially filled final
        # bid correctly (the previous implementation incorrectly charged 0).
        clearing = accepted[-1][0].amount.amount if remaining <= 0 else reserve
        seller = request.asks[0].seller_id if request.asks else "platform"; allocations = []; payments = []
        for bid, quantity in accepted:
            amount = _money(clearing * quantity, bid.amount.currency)
            allocations.append(Allocation(bid.buyer_id, bid.product_ids, quantity, _money(bid.amount.amount * quantity, bid.amount.currency), {"unit_price": str(clearing)}))
            payments.append(Payment(bid.buyer_id, seller, amount, "uniform_price", bid.product_ids, {"quantity": str(quantity)}))
        welfare = sum(bid.amount.amount * quantity for bid, quantity in accepted) - sum((request.asks[0].reserve.amount if request.asks else Decimal("0")) * quantity for _, quantity in accepted)
        return _outcome(self.spec.name, allocations, payments, welfare=welfare, diagnostics={"clearing": True, "unit_price": str(clearing), "supply": str(supply), "allocated": str(supply - remaining)})


class BudgetAwareProcurement(PricingMechanism):
    """Greedy procurement by reserve price with partial final quantity."""

    @property
    def spec(self) -> ComponentSpec:
        return ComponentSpec("budget_aware_procurement", "1.0.0", "data_price", "pricing_mechanism", capabilities=("budget", "partial_quantity", "procurement"))

    def price(self, request, context):
        del context
        budget = Decimal(str(request.market_context.get("budget", "0"))); buyer = str(request.market_context.get("buyer_id", "buyer")); spent = Decimal("0"); allocations = []; payments = []; skipped = []
        for ask in self._ordered_asks(request.asks):
            if ask.quantity <= 0 or ask.reserve.amount <= 0:
                skipped.append(ask.ask_id); continue
            # Avoid allocating numerical dust after a fractional fill (for
            # example 100 / 30 leaves a tiny Decimal remainder).
            if budget - spent <= Decimal("1e-12"):
                skipped.append(ask.ask_id)
                continue
            remaining = budget - spent; quantity = min(ask.quantity, remaining / ask.reserve.amount)
            if quantity <= 0:
                skipped.append(ask.ask_id); continue
            amount = ask.reserve.amount * quantity; allocations.append(Allocation(buyer, ask.product_ids, quantity, _money(amount, ask.reserve.currency))); payments.append(Payment(buyer, ask.seller_id, _money(amount, ask.reserve.currency), "budget_procurement", ask.product_ids, {"quantity": str(quantity)})); spent += amount
        return _outcome(self.spec.name, allocations, payments, diagnostics={"budget": str(budget), "spent": str(spent), "remaining": str(budget - spent), "skipped_asks": tuple(skipped)})

    def _ordered_asks(self, asks):
        """Return the deterministic procurement order used by the mechanism."""
        return sorted(asks, key=lambda item: item.reserve.amount)


class QualityAwareProcurement(BudgetAwareProcurement):
    """Procurement ranked by quality-per-cost rather than price alone."""

    @property
    def spec(self) -> ComponentSpec:
        return ComponentSpec("quality_aware_procurement", "1.0.0", "data_price", "pricing_mechanism", capabilities=("quality", "budget", "procurement"))

    def price(self, request, context):
        return super().price(request, context)

    def _ordered_asks(self, asks):
        def quality_per_cost(ask):
            quality = Decimal(str(ask.metadata.get("quality", "1")))
            return quality / max(ask.reserve.amount, Decimal("1e-12"))

        return sorted(asks, key=quality_per_cost, reverse=True)


__all__ = ["BudgetAwareProcurement", "MultiUnitUniformPriceAuction", "QualityAwareProcurement"]
