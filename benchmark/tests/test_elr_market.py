from __future__ import annotations

import pytest
from datamechbench.coalition_games import CoalitionGameTable
from datamechbench.elr_market import (
    build_owner_costs,
    evaluate_knapsack,
    evaluate_market_consequences,
    evaluate_sequential,
    evaluate_top_k,
)


def _game() -> CoalitionGameTable:
    owners = ("a", "b", "c")
    weights = (6.0, 4.0, 2.0)
    return CoalitionGameTable(
        owners,
        {
            mask: sum(weight for index, weight in enumerate(weights) if mask & (1 << index))
            for mask in range(8)
        },
        "high",
    )


def test_owner_costs_depend_only_on_rows_unit_cost_and_owner_tie_break() -> None:
    counts = {"b": 20, "a": 10, "c": 20}
    first = build_owner_costs(counts, unit_cost=0.5)
    second = build_owner_costs(counts, unit_cost=0.5)

    assert first == second == {"a": 5.0, "b": 10.0, "c": 10.0}


def test_top_k_and_knapsack_use_exact_game_for_realized_regret() -> None:
    game = _game()
    estimated = {"a": 2.0, "b": 4.0, "c": 6.0}
    truth = {"a": 6.0, "b": 4.0, "c": 2.0}
    costs = {owner: 1.0 for owner in game.owner_ids}

    top = evaluate_top_k(game, estimated, truth, k=1)
    assert top.selected_ids == ("c",)
    assert top.oracle_ids == ("a",)
    assert top.exact_utility_regret == pytest.approx(4.0)
    assert top.selected_owner_disagreement == 2

    procurement = evaluate_knapsack(game, estimated, costs, budget_fraction=0.5)
    assert procurement.selected_ids == ("c",)
    assert procurement.oracle_ids == ("a",)
    assert procurement.exact_utility_regret == pytest.approx(4.0)
    assert procurement.budget_violation == pytest.approx(0.0)


def test_sequential_stopping_and_complete_market_report_are_predeclared() -> None:
    game = _game()
    estimated = {"a": 2.0, "b": 4.0, "c": 6.0}
    truth = {"a": 6.0, "b": 4.0, "c": 2.0}
    costs = {owner: 1.0 for owner in game.owner_ids}

    sequential = evaluate_sequential(game, estimated, truth, target_fraction=0.5)
    assert sequential.stop_index == 2
    assert sequential.oracle_stop_index == 1
    assert sequential.stopping_regret == 1

    report = evaluate_market_consequences(game, estimated, truth, costs)
    assert set(report.top_k) == {1, 2, 3}
    assert set(report.knapsack) == {0.25, 0.5, 0.75}
    assert set(report.sequential) == {0.5, 0.8}
    assert report.revenue_conservation_error == pytest.approx(0.0)
    assert -1.0 <= report.rank_stability <= 1.0
