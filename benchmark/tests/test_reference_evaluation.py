from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from datamechbench.reference_evaluation import (
    audit_reference_results,
    write_reference_outcome_audit,
)
from datamechbench.report import write_jsonl
from datamechbench.runner import BenchmarkConfig, build_cases, run_benchmark


def _procurement_fixture():
    case = next(
        item
        for item in build_cases()["procurement"]
        if item.case_id == "PADD-independent-b30"
    )
    config = BenchmarkConfig(
        name="reference-outcome-audit",
        output_dir="unused",
        seeds=(0,),
        methods={
            "valuation": {},
            "procurement": {
                "budget_optimum": {},
                "cgl_deterministic": {},
            },
            "trading": {},
        },
        case_ids={
            "valuation": (),
            "procurement": (case.case_id,),
            "trading": (),
        },
        strategic_audit=True,
    )
    cases = {"valuation": (), "procurement": (case,), "trading": ()}
    return run_benchmark(config, cases=cases), cases


def test_reference_metrics_recompute_from_persisted_outcomes() -> None:
    results, cases = _procurement_fixture()

    audit = audit_reference_results(results, cases=cases)

    assert audit.passed is True
    assert audit.completed_rows == 2
    assert audit.outcome_rows == 2
    assert audit.auditable_rows == 2
    assert audit.metric_mismatches == ()
    assert audit.errors == ()
    assert audit.recomputed_metric_count > 0
    assert set(audit.execution_dependent_metric_ids) >= {
        "allocation_monotonicity_violation",
        "critical_payment_gap",
        "max_deviation_gain",
        "profitable_deviation_count",
        "runtime_seconds",
    }


def test_reference_audit_detects_tampered_outcome_derived_metric() -> None:
    results, cases = _procurement_fixture()
    target = next(row for row in results if row.method_id == "cgl_deterministic")
    tampered_metrics = dict(target.metrics)
    tampered_metrics["oracle_ratio"] = replace(
        tampered_metrics["oracle_ratio"], value=0.123456
    )
    tampered = tuple(
        replace(row, metrics=tampered_metrics) if row.run_id == target.run_id else row
        for row in results
    )

    audit = audit_reference_results(tampered, cases=cases)

    assert audit.passed is False
    assert len(audit.metric_mismatches) == 1
    assert audit.metric_mismatches[0]["run_id"] == target.run_id
    assert audit.metric_mismatches[0]["metric_id"] == "oracle_ratio"


def test_legacy_completed_rows_are_readable_but_not_outcome_auditable() -> None:
    results, cases = _procurement_fixture()
    legacy = tuple(
        replace(row, outcome=None, schema_version="1.1") for row in results
    )

    audit = audit_reference_results(legacy, cases=cases)

    assert audit.passed is False
    assert audit.outcome_rows == 0
    assert audit.auditable_rows == 0
    assert set(audit.errors) == {
        f"missing_outcome:{row.run_id}" for row in legacy
    }


def test_reference_outcome_receipt_binds_result_bytes(tmp_path: Path) -> None:
    results, cases = _procurement_fixture()
    results_path = write_jsonl(results, tmp_path / "raw_results.jsonl")
    output = tmp_path / "reference_outcome_audit.json"

    write_reference_outcome_audit(results_path, output, cases=cases)

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["passed"] is True
    assert payload["result_path"] == "raw_results.jsonl"
    assert len(payload["result_sha256"]) == 64
    assert payload["completed_rows"] == payload["outcome_rows"] == 2
