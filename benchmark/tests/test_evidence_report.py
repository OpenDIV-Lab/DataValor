from __future__ import annotations

import csv
from pathlib import Path

from datamechbench.evidence_report import write_evidence_artifacts
from datamechbench.models import BenchmarkResult


def _result(
    family: str,
    setting: str,
    case: str,
    value: float,
    *,
    provenance: str = "paper_exact",
) -> BenchmarkResult:
    return BenchmarkResult(
        run_id=f"{family}-{setting}-{case}",
        track="procurement",
        method_id=family,
        case_id=case,
        seed=0,
        status="completed",
        metrics={
            "oracle_ratio": value,
            "budget_violation": 0.0,
            "seller_ir_violation_count": 0.0,
        },
        runtime_seconds=0.01,
        metadata={
            "method_family": family,
            "benchmark_setting": setting,
            "implementation_kind": "native",
            "provenance_kind": provenance,
            "method_capabilities": [],
            "pilot": False,
        },
    )


def test_evidence_report_writes_stable_nonempty_artifacts(tmp_path: Path) -> None:
    rows = tuple(
        _result(family, setting, f"{setting}-{index}", base - 0.01 * index)
        for setting, offset in (("P-SUBMODULAR", 0.0), ("P-ML-ACQUISITION", 0.2))
        for family, base in (("a", 0.9 - offset), ("b", 0.7 - offset))
        for index in range(6)
    ) + tuple(
        _result(
            "common",
            setting,
            f"{setting}-{index}",
            0.5,
            provenance="common_baseline",
        )
        for setting in ("P-SUBMODULAR", "P-ML-ACQUISITION")
        for index in range(6)
    )

    paths = write_evidence_artifacts(rows, tmp_path)

    assert {path.name for path in paths} == {
        "constraint_leaderboard.csv",
        "mechanism_profiles.csv",
        "pairwise_comparisons.csv",
        "statistical_summary.md",
        "assumption_transfer.csv",
        "structural_curve_points.csv",
        "structural_profiles.csv",
        "structural_profiles.md",
        "discovery_findings.csv",
        "discovery_report.md",
        "deep_dive_auditability.csv",
        "deep_dive_market_thickness.csv",
        "deep_dive_replication.csv",
        "deep_dive_claim_aggregation.csv",
        "deep_dive_report.md",
    }
    for path in paths:
        assert path.stat().st_size > 0
    with (tmp_path / "constraint_leaderboard.csv").open(encoding="utf-8") as stream:
        constraint_rows = list(csv.DictReader(stream))
        assert {"constraint_status", "constraint_qualified_rank"} <= set(constraint_rows[0])
        assert "common" in {row["family_id"] for row in constraint_rows}
    with (tmp_path / "pairwise_comparisons.csv").open(encoding="utf-8") as stream:
        assert {"adjusted_p_value", "conclusion", "common_case_count"} <= set(next(csv.reader(stream)))
    summary = (tmp_path / "statistical_summary.md").read_text(encoding="utf-8")
    assert "not evidence of equivalence" in summary
    assert "sampled deviation" in summary
    deep_dive = (tmp_path / "deep_dive_report.md").read_text(encoding="utf-8")
    assert "Competing explanation / validity boundary" in deep_dive
    assert "Falsifiable next experiment" in deep_dive
    assert "price of auditability" in deep_dive
