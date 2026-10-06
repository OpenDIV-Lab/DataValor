from __future__ import annotations

from decimal import Decimal

import numpy as np
from datamechbench.metrics import evaluate_procurement_metrics
from datamechbench.models import ProcurementInput
from datamechbench.provenance import load_provenance
from datamechbench.runner import build_registry
from datamechbench.settings.procurement import make_procurement_additive_cases


def _additive_public(
    values: dict[str, float],
    *,
    costs: dict[str, str],
    budget: str,
) -> ProcurementInput:
    return ProcurementInput(
        seller_ids=tuple(values),
        reported_costs={seller: Decimal(costs[seller]) for seller in values},
        budget=Decimal(budget),
        utility=lambda selected: float(sum(values[seller] for seller in set(selected))),
        seller_values=values,
    )


def test_budget_oracle_is_exact_on_additive_instances() -> None:
    case = make_procurement_additive_cases(2)[0]
    registry = build_registry()
    oracle = registry.create("budget_optimum").allocate(case.public, 0)

    assert case.public.utility(oracle.selected_ids) == case.metadata["exact_opt_utility"]


def test_procurement_metrics_report_economic_surplus() -> None:
    case = make_procurement_additive_cases(4)[0]
    registry = build_registry()
    method = registry.create("generalized_proportional_share")
    oracle = registry.create("budget_optimum").allocate(case.public, 0)
    output = method.allocate(case.public, 0)

    metrics = evaluate_procurement_metrics(
        case, output, method.spec, oracle, method=method, seed=0
    )

    assert metrics["buyer_utility"].applicable
    assert metrics["seller_surplus"].applicable
    assert metrics["allocation_monotonicity_violation"].applicable
    assert metrics["critical_payment_gap"].applicable


def test_generalized_proportional_share_matches_singer_additive_core() -> None:
    public = _additive_public(
        {"a": 6.0, "b": 3.0, "c": 1.0},
        costs={"a": "2", "b": "2", "c": "2"},
        budget="6",
    )

    outcome = build_registry().create("generalized_proportional_share").allocate(
        public, seed=0
    )
    payments = {payment.payee_id: payment.amount for payment in outcome.payments}

    assert outcome.selected_ids == ("a", "b")
    assert abs(payments["a"] - Decimal("4")) <= Decimal("1e-12")
    assert abs(payments["b"] - Decimal("2")) <= Decimal("1e-12")
    assert outcome.diagnostics["budget_feasible"] is True


def test_generalized_proportional_share_declares_missing_full_singer_mechanism() -> None:
    record = load_provenance().mechanisms["generalized_proportional_share"]

    assert record.provenance_kind == "paper_variant"
    assert record.deviations == (
        "proportional-share allocation/payment core only; Singer singleton mixture, modified mechanism, and budget scaling omitted",
    )


def test_source_audited_procurement_mechanisms_are_labeled_paper_exact() -> None:
    catalog = load_provenance()

    for method_id in (
        "cgl_deterministic",
        "cgl_randomized",
        "jt_greedy_tm",
        "jt_random_tm",
        "jt_random_eom",
        "jt_deterministic_eom",
    ):
        record = catalog.mechanisms[method_id]
        assert record.provenance_kind == "paper_exact"
        assert record.deviations == ()


def test_cgl_deterministic_uses_paper_singleton_branch_and_threshold_payment() -> None:
    public = _additive_public(
        {"a": 10.0, "b": 1.0, "c": 1.0},
        costs={"a": "1", "b": "1", "c": "1"},
        budget="2",
    )

    outcome = build_registry().create("cgl_deterministic").allocate(public, seed=0)

    assert outcome.selected_ids == ("a",)
    assert outcome.diagnostics["allocation_rule"] == "CGL-Mechanism-SM"
    assert outcome.diagnostics["mechanism_branch"] == "best_singleton"
    assert outcome.payments[0].amount == public.budget


