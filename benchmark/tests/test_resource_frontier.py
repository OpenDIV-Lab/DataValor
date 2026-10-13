from __future__ import annotations

from datamechbench.metrics import MetricValue
from datamechbench.models import BenchmarkResult
from datamechbench.resource_frontier import analyze_resource_frontier


def _row(method: str, quality: float, calls: int | None) -> BenchmarkResult:
    return BenchmarkResult(
        run_id=f"run-{method}",
        track="valuation",
        method_id=method,
        case_id="case",
        seed=0,
        status="completed",
        metrics={"topk_test_utility": MetricValue(quality)},
        runtime_seconds=0.0,
        metadata={"independent_block": "block"},
        outcome={
            "kind": "valuation",
            "scores": {"owner": 1.0},
            "diagnostics": {},
            "utility_calls": calls,
        },
        schema_version="1.2",
    )


def test_frontier_preserves_ties_and_rejects_dominated_points() -> None:
    report = analyze_resource_frontier(
        (
            _row("cheap-good", 0.8, 10),
            _row("same-point", 0.8, 10),
            _row("expensive-worse", 0.7, 20),
            _row("best-expensive", 0.9, 30),
        )
    )

    by_method = {row.method_id: row for row in report.methods}
    assert by_method["cheap-good"].nondominated is True
    assert by_method["same-point"].nondominated is True
    assert by_method["best-expensive"].nondominated is True
    assert by_method["expensive-worse"].nondominated is False
    assert by_method["expensive-worse"].dominated_by == (
        "cheap-good",
        "same-point",
    )


def test_frontier_marks_missing_query_counters_not_auditable() -> None:
    report = analyze_resource_frontier(
        (_row("auditable", 0.8, 5), _row("missing", 0.9, None))
    )

    missing = next(row for row in report.methods if row.method_id == "missing")
    assert missing.status == "not_auditable"
    assert missing.mean_query_calls is None
    assert missing.nondominated is None
    assert missing.reason == "missing_utility_calls"


def test_market_tracks_are_explicitly_out_of_scope() -> None:
    report = analyze_resource_frontier((_row("auditable", 0.8, 5),))

    assert report.track_status == {
        "valuation": "auditable",
        "procurement": "not_auditable:no_standardized_query_counter",
        "trading": "not_auditable:no_standardized_query_counter",
    }
