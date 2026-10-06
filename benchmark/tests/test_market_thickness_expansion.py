from __future__ import annotations

from decimal import Decimal

import pytest
from datamechbench.metrics import evaluate_trading_metrics
from datamechbench.models import AllocationRecord, MarketOutcome, PaymentRecord
from datamechbench.runner import build_registry
from datamechbench.settings import trading as trading_settings


def test_market_thickness_cases_have_controlled_efficient_trade_counts() -> None:
    assert hasattr(trading_settings, "make_market_thickness_cases")
    cases = trading_settings.make_market_thickness_cases(seed=9)

    assert len(cases) == 20
    assert len({case.case_id for case in cases}) == 20
    assert {case.metadata["market_size"] for case in cases} == {2, 4, 8, 16}
    assert {case.metadata["surplus_margin_profile"] for case in cases} == {
        "tight",
        "narrow",
        "reference",
        "wide",
        "very_wide",
    }
    assert {
        "TTHICK-n2-k1",
        "TTHICK-n4-k3",
        "TTHICK-n8-k6",
        "TTHICK-n16-k12",
    } <= {case.case_id for case in cases}
    assert all(case.metadata["benchmark_setting"] == "T-MARKET-THICKNESS" for case in cases)
    for case in cases:
        ordered_values = sorted(case.true_values.values(), reverse=True)
        ordered_costs = sorted(case.true_costs.values())
        actual = sum(value >= cost for value, cost in zip(ordered_values, ordered_costs, strict=True))
        assert actual == case.metadata["efficient_trade_count"]
    for size in (2, 4, 8, 16):
        cohort = [case for case in cases if case.metadata["market_size"] == size]
        assert len(cohort) == 5
        assert len(
            {round(case.metadata["minimum_efficient_surplus"], 6) for case in cohort}
        ) == 5


def test_thickness_metrics_normalize_trade_loss_and_participant_surplus() -> None:
    case = trading_settings.make_market_thickness_cases(seed=9)[1]
    oracle = build_registry().create("efficient_clearing").clear(case.public, seed=0)
    output = MarketOutcome(
        selected_ids=("b0", "b1", "s0", "s1"),
        allocations=(
            AllocationRecord("b0", "s0", (case.public.product_id,)),
            AllocationRecord("b1", "s1", (case.public.product_id,)),
        ),
        payments=(
            PaymentRecord("b0", "s0", Decimal("0.5"), "test", (case.public.product_id,)),
            PaymentRecord("b1", "s1", Decimal("0.5"), "test", (case.public.product_id,)),
        ),
    )
    spec = build_registry().create("mcafee").spec

    metrics = evaluate_trading_metrics(case, output, spec, oracle)

    assert metrics["efficient_trade_count"].value == 3
    assert metrics["normalized_trade_loss"].value == pytest.approx(1 / 3)
    assert metrics["participant_surplus_ratio"].value == pytest.approx(1.58 / 2.34)
