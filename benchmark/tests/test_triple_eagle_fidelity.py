from __future__ import annotations

import math
from decimal import Decimal

import numpy as np
import pytest
from datamechbench.expectations import load_expectations
from datamechbench.metrics import evaluate_procurement_metrics
from datamechbench.models import ProcurementInput
from datamechbench.provenance import load_provenance, validate_provenance
from datamechbench.runner import (
    BenchmarkConfig,
    build_cases,
    build_registry,
    load_config,
    run_benchmark,
)


def _additive(
    values: dict[str, float],
    costs: dict[str, str],
    *,
    budget: str,
    baseline: float = 0.0,
) -> ProcurementInput:
    return ProcurementInput(
        seller_ids=tuple(values),
        reported_costs={seller: Decimal(costs[seller]) for seller in values},
        budget=Decimal(budget),
        utility=lambda selected: baseline
        + float(sum(values[seller] for seller in set(selected))),
        seller_values=values,
    )


def _payments(outcome) -> dict[str, Decimal]:
    return {payment.payee_id: payment.amount for payment in outcome.payments}


def test_triple_eagle_randomized_matches_lsd_pricing_and_suffix_free_branch() -> None:
    public = _additive(
        {"a": 3.0, "b": 2.0, "c": 1.0},
        {"a": "0.01", "b": "0.01", "c": "0.01"},
        budget="3",
    )

    outcome = build_registry().create("triple_eagle_randomized").allocate(public, 0)
    payments = _payments(outcome)
    alpha = (math.sqrt(13.0) + 1.0) / 2.0

    assert outcome.selected_ids == ("b", "c", "a")
    assert float(payments["b"]) == pytest.approx(2.0 / alpha)
    assert float(payments["c"]) == pytest.approx(3.0 / (2.0 + 3.0 * alpha))
    assert float(payments["a"]) == pytest.approx(3.0 / (1.0 + alpha))
    assert outcome.diagnostics["mechanism_branch"] == "lsd_suffix"
    assert outcome.diagnostics["suffix_truncated"] is False
    assert outcome.diagnostics["budget_feasible"] is True


def test_triple_eagle_randomized_uses_paper_low_supply_mixture() -> None:
    public = _additive(
        {"a": 10.0, "b": 1.0, "c": 1.0},
        {"a": "0.5", "b": "1", "c": "1"},
        budget="2",
    )
    method = build_registry().create("triple_eagle_randomized")

    singleton = method.allocate(public, 1)  # 0.5118... <= alpha/(alpha+2)
    best_effort = method.allocate(public, 0)  # 0.6369... > alpha/(alpha+2)
    alpha = (math.sqrt(13.0) + 1.0) / 2.0

    assert singleton.selected_ids == ("a",)
    assert _payments(singleton) == {"a": Decimal("2")}
    assert singleton.diagnostics["mechanism_branch"] == "best_singleton"
    assert best_effort.selected_ids == ("a",)
    assert _payments(best_effort) == {"a": Decimal("2")}
    assert best_effort.diagnostics["mechanism_branch"] == "best_effort"
    assert singleton.diagnostics["singleton_probability"] == pytest.approx(
        alpha / (alpha + 2.0)
    )


def test_triple_eagle_randomized_seed_panel_matches_paper_branch_probability() -> None:
    public = _additive(
        {"a": 10.0, "b": 1.0, "c": 1.0},
        {"a": "0.5", "b": "1", "c": "1"},
        budget="2",
    )
    method = build_registry().create("triple_eagle_randomized")
    alpha = (math.sqrt(13.0) + 1.0) / 2.0
    seeds = range(100)
    expected = sum(
        np.random.default_rng(seed).random() <= alpha / (alpha + 2.0)
        for seed in seeds
    )

    observed = sum(
        method.allocate(public, seed).diagnostics["mechanism_branch"]
        == "best_singleton"
        for seed in seeds
    )

    assert observed == expected


def test_triple_eagle_deterministic_matches_two_phase_prices() -> None:
    public = _additive(
        {"a": 3.0, "b": 2.0, "c": 1.0},
        {"a": "0.01", "b": "0.01", "c": "0.01"},
        budget="3",
    )

    outcome = build_registry().create("triple_eagle_deterministic").allocate(public, 0)
    payments = _payments(outcome)
    alpha = math.sqrt(6.0)

    assert outcome.selected_ids == ("b", "c", "a")
    assert float(payments["b"]) == pytest.approx(2.0 / alpha)
    assert float(payments["c"]) == pytest.approx(1.0 / alpha)
    assert float(payments["a"]) == pytest.approx(3.0 / (1.0 + alpha))
    assert outcome.diagnostics["mechanism_branch"] == "two_phase_suffix"
    assert outcome.diagnostics["first_phase_winners"] == ["b", "c"]


