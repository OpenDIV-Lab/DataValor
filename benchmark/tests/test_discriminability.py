from __future__ import annotations

from pathlib import Path

from datamechbench.discriminability import (
    analyze_discriminability,
    build_discriminability_audit,
    verify_discriminability_audit,
)
from datamechbench.metrics import MetricValue
from datamechbench.models import BenchmarkResult


def _row(
    track: str,
    method: str,
    block: str,
    case: str,
    seed: int,
    value: float | None,
    *,
    qualified: bool = True,
) -> BenchmarkResult:
    metric = {
        "valuation": "replication_owner_rank_change",
        "procurement": "oracle_ratio",
        "trading": "gain_from_trade_ratio",
    }[track]
    metrics: dict[str, object] = {
        metric: MetricValue(value, applicable=value is not None, reason=None if value is not None else "missing")
    }
    if track == "procurement":
        metrics.update(
            budget_violation=MetricValue(not qualified),
            seller_ir_violation_count=MetricValue(0 if qualified else 1),
        )
    elif track == "trading":
        metrics.update(
            individual_rationality=MetricValue(qualified),
            weak_budget_balance=MetricValue(qualified),
        )
    return BenchmarkResult(
        run_id=f"{track}-{method}-{block}-{case}-{seed}",
        track=track,
        method_id=method,
        case_id=case,
        seed=seed,
        status="completed",
        metrics=metrics,
        runtime_seconds=0.0,
        metadata={"independent_block": block, "primary_metric_eligible": True},
        outcome={"kind": "valuation", "scores": {}, "diagnostics": {}, "utility_calls": 0},
        schema_version="1.2",
    )


def test_discriminability_aggregates_seeds_before_ties_and_is_order_invariant() -> None:
    rows = (
        _row("procurement", "a", "b1", "c1", 0, 1.0),
        _row("procurement", "a", "b1", "c1", 1, 0.8),
        _row("procurement", "a", "b2", "c2", 0, 0.9),
        _row("procurement", "b", "b1", "c1", 0, 0.9000000000001),
        _row("procurement", "b", "b2", "c2", 0, 0.9),
        _row("procurement", "c", "b1", "c1", 0, 0.5, qualified=False),
        _row("procurement", "c", "b2", "c2", 0, 0.5, qualified=False),
    )
    forward = analyze_discriminability(rows, headline_methods={"procurement": ("a", "b", "c")})
    backward = analyze_discriminability(reversed(rows), headline_methods={"procurement": ("a", "b", "c")})

    assert forward == backward
    track = forward["tracks"]["procurement"]
    assert track["method_count"] == 3
    assert track["pair_count"] == 3
    assert track["exact_tie_pair_count"] == 1
    assert track["practical_tie_pair_count"] == 1
    assert track["winner_ids"] == ["a", "b"]
    assert track["qualification_rate"] == 2 / 3
    assert track["constraint_activation_rate"] == 1 / 3


def test_discriminability_reports_missing_coverage_and_saturation() -> None:
    rows = (
        _row("trading", "full", "b1", "c1", 0, 1.0),
        _row("trading", "full", "b2", "c2", 0, 1.0),
        _row("trading", "partial", "b1", "c1", 0, None),
        _row("trading", "partial", "b2", "c2", 0, 0.0),
    )
    report = analyze_discriminability(
        rows, headline_methods={"trading": ("full", "partial")}
    )["tracks"]["trading"]

    assert report["complete_coverage_method_count"] == 1
    assert report["missing_measurement_count"] == 1
    assert report["ceiling_saturation_rate"] == 2 / 3
    assert report["floor_saturation_rate"] == 1 / 3


def test_discriminability_builder_covers_both_waves_and_verifies(tmp_path: Path) -> None:
    summary = build_discriminability_audit(
        tmp_path,
        repository_root=Path.cwd(),
        catalog_path="benchmark/catalog/headline_suite.yaml",
        waves={
            "v1": "benchmark/outputs/kdd_heldout_confirmatory/raw_results.jsonl",
            "v2": "benchmark/outputs/kdd_heldout_replication_v2/raw_results.jsonl",
        },
    )
    assert summary["valid"] is True
    assert set(summary["waves"]) == {"v1", "v2"}
    assert all(set(wave["tracks"]) == {"valuation", "procurement", "trading"} for wave in summary["waves"].values())
    assert verify_discriminability_audit(tmp_path / "manifest.json") == {
        "valid": True,
        "errors": [],
    }
