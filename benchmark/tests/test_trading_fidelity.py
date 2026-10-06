from __future__ import annotations

from decimal import Decimal

from datamechbench.metrics import evaluate_trading_metrics
from datamechbench.models import TradeInput
from datamechbench.provenance import load_provenance
from datamechbench.runner import build_registry
from datamechbench.settings.trading import make_double_auction_cases, make_no_trade_cases


def _paper_market(bids: tuple[int, ...], asks: tuple[int, ...]) -> TradeInput:
    buyer_ids = tuple(f"b{index + 1}" for index in range(len(bids)))
    seller_ids = tuple(f"s{index + 1}" for index in range(len(asks)))
    return TradeInput(
        product_id="data-access",
        buyer_ids=buyer_ids,
        seller_ids=seller_ids,
        bids={buyer: Decimal(value) for buyer, value in zip(buyer_ids, bids, strict=True)},
        asks={seller: Decimal(value) for seller, value in zip(seller_ids, asks, strict=True)},
    )


def _muda_golden_market() -> TradeInput:
    return TradeInput(
        product_id="data-access",
        buyer_ids=("b1", "b2", "b3", "b4"),
        seller_ids=("s1", "s2", "s3", "s4"),
        bids={
            "b1": Decimal("100"),
            "b2": Decimal("40"),
            "b3": Decimal("80"),
            "b4": Decimal("30"),
        },
        asks={
            "s1": Decimal("10"),
            "s2": Decimal("15"),
            "s3": Decimal("5"),
            "s4": Decimal("60"),
        },
    )


def test_second_price_respects_seller_cost_in_no_trade_case() -> None:
    case = next(item for item in make_no_trade_cases(2) if item.case_type == "single_sale")
    output = build_registry().create("second_price").clear(case.public, 0)

    assert output.allocations == ()
    assert output.payments == ()


def test_double_auction_metrics_include_balance_trade_loss_and_false_trades() -> None:
    case = next(
        item
        for item in make_double_auction_cases(7)
        if item.metadata["market_size"] == 5 and item.metadata["overlap"] == "high"
    )
    registry = build_registry()
    oracle = registry.create("efficient_clearing").clear(case.public, 0)
    method = registry.create("trade_reduction")
    output = method.clear(case.public, 0)

    metrics = evaluate_trading_metrics(case, output, method.spec, oracle)

    assert metrics["trade_count_loss"].value <= 1
    assert metrics["false_trade_count"].value == 0
    assert metrics["strong_budget_balance"].applicable
    assert metrics["seller_surplus_trading"].applicable
    assert metrics["price_dispersion"].applicable


def test_sbba_direct_transfers_are_strongly_balanced() -> None:
    case = next(item for item in make_double_auction_cases(11) if item.metadata["overlap"] == "high")
    registry = build_registry()
    method = registry.create("sbba")
    oracle = registry.create("efficient_clearing").clear(case.public, 0)
    output = method.clear(case.public, 0)
    metrics = evaluate_trading_metrics(case, output, method.spec, oracle)

    assert metrics["strong_budget_balance"].value is True


def test_all_pay_ir_includes_losing_bidders_payments() -> None:
    from datamechbench.settings.trading import make_bilateral_trade_cases

    case = make_bilateral_trade_cases(13)[0]
    registry = build_registry()
    method = registry.create("all_pay")
    oracle = registry.create("efficient_single_sale").clear(case.public, 0)
    output = method.clear(case.public, 0)

    metrics = evaluate_trading_metrics(case, output, method.spec, oracle)

    assert len(case.public.buyer_ids) > 1
    assert metrics["individual_rationality"].value is False
    expected = sum(case.true_values.values()) * 0
    expected += case.true_values[output.allocations[0].actor_id]
    expected -= sum(case.public.bids.values())
    assert metrics["buyer_surplus"].value == str(expected)


def test_mcafee_matches_candidate_price_and_trade_reduction_rules() -> None:
    method = build_registry().create("mcafee")

    candidate = method.clear(_paper_market((10, 8, 5), (2, 4, 9)), seed=0)
    assert candidate.diagnostics["branch"] == "candidate_price"
    assert candidate.diagnostics["trade_count"] == 2
    assert {payment.amount for payment in candidate.payments} == {Decimal("7")}

    reduction = method.clear(_paper_market((10, 8, 1), (2, 7, 9)), seed=0)
    assert reduction.diagnostics["branch"] == "trade_reduction"
    assert reduction.diagnostics["trade_count"] == 1
    assert reduction.diagnostics["buyer_price"] == "8"
    assert reduction.diagnostics["seller_price"] == "7"