def test_triple_eagle_deterministic_uses_paper_singleton_fallback() -> None:
    public = _additive(
        {"a": 3.0, "b": 2.0, "c": 1.0},
        {"a": "0.5", "b": "1", "c": "1"},
        budget="3",
    )

    outcome = build_registry().create("triple_eagle_deterministic").allocate(public, 0)

    assert outcome.selected_ids == ("a",)
    assert _payments(outcome) == {"a": Decimal("3")}
    assert outcome.diagnostics["mechanism_branch"] == "best_singleton"


def test_triple_eagle_returns_largest_budget_feasible_insertion_suffix() -> None:
    public = _additive(
        {seller: 1.0 for seller in ("a", "b", "c", "d", "e")},
        {seller: "0" for seller in ("a", "b", "c", "d", "e")},
        budget="1",
    )

    outcome = build_registry().create("triple_eagle_randomized").allocate(public, 0)

    assert outcome.selected_ids == ("c", "d", "e", "a")
    assert outcome.diagnostics["accepted_order"] == ["b", "c", "d", "e", "a"]
    assert outcome.diagnostics["suffix_truncated"] is True
    assert sum(_payments(outcome).values(), Decimal("0")) <= public.budget


@pytest.mark.parametrize(
    "method_id",
    ["triple_eagle_randomized", "triple_eagle_deterministic"],
)
def test_triple_eagle_filters_above_budget_sellers_before_singleton_choice(
    method_id: str,
) -> None:
    public = _additive(
        {"expensive": 100.0, "b": 2.0, "c": 1.0},
        {"expensive": "2", "b": "0.2", "c": "0.2"},
        budget="1",
    )

    outcome = build_registry().create(method_id).allocate(public, 0)

    assert "expensive" not in outcome.selected_ids
    assert outcome.diagnostics["above_budget_filtered"] == ["expensive"]


@pytest.mark.parametrize(
    "method_id",
    ["triple_eagle_randomized", "triple_eagle_deterministic"],
)
def test_triple_eagle_is_invariant_to_nonzero_utility_baseline(method_id: str) -> None:
    values = {"a": 3.0, "b": 2.0, "c": 1.0}
    costs = {"a": "0.01", "b": "0.01", "c": "0.01"}
    original = _additive(values, costs, budget="3")
    shifted = _additive(values, costs, budget="3", baseline=100.0)
    method = build_registry().create(method_id)

    original_outcome = method.allocate(original, 0)
    shifted_outcome = method.allocate(shifted, 0)

    assert shifted_outcome.selected_ids == original_outcome.selected_ids
    assert _payments(shifted_outcome) == _payments(original_outcome)


@pytest.mark.parametrize(
    "method_id",
    ["triple_eagle_randomized", "triple_eagle_deterministic"],
)
def test_triple_eagle_has_complete_ir_budget_feasible_offer_payments(method_id: str) -> None:
    public = _additive(
        {seller: 1.0 for seller in ("a", "b", "c", "d", "e")},
        {seller: "0.1" for seller in ("a", "b", "c", "d", "e")},
        budget="1",
    )

    outcome = build_registry().create(method_id).allocate(public, 0)
    payments = _payments(outcome)

    assert set(payments) == set(outcome.selected_ids)
    assert all(payments[seller] >= public.reported_costs[seller] for seller in outcome.selected_ids)
    assert sum(payments.values(), Decimal("0")) <= public.budget
    assert outcome.diagnostics["payment_semantics"] == "paper_clock_offer"
    assert outcome.diagnostics["utility_query_count"] <= 2 * len(public.seller_ids) + 2


def test_triple_eagle_default_provenance_is_paper_exact_and_source_bounded() -> None:
    catalog = load_provenance()

    for method_id in ("triple_eagle_randomized", "triple_eagle_deterministic"):
        record = catalog.mechanisms[method_id]
        assert record.family_id == "triple_eagle"
        assert record.provenance_kind == "paper_exact"
        assert record.deviations == ()
        assert record.primary_reference.reference_id == "triple_eagle"
        assert record.primary_reference.repository_url is None

    validate_provenance(build_registry(), catalog)


