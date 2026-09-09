"""DataMarket 机制设计示例：订单匹配、性质审计、配额准入和 Shapley 分成。"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from datavalor.core import ActorProfile, ActorRole, DataProduct, DataReference, RunContext
from datavalor.data_market import (
    Listing,
    ListingStatus,
    QuotaAdmissionController,
    ShapleyRevenueAllocator,
    audit_market_mechanism,
    match_orders,
)
from datavalor.data_price import (
    Ask,
    Bid,
    FirstPriceAuction,
    Money,
    PricingRequest,
)

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    product = DataProduct("mobility", "城市出行流量", DataReference("memory://mobility", "parquet"), "seller-a")
    listing = Listing("listing-mobility", product, "seller-a", ListingStatus.ACTIVE, metadata={"quality": "0.94"})
    bids = (
        Bid("bid-a", "buyer-a", ("mobility",), Money(Decimal("80")), Decimal("1"), constraints={"min_quality": "0.9"}),
        Bid("bid-b", "buyer-b", ("mobility",), Money(Decimal("70"))),
    )
    asks = (Ask("ask-a", "seller-a", ("mobility",), Money(Decimal("45"))),)
    matches = match_orders(bids, asks, (listing,))
    # DataPrice 负责清算；DataMarket 在清算前后记录市场机制证据。
    outcome = FirstPriceAuction().price(PricingRequest((product,), bids, asks), RunContext("price"))
    audit = audit_market_mechanism(bids, asks, outcome)
    admitted = QuotaAdmissionController().admit(
        outcome, {"buyer-a": {"mobility": Decimal("1")}}, {("buyer-a", "mobility"): Decimal("0")}
    )
    revenue = ShapleyRevenueAllocator().allocate(
        Money(Decimal("65")),
        (ActorProfile("seller-a", ActorRole.SUPPLIER), ActorProfile("platform", ActorRole.PLATFORM)),
        {"seller-a": Decimal("3"), "platform": Decimal("1")},
        RunContext("share", metadata={"coalition_values": {"seller-a": "3", "platform": "1", "platform|seller-a": "4"}}),
    )
    output = {
        "matches": [match.__dict__ for match in matches],
        "audit": {"properties": audit.properties, "metrics": audit.metrics, "violations": audit.violations},
        "admission": {"allocations": [item.__dict__ for item in admitted.allocations], "payments": [item.__dict__ for item in admitted.payments], "denied": admitted.denied},
        "revenue_shares": [share.__dict__ for share in revenue.shares],
    }
    path = ROOT / "outputs/datamarket-mechanism-design/result.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"output": str(path), "matched": len(matches), "audit_violations": audit.violations, "admitted": len(admitted.allocations)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
