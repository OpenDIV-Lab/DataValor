from __future__ import annotations

import csv
import hashlib
import json
from decimal import Decimal
from pathlib import Path

from datamechbench.market_resources import (
    analyze_market_resources,
    attach_resource_usage,
    build_market_resource_report,
    instrument_procurement_input,
    trading_resource_usage,
    verify_market_resource_report,
)
from datamechbench.metrics import MetricValue
from datamechbench.models import (
    BenchmarkResult,
    MarketOutcome,
    ProcurementInput,
    TradeInput,
)
from datamechbench.report import write_jsonl


def _procurement_input() -> ProcurementInput:
    return ProcurementInput(
        seller_ids=("s0", "s1"),
        reported_costs={"s0": Decimal("1"), "s1": Decimal("2")},
        budget=Decimal("3"),
        utility=lambda selected: float(len(set(selected))),
    )


def test_procurement_counter_measures_only_calls_through_instrumented_input() -> None:
    """Catches metric/audit utility calls leaking into mechanism resource counts."""

    original = _procurement_input()
    instrumented, counter = instrument_procurement_input(original)

    assert instrumented.utility(()) == 0.0
    assert instrumented.utility(("s0",)) == 1.0
    original.utility(("s0", "s1"))
    output = attach_resource_usage(
        MarketOutcome(selected_ids=("s0",)),
        {"utility_oracle_calls": counter.calls},
    )

    assert output.diagnostics["resource_usage"] == {"utility_oracle_calls": 2}


def test_trading_resource_vector_uses_algorithm_events_not_wall_clock() -> None:
    """Catches an implementation that substitutes runtime for auditable units."""

    case = TradeInput(
        product_id="p",
        buyer_ids=("b0", "b1", "b2"),
        seller_ids=("s0", "s1"),
        bids={"b0": Decimal("1"), "b1": Decimal(".8"), "b2": Decimal(".2")},
        asks={"s0": Decimal(".1"), "s1": Decimal(".7")},
    )
    muda = MarketOutcome(
        diagnostics={
            "left_branch": "excess_demand_lottery",
            "right_branch": "balanced_lottery",
        }
    )
    sbba = MarketOutcome(diagnostics={"randomized_seller_exclusion": True})

    assert trading_resource_usage("lottery_muda", case, muda) == {
        "submitted_reports": 5,
        "clearing_passes": 2,
        "randomization_events": 6,
    }
    assert trading_resource_usage("sbba", case, sbba) == {
        "submitted_reports": 5,
        "clearing_passes": 1,
        "randomization_events": 1,
    }


def _result(
    run_id: str,
    *,
    track: str,
    method: str,
    case: str,
    block: str,
    quality: float,
    resources: dict[str, int] | None,
) -> BenchmarkResult:
    metric_id = "oracle_ratio" if track == "procurement" else "gain_from_trade_ratio"
    return BenchmarkResult(
        run_id=run_id,
        track=track,
        method_id=method,
        case_id=case,
        seed=0,
        status="completed",
        metrics={metric_id: MetricValue(quality)},
        runtime_seconds=99.0,
        metadata={"independent_block": block},
        outcome={
            "kind": "market",
            "selected_ids": [],
            "allocations": [],
            "payments": [],
            "diagnostics": (
                {"resource_usage": resources} if resources is not None else {}
            ),
        },
        schema_version="1.2",
    )


def test_market_resource_report_weights_registered_blocks_equally() -> None:
    """Catches row-weighting that lets a block with more cases dominate."""

    report = analyze_market_resources(
        (
            _result(
                "a1",
                track="procurement",
                method="m",
                case="c1",
                block="a",
                quality=.5,
                resources={"utility_oracle_calls": 10},
            ),
            _result(
                "a2",
                track="procurement",
                method="m",
                case="c2",
                block="a",
                quality=.7,
                resources={"utility_oracle_calls": 30},
            ),
            _result(
                "b1",
                track="procurement",
                method="m",
                case="c3",
                block="b",
                quality=.9,
                resources={"utility_oracle_calls": 100},
            ),
        )
    )

    row = report.rows[0]
    assert row.status == "auditable"
    assert row.mean_quality == .75
    assert row.mean_resources == {"utility_oracle_calls": 60.0}
    assert row.block_count == 2