def test_standalone_trade_reduction_matches_mcafee_marginal_prices() -> None:
    method = build_registry().create("trade_reduction")
    output = method.clear(_paper_market((12, 10, 8, 1), (2, 4, 7, 20)), seed=0)

    assert output.diagnostics == {
        "allocation_rule": "mcafee_trade_reduction",
        "trade_count": 2,
        "efficient_trade_count": 3,
        "buyer_price": "8",
        "seller_price": "7",
        "auctioneer_surplus": Decimal("2"),
        "weak_budget_balance": True,
        "strong_budget_balance": False,
    }
    assert [
        (allocation.actor_id, allocation.counterparty_id)
        for allocation in output.allocations
    ] == [("b1", "s1"), ("b2", "s2")]
    assert [
        (payment.payer_id, payment.payee_id, payment.amount)
        for payment in output.payments
    ] == [
        ("b1", "platform", Decimal("8")),
        ("platform", "s1", Decimal("7")),
        ("b2", "platform", Decimal("8")),
        ("platform", "s2", Decimal("7")),
    ]


def test_standalone_trade_reduction_audits_zero_quantity_boundaries() -> None:
    method = build_registry().create("trade_reduction")

    one_efficient = method.clear(_paper_market((10, 1), (2, 20)), seed=0)
    assert one_efficient.allocations == ()
    assert one_efficient.payments == ()
    assert one_efficient.diagnostics == {
        "allocation_rule": "mcafee_trade_reduction",
        "trade_count": 0,
        "efficient_trade_count": 1,
        "buyer_price": "10",
        "seller_price": "2",
        "auctioneer_surplus": Decimal("0"),
        "weak_budget_balance": True,
        "strong_budget_balance": True,
    }

    no_trade = method.clear(_paper_market((1,), (2,)), seed=0)
    assert no_trade.allocations == ()
    assert no_trade.payments == ()
    assert no_trade.diagnostics == {
        "allocation_rule": "mcafee_trade_reduction",
        "trade_count": 0,
        "efficient_trade_count": 0,
        "buyer_price": None,
        "seller_price": None,
        "auctioneer_surplus": Decimal("0"),
        "weak_budget_balance": True,
        "strong_budget_balance": True,
    }


def test_standalone_trade_reduction_ties_use_actor_id_without_changing_rule() -> None:
    method = build_registry().create("trade_reduction")
    output = method.clear(_paper_market((10, 8, 8, 1), (2, 7, 7, 20)), seed=19)

    assert output.diagnostics["efficient_trade_count"] == 3
    assert output.diagnostics["buyer_price"] == "8"
    assert output.diagnostics["seller_price"] == "7"
    assert [
        (allocation.actor_id, allocation.counterparty_id)
        for allocation in output.allocations
    ] == [("b1", "s1"), ("b2", "s2")]


def test_sbba_case_one_trades_k_without_lottery_over_price_setter() -> None:
    method = build_registry().create("sbba")
    market = _paper_market((10, 8, 5), (2, 4, 7))

    for seed in range(10):
        output = method.clear(market, seed=seed)
        assert output.diagnostics["branch"] == "full_trade"
        assert output.diagnostics["trade_count"] == 2
        assert {allocation.actor_id for allocation in output.allocations} == {"b1", "b2"}
        assert {allocation.counterparty_id for allocation in output.allocations} == {"s1", "s2"}
        assert {payment.amount for payment in output.payments} == {Decimal("7")}


def test_sbba_case_two_excludes_marginal_buyer_and_one_random_seller() -> None:
    method = build_registry().create("sbba")
    market = _paper_market((10, 8, 1), (2, 7, 9))
    excluded_sellers: set[str] = set()

    for seed in range(20):
        output = method.clear(market, seed=seed)
        assert output.diagnostics["branch"] == "seller_lottery_trade_reduction"
        assert output.diagnostics["trade_count"] == 1
        assert {allocation.actor_id for allocation in output.allocations} == {"b1"}
        trading_seller = output.allocations[0].counterparty_id
        assert trading_seller in {"s1", "s2"}
        excluded_sellers.add(({"s1", "s2"} - {trading_seller}).pop())
        assert {payment.amount for payment in output.payments} == {Decimal("8")}

    assert excluded_sellers == {"s1", "s2"}


