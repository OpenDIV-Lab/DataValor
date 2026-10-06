from __future__ import annotations

from datamechbench.data import (
    make_analytic_valuation_cases,
    make_procurement_cases,
    make_real_valuation_cases,
    make_trade_cases,
)
from datamechbench.runner import BenchmarkConfig, build_cases, build_registry, run_benchmark
from scipy.stats import spearmanr


def _by_id(cases):
    return {case.case_id: case for case in cases}


def test_formal_cases_have_selected_benchmark_settings():
    analytic = _by_id(make_analytic_valuation_cases())
    real = _by_id(make_real_valuation_cases(seed=42))
    procurement = _by_id(make_procurement_cases(seed=42))
    trading = _by_id(make_trade_cases(seed=42))

    assert analytic["C-add"].metadata["benchmark_setting"] == "valuation_game"
    assert real["C-real-clean"].metadata["benchmark_setting"] == "valuation_owner_ml"
    assert procurement["P-C-add-b50"].metadata["benchmark_setting"] == "procurement_additive"
    assert (
        procurement["P-C-coverage-b50"].metadata["benchmark_setting"]
        == "procurement_submodular"
    )
    assert (
        procurement["P-C-real-clean-b50"].metadata["benchmark_setting"]
        == "procurement_ml"
    )
    assert trading["S5-single-sale"].metadata["benchmark_setting"] == "single_sale"
    assert trading["S6-double-auction"].metadata["benchmark_setting"] == "double_auction"
    assert analytic["C-add"].metadata["pilot"] is False
    assert real["C-real-clean"].metadata["pilot"] is False


def test_eight_pilot_cases_are_deterministic_and_visibly_marked():
    first = build_cases(seed=42)
    second = build_cases(seed=42)
    pilot_ids = {
        case.case_id
        for cases in first.values()
        for case in cases
        if case.metadata.get("pilot") is True
    }

    assert pilot_ids == {
        "C-harmful",
        "C-real-size-skew",
        "P-C-coverage-positive-corr-b50",
        "P-C-coverage-negative-corr-b50",
        "S5-single-sale-no-trade",
        "S6-double-thin",
        "S6-double-buyer-heavy",
        "S6-double-low-overlap",
    }
    assert {
        case.case_id
        for cases in second.values()
        for case in cases
        if case.metadata.get("pilot") is True
    } == pilot_ids


def test_harmful_and_size_skew_pilots_exercise_distinct_valuation_properties():
    analytic = _by_id(make_analytic_valuation_cases())
    harmful = analytic["C-harmful"]
    without_bad = harmful.utility(tuple(owner for owner in harmful.owner_ids if owner != "o5"))
    assert harmful.utility(harmful.owner_ids) < without_bad
    assert harmful.metadata["property"] == "non_monotone_harmful_owner"
    assert harmful.metadata["bad_owner"] == "o5"

    real = _by_id(make_real_valuation_cases(seed=42))
    skew = real["C-real-size-skew"].metadata["owner_dataset"]
    sizes = [len(rows) for rows in skew.owner_rows.values()]
    assert max(sizes) >= 4 * min(sizes)
    assert sum(sizes) == len(skew.x_train)


def test_procurement_pilots_have_opposite_cost_quality_correlation():
    cases = _by_id(make_procurement_cases(seed=42))
    positive = cases["P-C-coverage-positive-corr-b50"].public
    negative = cases["P-C-coverage-negative-corr-b50"].public

    positive_rho = spearmanr(
        [positive.seller_values[seller] for seller in positive.seller_ids],
        [float(positive.reported_costs[seller]) for seller in positive.seller_ids],
    ).statistic
    negative_rho = spearmanr(
        [negative.seller_values[seller] for seller in negative.seller_ids],
        [float(negative.reported_costs[seller]) for seller in negative.seller_ids],
    ).statistic
    assert positive_rho > 0.9
    assert negative_rho < -0.9


def test_trade_pilots_keep_complete_true_types_and_expected_market_shapes():
    cases = _by_id(make_trade_cases(seed=42))
    no_trade = cases["S5-single-sale-no-trade"]
    assert max(no_trade.true_values.values()) < min(no_trade.true_costs.values())

    thin = cases["S6-double-thin"]
    assert len(thin.public.buyer_ids) == len(thin.public.seller_ids) == 2
    buyer_heavy = cases["S6-double-buyer-heavy"]
    assert len(buyer_heavy.public.buyer_ids) >= 3 * len(buyer_heavy.public.seller_ids)
    low_overlap = cases["S6-double-low-overlap"]
    assert max(low_overlap.true_values.values()) < min(low_overlap.true_costs.values())

    for case in (no_trade, thin, buyer_heavy, low_overlap):
        assert set(case.public.buyer_ids) == set(case.true_values)
        assert set(case.public.seller_ids) == set(case.true_costs)


def test_each_pilot_case_type_has_at_least_six_compatible_families():
    registry = build_registry()
    cases = build_cases(seed=42)
    for track, track_cases in cases.items():
        for case in track_cases:
            if not case.metadata.get("pilot"):
                continue
            families = {
                spec.family_id for spec in registry.compatible(track, case.case_type)
            }
            assert len(families) >= 6, case.case_id


def test_runner_propagates_serializable_case_grouping_metadata():
    config = BenchmarkConfig(
        name="metadata",
        output_dir="unused",
        seeds=(0,),
        methods={"valuation": {"random": {}}, "procurement": {}, "trading": {}},
        case_ids={"valuation": ("C-harmful",), "procurement": (), "trading": ()},
    )
    result = run_benchmark(config)[0]

    assert result.metadata["benchmark_setting"] == "valuation_game"
    assert result.metadata["pilot"] is True
    assert result.metadata["property"] == "non_monotone_harmful_owner"
