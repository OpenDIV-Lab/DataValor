"""Models for listings, discovery, transactions, incentives, and revenue sharing."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Mapping

from datavalor.core import ActorProfile, DataProduct, RightsBundle
from datavalor.data_price import Money, PricingOutcome


class ListingStatus(str, Enum):
    """Lifecycle state of a market listing."""

    DRAFT = "draft"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    CLOSED = "closed"


@dataclass(frozen=True)
class Listing:
    """Discoverable offer of a governed data product."""

    listing_id: str
    product: DataProduct
    seller_id: str
    status: ListingStatus
    rights: RightsBundle | None = None
    terms: Mapping[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DiscoveryQuery:
    """Market-facing product discovery request."""

    text: str | None = None
    buyer_id: str | None = None
    task_id: str | None = None
    tags: tuple[str, ...] = ()
    rights_required: RightsBundle | None = None
    filters: Mapping[str, Any] = field(default_factory=dict)
    limit: int = 100


@dataclass(frozen=True)
class Incentive:
    """Non-price or monetary incentive assigned to a participant."""

    actor_id: str
    kind: str
    amount: Money | None = None
    reason: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RevenueShare:
    """One stakeholder's share of realized platform or seller revenue."""

    actor_id: str
    amount: Money
    basis: str
    weight: float | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RevenueAllocation:
    """Auditable allocation of total revenue among stakeholders."""

    total: Money
    shares: tuple[RevenueShare, ...]
    method: str
    diagnostics: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TransactionRecord:
    """Execution record created after pricing, policy, and rights checks."""

    transaction_id: str
    outcome: PricingOutcome
    status: str
    rights: Mapping[str, RightsBundle] = field(default_factory=dict)
    settlements: tuple[RevenueShare, ...] = ()
    diagnostics: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ParticipantQuery:
    """Search criteria for market participant profiles."""

    roles: tuple[str, ...] = ()
    filters: Mapping[str, Any] = field(default_factory=dict)
    limit: int = 100


@dataclass(frozen=True)
class MarketSnapshot:
    """Read-only market inputs exposed to policies and operators."""

    listings: tuple[Listing, ...]
    participants: tuple[ActorProfile, ...]
    latest_outcome: PricingOutcome | None = None
    state: Mapping[str, Any] = field(default_factory=dict)

