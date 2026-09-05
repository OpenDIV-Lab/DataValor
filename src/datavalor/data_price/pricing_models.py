"""Concrete, dependency-free quote and online pricing models."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from datavalor.core import ComponentSpec

from .interfaces import OnlinePricingModel, PricingModel
from .models import Money, PriceQuote, PricingObservation, QuoteRequest


def _decimal(value: Any, default: str = "0") -> Decimal:
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal(default)


def _expiry(request: QuoteRequest, context) -> datetime | None:
    seconds = request.market_context.get("valid_seconds")
    if seconds is None:
        return None
    return context.started_at + timedelta(seconds=max(0, float(seconds)))


class CostPlusPricingModel(PricingModel):
    """Cost-plus quote with preparation, operation and margin components."""

    @property
    def spec(self) -> ComponentSpec:
        return ComponentSpec("pricing.cost_plus", "1.0.0", "data_price", "pricing_model", capabilities=("cost", "margin"))

    def quote(self, request: QuoteRequest, context) -> PriceQuote:
        ctx = request.market_context
        preparation = _decimal(ctx.get("preparation_cost", 0)); operation = _decimal(ctx.get("operation_cost", 0)); acquisition = _decimal(ctx.get("acquisition_cost", 0))
        margin_rate = _decimal(ctx.get("margin_rate", "0.2")); subtotal = preparation + operation + acquisition; margin = subtotal * margin_rate; total = subtotal + margin
        currency = str(ctx.get("currency", request.product.metadata.get("currency", "CNY")))
        return PriceQuote(f"cost-plus-{context.run_id}", request.product.product_id, Money(total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), currency), self.spec.name, request.buyer.actor_id if request.buyer else None, request.rights or request.product.rights, _expiry(request, context), {"acquisition": acquisition, "preparation": preparation, "operation": operation, "margin": margin}, {"margin_rate": margin_rate, "run_id": context.run_id})


class ValueBasedPricingModel(PricingModel):
    """Quote as an explicit buyer share of a supplied value estimate."""

    @property
    def spec(self) -> ComponentSpec:
        return ComponentSpec("pricing.value_based", "1.0.0", "data_price", "pricing_model", capabilities=("valuation", "buyer_share"))

    def quote(self, request: QuoteRequest, context) -> PriceQuote:
        ctx = request.market_context; estimated = _decimal(ctx.get("estimated_value")); share = max(Decimal("0"), min(Decimal("1"), _decimal(ctx.get("buyer_share", "0.5")))); floor = max(Decimal("0"), _decimal(ctx.get("floor", 0))); ceiling = _decimal(ctx.get("ceiling", estimated))
        total = min(max(estimated * share, floor), ceiling if ceiling >= floor else floor); currency = str(ctx.get("currency", "CNY"))
        return PriceQuote(f"value-{context.run_id}", request.product.product_id, Money(total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), currency), self.spec.name, request.buyer.actor_id if request.buyer else None, request.rights or request.product.rights, _expiry(request, context), {"estimated_value": estimated, "buyer_share": share, "floor": floor, "ceiling": ceiling}, {"run_id": context.run_id})


class UsageBasedPricingModel(PricingModel):
    """Fixed plus per-record/query/compute pricing from explicit usage units."""

    @property
    def spec(self) -> ComponentSpec:
        return ComponentSpec("pricing.usage_based", "1.0.0", "data_price", "pricing_model", capabilities=("usage", "metering"))

    def quote(self, request: QuoteRequest, context) -> PriceQuote:
        ctx = request.market_context; fixed = _decimal(ctx.get("fixed_fee", 0)); records = _decimal(ctx.get("records", 0)); queries = _decimal(ctx.get("queries", 0)); seconds = _decimal(ctx.get("compute_seconds", 0)); total = fixed + records * _decimal(ctx.get("per_record", 0)) + queries * _decimal(ctx.get("per_query", 0)) + seconds * _decimal(ctx.get("per_compute_second", 0)); currency = str(ctx.get("currency", "CNY"))
        return PriceQuote(f"usage-{context.run_id}", request.product.product_id, Money(total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), currency), self.spec.name, request.buyer.actor_id if request.buyer else None, request.rights or request.product.rights, _expiry(request, context), {"fixed": fixed, "records": records, "queries": queries, "compute_seconds": seconds}, {"run_id": context.run_id})


class QualityFreshnessPricingModel(PricingModel):
    """Quality/freshness adjusted quote with an explicit floor and cap."""

    @property
    def spec(self) -> ComponentSpec:
        return ComponentSpec("pricing.quality_freshness", "1.0.0", "data_price", "pricing_model", capabilities=("quality", "freshness", "bounds"))

    def quote(self, request: QuoteRequest, context) -> PriceQuote:
        ctx = request.market_context; base = _decimal(ctx.get("base_price", 0)); quality = max(Decimal("0"), min(Decimal("1"), _decimal(ctx.get("quality", 1)))); freshness = max(Decimal("0"), min(Decimal("1"), _decimal(ctx.get("freshness", 1)))); quality_weight = max(Decimal("0"), min(Decimal("1"), _decimal(ctx.get("quality_weight", "0.7")))); factor = quality_weight * quality + (Decimal("1") - quality_weight) * freshness; floor = _decimal(ctx.get("floor", 0)); ceiling = _decimal(ctx.get("ceiling", base)); total = min(max(base * factor, floor), ceiling if ceiling >= floor else floor); currency = str(ctx.get("currency", "CNY"))
        return PriceQuote(f"qf-{context.run_id}", request.product.product_id, Money(total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), currency), self.spec.name, request.buyer.actor_id if request.buyer else None, request.rights or request.product.rights, _expiry(request, context), {"base": base, "quality": quality, "freshness": freshness, "factor": factor}, {"run_id": context.run_id})


class AdaptiveDemandPricingModel(OnlinePricingModel):
    """Demand-responsive quote using a bounded multiplicative update."""

    def __init__(self, initial_price: Any = 100, *, learning_rate: float = 0.1, target_acceptance: float = 0.5, currency: str = "CNY") -> None:
        self.price = _decimal(initial_price); self.learning_rate = Decimal(str(max(0.0, learning_rate))); self.target = Decimal(str(max(0.0, min(1.0, target_acceptance)))); self.currency = currency; self.observations = 0

    @property
    def spec(self) -> ComponentSpec:
        return ComponentSpec("pricing.adaptive_demand", "1.0.0", "data_price", "online_pricing_model", capabilities=("online", "demand", "bounded_update"))

    def quote(self, request: QuoteRequest, context) -> PriceQuote:
        return PriceQuote(f"adaptive-{context.run_id}-{self.observations}", request.product.product_id, Money(max(Decimal("0"), self.price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), self.currency), self.spec.name, request.buyer.actor_id if request.buyer else None, request.rights or request.product.rights, _expiry(request, context), {"price": self.price}, {"observations": self.observations, "target_acceptance": self.target})

    def observe(self, observation: PricingObservation, context) -> None:
        del context
        self.observations += 1
        # Accepted demand above target raises price; rejection lowers it.
        signal = Decimal("1") if observation.accepted else Decimal("0")
        self.price *= Decimal("1") + self.learning_rate * (signal - self.target)
        if observation.realized_revenue is not None and observation.realized_revenue.currency != self.currency:
            raise ValueError("realized revenue currency does not match pricing model")


__all__ = ["AdaptiveDemandPricingModel", "CostPlusPricingModel", "QualityFreshnessPricingModel", "UsageBasedPricingModel", "ValueBasedPricingModel"]
