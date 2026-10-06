from __future__ import annotations

import csv
import json
from pathlib import Path

from datamechbench.qualification_analysis import (
    QualificationEvidence,
    analyze_qualification,
    build_qualification_analysis,
)


def test_decomposition_separates_failure_from_missing_evidence() -> None:
    rows = (
        QualificationEvidence(
            method_id="exact_one_gap",
            requirement_status={
                "source_fidelity": "pass",
                "individual_rationality": "pass",
                "strong_budget_balance": "fail",
                "finite_no_counterexample": "pass",
            },
        ),
        QualificationEvidence(
            method_id="missing_only",
            requirement_status={
                "source_fidelity": "pass",
                "individual_rationality": "pass",
                "strong_budget_balance": "not_auditable",
                "finite_no_counterexample": "pass",
            },
        ),
        QualificationEvidence(
            method_id="two_gaps",
            requirement_status={
                "source_fidelity": "fail",
                "individual_rationality": "pass",
                "strong_budget_balance": "pass",
                "finite_no_counterexample": "fail",
            },
        ),
    )

    analysis = analyze_qualification(rows)
    by_method = {row.method_id: row for row in analysis.methods}

    assert by_method["exact_one_gap"].joint_status == "fail"
    assert by_method["exact_one_gap"].failed_requirements == (
        "strong_budget_balance",
    )
    assert by_method["exact_one_gap"].minimum_relaxation_count == 1
    assert by_method["missing_only"].joint_status == "not_auditable"
    assert by_method["missing_only"].unauditable_requirements == (
        "strong_budget_balance",
    )
    assert by_method["two_gaps"].minimum_relaxation_requirements == (
        "finite_no_counterexample",
        "source_fidelity",
    )
    assert analysis.summary["joint_pass_count"] == 0
    assert analysis.summary["observed_failure_method_count"] == 2
    assert analysis.summary["evidence_missing_method_count"] == 1


def test_frontier_reports_minimum_method_specific_paths_not_a_new_rank() -> None:
    rows = (
        QualificationEvidence("m1", {"fidelity": "pass", "sbb": "fail"}),
        QualificationEvidence("m2", {"fidelity": "pass", "sbb": "fail"}),
        QualificationEvidence("m3", {"fidelity": "fail", "sbb": "fail"}),
    )

    analysis = analyze_qualification(rows)
    frontier = {
        row.relaxed_requirements: row for row in analysis.relaxation_frontier
    }

    assert frontier[("sbb",)].newly_admitted_method_ids == ("m1", "m2")
    assert frontier[("fidelity", "sbb")].newly_admitted_method_ids == ("m3",)
    assert frontier[("fidelity", "sbb")].admitted_method_ids == (
        "m1",
        "m2",
        "m3",
    )
    assert all(row.analysis_role == "diagnostic_not_official_rank" for row in frontier.values())


def test_builder_materializes_current_headline_failure_explanation(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    output = tmp_path / "qualification"

    receipt = build_qualification_analysis(
        joint_admissibility_path=(
            root
            / "benchmark"
            / "outputs"
            / "kdd_aggregate_type_envelope"
            / "joint_admissibility.csv"
        ),
        output_dir=output,
    )

    assert receipt["headline_method_count"] == 5
    assert receipt["joint_pass_count"] == 0
    with (output / "method_failure_decomposition.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        methods = list(csv.DictReader(handle))
    assert {row["method_id"] for row in methods} == {
        "lottery_muda",
        "mcafee",
        "sbba",
        "trade_reduction",
        "vickrey_muda",
    }
    mcafee = next(row for row in methods if row["method_id"] == "mcafee")
    assert mcafee["minimum_relaxation_requirements"] == "strong_budget_balance"
    lottery = next(row for row in methods if row["method_id"] == "lottery_muda")
    assert lottery["minimum_relaxation_requirements"] == (
        "finite_no_counterexample;source_fidelity"
    )
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    assert summary["one_requirement_near_miss_count"] == 3
    assert summary["analysis_role"] == "diagnostic_not_official_rank"
    report = (output / "report.md").read_text(encoding="utf-8")
    assert "observed failure" in report
    assert "not a new leaderboard" in report
