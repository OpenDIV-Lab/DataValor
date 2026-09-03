"""Finite market simulation runner using DataValor typed snapshots."""

from __future__ import annotations

from datavalor.core import ComponentSpec
from datavalor.data_price import FirstPriceAuction, PricingRequest

from .interfaces import MarketSimulator, ParticipantStrategy
from .models import MarketObservation, SimulationReport, SimulationStep


class FiniteMarketSimulator(MarketSimulator):
    def __init__(self, mechanism=None): self.mechanism = mechanism or FirstPriceAuction(); self.market = None

    @property
    def spec(self): return ComponentSpec("finite_market_simulator", "1.0", "data_market", "market_simulator")

    def reset(self, initial, context): self.market = initial; return initial

    def step(self, market, strategies: tuple[ParticipantStrategy, ...], context):
        decisions = tuple(strategy.decide(MarketObservation(context.metadata.get("round_id", 0), market=market, actor=context.metadata.get("actor", None) or context.metadata.get("actors", [None])[0]), context) for strategy in strategies)
        bids = tuple(bid for decision in decisions for bid in decision.bids); asks = tuple(ask for decision in decisions for ask in decision.asks)
        products = tuple(context.metadata.get("products", ())); outcome = self.mechanism.price(PricingRequest(products, bids, asks), context)
        return SimulationStep(context.metadata.get("round_id", 0), decisions, outcome, market)

    def run(self, initial, strategies, rounds, context):
        self.reset(initial, context); steps = []
        for index in range(rounds):
            context = type(context)(**{**context.__dict__, "metadata": {**context.metadata, "round_id": index}})
            step = self.step(self.market, strategies, context); steps.append(step)
            for strategy in strategies: strategy.observe(step, context)
        return SimulationReport(context.run_id, tuple(steps), summary={"rounds": rounds})