def test_market_resource_report_does_not_impute_missing_telemetry() -> None:
    """Catches missing counters being replaced with zero or inferred runtime."""

    report = analyze_market_resources(
        (
            _result(
                "missing",
                track="trading",
                method="m",
                case="c",
                block="b",
                quality=.8,
                resources=None,
            ),
        )
    )

    row = report.rows[0]
    assert row.status == "not_auditable"
    assert row.mean_resources == {}
    assert row.reason == "missing_resource_usage"


def test_market_resource_verifier_rejects_hash_consistent_unknown_track(
    tmp_path: Path,
) -> None:
    """Catches a verifier that checks hashes but not resource semantics."""

    results = tmp_path / "results.jsonl"
    write_jsonl(
        (
            _result(
                "row",
                track="procurement",
                method="m",
                case="c",
                block="b",
                quality=.8,
                resources={"utility_oracle_calls": 4},
            ),
        ),
        results,
    )
    output = tmp_path / "resources"
    build_market_resource_report(
        output,
        repository_root=tmp_path,
        results_path=results,
    )
    table = output / "resources.csv"
    rows = list(csv.DictReader(table.open(encoding="utf-8")))
    rows[0]["track"] = "unknown"
    with table.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0].keys(), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    manifest_path = output / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for artifact in manifest["outputs"]:
        if artifact["path"] == "resources.csv":
            artifact["sha256"] = hashlib.sha256(table.read_bytes()).hexdigest()
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    verification = verify_market_resource_report(manifest_path)

    assert verification["valid"] is False
    assert "invalid_track:unknown" in verification["errors"]


def test_market_resource_verifier_rejects_changed_bound_input(tmp_path: Path) -> None:
    """Catches resource reports surviving changes to the executions they summarize."""

    results = tmp_path / "results.jsonl"
    write_jsonl(
        (
            _result(
                "row",
                track="procurement",
                method="m",
                case="c",
                block="b",
                quality=.8,
                resources={"utility_oracle_calls": 4},
            ),
        ),
        results,
    )
    output = tmp_path / "resources"
    build_market_resource_report(output, repository_root=tmp_path, results_path=results)
    results.write_text(results.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    verification = verify_market_resource_report(output / "manifest.json")

    assert verification["valid"] is False
    assert any(error.startswith("input_hash_mismatch:") for error in verification["errors"])


def test_market_resource_verifier_recomputes_auditable_counts(tmp_path: Path) -> None:
    """Catches a hash-consistent summary overstating mechanism coverage."""

    results = tmp_path / "results.jsonl"
    write_jsonl(
        (
            _result(
                "row",
                track="procurement",
                method="m",
                case="c",
                block="b",
                quality=.8,
                resources={"utility_oracle_calls": 4},
            ),
        ),
        results,
    )
    output = tmp_path / "resources"
    build_market_resource_report(output, repository_root=tmp_path, results_path=results)
    summary_path = output / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["auditable_counts"]["procurement"] = 99
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest_path = output / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for record in manifest["outputs"]:
        if record["path"] == "summary.json":
            record["sha256"] = hashlib.sha256(summary_path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    verification = verify_market_resource_report(manifest_path)

    assert verification["valid"] is False
    assert "summary_auditable_counts_mismatch" in verification["errors"]


def test_market_resource_manifest_resolves_repository_relative_source(
    tmp_path: Path,
) -> None:
    """Catches a manifest path that only verifies when the caller used an absolute path."""

    results = tmp_path / "inputs" / "results.jsonl"
    results.parent.mkdir()
    write_jsonl(
        (
            _result(
                "row",
                track="procurement",
                method="m",
                case="c",
                block="b",
                quality=.8,
                resources={"utility_oracle_calls": 4},
            ),
        ),
        results,
    )
    output = tmp_path / "outputs" / "resources"
    build_market_resource_report(
        output,
        repository_root=tmp_path,
        results_path=Path("inputs/results.jsonl"),
    )

    verification = verify_market_resource_report(output / "manifest.json")

    assert verification["valid"] is True
