from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import numpy as np
from datamechbench.data import (
    make_analytic_valuation_cases,
    make_procurement_cases,
    make_real_valuation_cases,
    make_trade_cases,
)
from datamechbench.methods.procurement import register_procurement_methods
from datamechbench.methods.trading import register_trading_methods
from datamechbench.metrics import evaluate_procurement_metrics, evaluate_trading_metrics
from datamechbench.registry import MethodRegistry
from datamechbench.stress import (
    REPORT_MULTIPLIERS,
    bid_reports,
    cost_reports,
    duplicate_case,
    noise_case,
)


def _registry():
    result = MethodRegistry()
    register_procurement_methods(result)
    register_trading_methods(result)
    return result


def test_duplicate_and_noise_stresses_are_pure_and_deterministic():
    clean = make_analytic_valuation_cases()[0]
    duplicate_a = duplicate_case(clean, "o0")
    duplicate_b = duplicate_case(clean, "o0")
    duplicate_id = "o0__duplicate"
    assert clean.owner_ids == tuple(f"o{index}" for index in range(6))
    assert duplicate_a.owner_ids == duplicate_b.owner_ids
    assert duplicate_a.utility(("o0", duplicate_id)) == clean.utility(("o0",))
    assert duplicate_a.utility((duplicate_id,)) == clean.utility(("o0",))

    real_clean = make_real_valuation_cases(seed=42)[0]
    original_labels = real_clean.metadata["owner_dataset"].y_train.copy()
    noisy_a = noise_case(real_clean, "o3", rate=0.25, seed=9)
    noisy_b = noise_case(real_clean, "o3", rate=0.25, seed=9)
    assert np.array_equal(real_clean.metadata["owner_dataset"].y_train, original_labels)
    assert np.array_equal(
        noisy_a.metadata["owner_dataset"].y_train,
        noisy_b.metadata["owner_dataset"].y_train,
    )
    rows = real_clean.metadata["owner_dataset"].owner_rows["o3"]
    changed = np.count_nonzero(
        noisy_a.metadata["owner_dataset"].y_train[list(rows)] != original_labels[list(rows)]
    )
    assert changed == round(0.25 * len(rows))


def test_unilateral_report_grids_are_exact_and_do_not_mutate_inputs():
    procurement = make_procurement_cases(seed=42)[0]
    original_costs = dict(procurement.public.reported_costs)
    costs = cost_reports(procurement)
    assert REPORT_MULTIPLIERS == (0.5, 0.75, 1.0, 1.25, 1.5)
    assert {multiplier for _, multiplier in costs} == set(REPORT_MULTIPLIERS)
    assert procurement.public.reported_costs == original_costs
    for (seller, multiplier), public in costs.items():
        assert public.reported_costs[seller] == procurement.true_costs[seller] * Decimal(str(multiplier))

    trade = make_trade_cases(seed=42)[1]
    original_bids, original_asks = dict(trade.public.bids), dict(trade.public.asks)
    reports = bid_reports(trade)
    assert {multiplier for _, multiplier in reports} == set(REPORT_MULTIPLIERS)
    assert trade.public.bids == original_bids
    assert trade.public.asks == original_asks


def test_grid_deviation_metrics_are_nonnegative_and_report_profitable_count():
    registry = _registry()
    procurement = next(
        case
        for case in make_procurement_cases(seed=42)
        if case.metadata["source_case_id"] == "C-add" and case.metadata["budget_ratio"] == 0.5
    )
    p_method = registry.create("proportional_share")
    p_output = p_method.allocate(procurement.public, 0)
    p_metrics = evaluate_procurement_metrics(
        procurement, p_output, p_method.spec, method=p_method, seed=0
    )
    assert p_metrics["max_deviation_gain"].value >= 0
    assert (p_metrics["max_deviation_gain"].value == 0) == (
        p_metrics["profitable_deviation_count"].value == 0
    )

    trade = make_trade_cases(seed=42)[1]
    t_method = registry.create("mcafee")
    t_output = t_method.clear(trade.public, 0)
    t_metrics = evaluate_trading_metrics(trade, t_output, t_method.spec, method=t_method, seed=0)
    assert t_metrics["max_deviation_gain"].value >= 0
    assert (t_metrics["max_deviation_gain"].value == 0) == (
        t_metrics["profitable_deviation_count"].value == 0
    )


def test_metric_na_reasons_cover_missing_payments_truth_oracle_and_quantity():
    registry = _registry()
    procurement = make_procurement_cases(seed=42)[0]
    oracle_method = registry.create("budget_optimum")
    oracle_output = oracle_method.allocate(procurement.public, 0)
    oracle_metrics = evaluate_procurement_metrics(
        procurement, oracle_output, oracle_method.spec
    )
    assert oracle_metrics["total_payment"].reason == "missing_payments"
    assert oracle_metrics["oracle_ratio"].reason == "missing_oracle_output"

    p_method = registry.create("proportional_share")
    p_output = p_method.allocate(procurement.public, 0)
    missing_truth = replace(procurement, true_costs={})
    missing_truth_metrics = evaluate_procurement_metrics(
        missing_truth, p_output, p_method.spec
    )
    assert missing_truth_metrics["seller_ir_violation_count"].reason == "missing_true_types"

    trade = make_trade_cases(seed=42)[1]
    t_method = registry.create("mcafee")
    t_output = t_method.clear(trade.public, 0)
    trade_metrics = evaluate_trading_metrics(trade, t_output, t_method.spec)
    assert trade_metrics["gain_from_trade_ratio"].reason == "missing_oracle_output"
    assert trade_metrics["quantity_weighted_trade_volume"].reason == "single_unit_only"
