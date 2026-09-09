"""数据市场仿真动态：新鲜度衰减、隐私预算和市场健康指标。"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from datavalor.core import ActorProfile, ActorRole, DataProduct, DataReference, RunContext
from datavalor.data_market import Listing, ListingStatus, MarketSnapshot
from datavalor.data_market.simulation import (
    FiniteMarketSimulator,
    FixedReserveSellerStrategy,
    PrivacyAwareStrategy,
    PrivacyBudgetLedger,
    apply_participation_shock,
    decay_market_freshness,
    summarize_simulation,
)

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    product = DataProduct("traffic", "实时路况", DataReference("memory://traffic", "json"), "seller")
    listing = Listing("traffic-v1", product, "seller", ListingStatus.ACTIVE, metadata={"freshness": "0.8"})
    buyer = ActorProfile("buyer", ActorRole.BUYER, preferences={"value": "20", "product_id": "traffic", "privacy_cost": "2"})
    seller = ActorProfile("seller", ActorRole.SUPPLIER, preferences={"product_id": "traffic"})
    market = MarketSnapshot((listing,), (buyer, seller))
    ledger = PrivacyBudgetLedger({"buyer": Decimal("5")})
    strategies = (PrivacyAwareStrategy(ledger), FixedReserveSellerStrategy(8, quantity=1))
    context = RunContext("simulation-dynamics", seed=7, metadata={"strategy_actors": ("buyer", "seller"), "products": (product,)})
    report = FiniteMarketSimulator().run(market, strategies, 3, context)
    decayed = decay_market_freshness(report.steps[-1].market, Decimal("0.25"))
    shocked = apply_participation_shock(decayed, entrants=(ActorProfile("seller-2", ActorRole.SUPPLIER),), demand_multiplier="1.4")
    metrics = summarize_simulation(report)
    output = {"summary": metrics.__dict__, "privacy_remaining": ledger.snapshot(), "freshness_state": decayed.state, "shock_state": shocked.state}
    path = ROOT / "outputs/datamarket-simulation-dynamics/result.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"output": str(path), "conversion_rate": metrics.conversion_rate, "privacy_remaining": ledger.snapshot()}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
