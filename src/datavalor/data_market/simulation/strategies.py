"""Dependency-free participant strategies for finite market experiments.

Adaptive policies expose their state and update rule. They are experimental
baselines, not claims of equilibrium or incentive compatibility.
"""

from __future__ import annotations

import math
import random
from decimal import Decimal

from datavalor.core import ComponentSpec
from datavalor.data_price import Ask, Bid, Money

from .interfaces import ParticipantStrategy
from .models import MarketObservation, SimulationStep, StrategyDecision


def _decimal(value, default="0") -> Decimal:
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal(default)


def _won_and_paid(step: SimulationStep, actor_id: str) -> tuple[bool, Decimal]:
    if step.outcome is None:
        return False, Decimal("0")
    won = any(item.buyer_id == actor_id for item in step.outcome.allocations)
    paid = sum(
        (item.amount.amount for item in step.outcome.payments if item.payer_id == actor_id),
        Decimal("0"),
    )
    return won, paid


class _BaseStrategy(ParticipantStrategy):
    name = "strategy.base"

    def __init__(self) -> None:
        self.last_step: SimulationStep | None = None
        self._last_actor_id: str | None = None
        self._last_value = Decimal("0")

    @property
    def spec(self):
        return ComponentSpec(self.name, "1.1", "data_market", "participant_strategy")

    def observe(self, step: SimulationStep, context) -> None:
        del context
        self.last_step = step

    def _remember(self, observation: MarketObservation) -> Decimal:
        self._last_actor_id = observation.actor.actor_id
        self._last_value = _decimal(
            observation.actor.preferences.get(
                "value", observation.actor.preferences.get("valuation", 0)
            )
        )
        return self._last_value


class TruthfulStrategy(_BaseStrategy):
    """Bid the configured private value without strategic shading."""

    name = "truthful"

    def decide(self, observation: MarketObservation, context):
        del context
        value = self._remember(observation)
        product_id = str(observation.actor.preferences.get("product_id", "product"))
        currency = observation.actor.currency or str(
            observation.actor.preferences.get("currency", "CNY")
        )
        quantity = max(
            Decimal("0"), _decimal(observation.actor.preferences.get("quantity", 1), "1")
        )
        bid = Bid(
            f"{observation.actor.actor_id}-{observation.round_id}",
            observation.actor.actor_id,
            (product_id,),
            Money(value, currency),
            quantity,
            metadata={"truthful": True, "private_value": str(value)},
        )
        return StrategyDecision(
            observation.actor.actor_id,
            bids=(bid,),
            state={"private_value": str(value)},
        )


class FixedShadingStrategy(TruthfulStrategy):
    """Bid a fixed fraction of private value."""

    name = "fixed_shading"

    def __init__(self, shading: float = 0.9):
        super().__init__()
        self.shading = float(max(0.0, min(1.0, shading)))

    def decide(self, observation, context):
        decision = super().decide(observation, context)
        bid = decision.bids[0]
        amount = Money(bid.amount.amount * Decimal(str(self.shading)), bid.amount.currency)
        shaded = Bid(
            bid.bid_id,
            bid.buyer_id,
            bid.product_ids,
            amount,
            bid.quantity,
            bid.task_id,
            bid.constraints,
            {**bid.metadata, "shading": self.shading},
        )
        return StrategyDecision(
            decision.actor_id,
            bids=(shaded,),
            state={"shading": self.shading},
            diagnostics={"policy": "fixed_fraction"},
        )


class AdaptiveShadingStrategy(FixedShadingStrategy):
    """Raise bids after losses and shade more after wins."""

    name = "adaptive_shading"

    def __init__(self, shading=0.8, *, step=0.05, minimum=0.2, maximum=1.0):
        super().__init__(shading)
        self.step_size = float(max(0.0, step))
        self.minimum = float(max(0.0, minimum))
        self.maximum = float(min(1.0, max(maximum, self.minimum)))

    def observe(self, step, context):
        super().observe(step, context)
        if self._last_actor_id is None:
            return
        won, _ = _won_and_paid(step, self._last_actor_id)
        direction = -1.0 if won else 1.0
        self.shading = min(
            self.maximum, max(self.minimum, self.shading + direction * self.step_size)
        )


