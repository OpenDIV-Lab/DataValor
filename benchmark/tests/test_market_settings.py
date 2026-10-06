from __future__ import annotations

from decimal import Decimal

from datamechbench.settings import valuation as valuation_settings
from datamechbench.settings.procurement import (
    make_procurement_additive_cases,
    make_procurement_ml_cases,
    make_procurement_submodular_cases,
)
from datamechbench.settings.trading import (
    make_bilateral_trade_cases,
    make_correlated_trade_cases,
    make_double_auction_cases,
    make_no_trade_cases,
)


def test_procurement_settings_cover_utility_classes_and_information_models() -> None:
    additive = make_procurement_additive_cases(3)
    submodular = make_procurement_submodular_cases(3)
    ml = make_procurement_ml_cases(3)

    assert len(additive) >= 6
    assert {case.metadata["benchmark_setting"] for case in additive} == {"P-ADDITIVE"}
    assert {case.metadata["benchmark_setting"] for case in submodular} == {"P-SUBMODULAR"}
    assert {case.metadata["benchmark_setting"] for case in ml} == {"P-ML-ACQUISITION"}
    assert any(case.metadata.get("dominant_singleton") for case in additive)
    assert {case.metadata["cost_value_correlation"] for case in additive} >= {
        "independent",
        "positive",
        "negative",
    }
    assert all(case.metadata["evaluator_utility"] == "held_out_test" for case in ml)
    assert all(case.public.metadata["mechanism_utility"] == "validation_proxy" for case in ml)


def test_valuation_replication_setting_has_three_datasets_and_three_factors() -> None:
    assert hasattr(valuation_settings, "make_valuation_replication_cases")
    cases = valuation_settings.make_valuation_replication_cases(3)

    assert {case.metadata["dataset_name"] for case in cases} == {
        "breast_cancer", "wine", "digits"
    }
    assert {case.metadata["replication_factor"] for case in cases} == {1, 2, 4}


def test_trading_settings_cover_thickness_overlap_and_no_trade() -> None:
    bilateral = make_bilateral_trade_cases(5)
    double = make_double_auction_cases(5)
    no_trade = make_no_trade_cases(5)
    correlated = make_correlated_trade_cases(5)

    assert {case.metadata["benchmark_setting"] for case in bilateral} == {"T-BILATERAL"}
    assert {case.metadata["market_size"] for case in double} >= {2, 5, 10}
    assert {case.metadata["overlap"] for case in double} >= {"low", "medium", "high"}
    assert all(case.metadata["benchmark_setting"] == "T-NO-TRADE" for case in no_trade)
    assert all(max(case.true_values.values()) < min(case.true_costs.values()) for case in no_trade)
    assert all(case.metadata["benchmark_setting"] == "T-CORRELATED" for case in correlated)
    assert all("independent_private_values" not in case.metadata["assumptions"] for case in correlated)


def test_market_thickness_is_a_separate_formal_setting() -> None:
    from datamechbench.settings import trading as trading_settings

    assert hasattr(trading_settings, "make_market_thickness_cases")
    cases = trading_settings.make_market_thickness_cases(5)
    assert len(cases) == 20
    assert {case.metadata["efficient_trade_count"] for case in cases} == {1, 3, 6, 12}
    assert {case.metadata["surplus_margin_profile"] for case in cases} == {
        "tight", "narrow", "reference", "wide", "very_wide"
    }


def test_additive_setting_budget_matches_declared_ratio() -> None:
    for case in make_procurement_additive_cases(9):
        total = sum(case.true_costs.values(), Decimal("0"))
        assert case.public.budget == total * Decimal(str(case.metadata["budget_ratio"]))


def test_default_case_catalog_includes_all_formal_market_settings() -> None:
    from datamechbench.runner import build_cases

    cases = build_cases(seed=6)
    procurement_settings = {
        case.metadata.get("benchmark_setting") for case in cases["procurement"]
    }
    trading_settings = {
        case.metadata.get("benchmark_setting") for case in cases["trading"]
    }

    assert len({case.case_id for case in cases["procurement"]}) == len(cases["procurement"])
    assert len({case.case_id for case in cases["trading"]}) == len(cases["trading"])
    assert {"P-ADDITIVE", "P-SUBMODULAR", "P-ML-ACQUISITION"} <= procurement_settings
    assert {
        "T-BILATERAL", "T-DOUBLE", "T-NO-TRADE", "T-CORRELATED",
        "T-MARKET-THICKNESS",
    } <= trading_settings
