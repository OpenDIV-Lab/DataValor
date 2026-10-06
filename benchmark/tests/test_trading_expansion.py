from __future__ import annotations

from decimal import Decimal

import pytest
from datamechbench.models import TradeInput
from datamechbench.runner import build_registry

SINGLE_FAMILIES = {
    "posted_price",
    "first_price",
    "second_price",
    "second_price_reserve",
    "myerson_reserve",
    "english_auction",
    "dutch_auction",
    "all_pay",
    "efficient_single_sale",
}

DOUBLE_FAMILIES = {
    "efficient_clearing",
    "vcg_double_auction",
    "pay_as_bid_double",
    "seller_price_double",
    "midpoint_double",
    "buyer_price_double",
    "trade_reduction",
    "mcafee",
    "sbba",
    "random_sampling_double",
    "bilateral_midpoint",
    "lottery_muda",
    "vickrey_muda",
}


def _single() -> TradeInput:
    return TradeInput(
        product_id="p",
        buyer_ids=("b0", "b1", "b2"),
        seller_ids=("s0",),
        bids={"b0": Decimal("10"), "b1": Decimal("7"), "b2": Decimal("4")},
        asks={"s0": Decimal("6")},
        posted_price=Decimal("8"),
        metadata={"prior_values": ["2", "4", "6", "8", "10"]},
    )


def _double(*, one_pair: bool = False, no_trade: bool = False) -> TradeInput:
    if no_trade:
        bids = {"b0": Decimal("2"), "b1": Decimal("1")}
        asks = {"s0": Decimal("3"), "s1": Decimal("4")}
    elif one_pair:
        bids = {"b0": Decimal("10"), "b1": Decimal("2")}
        asks = {"s0": Decimal("4"), "s1": Decimal("8")}
    else:
        bids = {
            "b0": Decimal("12"),
            "b1": Decimal("10"),
            "b2": Decimal("8"),
            "b3": Decimal("4"),
        }
        asks = {
            "s0": Decimal("2"),
            "s1": Decimal("5"),
            "s2": Decimal("7"),
            "s3": Decimal("11"),
        }
    return TradeInput(
        product_id="p",
        buyer_ids=tuple(bids),
        seller_ids=tuple(asks),
        bids=bids,
        asks=asks,
    )


def test_trading_has_nine_single_and_thirteen_double_families():
    registry = build_registry()
    single = {spec.family_id for spec in registry.compatible("trading", "single_sale")}
    double = {spec.family_id for spec in registry.compatible("trading", "double_auction")}

    assert single == SINGLE_FAMILIES
    assert double == DOUBLE_FAMILIES
    assert len(single | double) >= 10


def test_single_sale_reserve_and_all_pay_transfers():
    registry = build_registry()
    case = _single()

    reserve = registry.create("second_price_reserve").clear(case, seed=0)
    all_pay = registry.create("all_pay").clear(case, seed=0)

    assert reserve.selected_ids == ("b0", "s0")
    assert reserve.payments[0].amount == Decimal("7")
    assert len(all_pay.allocations) == 1
    assert len(all_pay.payments) == len(case.buyer_ids)
    assert sum((payment.amount for payment in all_pay.payments), Decimal("0")) == Decimal("21")

    myerson = registry.create("myerson_reserve").clear(case, seed=0)
    assert myerson.diagnostics["reserve"] == Decimal("6")


@pytest.mark.parametrize(
    "method_id,expected_price",
    [
        ("seller_price_double", Decimal("7")),
        ("midpoint_double", Decimal("7.5")),
        ("buyer_price_double", Decimal("8")),
    ],
)
def test_k_double_auctions_clear_efficient_quantity_at_uniform_price(
    method_id, expected_price
):
    outcome = build_registry().create(method_id).clear(_double(), seed=0)

    assert len(outcome.allocations) == 3
    assert {payment.amount for payment in outcome.payments} == {expected_price}
    assert outcome.diagnostics["strong_budget_balance"] is True


def test_trade_reduction_vcg_and_sbba_expose_their_budget_tradeoffs():
    registry = build_registry()
    case = _double()

    reduced = registry.create("trade_reduction").clear(case, seed=0)
    vcg = registry.create("vcg_double_auction").clear(case, seed=0)
    sbba = registry.create("sbba").clear(case, seed=0)

    assert len(reduced.allocations) == 2
    assert reduced.diagnostics["weak_budget_balance"] is True
    assert vcg.diagnostics["auctioneer_surplus"] < Decimal("0")
    assert sbba.diagnostics["strong_budget_balance"] is True


def test_double_auction_edge_cases_and_random_sampling_are_deterministic():
    registry = build_registry()
    for method_id in DOUBLE_FAMILIES:
        method = registry.create(method_id)
        assert not method.clear(_double(no_trade=True), seed=3).allocations
    assert not registry.create("trade_reduction").clear(
        _double(one_pair=True), seed=3
    ).allocations

    method = registry.create("random_sampling_double")
    assert method.clear(_double(), seed=17) == method.clear(_double(), seed=17)
