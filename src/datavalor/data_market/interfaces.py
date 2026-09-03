"""Extension interfaces for the DataMarket lifecycle."""

from __future__ import annotations

from abc import abstractmethod
from decimal import Decimal
from typing import Mapping

from datavalor.core import ActorProfile, BaseComponent, RunContext
from datavalor.data_price import Money, PricingOutcome

from .models import (
    DiscoveryQuery,
    Incentive,
    Listing,
    MarketSnapshot,
    ParticipantQuery,
    RevenueAllocation,
    TransactionRecord,
)


class MarketCatalog(BaseComponent):
    """Register, update, withdraw, and discover data product listings."""

    @abstractmethod
    def publish(self, listing: Listing, context: RunContext) -> Listing:
        """Publish or update a listing after governance checks."""

    @abstractmethod
    def withdraw(self, listing_id: str, context: RunContext) -> Listing:
        """Withdraw a listing while retaining its audit history."""

    @abstractmethod
    def discover(self, query: DiscoveryQuery, context: RunContext) -> tuple[Listing, ...]:
        """Return listings visible and usable by the requesting actor."""


class ParticipantRepository(BaseComponent):
    """Store the minimal market profiles consumed by mechanisms and simulation."""

    @abstractmethod
    def upsert(self, profile: ActorProfile, context: RunContext) -> ActorProfile:
        """Create or update a participant profile."""

    @abstractmethod
    def get(self, actor_id: str, context: RunContext) -> ActorProfile | None:
        """Return one visible participant profile."""

    @abstractmethod
    def search(self, query: ParticipantQuery, context: RunContext) -> tuple[ActorProfile, ...]:
        """Search participant profiles under visibility rules."""


class IncentivePolicy(BaseComponent):
    """Compute incentives separately from market price and transaction settlement."""

    @abstractmethod
    def compute(
        self,
        market: MarketSnapshot,
        outcome: PricingOutcome,
        context: RunContext,
    ) -> tuple[Incentive, ...]:
        """Assign evidence-backed incentives to market participants."""


class RevenueAllocator(BaseComponent):
    """Allocate realized revenue using explicit stakeholder contributions."""

    @abstractmethod
    def allocate(
        self,
        total: Money,
        participants: tuple[ActorProfile, ...],
        contributions: Mapping[str, Decimal],
        context: RunContext,
    ) -> RevenueAllocation:
        """Return revenue shares whose amounts reconcile with ``total``."""


class TransactionProcessor(BaseComponent):
    """Execute rights, delivery, and settlement after a pricing outcome."""

    @abstractmethod
    def execute(self, outcome: PricingOutcome, context: RunContext) -> TransactionRecord:
        """Create an auditable transaction without hiding partial failures."""

