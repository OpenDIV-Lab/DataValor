"""Deterministic finite market simulation with participant-specific views."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from datavalor.core import ActorRole, ComponentSpec
from datavalor.data_price import FirstPriceAuction, PricingRequest

from .interfaces import MarketSimulator, ParticipantStrategy
from .models import MarketObservation, SimulationReport, SimulationStep


class FiniteMarketSimulator(MarketSimulator):
    """Run repeated market rounds without hiding decisions or state.

    Strategies are matched to actors by ``strategy_actors`` when supplied,
    otherwise by position in ``MarketSnapshot.participants``. Every strategy
    receives its own ActorProfile, fixing the earlier shared-actor behavior.
    """

    def __init__(self, mechanism=None):
        self.mechanism = mechanism or FirstPriceAuction()
        self.market = None

    @property
    def spec(self):
        return ComponentSpec(
            "finite_market_simulator",
            "1.1",
            "data_market",
            "market_simulator",
            capabilities=("multi_actor", "finite_horizon", "trace"),
        )

    def reset(self, initial, context):
        del context
        self.market = initial
        return initial

    def _actors(self, market, strategies, context):
        explicit = context.metadata.get("strategy_actors")
        if explicit:
            actors_by_id = {actor.actor_id: actor for actor in market.participants}
            actors = tuple(
                actors_by_id[item] if isinstance(item, str) else item for item in explicit
            )
        else:
            actors = tuple(context.metadata.get("actors", ()))
            if actors and len(actors) < len(strategies):
                used = {actor.actor_id for actor in actors if actor is not None}
                actors += tuple(
                    actor for actor in market.participants if actor.actor_id not in used
                )
            actors = actors or market.participants
        if len(actors) < len(strategies):
            raise ValueError("each participant strategy requires a matching actor")
        if any(actor is None for actor in actors[: len(strategies)]):
            raise ValueError("simulation actors must not be None")
        return actors[: len(strategies)]

    def step(self, market, strategies: tuple[ParticipantStrategy, ...], context):
        round_id = int(context.metadata.get("round_id", 0))
        total_rounds = int(context.metadata.get("total_rounds", 1))
        actors = self._actors(market, strategies, context)
        decisions = []
        for strategy, actor in zip(strategies, actors):
            observation = MarketObservation(
                round_id,
                actor,
                market,
                metadata={"total_rounds": total_rounds, "strategy": strategy.spec.name},
            )
            decision = strategy.decide(observation, context)
            if decision.actor_id != actor.actor_id:
                raise ValueError("strategy decision actor_id does not match assigned actor")
            decisions.append(decision)
        bids = tuple(bid for decision in decisions for bid in decision.bids)
        asks = tuple(ask for decision in decisions for ask in decision.asks)
        products = tuple(context.metadata.get("products", ())) or tuple(
            listing.product for listing in market.listings
        )
        supply = context.metadata.get("supply", {})
        demand = context.metadata.get("demand", {})
        market_context = {
            **market.state,
            **context.metadata.get("market_context", {}),
            "round_id": round_id,
        }
        outcome = self.mechanism.price(
            PricingRequest(products, bids, asks, supply=supply, demand=demand, market_context=market_context),
            context,
        )
        next_market = replace(
            market,
            latest_outcome=outcome,
            state={**market.state, "round": round_id + 1},
        )
        return SimulationStep(
            round_id,
            tuple(decisions),
            outcome,
            next_market,
            diagnostics={
                "bid_count": len(bids),
                "ask_count": len(asks),
                "actor_ids": tuple(actor.actor_id for actor in actors),
            },
        )

    def run(self, initial, strategies, rounds, context):
        if rounds < 0:
            raise ValueError("simulation rounds must be non-negative")
        self.reset(initial, context)
        steps = []
        for index in range(rounds):
            local = replace(
                context,
                metadata={
                    **context.metadata,
                    "round_id": index,
                    "total_rounds": rounds,
                },
            )
            step = self.step(self.market, strategies, local)
            steps.append(step)
            self.market = step.market
            for strategy in strategies:
                strategy.observe(step, local)
        sold_rounds = sum(
            1 for step in steps if step.outcome is not None and step.outcome.allocations
        )
        total_revenue = sum(
            (
                payment.amount.amount
                for step in steps
                if step.outcome is not None
                for payment in step.outcome.payments
            ),
            Decimal("0"),
        )
        welfare_values = [
            step.outcome.welfare
            for step in steps
            if step.outcome is not None and step.outcome.welfare is not None
        ]
        total_welfare = sum(welfare_values, Decimal("0"))
        buyer_ids = {
            actor.actor_id for actor in initial.participants if actor.role == ActorRole.BUYER
        }
        buyer_spend = {
            actor_id: str(
                sum(
                    (
                        payment.amount.amount
                        for step in steps
                        if step.outcome is not None
                        for payment in step.outcome.payments
                        if payment.payer_id == actor_id
                    ),
                    Decimal("0"),
                )
            )
            for actor_id in buyer_ids
        }
        summary = {
            "rounds": rounds,
            "sold_rounds": sold_rounds,
            "conversion_rate": sold_rounds / rounds if rounds else 0.0,
            "total_revenue": str(total_revenue),
            "mean_revenue": str(total_revenue / rounds) if rounds else "0",
            "total_reported_welfare": str(total_welfare),
            "buyer_spend": buyer_spend,
        }
        return SimulationReport(
            context.run_id,
            tuple(steps),
            summary=summary,
            diagnostics={
                "mechanism": self.mechanism.spec.name,
                "seed": context.seed,
                "equilibrium_claimed": False,
            },
        )
