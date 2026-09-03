"""Models for quotes, bids, allocations, payments, and market pricing."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Mapping

from datavalor.core import ActorProfile, ArtifactRef, DataProduct, RightsBundle, TaskContext


@dataclass(frozen=True)
class Money:
    """Currency-aware amount used at monetary boundaries."""

    amount: Decimal
    currency: str = "CNY"


@dataclass(frozen=True)
class QuoteRequest:
    """Request a product-specific price for a buyer, task, and rights bundle."""

    product: DataProduct
    buyer: ActorProfile | None = None
    task: TaskContext | None = None
    rights: RightsBundle | None = None
    valuation_artifacts: tuple[ArtifactRef, ...] = ()
    market_context: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PriceQuote:
    """Non-binding or binding price quote with explicit validity and rights."""

    quote_id: str
    product_id: str
    price: Money
    pricing_model: str
    buyer_id: str | None = None
    rights: RightsBundle | None = None
    valid_until: datetime | None = None
    components: Mapping[str, Decimal] = field(default_factory=dict)
    diagnostics: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Bid:
    """Reported buyer willingness to pay, distinct from estimated value."""

    bid_id: str
    buyer_id: str
    product_ids: tuple[str, ...]
    amount: Money
    quantity: Decimal = Decimal("1")
    task_id: str | None = None
    constraints: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Ask:
    """Seller offer or reserve for one data product or bundle."""

    ask_id: str
    seller_id: str
    product_ids: tuple[str, ...]
    reserve: Money
    quantity: Decimal = Decimal("1")
    constraints: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PricingRequest:
    """Complete market input to an auction or pricing mechanism."""

    products: tuple[DataProduct, ...]
    bids: tuple[Bid, ...] = ()
    asks: tuple[Ask, ...] = ()
    valuation_artifacts: tuple[ArtifactRef, ...] = ()
    supply: Mapping[str, Decimal] = field(default_factory=dict)
    demand: Mapping[str, Decimal] = field(default_factory=dict)
    market_context: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Allocation:
    """Quantity of products allocated to one buyer."""

    buyer_id: str
    product_ids: tuple[str, ...]
    quantity: Decimal = Decimal("1")
    reported_value: Money | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Payment:
    """Payment by one actor to another under a pricing mechanism."""

    payer_id: str
    payee_id: str
    amount: Money
    reason: str
    product_ids: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PricingOutcome:
    """Allocation and payments produced by a pricing mechanism."""

    mechanism: str
    allocations: tuple[Allocation, ...]
    payments: tuple[Payment, ...]
    welfare: Decimal | None = None
    seller_revenue: Mapping[str, Money] = field(default_factory=dict)
    properties: Mapping[str, bool | None] = field(default_factory=dict)
    diagnostics: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PricingObservation:
    """Feedback supplied to a stateful or online pricing model."""

    quote: PriceQuote
    accepted: bool
    realized_quantity: Decimal = Decimal("0")
    realized_revenue: Money | None = None
    context: Mapping[str, Any] = field(default_factory=dict)

