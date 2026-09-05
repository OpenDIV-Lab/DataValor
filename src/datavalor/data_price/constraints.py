"""Price quote constraint projections."""

from __future__ import annotations

from decimal import Decimal

from datavalor.core import ComponentSpec

from .interfaces import PriceConstraint
from .models import Money, PriceQuote


class PriceBandConstraint(PriceConstraint):
    """Clamp every quote to a configured floor and ceiling."""

    def __init__(self, floor=0, ceiling=None, currency="CNY"):
        self.floor, self.ceiling, self.currency = Decimal(str(floor)), Decimal(str(ceiling)) if ceiling is not None else None, currency
        if self.floor < 0:
            raise ValueError("price band floor must be non-negative")
        if self.ceiling is not None and self.ceiling < self.floor:
            raise ValueError("price band ceiling must be greater than or equal to floor")

    @property
    def spec(self) -> ComponentSpec:
        return ComponentSpec("constraint.price_band", "1.0.0", "data_price", "price_constraint", capabilities=("floor", "ceiling"))

    def project(self, quotes: tuple[PriceQuote, ...], context) -> tuple[PriceQuote, ...]:
        del context
        result = []
        for quote in quotes:
            if quote.price.currency != self.currency:
                raise ValueError("price band currency mismatch")
            amount = max(self.floor, quote.price.amount)
            if self.ceiling is not None:
                amount = min(amount, self.ceiling)
            result.append(PriceQuote(quote.quote_id, quote.product_id, Money(amount, quote.price.currency), quote.pricing_model, quote.buyer_id, quote.rights, quote.valid_until, quote.components, {**quote.diagnostics, "price_band_projected": True, "floor": self.floor, "ceiling": self.ceiling}))
        return tuple(result)


class VolumeDiscountConstraint(PriceConstraint):
    """Apply tiered volume discounts while retaining the original amount."""

    def __init__(self, tiers: tuple[tuple[int, Decimal], ...] = ((1, Decimal("0")), (10, Decimal("0.05")), (100, Decimal("0.15")))):
        self.tiers = tuple(sorted((int(quantity), Decimal(str(discount))) for quantity, discount in tiers))
        if any(quantity <= 0 for quantity, _ in self.tiers):
            raise ValueError("volume discount thresholds must be positive")
        if any(discount < 0 or discount > 1 for _, discount in self.tiers):
            raise ValueError("volume discount must be between 0 and 1")

    @property
    def spec(self) -> ComponentSpec:
        return ComponentSpec("constraint.volume_discount", "1.0.0", "data_price", "price_constraint", capabilities=("volume", "tiered"))

    def project(self, quotes: tuple[PriceQuote, ...], context) -> tuple[PriceQuote, ...]:
        quantity = int(context.config.get("quantity", 1)); discount = max((rate for threshold, rate in self.tiers if quantity >= threshold), default=Decimal("0")); result = []
        for quote in quotes:
            amount = quote.price.amount * max(Decimal("0"), Decimal("1") - discount)
            result.append(PriceQuote(quote.quote_id, quote.product_id, Money(amount, quote.price.currency), quote.pricing_model, quote.buyer_id, quote.rights, quote.valid_until, {**quote.components, "volume_discount": discount}, {**quote.diagnostics, "volume": quantity}))
        return tuple(result)


__all__ = ["PriceBandConstraint", "VolumeDiscountConstraint"]