class EpsilonGreedyShadingStrategy(FixedShadingStrategy):
    """Learn among discrete shading arms with epsilon-greedy exploration."""

    name = "epsilon_greedy_shading"

    def __init__(self, shading=0.9, epsilon=0.1, arms=None):
        super().__init__(shading)
        self.epsilon = float(max(0.0, min(1.0, epsilon)))
        self.arms = tuple(float(item) for item in (arms or (0.5, 0.65, 0.8, 0.9, 1.0)))
        if not self.arms:
            raise ValueError("epsilon-greedy strategy requires at least one arm")
        if any(item < 0 or item > 1 for item in self.arms):
            raise ValueError("shading arms must be between 0 and 1")
        self.counts = [0] * len(self.arms)
        self.rewards = [0.0] * len(self.arms)
        self._last_arm = 0

    def decide(self, observation, context):
        rng = random.Random(context.seed + observation.round_id * 1009)
        if rng.random() < self.epsilon:
            arm = rng.randrange(len(self.arms))
            explored = True
        else:
            arm = max(range(len(self.arms)), key=lambda idx: (self.rewards[idx], -idx))
            explored = False
        self._last_arm = arm
        self.shading = self.arms[arm]
        decision = super().decide(observation, context)
        return StrategyDecision(
            decision.actor_id,
            decision.bids,
            decision.asks,
            {"arm": arm, "shading": self.shading, "counts": tuple(self.counts)},
            {"explored": explored, "epsilon": self.epsilon},
        )

    def observe(self, step, context):
        super().observe(step, context)
        if self._last_actor_id is None:
            return
        won, paid = _won_and_paid(step, self._last_actor_id)
        reward = float(max(Decimal("0"), self._last_value - paid)) if won else 0.0
        index = self._last_arm
        self.counts[index] += 1
        self.rewards[index] += (reward - self.rewards[index]) / self.counts[index]


class BudgetPacingStrategy(FixedShadingStrategy):
    """Pace spend over a finite horizon and cap bids by remaining budget."""

    name = "budget_pacing"

    def __init__(self, shading=1.0, *, rounds=1, aggressiveness=1.0):
        super().__init__(shading)
        self.rounds = max(1, int(rounds))
        self.aggressiveness = max(0.0, float(aggressiveness))
        self.spent = Decimal("0")

    def decide(self, observation, context):
        decision = super().decide(observation, context)
        budget = observation.actor.budget
        if budget is None:
            return decision
        remaining = max(Decimal("0"), budget - self.spent)
        rounds_left = max(1, self.rounds - observation.round_id)
        per_round = remaining / Decimal(rounds_left)
        cap = min(remaining, per_round * Decimal(str(self.aggressiveness)))
        bid = decision.bids[0]
        paced = Bid(
            bid.bid_id,
            bid.buyer_id,
            bid.product_ids,
            Money(min(bid.amount.amount, cap), bid.amount.currency),
            bid.quantity,
            bid.task_id,
            bid.constraints,
            {**bid.metadata, "remaining_budget": str(remaining)},
        )
        return StrategyDecision(
            decision.actor_id,
            bids=(paced,),
            state={"spent": str(self.spent), "remaining": str(remaining)},
            diagnostics={"round_cap": str(cap), "rounds_left": rounds_left},
        )

    def observe(self, step, context):
        super().observe(step, context)
        if self._last_actor_id is not None:
            _, paid = _won_and_paid(step, self._last_actor_id)
            self.spent += paid


class MultiplicativeWeightsStrategy(EpsilonGreedyShadingStrategy):
    """Hedge-style learning over shading arms."""

    name = "multiplicative_weights"

    def __init__(self, arms=None, *, learning_rate=0.2):
        super().__init__(epsilon=0.0, arms=arms)
        self.learning_rate = float(max(0.0, learning_rate))
        self.weights = [1.0] * len(self.arms)

    def decide(self, observation, context):
        rng = random.Random(context.seed + observation.round_id * 2027)
        total = sum(self.weights)
        draw = rng.random() * total
        cumulative = 0.0
        arm = len(self.weights) - 1
        for index, weight in enumerate(self.weights):
            cumulative += weight
            if draw <= cumulative:
                arm = index
                break
        self._last_arm = arm
        self.shading = self.arms[arm]
        decision = FixedShadingStrategy.decide(self, observation, context)
        probabilities = tuple(weight / total for weight in self.weights)
        return StrategyDecision(
            decision.actor_id,
            decision.bids,
            state={"arm": arm, "probabilities": probabilities},
            diagnostics={"learning_rate": self.learning_rate},
        )

    def observe(self, step, context):
        _BaseStrategy.observe(self, step, context)
        if self._last_actor_id is None or self._last_value <= 0:
            return
        won, paid = _won_and_paid(step, self._last_actor_id)
        reward = max(Decimal("0"), self._last_value - paid) if won else Decimal("0")
        normalized = min(1.0, float(reward / self._last_value))
        self.weights[self._last_arm] *= math.exp(self.learning_rate * normalized)
        scale = max(self.weights)
        if scale > 1e100:
            self.weights = [weight / scale for weight in self.weights]


