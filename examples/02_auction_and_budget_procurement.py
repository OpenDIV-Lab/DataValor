"""把任务估值转成 bid，并比较三种交易机制。

运行：PYTHONPATH=src python examples/02_auction_and_budget_procurement.py
"""

from __future__ import annotations

import json
from decimal import Decimal

from datavalor.core import DataProduct, DataReference, RunContext
from datavalor.data_price import (
    Ask,
    Bid,
    BudgetFeasibleProcurement,
    McAfeeDoubleAuction,
    Money,
    PricingRequest,
    SecondPriceAuction,
)


def outcome_dict(outcome):
    return {
        "mechanism": outcome.mechanism,
        "allocations": [{"buyer": a.buyer_id, "products": a.product_ids, "quantity": str(a.quantity)} for a in outcome.allocations],
        "payments": [{"payer": p.payer_id, "payee": p.payee_id, "amount": str(p.amount.amount), "reason": p.reason} for p in outcome.payments],
        "welfare": str(outcome.welfare) if outcome.welfare is not None else None,
        "seller_revenue": {key: str(value.amount) for key, value in outcome.seller_revenue.items()},
        "diagnostics": dict(outcome.diagnostics),
    }


def main() -> None:
    products = tuple(
        DataProduct(f"weather-{index}", f"气象站数据 {index}", DataReference(f"memory://weather-{index}", "records"), f"seller-{index}")
        for index in range(1, 4)
    )
    bids = (
        Bid("b-1", "buyer-a", ("weather-1",), Money(Decimal("820")), metadata={"estimated_value": "820"}),
        Bid("b-2", "buyer-b", ("weather-1",), Money(Decimal("690")), metadata={"estimated_value": "690"}),
        Bid("b-3", "buyer-c", ("weather-1",), Money(Decimal("540")), metadata={"estimated_value": "540"}),
    )
    asks = (
        Ask("a-1", "seller-1", ("weather-1",), Money(Decimal("410"))),
        Ask("a-2", "seller-2", ("weather-2",), Money(Decimal("260"))),
        Ask("a-3", "seller-3", ("weather-3",), Money(Decimal("180"))),
    )
    context = RunContext("example-02", seed=11, actor_id="platform")
    single_item = PricingRequest(products[:1], bids=bids[:], asks=asks[:1], market_context={"currency": "CNY"})
    procurement = PricingRequest(products, asks=asks, market_context={"budget": "500", "buyer_id": "buyer-a"})
    results = {
        "second_price": outcome_dict(SecondPriceAuction().price(single_item, context)),
        "mcafee_double_auction": outcome_dict(McAfeeDoubleAuction().price(single_item, context)),
        "budget_feasible_procurement": outcome_dict(BudgetFeasibleProcurement().price(procurement, context)),
    }
    print(json.dumps({"assumption": "bid 是买方支付意愿，不等于平台报价；ask 是卖方保留价", "results": results}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
