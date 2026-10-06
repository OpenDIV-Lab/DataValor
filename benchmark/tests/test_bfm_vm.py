from __future__ import annotations

from decimal import Decimal

from datamechbench.methods.bfm_vm import allocate_bfm_vm
from datamechbench.metrics import evaluate_procurement_metrics
from datamechbench.models import ProcurementCase, ProcurementInput
from datamechbench.runner import build_registry


def _additive_case(
    values: dict[str, float],
    costs: dict[str, str],
    *,
    budget: str = "10",
) -> ProcurementInput:
    sellers = tuple(values)

    def utility(selected: tuple[str, ...]) -> float:
        return sum(values[seller] for seller in selected)

    return ProcurementInput(
        seller_ids=sellers,
        reported_costs={seller: Decimal(costs[seller]) for seller in sellers},
        budget=Decimal(budget),
        utility=utility,
        seller_values=values,
    )


def test_bfm_vm_matches_hand_derived_two_round_fixture() -> None:
    """Catches a wrong threshold update, candidate order, or terminal tie-break."""

    case = _additive_case(
        {"a": 6.0, "b": 4.0, "c": 2.0},
        {"a": "1", "b": "1", "c": "1"},
    )

    outcome = allocate_bfm_vm(case)

    assert outcome.selected_ids == ("a",)
    assert [(payment.payee_id, payment.amount) for payment in outcome.payments] == [
        ("a", Decimal("10"))
    ]
    assert outcome.diagnostics["round_count"] == 2
    assert outcome.diagnostics["budget_feasible"] is True


def test_bfm_vm_best_singleton_is_restricted_to_budget_accepting_sellers() -> None:
    """Catches the author-source bug that initializes from all sellers, not R."""

    case = _additive_case(
        {"ineligible_high": 100.0, "eligible": 10.0},
        {"ineligible_high": "11", "eligible": "1"},
    )

    outcome = allocate_bfm_vm(case)

    assert outcome.selected_ids == ("eligible",)
    assert outcome.diagnostics["eligible_sellers"] == ["eligible"]
    assert outcome.diagnostics["above_budget_filtered"] == ["ineligible_high"]


def test_bfm_vm_empty_eligible_set_returns_auditable_empty_outcome() -> None:
    """Catches division by zero or selection of an ineligible seller."""

    case = _additive_case(
        {"a": 5.0, "b": 4.0},
        {"a": "11", "b": "12"},
    )

    outcome = allocate_bfm_vm(case)

    assert outcome.selected_ids == ()
    assert outcome.payments == ()
    assert outcome.diagnostics["mechanism_branch"] == "empty_eligible_set"
    assert outcome.diagnostics["budget_feasible"] is True


def test_bfm_vm_is_registered_as_paper_exact_procurement_method() -> None:
    """Catches a paper implementation that cannot be scheduled by the runner."""

    spec = build_registry().create("bfm_vm").spec

    assert spec.family_id == "bfm_vm"
    assert spec.track == "procurement"
    assert spec.stochastic is False
    assert {"allocations", "payments", "truthful_payments"} <= spec.capabilities


def test_bfm_vm_exposes_oracle_query_count_to_the_metric_contract() -> None:
    """Catches diagnostic-key drift that makes compute cost silently N/A."""

    public = _additive_case(
        {"a": 6.0, "b": 4.0, "c": 2.0},
        {"a": "1", "b": "1", "c": "1"},
    )
    case = ProcurementCase(
        "fixture",
        public,
        true_costs=public.reported_costs,
        case_type="analytic",
    )
    method = build_registry().create("bfm_vm")
    outcome = method.allocate(public, seed=0)

    metric = evaluate_procurement_metrics(
        case,
        outcome,
        method.spec,
        oracle_output=outcome,
    )["value_oracle_queries"]

    assert metric.applicable is True
    assert metric.value == outcome.diagnostics["utility_query_count"]
