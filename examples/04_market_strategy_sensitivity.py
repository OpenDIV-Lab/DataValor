"""有限轮市场策略实验：成交率、收入和福利的简单敏感性分析。

运行：PYTHONPATH=src python examples/04_market_strategy_sensitivity.py
"""

from __future__ import annotations

import json
from decimal import Decimal

from datavalor.core import (
    ActorProfile,
    ActorRole,
    ComponentSpec,
    DataProduct,
    DataReference,
    RunContext,
)
from datavalor.data_market import Listing, ListingStatus, MarketSnapshot
from datavalor.data_market.simulation import FiniteMarketSimulator
from datavalor.data_market.simulation.interfaces import ParticipantStrategy
from datavalor.data_market.simulation.models import (
    MarketObservation,
    SimulationStep,
    StrategyDecision,
)
from datavalor.data_market.simulation.strategies import (
    BudgetPacingStrategy,
    FixedShadingStrategy,
    TruthfulStrategy,
)
from datavalor.data_price import Ask, FirstPriceAuction, Money


class SellerReserveStrategy(ParticipantStrategy):
    """为每轮提供一个固定保留价，避免把成交收入误记为平台收入。"""

    @property
    def spec(self) -> ComponentSpec:
        return ComponentSpec("example.seller_reserve", "1.0", "data_market", "participant_strategy")

    def decide(self, observation: MarketObservation, context: RunContext) -> StrategyDecision:
        product_id = str(observation.market.listings[0].product.product_id)
        return StrategyDecision("city-owner", asks=(Ask(f"ask-{observation.round_id}", "city-owner", (product_id,), Money(Decimal("300"))),))

    def observe(self, step: SimulationStep, context: RunContext) -> None:
        return None


def run(name, strategy):
    product = DataProduct("traffic-v1", "道路流量数据（合成）", DataReference("memory://traffic", "records"), "city-owner")
    seller = ActorProfile("city-owner", ActorRole.SUPPLIER)
    buyer = ActorProfile("logistics-01", ActorRole.BUYER, budget=Decimal("600"), preferences={"value": 500, "product_id": product.product_id})
    listing = Listing("listing-traffic", product, seller.actor_id, ListingStatus.ACTIVE)
    snapshot = MarketSnapshot((listing,), (seller, buyer), state={"round": 0})
    context = RunContext(f"example-04-{name}", seed=3, actor_id=buyer.actor_id, metadata={"products": (product,), "actors": (buyer,)})
    report = FiniteMarketSimulator(FirstPriceAuction()).run(snapshot, (strategy, SellerReserveStrategy()), rounds=8, context=context)
    sold = sum(1 for step in report.steps if step.outcome and step.outcome.allocations)
    revenue = sum((step.outcome.payments[0].amount.amount for step in report.steps if step.outcome and step.outcome.payments), Decimal("0"))
    welfare = sum((step.outcome.welfare or Decimal("0") for step in report.steps if step.outcome), Decimal("0"))
    return {"strategy": name, "rounds": report.summary["rounds"], "sold_rounds": sold, "conversion_rate": round(sold / 8, 3), "seller_revenue": str(revenue), "reported_welfare": str(welfare)}


def main() -> None:
    results = [run("truthful", TruthfulStrategy()), run("fixed_shading_0.85", FixedShadingStrategy(0.85)), run("budget_pacing", BudgetPacingStrategy(0.95))]
    print(json.dumps({"note": "这是有限轮观察，不等同于均衡或激励相容性证明", "results": results}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
