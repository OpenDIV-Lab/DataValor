from __future__ import annotations

from decimal import Decimal

from datamechbench.data import make_procurement_cases
from datamechbench.models import ProcurementInput
from datamechbench.runner import build_registry
from datamechbench.settings import procurement as procurement_settings

EXPECTED_METHODS = {
    "cheapest_first",
    "public_value_first",
    "value_cost_greedy",
    "marginal_utility_per_cost",
    "budget_optimum",
    "reverse_first_price",
    "reverse_second_price",
    "uniform_posted_offer",
    "value_scaled_posted_offer",
    "proportional_share",
    "generalized_proportional_share",
    "cgl_deterministic",
    "cgl_randomized",
    "procurement_vcg",
    "jt_greedy_tm",
    "jt_random_tm",
    "jt_random_eom",
    "jt_deterministic_eom",
    "bfm_vm",
    "triple_eagle_randomized",
    "triple_eagle_deterministic",
}
EXPECTED_FAMILIES = (
    EXPECTED_METHODS
    - {"triple_eagle_randomized", "triple_eagle_deterministic"}
) | {"triple_eagle"}


def test_concentration_case_bank_spans_value_and_budget_axes() -> None:
    cases = procurement_settings.make_procurement_concentration_cases(seed=9)

    assert len(cases) == 20
    assert len({case.case_id for case in cases}) == 20
    assert {case.metadata["concentration_level"] for case in cases} == {
        "diffuse",
        "low",
        "moderate",
        "high",
        "dominant",
    }
    assert {case.metadata["budget_item_count"] for case in cases} == {2, 3, 4, 5}
    assert {
        "PCONC-diffuse-b3",
        "PCONC-diffuse-b5",
        "PCONC-moderate-b3",
        "PCONC-moderate-b5",
        "PCONC-dominant-b3",
        "PCONC-dominant-b5",
    } <= {case.case_id for case in cases}

    order = {
        name: index
        for index, name in enumerate(
            ("diffuse", "low", "moderate", "high", "dominant")
        )
    }
    for budget_count in (2, 3, 4, 5):
        shares = [
            case.metadata["largest_singleton_share"]
            for case in sorted(
                (
                    item
                    for item in cases
                    if item.metadata["budget_item_count"] == budget_count
                ),
                key=lambda item: order[item.metadata["concentration_level"]],
            )
        ]
        assert all(left < right for left, right in zip(shares, shares[1:]))


def test_procurement_has_twenty_families_and_dense_settings():
    registry = build_registry()
    native = {spec.family_id for spec in registry.specs("procurement")}

    assert native == EXPECTED_FAMILIES
    assert len(registry.compatible("procurement", "analytic")) == 21
    assert len(registry.compatible("procurement", "submodular")) >= 20
    assert len(registry.compatible("procurement", "real_owner_data")) >= 13


def test_procurement_cases_include_weighted_coverage_setting():
    coverage = [
        case
        for case in make_procurement_cases()
        if case.case_type == "submodular" and not case.metadata.get("pilot", False)
    ]

    assert len(coverage) == 3
    case = coverage[1]
    assert case.metadata["utility_class"] == "monotone_submodular_coverage"
    assert case.metadata["dataset_id"] == "sklearn-breast-cancer-wisconsin-diagnostic"
    assert case.public.metadata["coverage_construction"] == "label_feature_quantile_cells"
    assert case.public.utility(()) == 0.0
    assert case.public.utility(case.public.seller_ids) > max(case.public.seller_values.values())


def _additive_case() -> ProcurementInput:
    values = {"s0": 9.0, "s1": 6.0, "s2": 4.0, "s3": 2.0}
    return ProcurementInput(
        seller_ids=tuple(values),
        reported_costs={
            "s0": Decimal("3"),
            "s1": Decimal("2"),
            "s2": Decimal("2"),
            "s3": Decimal("1"),
        },
        budget=Decimal("6"),
        utility=lambda selected: sum(values[item] for item in set(selected)),
        seller_values=values,
    )


def test_budget_feasible_mechanisms_respect_budget_and_seller_ir():
    registry = build_registry()
    case = _additive_case()
    method_ids = EXPECTED_METHODS - {"budget_optimum", "procurement_vcg"}

    for method_id in sorted(method_ids):
        outcome = registry.create(method_id).allocate(case, seed=5)
        total = sum(
            (payment.amount for payment in outcome.payments if payment.payer_id == "buyer"),
            Decimal("0"),
        )
        assert total <= case.budget, method_id
        paid = {payment.payee_id: payment.amount for payment in outcome.payments}
        for seller in outcome.selected_ids:
            assert paid[seller] >= case.reported_costs[seller], method_id


def test_threshold_mechanisms_keep_winner_after_lower_cost_report():
    registry = build_registry()
    truthful = _additive_case()
    for method_id in ("generalized_proportional_share", "cgl_deterministic"):
        method = registry.create(method_id)
        outcome = method.allocate(truthful, seed=0)
        winner = outcome.selected_ids[0]
        lowered = ProcurementInput(
            seller_ids=truthful.seller_ids,
            reported_costs={
                **truthful.reported_costs,
                winner: truthful.reported_costs[winner] / Decimal("2"),
            },
            budget=truthful.budget,
            utility=truthful.utility,
            seller_values=truthful.seller_values,
        )

        assert winner in method.allocate(lowered, seed=0).selected_ids


def test_procurement_vcg_exposes_budget_violation():
    registry = build_registry()
    case = ProcurementInput(
        seller_ids=("s0", "s1"),
        reported_costs={"s0": Decimal("0.5"), "s1": Decimal("0.5")},
        budget=Decimal("1"),
        utility=lambda selected: 10.0 * len(set(selected)),
        seller_values={"s0": 10.0, "s1": 10.0},
    )

    outcome = registry.create("procurement_vcg").allocate(case, seed=0)
    total = sum((payment.amount for payment in outcome.payments), Decimal("0"))

    assert total > case.budget
    assert outcome.diagnostics["budget_feasible"] is False
