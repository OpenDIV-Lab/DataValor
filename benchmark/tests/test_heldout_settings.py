from __future__ import annotations

from datamechbench.data import load_owner_dataset
from datamechbench.heldout_sources import CalibratedTradeProfile
from datamechbench.settings.heldout import (
    make_heldout_procurement_cases,
    make_heldout_trading_cases,
    make_heldout_valuation_cases,
)


def test_heldout_valuation_cases_preserve_block_and_replication_contract() -> None:
    dataset = load_owner_dataset(seed=1701, dataset_name="wine")

    cases = make_heldout_valuation_cases({"openml-44-spambase": dataset})

    assert len(cases) == 3
    assert {case.metadata["replication_factor"] for case in cases} == {1, 2, 4}
    assert all(case.metadata["cohort"] == "heldout" for case in cases)
    assert {case.metadata["independent_block"] for case in cases} == {"VHO-spambase"}
    assert {case.metadata["benchmark_setting"] for case in cases} == {
        "V-REPLICATION-ROBUSTNESS"
    }


def test_heldout_procurement_combines_real_utility_and_calibrated_costs() -> None:
    dataset = load_owner_dataset(seed=1701, dataset_name="wine")
    costs = {f"o{index}": 0.5 + index / 10 for index in range(8)}

    cases = make_heldout_procurement_cases(
        {"openml-44-spambase": dataset},
        {"PHO-chile-mar": costs},
    )

    assert len(cases) == 2
    assert {case.metadata["budget_ratio"] for case in cases} == {0.3, 0.5}
    assert all(case.metadata["cohort"] == "heldout" for case in cases)
    assert {case.metadata["benchmark_setting"] for case in cases} == {
        "P-MARKET-CONCENTRATION"
    }
    assert all(case.public.metadata["cost_calibration"] == "ChileCompra" for case in cases)


def test_heldout_trading_cases_use_market_blocks_not_parameter_points() -> None:
    profile = CalibratedTradeProfile(
        buyer_values=tuple(0.9 - index * 0.05 for index in range(8)),
        seller_costs=tuple(0.1 + index * 0.05 for index in range(8)),
        source_row_count=24,
        retained_bid_count=20,
        retained_offer_count=20,
    )

    cases = make_heldout_trading_cases({"THO-elexon-20240315-sp08": profile})

    assert len(cases) == 1
    [case] = cases
    assert case.metadata["cohort"] == "heldout"
    assert case.metadata["independent_block"] == "THO-elexon-20240315-sp08"
    assert case.metadata["benchmark_setting"] == "T-MARKET-THICKNESS"
    assert case.metadata["source_row_count"] == 24


def test_heldout_trading_sizes_are_cases_within_same_source_block() -> None:
    small = CalibratedTradeProfile(
        buyer_values=tuple(0.9 - index * 0.05 for index in range(8)),
        seller_costs=tuple(0.1 + index * 0.05 for index in range(8)),
        source_row_count=24,
        retained_bid_count=20,
        retained_offer_count=20,
    )
    large = CalibratedTradeProfile(
        buyer_values=tuple(0.9 - index * 0.02 for index in range(16)),
        seller_costs=tuple(0.1 + index * 0.02 for index in range(16)),
        source_row_count=24,
        retained_bid_count=20,
        retained_offer_count=20,
    )

    cases = make_heldout_trading_cases(
        {"THO-date-n8": small, "THO-date-n16": large},
        independent_blocks={"THO-date-n8": "THO-date", "THO-date-n16": "THO-date"},
    )

    assert len(cases) == 2
    assert {case.metadata["market_size"] for case in cases} == {8, 16}
    assert {case.metadata["independent_block"] for case in cases} == {"THO-date"}
