from __future__ import annotations

import hashlib
import json
from pathlib import Path

from datamechbench.metrics import MetricValue
from datamechbench.models import BenchmarkResult
from datamechbench.report import write_jsonl
from datamechbench.resolution_envelope import (
    analyze_resolution_envelope,
    build_resolution_envelope,
    verify_resolution_envelope,
)


def _row(
    run_id: str,
    *,
    track: str,
    method: str,
    case: str,
    block: str,
    value: float,
) -> BenchmarkResult:
    metric = "oracle_ratio" if track == "procurement" else "gain_from_trade_ratio"
    return BenchmarkResult(
        run_id=run_id,
        track=track,
        method_id=method,
        case_id=case,
        seed=0,
        status="completed",
        metrics={metric: MetricValue(value)},
        runtime_seconds=0.0,
        metadata={"independent_block": block},
    )


def _waves():
    v1 = (
        _row("v1-a-1", track="procurement", method="a", case="c1", block="x", value=0.90),
        _row("v1-b-1", track="procurement", method="b", case="c1", block="x", value=0.88),
        _row("v1-a-2", track="procurement", method="a", case="c2", block="y", value=0.80),
        _row("v1-b-2", track="procurement", method="b", case="c2", block="y", value=0.79),
    )
    v2 = (
        _row("v2-a-1", track="procurement", method="a", case="c3", block="z", value=0.70),
        _row("v2-b-1", track="procurement", method="b", case="c3", block="z", value=0.69),
    )
    challenge = (
        _row("ch-a-1", track="procurement", method="a", case="d1", block="d1", value=0.90),
        _row("ch-b-1", track="procurement", method="b", case="d1", block="d1", value=0.70),
    )
    return v1, v2, challenge


def test_resolution_envelope_covers_grid_and_is_monotone() -> None:
    v1, v2, challenge = _waves()
    summary = analyze_resolution_envelope(
        v1,
        v2,
        challenge,
        headline_methods={"procurement": ("a", "b")},
        tolerances=(0.0, 0.01, 0.02, 0.05),
    )

    assert summary["valid"] is True
    assert len(summary["pair_tolerance_rows"]) == 12
    assert summary["panels"]["heldout_v1"]["procurement"]["separable_pair_counts"] == {
        "0": 1,
        "0.01": 1,
        "0.02": 0,
        "0.05": 0,
    }
    assert summary["panels"]["challenge"]["procurement"]["robustly_separable_pair_count"] == 1
    assert summary["monotonicity_passed"] is True


def test_resolution_artifact_recomputes_and_rejects_semantic_tampering(tmp_path: Path) -> None:
    v1, v2, challenge = _waves()
    paths = {}
    for name, rows in (("v1", v1), ("v2", v2), ("challenge", challenge)):
        paths[name] = write_jsonl(rows, tmp_path / f"{name}.jsonl")
    catalog = tmp_path / "target.yaml"
    catalog.write_text(
        "flagships:\n  procurement:\n    method_ids: [a, b]\n",
        encoding="utf-8",
    )
    protocol = tmp_path / "resolution.yaml"
    protocol.write_text(
        "schema_version: '1.0'\n"
        "study_id: resolution-test\n"
        "tolerances: [0.0, 0.01, 0.02, 0.05]\n"
        "primary_tolerance: 0.01\n",
        encoding="utf-8",
    )
    output = tmp_path / "artifact"
    build_resolution_envelope(
        output,
        repository_root=tmp_path,
        catalog_path=catalog,
        protocol_path=protocol,
        v1_path=paths["v1"],
        v2_path=paths["v2"],
        challenge_path=paths["challenge"],
    )

    assert verify_resolution_envelope(output / "manifest.json")["valid"] is True

    summary_path = output / "summary.json"
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    payload["panels"]["heldout_v1"]["procurement"]["separable_pair_counts"]["0.02"] = 1
    summary_path.write_text(json.dumps(payload), encoding="utf-8")
    manifest_path = output / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for record in manifest["outputs"]:
        if record["path"] == "summary.json":
            record["sha256"] = hashlib.sha256(summary_path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    verification = verify_resolution_envelope(manifest_path)
    assert verification["valid"] is False
    assert "semantic_recomputation_mismatch" in verification["errors"]
