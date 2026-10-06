from __future__ import annotations

import math
from decimal import Decimal

import pytest
from datamechbench.metrics import evaluate_procurement_metrics
from datamechbench.models import ProcurementInput
from datamechbench.runner import build_registry
from datamechbench.settings import procurement as procurement_settings


def _public(values: dict[str, float], budget: str, cost: str = "0.2") -> ProcurementInput:
    return ProcurementInput(
        seller_ids=tuple(values),
        reported_costs={seller: Decimal(cost) for seller in values},
        budget=Decimal(budget),
        utility=lambda selected: float(sum(values[item] for item in set(selected))),
        seller_values=values,
    )


def test_greedy_tm_uses_paper_threshold_stopping_rule() -> None:
    public = ProcurementInput(
        seller_ids=("a", "b", "c"),
        reported_costs={item: Decimal("1") for item in ("a", "b", "c")},
        budget=Decimal("3"),
        utility=lambda selected: sum({"a": 3.0, "b": 2.0, "c": 1.0}[item] for item in set(selected)),
        seller_values={"a": 3.0, "b": 2.0, "c": 1.0},
    )

    outcome = build_registry().create("jt_greedy_tm").allocate(public, seed=0)

    assert outcome.selected_ids == ("a",)
    assert outcome.diagnostics["gamma"] == 0.5


def test_greedy_tm_matches_paper_tight_additive_example() -> None:
    epsilon = 1e-6
    values = {"s0": 1.0, **{f"s{i}": 1.0 - epsilon for i in range(1, 5)}}
    public = ProcurementInput(
        seller_ids=tuple(values),
        reported_costs={"s0": Decimal("0"), **{f"s{i}": Decimal("1") for i in range(1, 5)}},
        budget=Decimal("4"),
        utility=lambda selected: float(sum(values[item] for item in set(selected))),
        seller_values=values,
    )

    outcome = build_registry().create("jt_greedy_tm").allocate(public, seed=0)

    assert outcome.selected_ids == ("s0",)


def test_random_tm_fixes_the_paper_mixture_branch_from_seed() -> None:
    public = _public({"a": 1.0, "b": 1.0, "c": 1.0}, "4")
    method = build_registry().create("jt_random_tm")

    singleton = method.allocate(public, seed=0)
    greedy = method.allocate(public, seed=1)

    assert singleton.selected_ids == ("a",)
    assert singleton.diagnostics["mixture_branch"] == "best_singleton"
    assert greedy.selected_ids == ("a", "b", "c")
    assert greedy.diagnostics["mixture_branch"] == "greedy_tm"


def test_eom_variants_cover_singleton_and_exact_oracle_branches() -> None:
    singleton_public = _public({"a": 10.0, "b": 1.0, "c": 1.0}, "2", "1")
    balanced_public = _public(
        {item: 1.0 for item in ("a", "b", "c", "d", "e", "f")},
        "6",
        "1",
    )
    registry = build_registry()

    deterministic_singleton = registry.create("jt_deterministic_eom").allocate(
        singleton_public, seed=0
    )
    deterministic_greedy = registry.create("jt_deterministic_eom").allocate(
        balanced_public, seed=0
    )
    random_singleton = registry.create("jt_random_eom").allocate(
        balanced_public, seed=0
    )
    random_greedy = registry.create("jt_random_eom").allocate(
        balanced_public, seed=2
    )

    assert deterministic_singleton.selected_ids == ("a",)
    assert deterministic_singleton.diagnostics["eom_branch"] == "best_singleton"
    assert len(deterministic_greedy.selected_ids) == 3
    assert deterministic_greedy.diagnostics["eom_branch"] == "greedy_eom"
    assert random_singleton.diagnostics["mixture_branch"] == "best_singleton"
    assert random_greedy.diagnostics["mixture_branch"] == "greedy_eom"
    assert random_singleton.diagnostics["greedy_probability"] == 0.5
    assert random_greedy.diagnostics["greedy_probability"] == 0.5


def test_deterministic_eom_uses_published_branch_constant_near_boundary() -> None:
    boundary = (math.sqrt(17.0) - 3.0) / 4.0
    below = _public({"a": 1.1, "b": 1.0, "c": 1.0, "d": 1.0, "e": 1.0}, "5", "1")
    above = _public({"a": 1.2, "b": 1.0, "c": 1.0, "d": 1.0, "e": 1.0}, "5", "1")
    method = build_registry().create("jt_deterministic_eom")

    below_outcome = method.allocate(below, seed=0)
    above_outcome = method.allocate(above, seed=0)

    assert 1.1 < boundary * 4.0
    assert 1.2 >= boundary * 4.0
    assert below_outcome.diagnostics["eom_branch"] == "greedy_eom"
    assert above_outcome.selected_ids == ("a",)
    assert above_outcome.diagnostics["eom_branch"] == "best_singleton"


