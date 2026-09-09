"""DataMarket 拓展示例：挂牌排序、信誉、激励预算和幂等交易记录。"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from datavalor.core import ActorProfile, ActorRole, DataProduct, DataReference, RunContext
from datavalor.data_market import (
    ContributionIncentivePolicy,
    Listing,
    ListingStatus,
    MarketSnapshot,
    market_statistics,
    rank_listings,
    score_reputation,
)
from datavalor.data_market.models import TransactionRecord
from datavalor.data_price import Allocation, Money, Payment, PricingOutcome

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    product = DataProduct("demand-cn", "China retail demand", DataReference("memory://demand-cn", "json"), "supplier-1", tags=("retail", "forecast"))
    listing = Listing("listing-v1", product, "supplier-1", ListingStatus.ACTIVE, metadata={"quality": 0.92, "freshness": 0.88})
    participants = (ActorProfile("supplier-1", ActorRole.SUPPLIER), ActorProfile("buyer-1", ActorRole.BUYER), ActorProfile("buyer-2", ActorRole.BUYER))
    outcome = PricingOutcome("uniform_price", (Allocation("buyer-1", (product.product_id,))), (Payment("buyer-1", "supplier-1", Money(Decimal("120")), "sale", (product.product_id,))))
    snapshot = MarketSnapshot((listing,), participants, outcome)
    transaction = TransactionRecord("tx-demo", outcome, "succeeded", diagnostics={"seller_id": "supplier-1"})
    reputation = score_reputation("supplier-1", (transaction,))
    incentives = ContributionIncentivePolicy(Decimal("30")).compute(snapshot, outcome, RunContext("market", config={"contributions": {"supplier-1": "0.8", "buyer-1": "0.2"}}))
    output = {"ranked_listings": [item.listing_id for item in rank_listings(snapshot.listings, "retail", ("forecast",))], "market_statistics": market_statistics(snapshot), "reputation": reputation.__dict__, "incentives": [item.__dict__ for item in incentives]}
    path = ROOT / "outputs/datamarket-extension/result.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"output": str(path), "ranked_listings": output["ranked_listings"], "reliability": str(reputation.reliability_score), "incentive_total": str(sum(item.amount.amount for item in incentives))}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

