from __future__ import annotations

from decimal import Decimal

import pytest
from datamechbench.data import make_procurement_cases
from datamechbench.methods.procurement import register_procurement_methods
from datamechbench.metrics import evaluate_procurement_metrics
from datamechbench.models import MarketOutcome, ProcurementInput
from datamechbench.registry import MethodRegistry, validate_output


@pytest.fixture
def registry():
    result = MethodRegistry()
    register_procurement_methods(result)
    return result


def _case(source: str, ratio: float):
    return next(
        case
        for case in make_procurement_cases(seed=42)
        if case.metadata["source_case_id"] == source
        and case.metadata["budget_ratio"] == ratio
    )


def test_procurement_methods_are_registered(registry):
    assert {spec.method_id for spec in registry.specs("procurement")} == {
        "cheapest_first",
        "marginal_utility_per_cost",
        "budget_optimum",
        "proportional_share",
        "public_value_first",
        "value_cost_greedy",
        "reverse_first_price",
        "reverse_second_price",
        "uniform_posted_offer",
        "value_scaled_posted_offer",
        "generalized_proportional_share",
        "cgl_deterministic",
        "cgl_randomized",
        "procurement_vcg",
        "jt_greedy_tm",
        "jt_random_tm",
        "jt_random_eom",
        "jt_deterministic_eom",
        "triple_eagle_randomized",
        "triple_eagle_deterministic",
        "bfm_vm",
    }


def test_budget_optimum_is_an_allocation_upper_bound(registry):
    case = _case("C-comp", 0.5)
    outputs = {
        method_id: registry.create(method_id).allocate(case.public, seed=0)
        for method_id in (
            "cheapest_first",
            "marginal_utility_per_cost",
            "budget_optimum",
            "proportional_share",
        )
    }
    for method_id, output in outputs.items():
        validate_output(registry.create(method_id).spec, case.public, output)

    optimum = case.public.utility(outputs["budget_optimum"].selected_ids)
    assert optimum >= case.public.utility(outputs["cheapest_first"].selected_ids)
    assert optimum >= case.public.utility(outputs["marginal_utility_per_cost"].selected_ids)


def test_payment_truthfulness_metrics_are_capability_routed(registry):
    case = _case("C-add", 0.5)
    oracle = registry.create("budget_optimum").allocate(case.public, 0)
    for method_id in ("cheapest_first", "marginal_utility_per_cost", "budget_optimum"):
        method = registry.create(method_id)
        output = method.allocate(case.public, 0)
        metrics = evaluate_procurement_metrics(case, output, method.spec, oracle)
        assert not metrics["seller_ir_violation_count"].applicable
        assert metrics["seller_ir_violation_count"].reason == "truthful_payments_unsupported"
        assert not metrics["max_deviation_gain"].applicable

    method = registry.create("proportional_share")
    output = method.allocate(case.public, 0)
    metrics = evaluate_procurement_metrics(case, output, method.spec, oracle)
    assert metrics["budget_violation"].value is False
    assert metrics["seller_ir_violation_count"].value == 0
    assert sum((payment.amount for payment in output.payments), Decimal("0")) <= case.public.budget


@pytest.mark.parametrize("source,metric", [("C-real-dup", "duplicate_spend_ratio"), ("C-real-noise", "noisy_spend_ratio")])
def test_real_procurement_reports_bad_bundle_spend(registry, source, metric):
    case = _case(source, 0.7)
    method = registry.create("marginal_utility_per_cost")
    output = method.allocate(case.public, 0)
    metrics = evaluate_procurement_metrics(case, output, method.spec)
    assert metrics[metric].applicable
    assert 0.0 <= metrics[metric].value <= 1.0


def test_duplicate_and_unknown_sellers_are_rejected(registry):
    case = _case("C-add", 0.3)
    with pytest.raises(ValueError, match="unique"):
        ProcurementInput(
            seller_ids=("o0", "o0"),
            reported_costs={"o0": Decimal("1")},
            budget=Decimal("2"),
            utility=case.public.utility,
        )
    with pytest.raises(ValueError, match="unknown selected"):
        validate_output(
            registry.create("budget_optimum").spec,
            case.public,
            MarketOutcome(selected_ids=("unknown",)),
        )
