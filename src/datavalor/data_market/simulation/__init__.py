"""Reproducible market and participant simulations."""

from .backends import MesaMarketSimulator
from .extensions import (
    PrivacyAwareStrategy,
    PrivacyBudgetLedger,
    SimulationMetrics,
    apply_participation_shock,
    decay_market_freshness,
    summarize_simulation,
)
from .interfaces import MarketSimulator, ParticipantStrategy
from .models import (
    MarketObservation,
    SimulationReport,
    SimulationStep,
    StrategyDecision,
)
from .runner import FiniteMarketSimulator
from .strategies import (
    AdaptiveShadingStrategy,
    BestResponseGridStrategy,
    BudgetPacingStrategy,
    ContextualShadingStrategy,
    EpsilonGreedyShadingStrategy,
    FixedReserveSellerStrategy,
    FixedShadingStrategy,
    MultiplicativeWeightsStrategy,
    TruthfulStrategy,
)

__all__ = [
    "MarketObservation",
    "MarketSimulator",
    "ParticipantStrategy",
    "SimulationReport",
    "SimulationStep",
    "StrategyDecision",
    "FiniteMarketSimulator",
    "AdaptiveShadingStrategy",
    "BestResponseGridStrategy",
    "BudgetPacingStrategy",
    "ContextualShadingStrategy",
    "EpsilonGreedyShadingStrategy",
    "FixedReserveSellerStrategy",
    "FixedShadingStrategy",
    "MultiplicativeWeightsStrategy",
    "TruthfulStrategy",
    "MesaMarketSimulator",
    "decay_market_freshness",
    "apply_participation_shock",
    "PrivacyBudgetLedger",
    "PrivacyAwareStrategy",
    "SimulationMetrics",
    "summarize_simulation",
]