def test_deterministic_eom_is_invariant_to_nonzero_utility_baseline() -> None:
    values = {item: 1.0 for item in ("a", "b", "c", "d", "e", "f")}
    public = ProcurementInput(
        seller_ids=tuple(values),
        reported_costs={item: Decimal("1") for item in values},
        budget=Decimal("6"),
        utility=lambda selected: 100.0 + sum(values[item] for item in set(selected)),
        seller_values=values,
    )

    outcome = build_registry().create("jt_deterministic_eom").allocate(public, seed=0)

    assert outcome.diagnostics["eom_branch"] == "greedy_eom"
    assert len(outcome.selected_ids) == 3


@pytest.mark.parametrize(
    ("method_id", "seed"),
    [("jt_greedy_tm", 0), ("jt_random_eom", 2), ("jt_deterministic_eom", 0)],
)
def test_jalaly_tardos_winner_payment_is_critical_threshold(
    method_id: str,
    seed: int,
) -> None:
    public = _public({item: 1.0 for item in ("a", "b", "c", "d", "e", "f")}, "6", "1")
    method = build_registry().create(method_id)
    outcome = method.allocate(public, seed)
    payments = {payment.payee_id: payment.amount for payment in outcome.payments}
    epsilon = Decimal("1e-10")

    for winner in outcome.selected_ids:
        threshold = payments[winner]
        below = ProcurementInput(
            seller_ids=public.seller_ids,
            reported_costs={**public.reported_costs, winner: max(Decimal("0"), threshold - epsilon)},
            budget=public.budget,
            utility=public.utility,
            seller_values=public.seller_values,
        )
        above = ProcurementInput(
            seller_ids=public.seller_ids,
            reported_costs={**public.reported_costs, winner: threshold + epsilon},
            budget=public.budget,
            utility=public.utility,
            seller_values=public.seller_values,
        )

        assert winner in method.allocate(below, seed).selected_ids
        assert winner not in method.allocate(above, seed).selected_ids


@pytest.mark.parametrize(
    "method_id",
    ["jt_greedy_tm", "jt_random_tm", "jt_random_eom", "jt_deterministic_eom"],
)
def test_jalaly_tardos_threshold_payments_are_budget_feasible_and_monotone(
    method_id: str,
) -> None:
    public = _public({item: 1.0 for item in ("a", "b", "c", "d", "e", "f")}, "6", "1")
    method = build_registry().create(method_id)
    outcome = method.allocate(public, seed=2)
    assert sum((payment.amount for payment in outcome.payments), Decimal("0")) <= public.budget
    for winner in outcome.selected_ids:
        lowered = ProcurementInput(
            seller_ids=public.seller_ids,
            reported_costs={**public.reported_costs, winner: Decimal("0.5")},
            budget=public.budget,
            utility=public.utility,
            seller_values=public.seller_values,
        )
        assert winner in method.allocate(lowered, seed=2).selected_ids


def test_market_concentration_cases_and_metrics_expose_difficulty_axis() -> None:
    assert hasattr(procurement_settings, "make_procurement_concentration_cases")
    cases = procurement_settings.make_procurement_concentration_cases(seed=7)
    assert len(cases) == 20
    assert {case.metadata["concentration_level"] for case in cases} == {
        "diffuse", "low", "moderate", "high", "dominant"
    }
    assert len({round(case.metadata["largest_singleton_share"], 3) for case in cases}) >= 5
    assert all(case.metadata["benchmark_setting"] == "P-MARKET-CONCENTRATION" for case in cases)

    case = cases[0]
    registry = build_registry()
    oracle = registry.create("budget_optimum").allocate(case.public, 0)
    method = registry.create("jt_greedy_tm")
    output = method.allocate(case.public, 0)
    metrics = evaluate_procurement_metrics(case, output, method.spec, oracle)
    assert metrics["procurement_efficiency_loss"].value == pytest.approx(
        1.0 - metrics["oracle_ratio"].value
    )
    assert metrics["largest_singleton_share"].value == pytest.approx(
        case.metadata["largest_singleton_share"]
    )


def test_eom_reuses_fixed_subset_utilities_during_threshold_search() -> None:
    calls = 0
    values = {item: 1.0 for item in ("a", "b", "c", "d", "e", "f")}

    def utility(selected):
        nonlocal calls
        calls += 1
        return float(sum(values[item] for item in set(selected)))

    public = ProcurementInput(
        seller_ids=tuple(values),
        reported_costs={item: Decimal("1") for item in values},
        budget=Decimal("6"),
        utility=utility,
        seller_values=values,
    )

    build_registry().create("jt_random_eom").allocate(public, seed=2)

    assert calls < 5_000
