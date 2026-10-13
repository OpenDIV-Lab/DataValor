from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest
from datamechbench.metrics import MetricValue
from datamechbench.metrology import (
    PRIMARY_METRIC_RULES,
    analyze_block_reliability,
    audit_mutation_panel,
    build_benchmark_metrology,
    build_metrology_probe,
    verify_benchmark_metrology,
)
from datamechbench.models import BenchmarkResult


def _row(
    track: str,
    method: str,
    block: str,
    value: float,
    *,
    case: str | None = None,
) -> BenchmarkResult:
    metric = PRIMARY_METRIC_RULES[track]["metric_id"]
    return BenchmarkResult(
        run_id=f"{track}-{method}-{block}-{case or 'case'}",
        track=track,
        method_id=method,
        case_id=case or f"{block}-case",
        seed=0,
        status="completed",
        metrics={metric: MetricValue(value)},
        runtime_seconds=0.0,
        metadata={
            "independent_block": block,
            "primary_metric_eligible": True,
        },
        outcome={"kind": "valuation", "scores": {"x": 1.0}, "diagnostics": {}, "utility_calls": 1},
        schema_version="1.2",
    )


def test_reliability_preserves_ties_and_metric_direction() -> None:
    rows = (
        _row("valuation", "low", "b1", 0.1),
        _row("valuation", "tie", "b1", 0.1),
        _row("valuation", "high", "b1", 0.9),
        _row("valuation", "low", "b2", 0.2),
        _row("valuation", "tie", "b2", 0.2),
        _row("valuation", "high", "b2", 0.8),
        _row("valuation", "low", "b3", 0.3),
        _row("valuation", "tie", "b3", 0.3),
        _row("valuation", "high", "b3", 0.7),
    )

    report = analyze_block_reliability(rows)

    valuation = report.tracks["valuation"]
    assert valuation.full_winner_ids == ("low", "tie")
    assert valuation.leave_one_out_exact_winner_rate == 1.0
    assert valuation.leave_one_out_mean_jaccard == 1.0
    assert all(row.direction == "lower" for row in report.curve if row.track == "valuation")


def test_reliability_rejects_missing_independent_blocks() -> None:
    row = _row("trading", "method", "", 0.5)
    row = BenchmarkResult(**{**row.to_dict(), "metrics": row.metrics})

    with pytest.raises(ValueError, match="independent_block"):
        analyze_block_reliability((row,))


def test_undefined_tau_does_not_treat_broken_full_tie_as_agreement() -> None:
    rows = (
        _row("valuation", "a", "b1", 0.0),
        _row("valuation", "b", "b1", 1.0),
        _row("valuation", "a", "b2", 1.0),
        _row("valuation", "b", "b2", 0.0),
    )

    report = analyze_block_reliability(rows)

    singleton = [
        point
        for point in report.curve
        if point.track == "valuation" and point.block_subset_size == 1
    ]
    assert len(singleton) == 1
    assert singleton[0].mean_rank_tau == 0.0


