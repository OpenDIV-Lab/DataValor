"""Feedback-driven pricing methods over existing quote observations."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Mapping, Sequence

from datavalor.core import ComponentSpec

from .interfaces import OnlinePricingModel, PricingModel
from .models import Money, PriceQuote, PricingObservation
from .pricing_models import _expiry


def _number(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _money(value: float | Decimal, currency: str) -> Money:
    amount = max(Decimal("0"), Decimal(str(value)))
    return Money(amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), currency)


@dataclass(frozen=True)
class AcceptanceTrainingReport:
    observations: int
    iterations: int
    loss: float
    coefficients: Mapping[str, float]


class AcceptanceProbabilityModel:
    """Small auditable logistic model for quote acceptance probability."""

    features = ("price_ratio", "quality", "rights_fit", "buyer_history")

    def __init__(self, coefficients: Mapping[str, float] | None = None):
        defaults = {"intercept": 0.0, "price_ratio": -2.0, "quality": 1.0, "rights_fit": 0.5, "buyer_history": 0.5}
        self.coefficients = {**defaults, **dict(coefficients or {})}

    @staticmethod
    def _sigmoid(value: float) -> float:
        if value >= 0:
            return 1.0 / (1.0 + math.exp(-min(value, 700)))
        exp_value = math.exp(max(value, -700))
        return exp_value / (1.0 + exp_value)

    def predict(self, price: float | Decimal, context: Mapping[str, Any]) -> float:
        estimated = max(1e-12, _number(context.get("estimated_value"), 1.0))
        values = {"price_ratio": max(0.0, _number(price) / estimated), "quality": min(1.0, max(0.0, _number(context.get("quality"), 0.5))), "rights_fit": min(1.0, max(0.0, _number(context.get("rights_fit"), 1.0))), "buyer_history": min(1.0, max(0.0, _number(context.get("buyer_history"), 0.5)))}
        linear = self.coefficients["intercept"] + sum(self.coefficients[name] * values[name] for name in self.features)
        return self._sigmoid(linear)

    def fit(self, observations: Sequence[PricingObservation], *, learning_rate: float = 0.1, iterations: int = 200, l2: float = 0.0) -> AcceptanceTrainingReport:
        if learning_rate <= 0 or iterations < 1 or l2 < 0:
            raise ValueError("learning_rate and iterations must be positive; l2 non-negative")
        rows = []
        for observation in observations:
            estimated = _number(observation.context.get("estimated_value"))
            if estimated <= 0:
                continue
            values = {"price_ratio": float(observation.quote.price.amount) / estimated, "quality": _number(observation.context.get("quality"), 0.5), "rights_fit": _number(observation.context.get("rights_fit"), 1.0), "buyer_history": _number(observation.context.get("buyer_history"), 0.5)}
            rows.append((values, 1.0 if observation.accepted else 0.0))
        if not rows:
            raise ValueError("no observations with positive estimated_value")
        loss = 0.0
        for _ in range(iterations):
            gradients = {name: 0.0 for name in ("intercept", *self.features)}; loss = 0.0
            for values, label in rows:
                prediction = self._sigmoid(self.coefficients["intercept"] + sum(self.coefficients[name] * values[name] for name in self.features))
                error = prediction - label; gradients["intercept"] += error
                for name in self.features: gradients[name] += error * values[name]
                loss -= label * math.log(max(prediction, 1e-12)) + (1 - label) * math.log(max(1 - prediction, 1e-12))
            for name in gradients:
                penalty = l2 * self.coefficients[name] if name != "intercept" else 0.0
                self.coefficients[name] -= learning_rate * (gradients[name] / len(rows) + penalty)
        return AcceptanceTrainingReport(len(rows), iterations, loss / len(rows), dict(self.coefficients))


class ExpectedRevenuePricingModel(PricingModel):
    """Choose the candidate price with maximum price times acceptance probability."""

    def __init__(self, acceptance_model: AcceptanceProbabilityModel | None = None, currency: str = "CNY"):
        self.acceptance_model, self.currency = acceptance_model or AcceptanceProbabilityModel(), currency

    @property
    def spec(self):
        return ComponentSpec("pricing.expected_revenue", "1.0.0", "data_price", "pricing_model", capabilities=("acceptance_probability", "expected_revenue", "candidates"))

    def quote(self, request, context):
        ctx = request.market_context; candidates = sorted({max(0.0, _number(value)) for value in ctx.get("candidate_prices", ())})
        if not candidates:
            raise ValueError("candidate_prices must contain at least one price")
        scored = [(price, self.acceptance_model.predict(price, ctx)) for price in candidates]
        price, probability = max(scored, key=lambda item: (item[0] * item[1], -item[0]))
        currency = str(ctx.get("currency", self.currency))
        components = {"selected_probability": Decimal(str(probability)), "expected_revenue": Decimal(str(price * probability)), "candidate_count": Decimal(len(scored))}
        return PriceQuote(f"expected-revenue-{context.run_id}", request.product.product_id, _money(price, currency), self.spec.name, request.buyer.actor_id if request.buyer else None, request.rights or request.product.rights, _expiry(request, context), components, {"run_id": context.run_id, "candidates": tuple({"price": value, "probability": prob, "expected_revenue": value * prob} for value, prob in scored)})


class SafeExplorationPricingModel(OnlinePricingModel):
    """Bounded epsilon exploration with beta-smoothed acceptance feedback."""

    def __init__(self, candidate_prices: Sequence[Any] = (50, 75, 100, 125), *, epsilon: float = 0.1, max_change_ratio: float = 0.2, currency: str = "CNY"):
        candidates = sorted({Decimal(str(value)) for value in candidate_prices})
        if not candidates or any(not value.is_finite() or value < 0 for value in candidates) or not 0 <= epsilon <= 1 or max_change_ratio < 0:
            raise ValueError("invalid candidates, epsilon, or max_change_ratio")
        self.candidates, self.epsilon, self.max_change_ratio, self.currency = tuple(candidates), float(epsilon), Decimal(str(max_change_ratio)), currency
        self.successes = {value: 0 for value in self.candidates}; self.trials = {value: 0 for value in self.candidates}; self.last_price: Decimal | None = None; self.seen_quotes = set()

    @property
    def spec(self):
        return ComponentSpec("pricing.safe_exploration", "1.0.0", "data_price", "online_pricing_model", capabilities=("online", "bounded_change", "epsilon_greedy", "deduplicated_feedback"))

    def _allowed(self) -> tuple[Decimal, ...]:
        if self.last_price is None:
            return self.candidates
        lower = self.last_price * (Decimal("1") - self.max_change_ratio); upper = self.last_price * (Decimal("1") + self.max_change_ratio)
        allowed = tuple(value for value in self.candidates if lower <= value <= upper)
        return allowed or (min(self.candidates, key=lambda value: abs(value - self.last_price)),)

    def quote(self, request, context):
        allowed = self._allowed(); rng = random.Random(context.seed + sum(self.trials.values()))
        explore = rng.random() < self.epsilon
        if explore:
            selected = allowed[rng.randrange(len(allowed))]
        else:
            selected = max(allowed, key=lambda value: (value * Decimal(self.successes[value] + 1) / Decimal(self.trials[value] + 2), -value))
        previous = self.last_price; self.last_price = selected
        return PriceQuote(f"safe-explore-{context.run_id}-{sum(self.trials.values())}", request.product.product_id, _money(selected, self.currency), self.spec.name, request.buyer.actor_id if request.buyer else None, request.rights or request.product.rights, _expiry(request, context), {"selected_price": selected, "previous_price": previous or selected}, {"explore": explore, "allowed_prices": tuple(str(value) for value in allowed), "observations": sum(self.trials.values())})

    def observe(self, observation, context):
        del context
        if observation.quote.quote_id in self.seen_quotes:
            return
        if observation.quote.price.currency != self.currency:
            raise ValueError("observation currency mismatch")
        price = observation.quote.price.amount
        if price not in self.trials:
            raise ValueError("observation price is not a configured candidate")
        self.seen_quotes.add(observation.quote.quote_id); self.trials[price] += 1
        if observation.accepted: self.successes[price] += 1


__all__ = ["AcceptanceProbabilityModel", "AcceptanceTrainingReport", "ExpectedRevenuePricingModel", "SafeExplorationPricingModel"]
