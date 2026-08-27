"""Extension interfaces for agent and market simulation."""

from __future__ import annotations

from abc import abstractmethod

from datavalor.core import BaseComponent, RunContext
from datavalor.data_market.models import MarketSnapshot

from .models import MarketObservation, SimulationReport, SimulationStep, StrategyDecision


class ParticipantStrategy(BaseComponent):
    """Stateful or stateless participant decision policy."""

    @abstractmethod
    def decide(self, observation: MarketObservation, context: RunContext) -> StrategyDecision:
        """Choose bids, asks, or abstention from the permitted observation."""

    @abstractmethod
    def observe(self, step: SimulationStep, context: RunContext) -> None:
        """Update strategy state after a market outcome."""


class MarketSimulator(BaseComponent):
    """Coordinate participants, pricing mechanisms, and state transitions."""

    @abstractmethod
    def reset(self, initial: MarketSnapshot, context: RunContext) -> MarketSnapshot:
        """Reset all simulation state deterministically."""

    @abstractmethod
    def step(
        self,
        market: MarketSnapshot,
        strategies: tuple[ParticipantStrategy, ...],
        context: RunContext,
    ) -> SimulationStep:
        """Advance one market round."""

    @abstractmethod
    def run(
        self,
        initial: MarketSnapshot,
        strategies: tuple[ParticipantStrategy, ...],
        rounds: int,
        context: RunContext,
    ) -> SimulationReport:
        """Run a finite experiment without claiming equilibrium by default."""