def test_triple_eagle_theorem_expectations_are_variant_scoped() -> None:
    expectations = {
        item.expectation_id: item
        for item in load_expectations()
        if item.family_id == "triple_eagle"
    }

    assert set(expectations) == {
        "triple-eagle-randomized-budget",
        "triple-eagle-randomized-ir",
        "triple-eagle-randomized-approximation",
        "triple-eagle-deterministic-budget",
        "triple-eagle-deterministic-ir",
        "triple-eagle-deterministic-approximation",
    }
    assert expectations["triple-eagle-randomized-approximation"].method_id == (
        "triple_eagle_randomized"
    )
    assert expectations["triple-eagle-randomized-approximation"].target == pytest.approx(
        2.0 / (math.sqrt(13.0) + 5.0)
    )
    assert expectations["triple-eagle-deterministic-approximation"].method_id == (
        "triple_eagle_deterministic"
    )
    assert expectations["triple-eagle-deterministic-approximation"].target == pytest.approx(
        1.0 / (2.0 + math.sqrt(6.0))
    )


def test_triple_eagle_value_oracle_query_cost_is_a_first_class_metric() -> None:
    case = next(
        item
        for item in build_cases()["procurement"]
        if item.case_id == "PSMOD-coverage-b50"
    )
    registry = build_registry()
    method = registry.create("triple_eagle_randomized")
    output = method.allocate(case.public, 0)
    oracle = registry.create("budget_optimum").allocate(case.public, 0)

    metrics = evaluate_procurement_metrics(case, output, method.spec, oracle)

    assert metrics["value_oracle_queries"].value == output.diagnostics[
        "utility_query_count"
    ]


def test_normalized_oracle_gain_ratio_removes_nonzero_ml_baseline() -> None:
    case = next(
        item
        for item in build_cases()["procurement"]
        if item.case_id == "PML-clean-b50"
    )
    registry = build_registry()
    method = registry.create("triple_eagle_deterministic")
    output = method.allocate(case.public, 0)
    oracle = registry.create("budget_optimum").allocate(case.public, 0)

    metrics = evaluate_procurement_metrics(case, output, method.spec, oracle)
    baseline = float(case.public.utility(()))
    realized = float(case.public.utility(output.selected_ids))
    optimum = float(case.public.utility(oracle.selected_ids))

    assert metrics["normalized_oracle_gain_ratio"].value == pytest.approx(
        (realized - baseline) / (optimum - baseline)
    )
    assert metrics["normalized_oracle_gain_ratio"].value < metrics[
        "oracle_ratio"
    ].value


def test_runner_preserves_triple_eagle_branch_audit_metadata() -> None:
    config = BenchmarkConfig(
        name="triple-eagle-audit-metadata",
        output_dir="unused",
        seeds=(0,),
        methods={
            "valuation": {},
            "procurement": {
                "budget_optimum": {},
                "triple_eagle_randomized": {},
            },
            "trading": {},
        },
        case_ids={
            "valuation": (),
            "procurement": ("PSMOD-coverage-b50",),
            "trading": (),
        },
        strategic_audit=False,
    )

    result = next(
        row
        for row in run_benchmark(config)
        if row.method_id == "triple_eagle_randomized"
    )

    assert result.metadata["mechanism_branch"] in {
        "lsd_suffix",
        "best_singleton",
        "best_effort",
    }
    assert result.metadata["utility_query_count"] == result.metrics[
        "value_oracle_queries"
    ].value
    assert isinstance(result.metadata["suffix_truncated"], bool)


def test_triple_eagle_extension_config_covers_four_procurement_settings() -> None:
    config = load_config("benchmark/configs/kdd_triple_eagle_extension.yaml")
    cases = {
        case.case_id: case
        for case in build_cases()["procurement"]
        if case.metadata.get("benchmark_setting")
        in {"P-ADDITIVE", "P-SUBMODULAR", "P-ML-ACQUISITION", "P-MARKET-CONCENTRATION"}
    }

    assert set(config.case_ids["procurement"]) == set(cases)
    assert set(config.methods["procurement"]) == {
        "budget_optimum",
        "triple_eagle_randomized",
        "triple_eagle_deterministic",
    }
    assert config.seeds == tuple(range(10))
    assert config.strategic_audit is True


def test_triple_eagle_baseline_completion_only_fills_missing_ml_cells() -> None:
    config = load_config(
        "benchmark/configs/kdd_triple_eagle_baseline_completion.yaml"
    )

    assert config.case_ids["procurement"] == (
        "PML-clean-b30",
        "PML-clean-b50",
        "PML-clean-b70",
    )
    assert set(config.methods["procurement"]) == {
        "budget_optimum",
        "generalized_proportional_share",
        "cgl_deterministic",
        "cgl_randomized",
        "jt_greedy_tm",
        "jt_random_tm",
        "jt_random_eom",
        "jt_deterministic_eom",
    }
    assert config.seeds == tuple(range(10))