def test_mcafee_and_sbba_are_reference_grade_after_paper_parity_audit() -> None:
    catalog = load_provenance()

    assert catalog.mechanisms["mcafee"].provenance_kind == "paper_exact"
    assert catalog.mechanisms["mcafee"].deviations == ()
    assert catalog.mechanisms["sbba"].provenance_kind == "paper_exact"
    assert catalog.mechanisms["sbba"].deviations == ()


def test_standalone_trade_reduction_is_reference_grade_after_parity_audit() -> None:
    record = load_provenance().mechanisms["trade_reduction"]

    assert record.provenance_kind == "paper_exact"
    assert record.deviations == ()


def test_lottery_muda_uses_cross_market_equilibrium_prices_and_long_side_lotteries() -> None:
    output = build_registry().create("lottery_muda").clear(
        _muda_golden_market(), seed=1
    )

    assert output.diagnostics["left_buyers"] == ["b3"]
    assert output.diagnostics["left_sellers"] == ["s1", "s2", "s4"]
    assert output.diagnostics["right_buyers"] == ["b1", "b2", "b4"]
    assert output.diagnostics["right_sellers"] == ["s3"]
    assert output.diagnostics["left_price"] == Decimal("12.5")
    assert output.diagnostics["right_price"] == Decimal("70")
    assert output.diagnostics["left_branch"] == "excess_supply_lottery"
    assert output.diagnostics["right_branch"] == "excess_demand_lottery"
    assert output.diagnostics["trade_count"] == 2
    assert output.diagnostics["auctioneer_surplus"] == Decimal("0")
    assert output.diagnostics["strong_budget_balance"] is True
    assert [
        (allocation.actor_id, allocation.counterparty_id)
        for allocation in output.allocations
    ] == [("b3", "s2"), ("b2", "s3")]
    assert [
        (payment.payer_id, payment.payee_id, payment.amount)
        for payment in output.payments
    ] == [
        ("b3", "s2", Decimal("70")),
        ("b2", "s3", Decimal("12.5")),
    ]


def test_vickrey_muda_uses_displaced_long_side_reports_as_thresholds() -> None:
    output = build_registry().create("vickrey_muda").clear(
        _muda_golden_market(), seed=1
    )

    assert output.diagnostics["left_price"] == Decimal("12.5")
    assert output.diagnostics["right_price"] == Decimal("70")
    assert output.diagnostics["left_branch"] == "excess_supply_vickrey"
    assert output.diagnostics["right_branch"] == "excess_demand_vickrey"
    assert output.diagnostics["auctioneer_surplus"] == Decimal("82.5")
    assert output.diagnostics["weak_budget_balance"] is True
    assert output.diagnostics["strong_budget_balance"] is False
    assert [
        (allocation.actor_id, allocation.counterparty_id)
        for allocation in output.allocations
    ] == [("b3", "s1"), ("b1", "s3")]
    assert [
        (payment.payer_id, payment.payee_id, payment.amount)
        for payment in output.payments
    ] == [
        ("b3", "platform", Decimal("70")),
        ("platform", "s1", Decimal("15")),
        ("b1", "platform", Decimal("40")),
        ("platform", "s3", Decimal("12.5")),
    ]


def test_muda_strict_willingness_does_not_trade_equal_reports() -> None:
    tied = _paper_market((10, 10, 10, 10), (10, 10, 10, 10))

    for method_id in ("lottery_muda", "vickrey_muda"):
        output = build_registry().create(method_id).clear(tied, seed=1)
        assert output.allocations == ()
        assert output.payments == ()
        assert output.diagnostics["trade_count"] == 0


def test_muda_variants_declare_only_the_single_unit_domain_boundary() -> None:
    catalog = load_provenance()

    for method_id in ("lottery_muda", "vickrey_muda"):
        record = catalog.mechanisms[method_id]
        assert record.provenance_kind == "paper_variant"
        assert record.deviations == (
            "single-unit homogeneous specialization; multi-unit virtual-trader treatment omitted",
        )


def test_muda_provenance_preserves_complete_source_algorithm_locations() -> None:
    catalog = load_provenance()

    assert catalog.mechanisms["lottery_muda"].algorithm_location == (
        "independent random split, cross-market Walrasian price, and real-trader lottery rationing"
    )
    assert catalog.mechanisms["vickrey_muda"].algorithm_location == (
        "independent random split, cross-market Walrasian price, and displaced long-side threshold fees"
    )
