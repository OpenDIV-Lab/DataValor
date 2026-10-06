from __future__ import annotations

import hashlib
import json
from pathlib import Path

from datamechbench.case_bank import audit_case_bank_manifests
from datamechbench.models import BenchmarkResult

TRACKS = ("valuation", "procurement", "trading")


def _result(track: str, case_id: str, setting: str, *, status: str = "completed") -> BenchmarkResult:
    return BenchmarkResult(
        run_id=f"{track}-{case_id}",
        track=track,
        method_id=f"{track}-method",
        case_id=case_id,
        seed=0,
        status=status,
        metrics={},
        runtime_seconds=0.01,
        metadata={"benchmark_setting": setting},
    )


def _write_manifest(tmp_path: Path, tracks: dict | None = None) -> tuple[Path, tuple[BenchmarkResult, ...]]:
    rows = tuple(_result(track, f"{track}-case", f"{track}-setting") for track in TRACKS)
    raw = tmp_path / "raw_results.jsonl"
    raw.write_text("frozen raw result fixture\n", encoding="utf-8")
    payload = {
        "schema_version": "1.0",
        "manifest_kind": "independent_case_bank",
        "results": {
            "path": str(raw),
            "sha256": hashlib.sha256(raw.read_bytes()).hexdigest(),
        },
        "tracks": tracks or {
            track: {
                "blocks": [{
                    "block_id": f"{track}-block",
                    "cohort": "development",
                    "setting_id": f"{track}-setting",
                    "generator_family": f"{track}-generator",
                    "independence_unit": "generator_family",
                    "source_kind": "controlled_generator",
                    "source_uri": f"benchmark://{track}",
                    "license_id": "MIT",
                    "input_hash": hashlib.sha256(track.encode()).hexdigest(),
                    "case_ids": [f"{track}-case"],
                }],
            }
            for track in TRACKS
        },
    }
    manifest = tmp_path / "case_bank.json"
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    return manifest, rows


def test_explicit_case_bank_derives_counts_from_completed_cases(tmp_path: Path) -> None:
    manifest, rows = _write_manifest(tmp_path)

    audit = audit_case_bank_manifests((str(manifest),), tmp_path, rows)

    assert audit.errors == ()
    assert audit.block_counts == {track: 1 for track in TRACKS}
    assert audit.generator_counts == {track: 1 for track in TRACKS}
    assert audit.cohorts == {track: ("development",) for track in TRACKS}


def test_legacy_count_only_manifest_cannot_satisfy_case_bank_gate(tmp_path: Path) -> None:
    manifest, rows = _write_manifest(
        tmp_path,
        tracks={
            track: {"independent_blocks": 99, "generator_families": 99}
            for track in TRACKS
        },
    )

    audit = audit_case_bank_manifests((str(manifest),), tmp_path, rows)

    assert audit.block_counts == {track: 0 for track in TRACKS}
    assert all(f"legacy_count_only:{track}" in " ".join(audit.errors) for track in TRACKS)


def test_case_bank_rejects_wrong_result_hash(tmp_path: Path) -> None:
    manifest, rows = _write_manifest(tmp_path)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["results"]["sha256"] = "0" * 64
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    audit = audit_case_bank_manifests((str(manifest),), tmp_path, rows)

    assert any("results_sha256_mismatch" in error for error in audit.errors)
    assert audit.block_counts == {track: 0 for track in TRACKS}


def test_case_bank_rejects_duplicate_case_assignments(tmp_path: Path) -> None:
    manifest, rows = _write_manifest(tmp_path)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    duplicate = dict(payload["tracks"]["valuation"]["blocks"][0])
    duplicate["block_id"] = "valuation-block-two"
    duplicate["generator_family"] = "valuation-generator-two"
    payload["tracks"]["valuation"]["blocks"].append(duplicate)
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    audit = audit_case_bank_manifests((str(manifest),), tmp_path, rows)

    assert any("duplicate_case:valuation:valuation-case" in error for error in audit.errors)
    assert audit.block_counts["valuation"] == 0


def test_case_bank_rejects_case_without_completed_result(tmp_path: Path) -> None:
    manifest, rows = _write_manifest(tmp_path)
    rows = tuple(
        _result(row.track, row.case_id, row.metadata["benchmark_setting"], status="skipped")
        if row.track == "procurement" else row
        for row in rows
    )

    audit = audit_case_bank_manifests((str(manifest),), tmp_path, rows)

    assert any("missing_completed_case:procurement:procurement-case" in error for error in audit.errors)
    assert audit.block_counts["procurement"] == 0


def test_case_bank_rejects_case_completed_in_wrong_setting(tmp_path: Path) -> None:
    manifest, rows = _write_manifest(tmp_path)
    rows = tuple(
        _result(row.track, row.case_id, "different-setting")
        if row.track == "trading" else row
        for row in rows
    )

    audit = audit_case_bank_manifests((str(manifest),), tmp_path, rows)

    assert any("setting_mismatch:trading:trading-case" in error for error in audit.errors)
    assert audit.block_counts["trading"] == 0
