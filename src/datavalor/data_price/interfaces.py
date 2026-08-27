"""Extension interfaces for DataPrice."""

from __future__ import annotations

from abc import abstractmethod

from datavalor.core import BaseComponent, RunContext

from .models import PriceQuote, PricingObservation, PricingOutcome, PricingRequest, QuoteRequest


class PricingModel(BaseComponent):
    """Produce a price quote without running market allocation."""

    @abstractmethod
    def quote(self, request: QuoteRequest, context: RunContext) -> PriceQuote:
        """Return an attributable, rights-aware price quote."""


class OnlinePricingModel(PricingModel):
    """Stateful pricing model that learns from observed decisions and revenue."""

    @abstractmethod
    def observe(self, observation: PricingObservation, context: RunContext) -> None:
        """Update model state from logged, policy-aware feedback."""


class PriceConstraint(BaseComponent):
    """Project quotes or outcomes onto constraints such as no-arbitrage rules."""

    @abstractmethod
    def project(self, quotes: tuple[PriceQuote, ...], context: RunContext) -> tuple[PriceQuote, ...]:
        """Return constrained quotes while retaining projection diagnostics."""


class PricingMechanism(BaseComponent):
    """Compute allocation and payments from reported bids, asks, and supply."""

    @abstractmethod
    def price(self, request: PricingRequest, context: RunContext) -> PricingOutcome:
        """Run one explicitly named market-pricing mechanism."""

