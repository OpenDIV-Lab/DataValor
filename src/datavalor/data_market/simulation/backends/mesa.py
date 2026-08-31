"""Mesa-backed market simulation using DataValor snapshots and strategies.

Mesa supplies agent scheduling/data collection; pricing and rights semantics
remain DataValor concerns.  A ``model_factory`` may be injected to attach a
project-specific Mesa model without exposing Mesa objects through the public
simulation result.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from datavalor.core import ComponentSpec, RunContext, require_capability
from datavalor.data_price import FirstPriceAuction, PricingRequest

from ..interfaces import MarketSimulator, ParticipantStrategy
from ..models import MarketObservation, SimulationReport, SimulationStep


class MesaMarketSimulator(MarketSimulator):
    def __init__(self, mechanism: Any = None, *, model_factory: Callable[..., Any] | None = None) -> None:
        self.mechanism = mechanism or FirstPriceAuction()
        self.model_factory = model_factory
        self._model: Any = None
        self._market = None

    @property
    def spec(self) -> ComponentSpec:
        return ComponentSpec("mesa.market_simulator", "0.1.0", "data_market", "market_simulator",
                             capabilities=("agent", "scheduler", "datacollector"), requires=("mesa>=2.0",))

    def reset(self, initial, context: RunContext):
        self._market = initial
        if self.model_factory is not None:
            self._model = self.model_factory(initial=initial, context=context)
        return initial

    def _advance_mesa(self, context: RunContext) -> None:
        if self._model is None and self.model_factory is None:
            mesa = require_capability("mesa", "mesa", distribution="mesa", extra="simulation")
            model_cls = getattr(mesa, "Model", None)
            if model_cls is None:
                raise RuntimeError("Mesa package does not expose Model")
            self._model = model_cls()
        if self._model is not None:
            step = getattr(self._model, "step", None)
            if callable(step):
                step()

    def step(self, market, strategies: tuple[ParticipantStrategy, ...], context: RunContext) -> SimulationStep:
        round_id = int(context.metadata.get("round_id", 0))
        self._advance_mesa(context)
        actors = tuple(market.participants)
        decisions = []
        for index, strategy in enumerate(strategies):
            actor = actors[index] if index < len(actors) else context.metadata.get("actor")
            if actor is None:
                continue
            observation = MarketObservation(round_id, actor, market, metadata={"backend": "mesa"})
            decisions.append(strategy.decide(observation, context))
        bids = tuple(bid for decision in decisions for bid in decision.bids)
        asks = tuple(ask for decision in decisions for ask in decision.asks)
        products = tuple(context.metadata.get("products", (listing.product for listing in market.listings)))
        outcome = self.mechanism.price(PricingRequest(products, bids, asks), context)
        return SimulationStep(round_id, tuple(decisions), outcome, market,
                              diagnostics={"backend": "mesa", "model_attached": self._model is not None})

    def run(self, initial, strategies, rounds: int, context: RunContext) -> SimulationReport:
        if rounds < 0:
            raise ValueError("rounds must be non-negative")
        self.reset(initial, context)
        steps = []
        for round_id in range(rounds):
            current = type(context)(**{**context.__dict__, "metadata": {**context.metadata, "round_id": round_id}})
            step = self.step(initial, strategies, current)
            steps.append(step)
            for strategy in strategies:
                strategy.observe(step, current)
        return SimulationReport(context.run_id, tuple(steps), summary={"rounds": rounds, "backend": "mesa"},
                                diagnostics={"model_attached": self._model is not None})


__all__ = ["MesaMarketSimulator"]
