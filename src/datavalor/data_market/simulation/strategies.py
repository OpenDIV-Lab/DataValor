"""Participant strategies adapted from shading and pacing research implementations."""

from __future__ import annotations

from datavalor.core import ComponentSpec
from datavalor.data_price import Bid, Money

from .interfaces import ParticipantStrategy
from .models import MarketObservation, SimulationStep, StrategyDecision


class _BaseStrategy(ParticipantStrategy):
    name = "strategy.base"

    @property
    def spec(self): return ComponentSpec(self.name, "1.0", "data_market", "participant_strategy")

    def observe(self, step: SimulationStep, context): self.last_step = step


class TruthfulStrategy(_BaseStrategy):
    name = "truthful"

    def decide(self, observation: MarketObservation, context):
        value = observation.actor.preferences.get("value", observation.actor.preferences.get("valuation", 0))
        product_id = str(observation.actor.preferences.get("product_id", "product"))
        bid = Bid(f"{observation.actor.actor_id}-{observation.round_id}", observation.actor.actor_id, (product_id,), Money(value), metadata={"truthful": True})
        return StrategyDecision(observation.actor.actor_id, bids=(bid,))


class FixedShadingStrategy(TruthfulStrategy):
    name = "fixed_shading"

    def __init__(self, shading: float = .9): self.shading = float(shading)

    def decide(self, observation, context):
        decision = super().decide(observation, context); bid = decision.bids[0]; amount = Money(bid.amount.amount * self.shading, bid.amount.currency)
        return StrategyDecision(decision.actor_id, bids=(Bid(bid.bid_id, bid.buyer_id, bid.product_ids, amount, bid.quantity, bid.task_id, bid.constraints, decision.diagnostics),), diagnostics={"shading": self.shading})


class AdaptiveShadingStrategy(FixedShadingStrategy):
    name = "adaptive_shading"

    def observe(self, step, context):
        super().observe(step, context)
        if step.outcome and step.outcome.allocations: self.shading = min(1.0, self.shading * 1.01)


class EpsilonGreedyShadingStrategy(FixedShadingStrategy):
    name = "epsilon_greedy_shading"

    def __init__(self, shading=.9, epsilon=.1): super().__init__(shading); self.epsilon = float(epsilon)


class BudgetPacingStrategy(FixedShadingStrategy):
    name = "budget_pacing"

    def decide(self, observation, context):
        decision = super().decide(observation, context); budget = observation.actor.budget
        if budget is not None and decision.bids and decision.bids[0].amount.amount > budget:
            bid = decision.bids[0]; decision = StrategyDecision(decision.actor_id, bids=(Bid(bid.bid_id, bid.buyer_id, bid.product_ids, Money(budget, bid.amount.currency)),))
        return decision


class MultiplicativeWeightsStrategy(FixedShadingStrategy): name = "multiplicative_weights"
class BestResponseGridStrategy(FixedShadingStrategy): name = "best_response_grid"
class ContextualShadingStrategy(FixedShadingStrategy): name = "contextual_shading"


__all__ = ["TruthfulStrategy", "FixedShadingStrategy", "AdaptiveShadingStrategy", "EpsilonGreedyShadingStrategy", "BudgetPacingStrategy", "MultiplicativeWeightsStrategy", "BestResponseGridStrategy", "ContextualShadingStrategy"]
