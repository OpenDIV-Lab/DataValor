from __future__ import annotations

from datamechbench.metrics import evaluate_valuation_metrics
from datamechbench.runner import build_cases, build_registry


def test_gradient_attribution_families_run_on_owner_data() -> None:
    case = next(case for case in build_cases()["valuation"] if case.case_id == "VCONT-breast_cancer")
    registry = build_registry()

    for method_id in ("tracin_cp", "gradient_cosine", "datainf"):
        method = registry.create(method_id, {})
        output = method.evaluate(case, seed=7)
        assert set(output.scores) == set(case.owner_ids)
        assert all(value == value for value in output.scores.values())
        metrics = evaluate_valuation_metrics(case, output)
        assert metrics["utility_recovery"].applicable
        assert metrics["utility_recovery"].value > 0


def test_muda_variants_are_feasible_double_auction_outcomes() -> None:
    case = next(
        case for case in build_cases()["trading"] if case.case_id == "TDOUBLE-n10-high"
    )
    registry = build_registry()

    for method_id in ("lottery_muda", "vickrey_muda"):
        method = registry.create(method_id, {})
        output = method.clear(case.public, seed=11)
        buyers = {allocation.actor_id for allocation in output.allocations}
        sellers = {allocation.counterparty_id for allocation in output.allocations}
        assert buyers <= set(case.public.buyer_ids)
        assert sellers <= set(case.public.seller_ids)
        assert len(buyers) == len(sellers)
        assert output.diagnostics["weak_budget_balance"] is True
        if method_id == "lottery_muda":
            assert output.diagnostics["strong_budget_balance"] is True
        else:
            assert output.diagnostics["auctioneer_surplus"] >= 0
