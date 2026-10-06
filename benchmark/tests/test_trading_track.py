from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest
from datamechbench.data import make_trade_cases
from datamechbench.methods.trading import register_trading_methods
from datamechbench.metrics import evaluate_trading_metrics
from datamechbench.models import TradeCase
from datamechbench.registry import MethodRegistry, validate_output


@pytest.fixture
def registry():
    result = MethodRegistry()
    register_trading_methods(result)
    return result


def _cases():
    return {case.case_id: case for case in make_trade_cases(seed=42)}


def test_trading_methods_are_registered(registry):
    assert {spec.method_id for spec in registry.specs("trading")} == {
        "posted_price",
        "first_price",
        "second_price",
        "second_price_reserve",
        "myerson_reserve",
        "english_auction",
        "dutch_auction",
        "all_pay",
        "efficient_single_sale",
        "efficient_clearing",
        "mcafee",
        "vcg_double_auction",
        "pay_as_bid_double",
        "seller_price_double",
        "midpoint_double",
        "buyer_price_double",
        "trade_reduction",
        "sbba",
        "random_sampling_double",
        "bilateral_midpoint",
        "lottery_muda",
        "vickrey_muda",
    }


def test_posted_price_is_fixed_before_current_bids(registry):
    case = _cases()["S5-single-sale"]
    price = case.public.posted_price
    high_bids = {buyer: price * Decimal("2") for buyer in case.public.buyer_ids}
    low_bids = {buyer: price / Decimal("2") for buyer in case.public.buyer_ids}
    method = registry.create("posted_price")
    accepted = method.clear(replace(case.public, bids=high_bids), seed=0)
    rejected = method.clear(replace(case.public, bids=low_bids), seed=0)

    assert {payment.amount for payment in accepted.payments} == {price}
    assert accepted.diagnostics["posted_price"] == str(price)
    assert rejected.diagnostics["posted_price"] == str(price)
    assert not rejected.allocations


def test_second_price_allocates_single_sale_to_highest_bid(registry):
    case = _cases()["S5-single-sale"]
    method = registry.create("second_price")
    output = method.clear(case.public, seed=0)
    validate_output(method.spec, case.public, output)
    expected = max(case.public.buyer_ids, key=case.public.bids.__getitem__)
    assert output.allocations[0].actor_id == expected


def test_efficient_clearing_weakly_dominates_mcafee_gft(registry):
    case = _cases()["S6-double-auction"]
    efficient_method = registry.create("efficient_clearing")
    mcafee_method = registry.create("mcafee")
    efficient = efficient_method.clear(case.public, 0)
    mcafee = mcafee_method.clear(case.public, 0)
    efficient_metrics = evaluate_trading_metrics(case, efficient, efficient_method.spec, efficient)
    mcafee_metrics = evaluate_trading_metrics(case, mcafee, mcafee_method.spec, efficient)

    assert efficient_metrics["realized_gain_from_trade"].value >= mcafee_metrics["realized_gain_from_trade"].value
    assert 0 <= mcafee_metrics["gain_from_trade_ratio"].value <= 1
    assert mcafee_metrics["individual_rationality"].value is True
    assert mcafee_metrics["weak_budget_balance"].value is True


def test_trade_metrics_use_evaluator_truth_not_reports(registry):
    case = _cases()["S6-double-auction"]
    fake_bids = {buyer: Decimal("0") for buyer in case.public.buyer_ids}
    fake_bids["b0"] = Decimal("999999")
    fake_asks = {seller: Decimal("999999") for seller in case.public.seller_ids}
    fake_asks["s0"] = Decimal("0")
    public = replace(case.public, bids=fake_bids, asks=fake_asks)
    attacked = TradeCase(
        case_id="attacked",
        public=public,
        true_values=case.true_values,
        true_costs=case.true_costs,
        case_type=case.case_type,
    )
    method = registry.create("efficient_clearing")
    outcome = method.clear(public, 0)
    metrics = evaluate_trading_metrics(attacked, outcome, method.spec, outcome)
    expected = float(case.true_values["b0"] - case.true_costs["s0"])
    assert metrics["realized_gain_from_trade"].value == pytest.approx(expected)