class BestResponseGridStrategy(EpsilonGreedyShadingStrategy):
    """Empirical UCB search over a finite bid-shading grid."""

    name = "best_response_grid"

    def __init__(self, arms=None, *, exploration=0.5):
        super().__init__(epsilon=0.0, arms=arms)
        self.exploration = max(0.0, float(exploration))

    def decide(self, observation, context):
        total = sum(self.counts)
        untried = [index for index, count in enumerate(self.counts) if count == 0]
        if untried:
            arm = untried[0]
        else:
            arm = max(
                range(len(self.arms)),
                key=lambda idx: self.rewards[idx]
                + self.exploration * math.sqrt(math.log(max(2, total)) / self.counts[idx]),
            )
        self._last_arm = arm
        self.shading = self.arms[arm]
        decision = FixedShadingStrategy.decide(self, observation, context)
        return StrategyDecision(
            decision.actor_id,
            decision.bids,
            state={"arm": arm, "counts": tuple(self.counts), "means": tuple(self.rewards)},
            diagnostics={"selection": "ucb_grid", "exploration": self.exploration},
        )


class ContextualShadingStrategy(FixedShadingStrategy):
    """Linear policy over competition, round progress, and budget context."""

    name = "contextual_shading"

    def __init__(self, intercept=0.65, coefficients=None, *, minimum=0.2, maximum=1.0):
        super().__init__(intercept)
        self.intercept = float(intercept)
        self.coefficients = {
            "competition": 0.08,
            "progress": 0.12,
            "budget_ratio": 0.10,
            **(coefficients or {}),
        }
        self.minimum = float(minimum)
        self.maximum = float(maximum)

    def decide(self, observation, context):
        competition = max(0, len(observation.market.participants) - 1)
        total_rounds = max(1, int(observation.metadata.get("total_rounds", 1)))
        progress = min(1.0, observation.round_id / total_rounds)
        value = _decimal(
            observation.actor.preferences.get(
                "value", observation.actor.preferences.get("valuation", 0)
            )
        )
        budget = observation.actor.budget
        budget_ratio = float(min(Decimal("1"), budget / value)) if budget and value > 0 else 1.0
        features = {
            "competition": math.log1p(competition),
            "progress": progress,
            "budget_ratio": budget_ratio,
        }
        raw = self.intercept + sum(
            float(self.coefficients.get(name, 0.0)) * feature
            for name, feature in features.items()
        )
        self.shading = min(self.maximum, max(self.minimum, raw))
        decision = FixedShadingStrategy.decide(self, observation, context)
        return StrategyDecision(
            decision.actor_id,
            decision.bids,
            state={"shading": self.shading, "features": features},
            diagnostics={"linear_score": raw},
        )


class FixedReserveSellerStrategy(_BaseStrategy):
    """Post a deterministic seller ask for every round."""

    name = "fixed_reserve_seller"

    def __init__(self, reserve=0, *, quantity=1, currency="CNY"):
        super().__init__()
        self.reserve = _decimal(reserve)
        self.quantity = max(Decimal("0"), _decimal(quantity, "1"))
        self.currency = currency

    def decide(self, observation, context):
        del context
        self._last_actor_id = observation.actor.actor_id
        product_id = str(
            observation.actor.preferences.get(
                "product_id",
                observation.market.listings[0].product.product_id
                if observation.market.listings
                else "product",
            )
        )
        ask = Ask(
            f"ask-{observation.actor.actor_id}-{observation.round_id}",
            observation.actor.actor_id,
            (product_id,),
            Money(self.reserve, self.currency),
            self.quantity,
        )
        return StrategyDecision(
            observation.actor.actor_id,
            asks=(ask,),
            state={"reserve": str(self.reserve), "quantity": str(self.quantity)},
        )


__all__ = [
    "AdaptiveShadingStrategy",
    "BestResponseGridStrategy",
    "BudgetPacingStrategy",
    "ContextualShadingStrategy",
    "EpsilonGreedyShadingStrategy",
    "FixedReserveSellerStrategy",
    "FixedShadingStrategy",
    "MultiplicativeWeightsStrategy",
    "TruthfulStrategy",
]
