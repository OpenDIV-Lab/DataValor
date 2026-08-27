"""Models for reproducible participant and market simulation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from datavalor.core import ActorProfile, ArtifactRef
from datavalor.data_market.models import MarketSnapshot
from datavalor.data_price import Ask, Bid, PriceQuote, PricingOutcome


@dataclass(frozen=True)
class MarketObservation:
    """Information exposed to one strategy at a simulation step."""

    round_id: int
    actor: ActorProfile
    market: MarketSnapshot
    quotes: tuple[PriceQuote, ...] = ()
    history: tuple[ArtifactRef, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StrategyDecision:
    """Bid, ask, or abstention chosen by a participant strategy."""

    actor_id: str
    bids: tuple[Bid, ...] = ()
    asks: tuple[Ask, ...] = ()
    state: Mapping[str, Any] = field(default_factory=dict)
    diagnostics: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SimulationStep:
    """One transition with decisions, outcome, and next state."""

    round_id: int
    decisions: tuple[StrategyDecision, ...]
    outcome: PricingOutcome | None
    market: MarketSnapshot
    diagnostics: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SimulationReport:
    """Complete simulation trace and named output artifacts."""

    simulation_id: str
    steps: tuple[SimulationStep, ...]
    artifacts: tuple[ArtifactRef, ...] = ()
    summary: Mapping[str, Any] = field(default_factory=dict)
    diagnostics: Mapping[str, Any] = field(default_factory=dict)

