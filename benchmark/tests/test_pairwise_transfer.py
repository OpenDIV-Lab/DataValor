from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from datamechbench.metrics import MetricValue
from datamechbench.models import BenchmarkResult
from datamechbench.pairwise_transfer import (
    analyze_pairwise_transfer,
    build_pairwise_transfer_audit,
    classify_transfer,
    verify_pairwise_transfer_audit,
)


def _row(
    track: str,
    method: str,
    block: str,
    case: str,
    seed: int,
    value: float | None,
) -> BenchmarkResult:
    metric = {
        "valuation": "replication_owner_rank_change",
        "procurement": "oracle_ratio",
        "trading": "gain_from_trade_ratio",
    }[track]
    return BenchmarkResult(
        run_id=f"{track}-{method}-{block}-{case}-{seed}",
        track=track,
        method_id=method,
        case_id=case,
        seed=seed,
        status="completed",
        metrics={
            metric: MetricValue(
                value,
                applicable=value is not None,
                reason=None if value is not None else "missing",
            )
        },
        runtime_seconds=0.0,
        metadata={"independent_block": block, "primary_metric_eligible": True},
        outcome={"kind": track, "diagnostics": {}},
        schema_version="1.2",
    )


def test_transfer_classifier_covers_all_five_categories() -> None:
    assert classify_transfer("left_better", "left_better") == "stable_order"
    assert classify_transfer("practical_tie", "practical_tie") == "stable_tie"
    assert classify_transfer("right_better", "practical_tie") == "attenuation_to_tie"
    assert classify_transfer("practical_tie", "left_better") == "emerging_order"
    assert classify_transfer("left_better", "right_better") == "reversal"


def test_pairwise_transfer_orients_metrics_and_aggregates_seeds_before_blocks() -> None:
    v1 = (
        _row("valuation", "a", "b1", "c1", 0, 0.0),
        _row("valuation", "a", "b1", "c1", 1, 0.2),
        _row("valuation", "a", "b2", "c2", 0, 0.3),
        _row("valuation", "b", "b1", "c1", 0, 0.2),
        _row("valuation", "b", "b2", "c2", 0, 0.4),
        _row("procurement", "x", "b1", "c1", 0, 0.9),
        _row("procurement", "y", "b1", "c1", 0, 0.8),
    )
    v2 = (
        _row("valuation", "a", "b3", "c3", 0, 0.5),
        _row("valuation", "b", "b3", "c3", 0, 0.4),
        _row("procurement", "x", "b2", "c2", 0, 0.7),
        _row("procurement", "y", "b2", "c2", 0, 0.7),
    )
    methods = {"valuation": ("a", "b"), "procurement": ("x", "y")}

    forward = analyze_pairwise_transfer(v1, v2, headline_methods=methods)
    backward = analyze_pairwise_transfer(
        reversed(v1), reversed(v2), headline_methods=methods
    )

    assert forward == backward
    assert forward["valid"] is True
    valuation = next(pair for pair in forward["pairs"] if pair["track"] == "valuation")
    procurement = next(
        pair for pair in forward["pairs"] if pair["track"] == "procurement"
    )
    assert valuation["v1_left_advantage"] == pytest.approx(0.1)
    assert valuation["v1_relation"] == "left_better"
    assert valuation["v2_relation"] == "right_better"
    assert valuation["transfer_category"] == "reversal"
    assert procurement["v1_relation"] == "left_better"
    assert procurement["v2_relation"] == "practical_tie"
    assert procurement["transfer_category"] == "attenuation_to_tie"


def test_pairwise_transfer_fails_closed_on_incomplete_method_coverage() -> None:
    report = analyze_pairwise_transfer(
        (_row("trading", "a", "b1", "c1", 0, 0.5),),
        (
            _row("trading", "a", "b2", "c2", 0, 0.5),
            _row("trading", "b", "b2", "c2", 0, 0.4),
        ),
        headline_methods={"trading": ("a", "b")},
    )

    assert report["valid"] is False
    assert "missing_method_wave:v1:trading:b" in report["errors"]
    assert report["tracks"]["trading"]["expected_pair_count"] == 1
    assert report["tracks"]["trading"]["observed_pair_count"] == 0


def test_pairwise_transfer_builder_covers_all_headline_pairs(tmp_path: Path) -> None:
    summary = build_pairwise_transfer_audit(
        tmp_path,
        repository_root=Path.cwd(),
        catalog_path="benchmark/catalog/headline_suite.yaml",
        v1_path="benchmark/outputs/kdd_heldout_confirmatory/raw_results.jsonl",
        v2_path="benchmark/outputs/kdd_heldout_replication_v2/raw_results.jsonl",
    )

    assert summary["valid"] is True
    assert summary["pair_count"] == 40
    assert {
        track: report["expected_pair_count"]
        for track, report in summary["tracks"].items()
    } == {"procurement": 15, "trading": 10, "valuation": 15}
    assert verify_pairwise_transfer_audit(tmp_path / "manifest.json") == {
        "valid": True,
        "errors": [],
    }


def test_pairwise_transfer_verifier_rejects_hash_consistent_bad_partition(
    tmp_path: Path,
) -> None:
    build_pairwise_transfer_audit(
        tmp_path,
        repository_root=Path.cwd(),
        catalog_path="benchmark/catalog/headline_suite.yaml",
        v1_path="benchmark/outputs/kdd_heldout_confirmatory/raw_results.jsonl",
        v2_path="benchmark/outputs/kdd_heldout_replication_v2/raw_results.jsonl",
    )
    summary_path = tmp_path / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["tracks"]["valuation"]["category_counts"]["stable_order"] = "bad"
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    manifest_path = tmp_path / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for output in manifest["outputs"]:
        if output["path"] == "summary.json":
            output["sha256"] = hashlib.sha256(summary_path.read_bytes()).hexdigest()
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    checked = verify_pairwise_transfer_audit(manifest_path)

    assert checked["valid"] is False
    assert "invalid_category_partition:valuation" in checked["errors"]
