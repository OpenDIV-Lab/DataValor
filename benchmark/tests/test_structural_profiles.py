from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest
from datamechbench.metrics import MetricValue
from datamechbench.models import BenchmarkResult
from datamechbench.structural_profiles import (
    structural_curve_points,
    summarize_structural_profiles,
)


def _result(
    family: str,
    case_id: str,
    value: float,
    *,
    setting: str,
    seed: int = 0,
    **axis_metadata,
) -> BenchmarkResult:
    track = {
        "V-REPLICATION-ROBUSTNESS": "valuation",
        "P-MARKET-CONCENTRATION": "procurement",
        "T-MARKET-THICKNESS": "trading",
    }[setting]
    metric = {
        "valuation": "replication_owner_rank_change",
        "procurement": "oracle_ratio",
        "trading": "gain_from_trade_ratio",
    }[track]
    return BenchmarkResult(
        run_id=f"{family}-{case_id}-{seed}",
        track=track,
        method_id=family,
        case_id=case_id,
        seed=seed,
        status="completed",
        metrics={metric: MetricValue(value)},
        runtime_seconds=0.01,
        metadata={
            "method_family": family,
            "method_role": "method",
            "implementation_kind": "native",
            "provenance_kind": "paper_exact",
            "benchmark_setting": setting,
            "pilot": False,
            "primary_metric_eligible": True,
            **axis_metadata,
        },
    )


def test_structural_profile_macro_averages_blocks_and_seed_averaged_cases() -> None:
    rows = (
        _result("a", "b2-low", 0.7, setting="P-MARKET-CONCENTRATION", seed=0, budget_item_count=2, largest_singleton_share=0.2),
        _result("a", "b2-low", 0.9, setting="P-MARKET-CONCENTRATION", seed=1, budget_item_count=2, largest_singleton_share=0.2),
        _result("a", "b2-high", 0.6, setting="P-MARKET-CONCENTRATION", budget_item_count=2, largest_singleton_share=0.8),
        _result("a", "b3-low", 0.9, setting="P-MARKET-CONCENTRATION", budget_item_count=3, largest_singleton_share=0.2),
        _result("a", "b3-high", 0.7, setting="P-MARKET-CONCENTRATION", budget_item_count=3, largest_singleton_share=0.8),
        _result("b", "b2-low", 0.5, setting="P-MARKET-CONCENTRATION", budget_item_count=2, largest_singleton_share=0.2),
        _result("b", "b2-high", 0.5, setting="P-MARKET-CONCENTRATION", budget_item_count=2, largest_singleton_share=0.8),
    )

    points = structural_curve_points(rows)
    profiles = {row.family_id: row for row in summarize_structural_profiles(rows)}

    assert len([point for point in points if point.family_id == "a"]) == 4
    low = next(point for point in points if point.family_id == "a" and point.case_id == "b2-low")
    assert low.primary_value == pytest.approx(0.8)
    assert low.normalized_axis == pytest.approx(0.0)

    a = profiles["a"]
    assert a.case_count == 4
    assert a.observation_count == 5
    assert a.block_count == a.expected_block_count == 2
    assert a.coverage_ratio == 1.0
    assert a.mean_primary == pytest.approx(0.75)
    assert a.worst_case_primary == pytest.approx(0.6)
    assert a.oriented_axis_auc == pytest.approx(0.75)
    assert a.oriented_slope == pytest.approx(-0.2)
    assert a.oriented_endpoint_change == pytest.approx(-0.2)
    assert a.nondegradation_rate == pytest.approx(0.0)

    b = profiles["b"]
    assert b.block_count == 1
    assert b.expected_block_count == 2
    assert b.coverage_ratio == pytest.approx(0.5)


def test_minimize_metric_is_oriented_so_negative_slope_means_degradation() -> None:
    rows = (
        _result("v", "c2", 0.1, setting="V-REPLICATION-ROBUSTNESS", replication_group_id="dataset-owner", replication_factor=2),
        _result("v", "c4", 0.3, setting="V-REPLICATION-ROBUSTNESS", replication_group_id="dataset-owner", replication_factor=4),
    )

    (profile,) = summarize_structural_profiles(rows)

    assert profile.direction == "minimize"
    assert profile.mean_primary == pytest.approx(0.2)
    assert profile.worst_case_primary == pytest.approx(0.3)
    assert profile.oriented_axis_auc == pytest.approx(-0.2)
    assert profile.oriented_slope == pytest.approx(-0.2)
    assert profile.oriented_endpoint_change == pytest.approx(-0.2)
    assert profile.nondegradation_rate == pytest.approx(0.0)


def test_profile_summary_supports_the_declared_numpy_124_floor(monkeypatch) -> None:
    rows = (
        _result("p", "low", 0.7, setting="P-MARKET-CONCENTRATION", budget_item_count=2, largest_singleton_share=0.2),
        _result("p", "high", 0.5, setting="P-MARKET-CONCENTRATION", budget_item_count=2, largest_singleton_share=0.8),
    )
    monkeypatch.delattr(np, "trapezoid")

    (profile,) = summarize_structural_profiles(rows)

    assert profile.oriented_axis_auc == pytest.approx(0.6)


def test_profile_coverage_counts_blocks_with_only_skipped_results() -> None:
    completed = (
        _result("p", "b2-low", 0.7, setting="P-MARKET-CONCENTRATION", budget_item_count=2, largest_singleton_share=0.2),
        _result("p", "b2-high", 0.5, setting="P-MARKET-CONCENTRATION", budget_item_count=2, largest_singleton_share=0.8),
    )
    skipped = tuple(
        replace(row, status="skipped", metrics={}, error="adapter unavailable")
        for row in (
            _result("p", "b3-low", 0.7, setting="P-MARKET-CONCENTRATION", budget_item_count=3, largest_singleton_share=0.2),
            _result("p", "b3-high", 0.5, setting="P-MARKET-CONCENTRATION", budget_item_count=3, largest_singleton_share=0.8),
        )
    )

    (profile,) = summarize_structural_profiles(completed + skipped)

    assert profile.block_count == 1
    assert profile.expected_block_count == 2
    assert profile.coverage_ratio == pytest.approx(0.5)


def test_conflicting_case_axis_metadata_is_rejected() -> None:
    rows = (
        _result("a", "same", 0.7, setting="P-MARKET-CONCENTRATION", budget_item_count=2, largest_singleton_share=0.2),
        _result("b", "same", 0.7, setting="P-MARKET-CONCENTRATION", budget_item_count=2, largest_singleton_share=0.8),
    )

    with pytest.raises(ValueError, match="conflicting structural metadata"):
        structural_curve_points(rows)