def test_cgl_deterministic_uses_paper_greedy_sm_branch() -> None:
    values = {f"s{i}": 1.0 for i in range(10)}
    public = _additive_public(
        values,
        costs={seller: "0.5" for seller in values},
        budget="10",
    )

    outcome = build_registry().create("cgl_deterministic").allocate(public, seed=0)

    assert outcome.selected_ids == tuple(values)
    assert outcome.diagnostics["mechanism_branch"] == "greedy_sm"
    assert outcome.diagnostics["greedy_budget_fraction"] == "0.5"


def test_cgl_random_sm_uses_paper_three_fifths_mixture() -> None:
    public = _additive_public(
        {"a": 1.0, "b": 1.0, "c": 1.0},
        costs={"a": "0.2", "b": "0.2", "c": "0.2"},
        budget="4",
    )
    method = build_registry().create("cgl_randomized")

    singleton = method.allocate(public, seed=0)  # draw 0.6369... >= 3/5
    greedy = method.allocate(public, seed=1)  # draw 0.5118... < 3/5

    assert singleton.selected_ids == ("a",)
    assert singleton.diagnostics["mixture_branch"] == "best_singleton"
    assert greedy.selected_ids == ("a", "b", "c")
    assert greedy.diagnostics["mixture_branch"] == "greedy_sm"
    assert greedy.diagnostics["greedy_probability"] == 0.6


def test_cgl_random_sm_seeded_branch_frequency_matches_paper_probability() -> None:
    public = _additive_public(
        {"a": 1.0, "b": 1.0},
        costs={"a": "0.2", "b": "0.2"},
        budget="2",
    )
    method = build_registry().create("cgl_randomized")
    seeds = range(100)
    expected = sum(np.random.default_rng(seed).random() < 0.6 for seed in seeds)

    observed = sum(
        method.allocate(public, seed).diagnostics["mixture_branch"] == "greedy_sm"
        for seed in seeds
    )

    assert observed == expected


def test_cgl_excludes_above_budget_seller_before_singleton_choice() -> None:
    public = _additive_public(
        {"expensive": 100.0, "b": 1.0, "c": 1.0},
        costs={"expensive": "3", "b": "1", "c": "1"},
        budget="2",
    )

    deterministic = build_registry().create("cgl_deterministic").allocate(public, seed=0)
    randomized_singleton = build_registry().create("cgl_randomized").allocate(public, seed=0)

    assert deterministic.selected_ids == ("b",)
    assert randomized_singleton.selected_ids == ("b",)


def test_cgl_deterministic_payment_is_threshold_of_complete_branch_rule() -> None:
    values = {f"s{i}": 1.0 for i in range(9)}
    public = _additive_public(
        values,
        costs={seller: "0.2" for seller in values},
        budget="9",
    )
    method = build_registry().create("cgl_deterministic")
    outcome = method.allocate(public, seed=0)
    winner = outcome.selected_ids[-1]
    threshold = next(
        payment.amount for payment in outcome.payments if payment.payee_id == winner
    )
    epsilon = Decimal("1e-10")

    below = _additive_public(
        values,
        costs={
            seller: str(
                max(Decimal("0"), threshold - epsilon)
                if seller == winner
                else public.reported_costs[seller]
            )
            for seller in values
        },
        budget="9",
    )
    above = _additive_public(
        values,
        costs={
            seller: str(
                threshold + epsilon
                if seller == winner
                else public.reported_costs[seller]
            )
            for seller in values
        },
        budget="9",
    )

    assert winner in method.allocate(below, seed=0).selected_ids
    assert winner not in method.allocate(above, seed=0).selected_ids


def test_cgl_deterministic_normalizes_nonzero_empty_set_utility() -> None:
    values = {f"s{i}": 1.0 for i in range(9)}
    costs = {seller: Decimal("0.2") for seller in values}

    def shifted_utility(selected) -> float:
        return 100.0 + sum(values[seller] for seller in set(selected))

    public = ProcurementInput(
        seller_ids=tuple(values),
        reported_costs=costs,
        budget=Decimal("9"),
        utility=shifted_utility,
        seller_values=values,
    )

    outcome = build_registry().create("cgl_deterministic").allocate(public, seed=0)

    assert outcome.diagnostics["mechanism_branch"] == "greedy_sm"
    assert outcome.selected_ids == tuple(values)
