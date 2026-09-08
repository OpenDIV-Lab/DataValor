"""Additional pricing models and outcome diagnostics.

These implementations stay on the pricing side of the boundary: they compute
quotes or check a settlement result, but do not register listings, simulate
participants, or make market-discovery decisions.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Mapping, Sequence

from datavalor.core import ComponentSpec

from .interfaces import OnlinePricingModel, PricingModel
from .models import Money, PriceQuote, PricingObservation, PricingOutcome, QuoteRequest


def _decimal(value: Any, default: str = "0") -> Decimal:
    try:
        converted = Decimal(str(value))
    except Exception:
        return Decimal(default)
    return converted if converted.is_finite() else Decimal(default)


def _money(value: Decimal, currency: str) -> Money:
    return Money(max(Decimal("0"), value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), currency)


def _expiry(request: QuoteRequest, context) -> Any:
    seconds = request.market_context.get("valid_seconds")
    return context.started_at + timedelta(seconds=max(0.0, float(seconds))) if seconds is not None else None


class TieredUsagePricingModel(PricingModel):
    """Progressive usage quote with explicit inclusive tier boundaries.

    ``tiers`` is a sequence of ``(upper_bound, unit_price)`` pairs.  Usage is
    charged progressively, so crossing a boundary only changes the marginal
    price of units in the next tier.
    """

    def __init__(self, tiers: Sequence[Sequence[Any]] = ((100, "1.0"), (1000, "0.8"), (math.inf, "0.5")), currency: str = "CNY"):
        normalized = [(Decimal(str(bound)) if bound != math.inf else Decimal("Infinity"), _decimal(price)) for bound, price in tiers]
        if not normalized or any(bound <= 0 or price < 0 for bound, price in normalized):
            raise ValueError("tiers must contain positive bounds and non-negative prices")
        if any(left[0] >= right[0] for left, right in zip(normalized, normalized[1:])):
            raise ValueError("tier upper bounds must be strictly increasing")
        if normalized[-1][0].is_finite():
            normalized.append((Decimal("Infinity"), normalized[-1][1]))
        self.tiers, self.currency = tuple(normalized), currency

    @property
    def spec(self) -> ComponentSpec:
        return ComponentSpec("pricing.tiered_usage", "1.0.0", "data_price", "pricing_model", capabilities=("usage", "tiered", "progressive"))

    def quote(self, request: QuoteRequest, context) -> PriceQuote:
        usage = max(Decimal("0"), _decimal(request.market_context.get("usage", request.market_context.get("records", 0))))
        previous = Decimal("0"); total = Decimal("0"); components: dict[str, Decimal] = {}
        remaining = usage
        for index, (bound, unit_price) in enumerate(self.tiers):
            quantity = remaining if not bound.is_finite() else min(remaining, bound - previous)
            if quantity > 0:
                charge = quantity * unit_price; total += charge; components[f"tier_{index}_quantity"] = quantity; components[f"tier_{index}_charge"] = charge
            remaining -= quantity; previous = bound
            if remaining <= 0:
                break
        return PriceQuote(f"tiered-{context.run_id}", request.product.product_id, _money(total, str(request.market_context.get("currency", self.currency))), self.spec.name, request.buyer.actor_id if request.buyer else None, request.rights or request.product.rights, _expiry(request, context), components, {"usage": usage, "run_id": context.run_id})


class SubscriptionPricingModel(PricingModel):
    """Periodic subscription with included usage and overage billing."""

    @property
    def spec(self) -> ComponentSpec:
        return ComponentSpec("pricing.subscription", "1.0.0", "data_price", "pricing_model", capabilities=("subscription", "usage", "overage"))

    def quote(self, request: QuoteRequest, context) -> PriceQuote:
        ctx = request.market_context; fee = _decimal(ctx.get("period_fee", 0)); included = max(Decimal("0"), _decimal(ctx.get("included_usage", 0))); usage = max(Decimal("0"), _decimal(ctx.get("usage", 0))); overage = max(Decimal("0"), usage - included); overage_price = max(Decimal("0"), _decimal(ctx.get("overage_unit_price", 0))); discount = max(Decimal("0"), min(Decimal("1"), _decimal(ctx.get("commitment_discount", 0)))); discounted_fee = fee * (Decimal("1") - discount); overage_charge = overage * overage_price; total = discounted_fee + overage_charge; currency = str(ctx.get("currency", "CNY"))
        return PriceQuote(f"subscription-{context.run_id}", request.product.product_id, _money(total, currency), self.spec.name, request.buyer.actor_id if request.buyer else None, request.rights or request.product.rights, _expiry(request, context), {"period_fee": fee, "discount": discount, "included_usage": included, "usage": usage, "overage": overage, "overage_charge": overage_charge}, {"run_id": context.run_id, "billing_period": ctx.get("billing_period", "month")})


class RiskAdjustedPricingModel(PricingModel):
    """Quote below buyer value when uncertainty or rights restrictions are high."""

    def __init__(self, risk_aversion: float = 0.5, currency: str = "CNY"):
        if risk_aversion < 0:
            raise ValueError("risk_aversion must be non-negative")
        self.risk_aversion, self.currency = float(risk_aversion), currency

    @property
    def spec(self) -> ComponentSpec:
        return ComponentSpec("pricing.risk_adjusted", "1.0.0", "data_price", "pricing_model", capabilities=("valuation", "uncertainty", "risk"))

    def quote(self, request: QuoteRequest, context) -> PriceQuote:
        ctx = request.market_context; estimated = max(Decimal("0"), _decimal(ctx.get("estimated_value", 0))); std_error = max(Decimal("0"), _decimal(ctx.get("std_error", 0))); share = max(Decimal("0"), min(Decimal("1"), _decimal(ctx.get("buyer_share", "0.5")))); risk_penalty = Decimal(str(self.risk_aversion)) * Decimal("1.96") * std_error; rights_factor = max(Decimal("0"), min(Decimal("1"), _decimal(ctx.get("rights_factor", 1)))); floor = max(Decimal("0"), _decimal(ctx.get("floor", 0))); ceiling = max(floor, _decimal(ctx.get("ceiling", estimated))); base = estimated * share * rights_factor; total = min(ceiling, max(floor, base - risk_penalty)); currency = str(ctx.get("currency", self.currency))
        return PriceQuote(f"risk-{context.run_id}", request.product.product_id, _money(total, currency), self.spec.name, request.buyer.actor_id if request.buyer else None, request.rights or request.product.rights, _expiry(request, context), {"estimated_value": estimated, "buyer_share": share, "rights_factor": rights_factor, "risk_penalty": risk_penalty, "floor": floor, "ceiling": ceiling}, {"run_id": context.run_id, "risk_aversion": self.risk_aversion})


class ElasticityPricingModel(OnlinePricingModel):
    """Demand-elastic price update using observed acceptance and quantity."""

    def __init__(self, initial_price: Any = 100, elasticity: float = 0.2, learning_rate: float = 0.1, target_quantity: float = 1.0, currency: str = "CNY"):
        if elasticity < 0 or learning_rate < 0:
            raise ValueError("elasticity and learning_rate must be non-negative")
        self.price, self.elasticity, self.learning_rate, self.target_quantity, self.currency = _decimal(initial_price), Decimal(str(elasticity)), Decimal(str(learning_rate)), Decimal(str(max(0.0, target_quantity))), currency
        self.observations = 0

    @property
    def spec(self) -> ComponentSpec:
        return ComponentSpec("pricing.elasticity", "1.0.0", "data_price", "online_pricing_model", capabilities=("online", "elasticity", "quantity_feedback"))

    def quote(self, request: QuoteRequest, context) -> PriceQuote:
        return PriceQuote(f"elasticity-{context.run_id}-{self.observations}", request.product.product_id, _money(self.price, self.currency), self.spec.name, request.buyer.actor_id if request.buyer else None, request.rights or request.product.rights, _expiry(request, context), {"price": self.price}, {"observations": self.observations, "target_quantity": self.target_quantity, "elasticity": self.elasticity})

    def observe(self, observation: PricingObservation, context) -> None:
        del context
        realized = max(Decimal("0"), observation.realized_quantity); target = max(Decimal("1e-12"), self.target_quantity); ratio = realized / target; adjustment = Decimal("1") + self.learning_rate * self.elasticity * (ratio - Decimal("1")); self.price = max(Decimal("0"), self.price * adjustment); self.observations += 1


@dataclass(frozen=True)
class QuoteCalibration:
    observations: int
    mean_absolute_error: Decimal
    root_mean_squared_error: Decimal
    mean_signed_error: Decimal
    acceptance_rate: Decimal


def calibrate_quotes(quotes: Sequence[PriceQuote], realized_prices: Sequence[Money], accepted: Sequence[bool] | None = None) -> QuoteCalibration:
    """Compare quoted prices with realized transaction prices."""
    if len(quotes) != len(realized_prices) or not quotes:
        raise ValueError("quotes and realized_prices must be non-empty and equally sized")
    if any(quote.price.currency != realized.currency for quote, realized in zip(quotes, realized_prices)):
        raise ValueError("quote and realized currencies must match per observation")
    errors = [quote.price.amount - realized.amount for quote, realized in zip(quotes, realized_prices)]
    accepted_rate = Decimal(sum(bool(value) for value in accepted)) / Decimal(len(quotes)) if accepted is not None and len(accepted) == len(quotes) else Decimal("0")
    return QuoteCalibration(len(errors), sum(abs(error) for error in errors) / len(errors), (sum(error * error for error in errors) / len(errors)).sqrt(), sum(errors) / len(errors), accepted_rate)


def audit_pricing_outcome(outcome: PricingOutcome) -> Mapping[str, Any]:
    """Check accounting invariants of allocations and payments."""
    allocation_quantity = sum((allocation.quantity for allocation in outcome.allocations), Decimal("0")); payment_total = sum((payment.amount.amount for payment in outcome.payments), Decimal("0")); negative_payments = [str(payment.amount.amount) for payment in outcome.payments if payment.amount.amount < 0]; quantity_issues = [allocation.buyer_id for allocation in outcome.allocations if allocation.quantity < 0]; revenue_total = sum((money.amount for money in outcome.seller_revenue.values()), Decimal("0"))
    return {"mechanism": outcome.mechanism, "allocation_count": len(outcome.allocations), "payment_count": len(outcome.payments), "allocated_quantity": allocation_quantity, "payment_total": payment_total, "seller_revenue_total": revenue_total, "revenue_reconciles": revenue_total == payment_total if outcome.seller_revenue else None, "negative_payment": bool(negative_payments), "negative_quantity": bool(quantity_issues), "status": "valid" if not negative_payments and not quantity_issues and (not outcome.seller_revenue or revenue_total == payment_total) else "invalid"}


__all__ = ["TieredUsagePricingModel", "SubscriptionPricingModel", "RiskAdjustedPricingModel", "ElasticityPricingModel", "QuoteCalibration", "calibrate_quotes", "audit_pricing_outcome"]
