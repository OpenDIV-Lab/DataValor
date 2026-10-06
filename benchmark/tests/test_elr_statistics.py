from __future__ import annotations

import math

import pytest
from datamechbench.elr_statistics import (
    dataset_level_summary,
    paired_method_comparison,
    routing_summary,
    score_vector_metrics,
    summarize_cell,
)


def test_score_metrics_match_hand_computed_fixture() -> None:
    metrics = score_vector_metrics((1.0, 0.0, 4.0), (1.0, 2.0, 3.0))

    assert metrics["mae"] == pytest.approx(1.0)
    assert metrics["normalized_mae"] == pytest.approx(0.5)
    assert metrics["rmse"] == pytest.approx(math.sqrt(5 / 3))
    assert metrics["max_owner_error"] == pytest.approx(2.0)
    assert metrics["spearman"] == pytest.approx(0.5)
    assert metrics["ndcg"] == pytest.approx(0.9725044904464192)


def _row(dataset: str, method: str, seed: int, mae: float, status: str = "completed"):
    return {
        "dataset_id": dataset,
        "partition": "iid",
        "budget": 192,
        "method_id": method,
        "estimator_seed": seed,
        "mae": mae,
        "status": status,
    }


def test_paired_comparison_pairs_seeds_and_is_bootstrap_reproducible() -> None:
    rows = tuple(
        _row("a", method, seed, value)
        for method, values in (("ours", (0.5, 0.4, 0.3)), ("base", (1.0, 1.0, 1.0)))
        for seed, value in enumerate(values)
    )
    first = paired_method_comparison(rows, method_id="ours", baseline_id="base")
    second = paired_method_comparison(rows, method_id="ours", baseline_id="base")

    assert first == second
    assert first.paired_seeds == 3
    assert first.mean_mae_difference == pytest.approx(-0.6)
    assert first.wilcoxon_p_value == pytest.approx(0.25)
    assert first.cliffs_delta == pytest.approx(-1.0)
    assert first.outcome == "win"


def test_cell_and_dataset_aggregation_keep_na_coverage_and_dataset_units() -> None:
    rows = (
        _row("a", "ours", 0, 0.5),
        _row("a", "ours", 1, 0.7),
        _row("a", "base", 0, 1.0),
        _row("a", "base", 1, 1.0),
        _row("b", "ours", 0, 0.0, status="not_applicable"),
    )
    cell = summarize_cell(rows, dataset_id="a", partition="iid", budget=192, method_id="ours")
    aggregate = dataset_level_summary((cell,), baseline_medians={"a": 1.0})

    assert cell.seed_count == 2
    assert cell.median_mae == pytest.approx(0.6)
    assert aggregate.dataset_count == 1
    assert aggregate.geometric_mean_normalized_mae == pytest.approx(0.6)
    assert aggregate.inference_unit == "dataset"


def test_routing_summary_reports_accuracy_regret_disagreement_and_missingness() -> None:
    rows = (
        {"status": "completed", "selected_method": "a", "oracle_method": "a", "selected_mae": 0.4, "oracle_mae": 0.4, "probe_disagreement": False},
        {"status": "completed", "selected_method": "b", "oracle_method": "a", "selected_mae": 0.8, "oracle_mae": 0.5, "probe_disagreement": True},
        {"status": "not_applicable", "reason": "budget"},
    )
    summary = routing_summary(rows)

    assert summary.completed_cells == 2
    assert summary.not_applicable_cells == 1
    assert summary.routing_accuracy == pytest.approx(0.5)
    assert summary.mean_normalized_regret == pytest.approx(0.3)
    assert summary.disagreement_frequency == pytest.approx(0.5)