def test_metrology_builder_detects_scientific_mutations_and_accepts_controls(
    tmp_path: Path,
) -> None:
    summary = build_benchmark_metrology(
        tmp_path,
        repository_root=Path.cwd(),
        v1_results=Path("benchmark/outputs/kdd_heldout_confirmatory/raw_results.jsonl"),
        v2_results=Path("benchmark/outputs/kdd_heldout_replication_v2/raw_results.jsonl"),
    )

    assert summary["valid"] is True
    assert summary["mutation_panel"] == {
        "headline_method_count": 17,
        "covered_method_count": 17,
        "scientific_mutation_count": 56,
        "scientific_mutations_detected": 56,
        "benign_control_count": 34,
        "benign_controls_accepted": 34,
        "sensitivity": 1.0,
        "specificity": 1.0,
        "track_method_counts": {
            "procurement": 6,
            "trading": 5,
            "valuation": 6,
        },
        "covered_method_ids": {
            "procurement": [
                "cgl_deterministic",
                "cgl_randomized",
                "generalized_proportional_share",
                "jt_deterministic_eom",
                "jt_greedy_tm",
                "jt_random_eom",
            ],
            "trading": [
                "lottery_muda",
                "mcafee",
                "sbba",
                "trade_reduction",
                "vickrey_muda",
            ],
            "valuation": [
                "banzhaf_exact",
                "knn_shapley",
                "robust_volume_shapley",
                "shapley_exact",
                "tmc_shapley",
                "volume_shapley",
            ],
        },
        "operator_cell_counts": {
            "procurement": {
                "allocation_deletion": 6,
                "canonical_reordering": 6,
                "payment_perturbation": 6,
                "runtime_only": 6,
                "stored_metric_tampering": 6,
                "unknown_actor": 6,
            },
            "trading": {
                "allocation_deletion": 5,
                "canonical_reordering": 5,
                "payment_perturbation": 5,
                "runtime_only": 5,
                "stored_metric_tampering": 5,
                "unknown_actor": 5,
            },
            "valuation": {
                "canonical_reordering": 6,
                "runtime_only": 6,
                "score_perturbation": 6,
                "stored_metric_tampering": 6,
            },
        },
    }
    assert summary["reliability"]["track_count"] == 3
    assert summary["reliability"]["block_counts"] == {
        "procurement": 5,
        "trading": 5,
        "valuation": 5,
    }
    rows = json.loads((tmp_path / "summary.json").read_text())
    assert rows["claim_boundary"].startswith("Mutation sensitivity")
    with (tmp_path / "mutation_panel.csv").open(newline="", encoding="utf-8") as stream:
        mutations = tuple(csv.DictReader(stream))
    assert len(mutations) == 90
    assert len({row["method_id"] for row in mutations}) == 17
    operators = {
        track: {
            row["operator_id"]
            for row in mutations
            if row["track"] == track
        }
        for track in ("valuation", "procurement", "trading")
    }
    assert operators == {
        "valuation": {
            "score_perturbation",
            "stored_metric_tampering",
            "runtime_only",
            "canonical_reordering",
        },
        "procurement": {
            "allocation_deletion",
            "payment_perturbation",
            "unknown_actor",
            "stored_metric_tampering",
            "runtime_only",
            "canonical_reordering",
        },
        "trading": {
            "allocation_deletion",
            "payment_perturbation",
            "unknown_actor",
            "stored_metric_tampering",
            "runtime_only",
            "canonical_reordering",
        },
    }
    assert verify_benchmark_metrology(tmp_path / "manifest.json") == {
        "valid": True,
        "errors": [],
        "output_count": 4,
    }


def test_metrology_verifier_rejects_drift(tmp_path: Path) -> None:
    build_benchmark_metrology(
        tmp_path,
        repository_root=Path.cwd(),
        v1_results=Path("benchmark/outputs/kdd_heldout_confirmatory/raw_results.jsonl"),
        v2_results=Path("benchmark/outputs/kdd_heldout_replication_v2/raw_results.jsonl"),
    )
    target = tmp_path / "mutation_panel.csv"
    target.write_text(target.read_text() + "\n", encoding="utf-8")

    report = verify_benchmark_metrology(tmp_path / "manifest.json")

    assert report["valid"] is False
    assert report["errors"] == ["hash_mismatch:mutation_panel.csv"]


def test_metrology_verifier_rejects_hash_consistent_semantic_tampering(
    tmp_path: Path,
) -> None:
    build_benchmark_metrology(
        tmp_path,
        repository_root=Path.cwd(),
        v1_results=Path("benchmark/outputs/kdd_heldout_confirmatory/raw_results.jsonl"),
        v2_results=Path("benchmark/outputs/kdd_heldout_replication_v2/raw_results.jsonl"),
    )
    target = tmp_path / "mutation_panel.csv"
    lines = target.read_text(encoding="utf-8").splitlines()
    target.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")
    manifest_path = tmp_path / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for record in manifest["outputs"]:
        if record["path"] == target.name:
            record["sha256"] = hashlib.sha256(target.read_bytes()).hexdigest()
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    report = verify_benchmark_metrology(manifest_path)

    assert report["valid"] is False
    assert report["errors"] == ["mutation_matrix_summary_mismatch"]


def test_mutation_panel_rejects_missing_headline_method() -> None:
    rows, cases, headline_methods = build_metrology_probe()
    missing = next(row for row in rows if row.method_id == "volume_shapley")

    with pytest.raises(ValueError, match="missing headline probe method.*volume_shapley"):
        audit_mutation_panel(
            tuple(row for row in rows if row is not missing),
            cases=cases,
            headline_methods=headline_methods,
        )


def test_mutation_panel_rejects_inapplicable_headline_outcome() -> None:
    rows, cases, headline_methods = build_metrology_probe()
    malformed = []
    for row in rows:
        if row.method_id != "cgl_deterministic":
            malformed.append(row)
            continue
        outcome = dict(row.outcome or {})
        outcome["payments"] = []
        malformed.append(replace(row, outcome=outcome))

    with pytest.raises(
        ValueError,
        match="cgl_deterministic.*applicable.*payment_perturbation",
    ):
        audit_mutation_panel(
            tuple(malformed),
            cases=cases,
            headline_methods=headline_methods,
        )
