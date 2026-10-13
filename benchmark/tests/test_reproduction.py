from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import datamechbench.reproduction as reproduction
import pytest
from datamechbench.metrics import MetricValue
from datamechbench.models import BenchmarkResult
from datamechbench.report import load_jsonl_results, write_jsonl
from datamechbench.reproduction import (
    audit_clean_room_records,
    create_clean_room_record,
    load_reproduction_manifest,
    scientific_result_digest,
    verify_reproduction_manifest,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
REPRODUCE_SCRIPT = REPOSITORY_ROOT / "benchmark" / "scripts" / "reproduce_kdd_core.py"
_TEST_LOCK_BYTES = b"numpy==2.3.5\nPyYAML==6.0.2\n"
_TEST_LOCK_SHA256 = hashlib.sha256(_TEST_LOCK_BYTES).hexdigest()


def _load_reproduce_script():
    spec = importlib.util.spec_from_file_location("reproduce_kdd_core_under_test", REPRODUCE_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _result(
    *,
    run_id: str = "run-a",
    runtime_seconds: float = 1.25,
    score: float = 0.75,
    metadata: dict[str, object] | None = None,
) -> BenchmarkResult:
    return BenchmarkResult(
        run_id=run_id,
        track="valuation",
        method_id="method-a",
        case_id="case-a",
        seed=7,
        status="completed",
        metrics={
            "score": MetricValue(score),
            "runtime_seconds": MetricValue(runtime_seconds),
        },
        runtime_seconds=runtime_seconds,
        metadata=metadata or {"benchmark_setting": "V-TEST"},
    )


def test_scientific_digest_is_order_invariant() -> None:
    first = _result(run_id="run-a")
    second = replace(_result(run_id="run-b"), case_id="case-b")

    assert scientific_result_digest((first, second)) == scientific_result_digest(
        (second, first)
    )


def test_resolve_repository_file_rejects_absolute_and_escape(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact.json"
    artifact.write_text("{}\n", encoding="utf-8")

    assert reproduction.resolve_repository_file("artifact.json", tmp_path) == artifact
    with pytest.raises(ValueError, match="repository-relative"):
        reproduction.resolve_repository_file(str(artifact), tmp_path)
    with pytest.raises(ValueError, match="escapes repository root"):
        reproduction.resolve_repository_file("../artifact.json", tmp_path)


def test_frozen_procurement_receipts_are_portable_repository_paths() -> None:
    receipt_path = (
        REPOSITORY_ROOT
        / "benchmark"
        / "data"
        / "heldout"
        / "raw"
        / "chilecompra"
        / "chilecompra-2024-source-receipt.json"
    )
    receipt_payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert not Path(receipt_payload["source_path"]).is_absolute()

    processed = sorted(
        (REPOSITORY_ROOT / "benchmark" / "data" / "heldout" / "processed").glob(
            "chilecompra-*-costs.json"
        )
    )

    assert len(processed) == 3
    for path in processed:
        payload = json.loads(path.read_text(encoding="utf-8"))
        receipt = payload["source_receipt"]
        assert not Path(receipt).is_absolute(), path
        resolved = reproduction.resolve_repository_file(
            receipt,
            REPOSITORY_ROOT,
            label="ChileCompra source receipt",
        )
        assert resolved.name == "chilecompra-2024-source-receipt.json"


def test_scientific_digest_excludes_only_runtime_measurements() -> None:
    baseline = _result(runtime_seconds=1.25)
    slower = _result(runtime_seconds=99.0)
    changed_score = _result(runtime_seconds=1.25, score=0.76)
    changed_metadata = _result(
        runtime_seconds=1.25,
        metadata={"benchmark_setting": "V-OTHER"},
    )

    assert scientific_result_digest((baseline,)) == scientific_result_digest((slower,))
    assert scientific_result_digest((baseline,)) != scientific_result_digest(
        (changed_score,)
    )
    assert scientific_result_digest((baseline,)) != scientific_result_digest(
        (changed_metadata,)
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _manifest_payload(
    raw_results: Path,
    artifact: Path,
    environment_lock: Path,
    *,
    scientific_digest: str | None = None,
) -> dict[str, object]:
    if scientific_digest is None:
        scientific_digest = scientific_result_digest(load_jsonl_results(raw_results))
    return {
        "schema_version": "1.0",
        "manifest_kind": "kdd_core_reproduction",
        "release_id": "fixture-v1",
        "required_tracks": ["valuation"],
        "scientific_results": {
            "path": raw_results.name,
            "sha256": _sha256(raw_results),
            "scientific_digest": scientific_digest,
            "row_count": 1,
            "status_counts": {"completed": 1},
            "track_counts": {"valuation": 1},
        },
        "artifacts": [
            {"path": artifact.name, "sha256": _sha256(artifact), "role": "protocol"},
            {
                "path": environment_lock.name,
                "sha256": _sha256(environment_lock),
                "role": "environment_lock",
            },
        ],
        "source_trees": [
            {
                "path": "source",
                "sha256": "de71886c2f4c0e7630d3c64731ec57bd248ff8128086f3681c7b884ce26b68a2",
                "file_count": 1,
            }
        ],
    }


def _write_manifest_fixture(tmp_path: Path) -> Path:
    raw_results = write_jsonl((_result(),), tmp_path / "results.jsonl")
    artifact = tmp_path / "protocol.json"
    artifact.write_text('{"frozen":true}\n', encoding="utf-8")
    environment_lock = tmp_path / "requirements-cpu.lock"
    environment_lock.write_bytes(_TEST_LOCK_BYTES)
    source = tmp_path / "source"
    source.mkdir()
    (source / "a.py").write_text("x=1\n", encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(_manifest_payload(raw_results, artifact, environment_lock)),
        encoding="utf-8",
    )
    return manifest


def test_manifest_verifier_accepts_hash_bound_complete_release(tmp_path: Path) -> None:
    manifest_path = _write_manifest_fixture(tmp_path)

    manifest = load_reproduction_manifest(manifest_path, tmp_path)
    verification = verify_reproduction_manifest(manifest, tmp_path)

    assert verification.passed is True
    assert verification.errors == ()
    assert verification.verified_artifacts == 4
    assert verification.track_counts == {"valuation": 1}


def test_reproduction_mode_allows_timing_only_raw_byte_difference(
    tmp_path: Path,
) -> None:
    manifest_path = _write_manifest_fixture(tmp_path)
    write_jsonl((_result(runtime_seconds=99.0),), tmp_path / "results.jsonl")
    manifest = load_reproduction_manifest(manifest_path, tmp_path)

    archive = verify_reproduction_manifest(manifest, tmp_path)
    reproduced = verify_reproduction_manifest(
        manifest, tmp_path, verification_mode="reproduction"
    )

    assert archive.passed is False
    assert any(error.startswith("hash_mismatch:results.jsonl") for error in archive.errors)
    assert reproduced.passed is True
    assert reproduced.errors == ()
    assert reproduced.non_scientific_differences == ("byte_hash:results.jsonl",)


def test_replication_result_set_rejects_science_change_but_allows_timing(
    tmp_path: Path,
) -> None:
    manifest_path = _write_manifest_fixture(tmp_path)
    replication_path = write_jsonl(
        (_result(run_id="replication", runtime_seconds=2.0),),
        tmp_path / "replication.jsonl",
    )
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["replication_scientific_results"] = {
        "path": replication_path.name,
        "sha256": _sha256(replication_path),
        "scientific_digest": scientific_result_digest(
            (_result(run_id="replication", runtime_seconds=2.0),)
        ),
        "row_count": 1,
        "status_counts": {"completed": 1},
        "track_counts": {"valuation": 1},
    }
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    write_jsonl(
        (_result(run_id="replication", runtime_seconds=99.0),),
        replication_path,
    )

    manifest = load_reproduction_manifest(manifest_path, tmp_path)
    timing_only = verify_reproduction_manifest(
        manifest, tmp_path, verification_mode="reproduction"
    )
    assert timing_only.passed is True
    assert "byte_hash:replication.jsonl" in timing_only.non_scientific_differences

    write_jsonl(
        (_result(run_id="replication", runtime_seconds=99.0, score=0.99),),
        replication_path,
    )
    changed = verify_reproduction_manifest(
        manifest, tmp_path, verification_mode="reproduction"
    )
    assert changed.passed is False
    assert any(
        error.startswith("replication_scientific_digest_mismatch:")
        for error in changed.errors
    )


def test_manifest_verifier_detects_source_tree_tampering(tmp_path: Path) -> None:
    manifest_path = _write_manifest_fixture(tmp_path)
    (tmp_path / "source" / "a.py").write_text("x=2\n", encoding="utf-8")

    verification = verify_reproduction_manifest(
        load_reproduction_manifest(manifest_path, tmp_path), tmp_path
    )

    assert verification.passed is False
    assert any(error.startswith("source_tree_hash_mismatch:source") for error in verification.errors)


@pytest.mark.parametrize(
    ("mutation", "expected_error"),
    [
        ("artifact_hash", "hash_mismatch:protocol.json"),
        ("scientific_digest", "scientific_digest_mismatch:results.jsonl"),
        ("row_count", "row_count_mismatch:expected=2:observed=1"),
        ("track_count", "track_counts_mismatch"),
        ("missing_file", "missing:missing.json"),
    ],
)
def test_manifest_verifier_fails_closed_on_tampering(
    tmp_path: Path, mutation: str, expected_error: str
) -> None:
    manifest_path = _write_manifest_fixture(tmp_path)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if mutation == "artifact_hash":
        payload["artifacts"][0]["sha256"] = "0" * 64
    elif mutation == "scientific_digest":
        payload["scientific_results"]["scientific_digest"] = "0" * 64
    elif mutation == "row_count":
        payload["scientific_results"]["row_count"] = 2
    elif mutation == "track_count":
        payload["scientific_results"]["track_counts"] = {"valuation": 2}
    elif mutation == "missing_file":
        payload["artifacts"][0]["path"] = "missing.json"
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    verification = verify_reproduction_manifest(
        load_reproduction_manifest(manifest_path, tmp_path), tmp_path
    )

    assert verification.passed is False
    assert any(error.startswith(expected_error) for error in verification.errors)


def test_manifest_verifier_rejects_missing_required_track(tmp_path: Path) -> None:
    manifest_path = _write_manifest_fixture(tmp_path)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["required_tracks"] = ["valuation", "trading"]
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    verification = verify_reproduction_manifest(
        load_reproduction_manifest(manifest_path, tmp_path), tmp_path
    )

    assert verification.passed is False
    assert "missing_required_tracks:trading" in verification.errors


@pytest.mark.parametrize("bad_hash", ["ABC", "g" * 64, "A" * 64])
def test_manifest_loader_rejects_noncanonical_sha256(
    tmp_path: Path, bad_hash: str
) -> None:
    manifest_path = _write_manifest_fixture(tmp_path)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["scientific_results"]["sha256"] = bad_hash
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="sha256"):
        load_reproduction_manifest(manifest_path, tmp_path)


def test_manifest_loader_rejects_repository_escape(tmp_path: Path) -> None:
    manifest_path = _write_manifest_fixture(tmp_path)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["artifacts"][0]["path"] = "../outside.json"
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="escapes repository root"):
        load_reproduction_manifest(manifest_path, tmp_path)


def test_manifest_loader_rejects_missing_artifact_path(tmp_path: Path) -> None:
    manifest_path = _write_manifest_fixture(tmp_path)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["artifacts"][0].pop("path")
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="path must be non-empty"):
        load_reproduction_manifest(manifest_path, tmp_path)


def _clean_room_record(
    manifest_path: Path,
    operator_id: str,
    *,
    scientific_digest: str | None = None,
) -> dict[str, object]:
    if scientific_digest is None:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        scientific_digest = str(
            manifest["scientific_results"]["scientific_digest"]
        )
    preflight = _native_environment_preflight()
    return {
        "schema_version": "1.1",
        "record_kind": "clean_room_reproduction",
        "status": "passed",
        "operator": {
            "operator_id": operator_id,
            "independent_of_implementation": True,
        },
        "environment": {
            "isolation": "fresh_venv",
            "os": "Linux",
            "python": "3.12.7",
            "preflight": preflight,
            "preflight_sha256": _canonical_json_sha256(preflight),
        },
        "execution": {
            "command": "python benchmark/scripts/reproduce_kdd_core.py --run",
            "exit_code": 0,
            "setup_minutes": 12.5,
        },
        "release": {
            "manifest_path": manifest_path.name,
            "manifest_sha256": _sha256(manifest_path),
            "scientific_digest": scientific_digest,
            "artifact_verification": "passed",
            "source_archive": {
                "url": "https://archive.example.org/datamechbench-v1.tar.gz",
                "sha256": "a" * 64,
            },
        },
        "tracks": ["valuation", "procurement", "trading"],
        "attestation": {
            "operator_confirmed": True,
            "no_source_modifications": True,
            "unexpected_differences": [],
        },
    }


def _canonical_json_sha256(payload: object) -> str:
    rendered = json.dumps(
        payload, ensure_ascii=False, indent=2, sort_keys=True
    ) + "\n"
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def _native_environment_preflight() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "report_kind": "native_python_environment_preflight",
        "passed": True,
        "runtime_kind": "native_python_source_library",
        "container_or_vm_image_required": False,
        "lock_file": "benchmark/reproduction/requirements-cpu.lock",
        "lock_sha256": _TEST_LOCK_SHA256,
        "repository_root": ".",
        "python_version": "3.12.7",
        "reference_python": "3.12.7",
        "minimum_python": "3.10.0",
        "system": "Linux",
        "machine": "x86_64",
        "package_counts": {"matched": 2, "mismatched": 0, "missing": 0},
        "packages": [
            {
                "name": "numpy",
                "expected": "2.3.5",
                "observed": "2.3.5",
                "status": "matched",
            },
            {
                "name": "PyYAML",
                "expected": "6.0.2",
                "observed": "6.0.2",
                "status": "matched",
            },
        ],
        "errors": [],
        "warnings": [],
    }


def _write_clean_record(tmp_path: Path, name: str, payload: dict[str, object]) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_clean_room_audit_requires_two_distinct_independent_operators(
    tmp_path: Path,
) -> None:
    manifest_path = _write_manifest_fixture(tmp_path)
    first = _write_clean_record(
        tmp_path, "operator-a.json", _clean_room_record(manifest_path, "operator-a")
    )
    second = _write_clean_record(
        tmp_path, "operator-b.json", _clean_room_record(manifest_path, "operator-b")
    )

    audit = audit_clean_room_records(
        (first.name, second.name),
        tmp_path,
        manifest_path.name,
        required_operators=2,
        expected_archive_url="https://archive.example.org/datamechbench-v1.tar.gz",
        expected_archive_sha256="a" * 64,
    )

    assert audit.passed is True
    assert audit.errors == ()
    assert audit.operator_ids == ("operator-a", "operator-b")
    assert audit.covered_tracks == ("procurement", "trading", "valuation")


@pytest.mark.parametrize(
    ("mutation", "expected_error"),
    [
        ("template", "record_not_passed"),
        ("self_authored", "operator_not_independent"),
        ("partial_tracks", "missing_tracks:trading"),
        ("wrong_manifest_hash", "manifest_hash_mismatch"),
        ("wrong_scientific_digest", "scientific_digest_mismatch"),
        ("not_isolated", "invalid_isolation"),
        ("nonzero_exit", "nonzero_exit_code"),
        ("missing_setup_time", "invalid_setup_minutes"),
        ("missing_attestation", "invalid_attestation"),
        ("missing_preflight", "missing_environment_preflight"),
        ("failed_preflight", "environment_preflight_not_passed"),
        ("container_preflight", "environment_preflight_not_native"),
        ("wrong_preflight_hash", "environment_preflight_hash_mismatch"),
        ("wrong_lock_hash", "environment_preflight_lock_hash_mismatch"),
        ("unredacted_preflight_paths", "environment_preflight_paths_not_normalized"),
        ("wrong_archive_url", "source_archive_url_mismatch"),
        ("wrong_archive_hash", "source_archive_hash_mismatch"),
    ],
)
def test_clean_room_audit_rejects_unverifiable_records(
    tmp_path: Path, mutation: str, expected_error: str
) -> None:
    manifest_path = _write_manifest_fixture(tmp_path)
    payload = _clean_room_record(manifest_path, "operator-a")
    if mutation == "template":
        payload["status"] = "template"
    elif mutation == "self_authored":
        payload["operator"]["independent_of_implementation"] = False
    elif mutation == "partial_tracks":
        payload["tracks"] = ["valuation", "procurement"]
    elif mutation == "wrong_manifest_hash":
        payload["release"]["manifest_sha256"] = "0" * 64
    elif mutation == "wrong_scientific_digest":
        payload["release"]["scientific_digest"] = "0" * 64
    elif mutation == "not_isolated":
        payload["environment"]["isolation"] = "developer_checkout"
    elif mutation == "nonzero_exit":
        payload["execution"]["exit_code"] = 1
    elif mutation == "missing_setup_time":
        payload["execution"].pop("setup_minutes")
    elif mutation == "missing_attestation":
        payload["attestation"]["operator_confirmed"] = False
    elif mutation == "missing_preflight":
        payload["environment"].pop("preflight")
    elif mutation == "failed_preflight":
        payload["environment"]["preflight"]["passed"] = False
        payload["environment"]["preflight"]["errors"] = ["package_missing:numpy"]
        payload["environment"]["preflight_sha256"] = _canonical_json_sha256(
            payload["environment"]["preflight"]
        )
    elif mutation == "container_preflight":
        payload["environment"]["preflight"]["runtime_kind"] = "container_image"
        payload["environment"]["preflight"]["container_or_vm_image_required"] = True
        payload["environment"]["preflight_sha256"] = _canonical_json_sha256(
            payload["environment"]["preflight"]
        )
    elif mutation == "wrong_preflight_hash":
        payload["environment"]["preflight_sha256"] = "0" * 64
    elif mutation == "wrong_lock_hash":
        payload["environment"]["preflight"]["lock_sha256"] = "c" * 64
        payload["environment"]["preflight_sha256"] = _canonical_json_sha256(
            payload["environment"]["preflight"]
        )
    elif mutation == "unredacted_preflight_paths":
        payload["environment"]["preflight"]["repository_root"] = (
            "/home/private-operator/DataMechBench"
        )
        payload["environment"]["preflight"]["lock_file"] = (
            "/home/private-operator/DataMechBench/benchmark/reproduction/requirements-cpu.lock"
        )
        payload["environment"]["preflight_sha256"] = _canonical_json_sha256(
            payload["environment"]["preflight"]
        )
    elif mutation == "wrong_archive_url":
        payload["release"]["source_archive"]["url"] = "https://example.org/other.tar.gz"
    elif mutation == "wrong_archive_hash":
        payload["release"]["source_archive"]["sha256"] = "0" * 64
    record = _write_clean_record(tmp_path, "operator-a.json", payload)

    audit = audit_clean_room_records(
        (record.name,),
        tmp_path,
        manifest_path.name,
        required_operators=1,
        expected_archive_url="https://archive.example.org/datamechbench-v1.tar.gz",
        expected_archive_sha256="a" * 64,
    )

    assert audit.passed is False
    assert any(expected_error in error for error in audit.errors)


def test_clean_room_audit_does_not_double_count_duplicate_operator(
    tmp_path: Path,
) -> None:
    manifest_path = _write_manifest_fixture(tmp_path)
    first = _write_clean_record(
        tmp_path, "run-1.json", _clean_room_record(manifest_path, "same-operator")
    )
    second = _write_clean_record(
        tmp_path, "run-2.json", _clean_room_record(manifest_path, "same-operator")
    )

    audit = audit_clean_room_records(
        (first.name, second.name),
        tmp_path,
        manifest_path.name,
        required_operators=2,
        expected_archive_url="https://archive.example.org/datamechbench-v1.tar.gz",
        expected_archive_sha256="a" * 64,
    )

    assert audit.passed is False
    assert "duplicate_operator:same-operator" in audit.errors
    assert "insufficient_independent_operators:required=2:observed=1" in audit.errors


def test_clean_room_record_creator_produces_auditable_passed_record(
    tmp_path: Path,
) -> None:
    manifest_path = _write_manifest_fixture(tmp_path)
    manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_payload["required_tracks"] = ["valuation", "procurement", "trading"]
    manifest_path.write_text(json.dumps(manifest_payload), encoding="utf-8")

    preflight = _native_environment_preflight()
    preflight["repository_root"] = "/home/private-operator/DataMechBench"
    preflight["lock_file"] = (
        "/home/private-operator/DataMechBench/benchmark/reproduction/requirements-cpu.lock"
    )
    record = create_clean_room_record(
        manifest_path.name,
        tmp_path,
        operator_id="operator-a",
        independent_of_implementation=True,
        isolation="fresh_venv",
        os_description="ExampleOS 1.0",
        python_version="3.12.7",
        command="python benchmark/scripts/reproduce_kdd_core.py --run",
        exit_code=0,
        setup_minutes=4.5,
        artifact_verification_passed=True,
        observed_scientific_digest=manifest_payload["scientific_results"][
            "scientific_digest"
        ],
        operator_confirmed=True,
        no_source_modifications=True,
        unexpected_differences=(),
        source_archive_url="https://archive.example.org/datamechbench-v1.tar.gz",
        source_archive_sha256="a" * 64,
        environment_preflight=preflight,
    )
    record_path = tmp_path / "operator-a.json"
    record_path.write_text(json.dumps(record), encoding="utf-8")

    audit = audit_clean_room_records(
        (record_path.name,),
        tmp_path,
        manifest_path.name,
        required_operators=1,
        expected_archive_url="https://archive.example.org/datamechbench-v1.tar.gz",
        expected_archive_sha256="a" * 64,
    )

    assert record["status"] == "passed"
    assert record["release"]["artifact_verification"] == "passed"
    assert record["environment"]["preflight"]["repository_root"] == "."
    assert record["environment"]["preflight"]["lock_file"] == (
        "benchmark/reproduction/requirements-cpu.lock"
    )
    assert "private-operator" not in json.dumps(record)
    assert audit.passed is True


def test_clean_room_record_rejects_vm_image_workflow(tmp_path: Path) -> None:
    """Clean-room evidence must use the published Python library workflow."""

    manifest_path = _write_manifest_fixture(tmp_path)
    manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))

    with pytest.raises(ValueError, match="unsupported isolation mode: fresh_vm"):
        create_clean_room_record(
            manifest_path.name,
            tmp_path,
            operator_id="operator-a",
            independent_of_implementation=True,
            isolation="fresh_vm",
            os_description="ExampleOS 1.0",
            python_version="3.12.7",
            command="python benchmark/scripts/reproduce_kdd_core.py --run",
            exit_code=0,
            setup_minutes=4.5,
            artifact_verification_passed=True,
            observed_scientific_digest=manifest_payload["scientific_results"][
                "scientific_digest"
            ],
            operator_confirmed=True,
            no_source_modifications=True,
            unexpected_differences=(),
            source_archive_url="https://archive.example.org/datamechbench-v1.tar.gz",
            source_archive_sha256="a" * 64,
            environment_preflight=_native_environment_preflight(),
        )


def test_clean_room_record_rejects_placeholder_archive_url(tmp_path: Path) -> None:
    manifest_path = _write_manifest_fixture(tmp_path)
    manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))

    with pytest.raises(
        ValueError, match="source_archive_url must be a non-placeholder HTTPS URL"
    ):
        create_clean_room_record(
            manifest_path.name,
            tmp_path,
            operator_id="operator-a",
            independent_of_implementation=True,
            isolation="fresh_venv",
            os_description="ExampleOS 1.0",
            python_version="3.12.7",
            command="python benchmark/scripts/reproduce_kdd_core.py --run",
            exit_code=0,
            setup_minutes=4.5,
            artifact_verification_passed=True,
            observed_scientific_digest=manifest_payload["scientific_results"][
                "scientific_digest"
            ],
            operator_confirmed=True,
            no_source_modifications=True,
            unexpected_differences=(),
            source_archive_url="https://<public-host>/<archive>",
            source_archive_sha256="a" * 64,
            environment_preflight=_native_environment_preflight(),
        )


@pytest.mark.parametrize(
    ("mutation", "expected_status"),
    [
        ("internal_operator", "draft"),
        ("unconfirmed", "draft"),
        ("source_modified", "draft"),
        ("unexpected_difference", "draft"),
        ("failed_execution", "failed"),
        ("digest_mismatch", "failed"),
    ],
)
def test_clean_room_record_creator_fails_closed(
    tmp_path: Path, mutation: str, expected_status: str
) -> None:
    manifest_path = _write_manifest_fixture(tmp_path)
    manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    values: dict[str, object] = {
        "independent_of_implementation": True,
        "operator_confirmed": True,
        "no_source_modifications": True,
        "unexpected_differences": (),
        "exit_code": 0,
        "artifact_verification_passed": True,
        "observed_scientific_digest": manifest_payload["scientific_results"][
            "scientific_digest"
        ],
    }
    if mutation == "internal_operator":
        values["independent_of_implementation"] = False
    elif mutation == "unconfirmed":
        values["operator_confirmed"] = False
    elif mutation == "source_modified":
        values["no_source_modifications"] = False
    elif mutation == "unexpected_difference":
        values["unexpected_differences"] = ("generated table differs",)
    elif mutation == "failed_execution":
        values["exit_code"] = 1
        values["artifact_verification_passed"] = False
    elif mutation == "digest_mismatch":
        values["observed_scientific_digest"] = "0" * 64

    record = create_clean_room_record(
        manifest_path.name,
        tmp_path,
        operator_id="operator-a",
        isolation="fresh_venv",
        os_description="ExampleOS 1.0",
        python_version="3.12.7",
        command="python benchmark/scripts/reproduce_kdd_core.py --run",
        setup_minutes=2.0,
        source_archive_url="https://archive.example.org/datamechbench-v1.tar.gz",
        source_archive_sha256="a" * 64,
        environment_preflight=_native_environment_preflight(),
        **values,
    )

    assert record["status"] == expected_status


def test_reproduction_cli_writes_operator_record_only_after_full_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest_path = _write_manifest_fixture(tmp_path)
    module = _load_reproduce_script()
    monkeypatch.setattr(module, "_run_pipeline", lambda *args, **kwargs: None)
    report_path = tmp_path / "verification.json"
    record_path = tmp_path / "operator.json"
    preflight_path = tmp_path / "environment-preflight.json"
    preflight = _native_environment_preflight()
    preflight["python_version"] = module.platform.python_version()
    preflight_path.write_text(json.dumps(preflight), encoding="utf-8")

    exit_code = module.main(
        [
            "--run",
            "--manifest",
            manifest_path.name,
            "--repository-root",
            str(tmp_path),
            "--report",
            str(report_path),
            "--operator-record",
            str(record_path),
            "--operator-id",
            "operator-a",
            "--isolation",
            "fresh_venv",
            "--setup-minutes",
            "3.25",
            "--source-archive-url",
            "https://archive.example.org/datamechbench-v1.tar.gz",
            "--source-archive-sha256",
            "a" * 64,
            "--environment-preflight",
            str(preflight_path),
            "--attest-independent-of-implementation",
            "--attest-no-source-modifications",
            "--attest-no-unexpected-differences",
        ]
    )
    record = json.loads(record_path.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert record["status"] == "passed"
    assert record["operator"]["operator_id"] == "operator-a"
    assert record["execution"]["setup_minutes"] == 3.25
    assert record["release"]["scientific_digest"] == (
        json.loads(manifest_path.read_text(encoding="utf-8"))["scientific_results"][
            "scientific_digest"
        ]
    )
    assert record["schema_version"] == "1.1"
    assert record["release"]["source_archive"]["sha256"] == "a" * 64
    assert record["environment"]["preflight"]["passed"] is True
    assert str(tmp_path) not in record["execution"]["command"]
    assert sys.executable not in record["execution"]["command"]
    assert record["execution"]["command"].startswith(
        "python benchmark/scripts/reproduce_kdd_core.py --run"
    )


def test_reproduction_cli_requires_public_source_and_preflight_for_operator_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest_path = _write_manifest_fixture(tmp_path)
    module = _load_reproduce_script()
    monkeypatch.setattr(module, "_run_pipeline", lambda *args, **kwargs: None)

    with pytest.raises(SystemExit, match="2"):
        module.main(
            [
                "--run",
                "--manifest",
                manifest_path.name,
                "--repository-root",
                str(tmp_path),
                "--report",
                str(tmp_path / "verification.json"),
                "--operator-record",
                str(tmp_path / "operator.json"),
                "--operator-id",
                "operator-a",
                "--isolation",
                "fresh_venv",
                "--setup-minutes",
                "1.0",
            ]
        )

    error = capsys.readouterr().err
    assert "--source-archive-url" in error
    assert "--source-archive-sha256" in error
    assert "--environment-preflight" in error


def test_reproduction_cli_preserves_failed_operator_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest_path = _write_manifest_fixture(tmp_path)
    module = _load_reproduce_script()
    monkeypatch.setattr(
        module,
        "_run_pipeline",
        lambda *args, **kwargs: "heldout_runner_exit_code:7",
    )
    report_path = tmp_path / "verification.json"
    record_path = tmp_path / "operator.json"
    preflight_path = tmp_path / "environment-preflight.json"
    preflight = _native_environment_preflight()
    preflight["python_version"] = module.platform.python_version()
    preflight_path.write_text(json.dumps(preflight), encoding="utf-8")

    exit_code = module.main(
        [
            "--run",
            "--manifest",
            manifest_path.name,
            "--repository-root",
            str(tmp_path),
            "--report",
            str(report_path),
            "--operator-record",
            str(record_path),
            "--operator-id",
            "operator-a",
            "--isolation",
            "fresh_venv",
            "--setup-minutes",
            "1.0",
            "--source-archive-url",
            "https://archive.example.org/datamechbench-v1.tar.gz",
            "--source-archive-sha256",
            "a" * 64,
            "--environment-preflight",
            str(preflight_path),
            "--attest-independent-of-implementation",
            "--attest-no-source-modifications",
            "--attest-no-unexpected-differences",
        ]
    )
    record = json.loads(record_path.read_text(encoding="utf-8"))

    assert exit_code == 1
    assert record["status"] == "failed"
    assert record["execution"]["exit_code"] == 1
    assert record["release"]["artifact_verification"] == "failed"


def _run_reproduction_cli(tmp_path: Path, manifest_path: Path) -> subprocess.CompletedProcess[str]:
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(REPOSITORY_ROOT / "benchmark" / "src")
    return subprocess.run(
        [
            sys.executable,
            str(REPRODUCE_SCRIPT),
            "--verify-only",
            "--manifest",
            manifest_path.name,
            "--repository-root",
            str(tmp_path),
            "--report",
            str(tmp_path / "verification.json"),
        ],
        cwd=REPOSITORY_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )


def test_reproduction_cli_verifies_without_claiming_independence(tmp_path: Path) -> None:
    manifest_path = _write_manifest_fixture(tmp_path)

    completed = _run_reproduction_cli(tmp_path, manifest_path)
    report = json.loads((tmp_path / "verification.json").read_text(encoding="utf-8"))

    assert completed.returncode == 0, completed.stderr
    assert report["passed"] is True
    assert report["evidence_class"] == "internal_artifact_verification"
    assert report["independent_reproduction"] is False
    assert report["mode"] == "verify_only"


def test_reproduction_cli_returns_nonzero_when_artifact_is_tampered(
    tmp_path: Path,
) -> None:
    manifest_path = _write_manifest_fixture(tmp_path)
    (tmp_path / "protocol.json").write_text("tampered\n", encoding="utf-8")

    completed = _run_reproduction_cli(tmp_path, manifest_path)
    report = json.loads((tmp_path / "verification.json").read_text(encoding="utf-8"))

    assert completed.returncode == 1
    assert report["passed"] is False
    assert any(error.startswith("hash_mismatch:protocol.json") for error in report["errors"])


def test_run_pipeline_orders_heldout_incentive_and_paper_builds() -> None:
    module = _load_reproduce_script()
    observed: list[tuple[str, tuple[str, ...]]] = []

    def fake_run(command, **kwargs):
        del kwargs
        observed.append((Path(command[1]).name, tuple(command[2:])))
        return SimpleNamespace(returncode=0)

    failure = module._run_pipeline(REPOSITORY_ROOT, {"PYTHONPATH": "x"}, runner=fake_run)

    assert failure is None
    assert observed == [
        ("run_kdd_heldout_confirmation.py", ()),
        (
            "run_kdd_heldout_confirmation.py",
            (
                "--config", "benchmark/configs/kdd_heldout_replication_v2.yaml",
                "--protocol", "benchmark/evidence/kdd_heldout_replication_protocol_v1.json",
                "--output", "benchmark/outputs/kdd_heldout_replication_v2",
                "--manifest", "benchmark/evidence/kdd_heldout_replication_v2.json",
                "--data-root", "benchmark/data/replication_v2",
                "--run-name", "datamechbench-kdd-heldout-replication-v2",
            ),
        ),
        ("build_kdd_replication_report.py", ()),
        ("run_kdd_finite_incentives.py", ()),
        ("run_trading_geometry_study.py", ("--build",)),
        ("run_aggregate_type_envelope.py", ("--build",)),
        ("build_dadada_market_calibration.py", ("--verify",)),
        ("run_direct_market_transfer.py", ("--build",)),
        ("run_external_shapley_validation.py", ("--build",)),
        ("run_external_mcafee_validation.py", ("--build",)),
        ("run_external_sbba_validation.py", ("--build",)),
        ("run_triple_eagle_extension.py", ("--build",)),
        ("run_bfm_vm_extension.py", ("--build",)),
            ("build_market_semantic_alignment.py", ()),
            ("build_qualification_analysis.py", ()),
            ("run_induced_value_gold.py", ()),
            ("build_benchmark_metrology.py", ()),
            ("build_source_hierarchy_audit.py", ()),
            ("build_discriminability_audit.py", ()),
            ("build_pairwise_transfer_audit.py", ()),
            ("build_resource_and_incidence.py", ()),
            ("run_diagnostic_challenge_panel.py", ()),
            ("build_resolution_envelope.py", ()),
            ("audit_external_assets.py", ()),
            ("build_independent_validity.py", ()),
        ("build_decision_impact.py", ("--build",)),
        ("build_mechanism_risk_cards.py", ("--build",)),
    ]


def test_frozen_core_manifest_binds_trading_geometry_evidence() -> None:
    payload = json.loads(
        (
            REPOSITORY_ROOT
            / "benchmark"
            / "reproduction"
            / "kdd2027_core_manifest.json"
        ).read_text(encoding="utf-8")
    )
    artifacts = {item["path"]: item["role"] for item in payload["artifacts"]}

    assert artifacts["benchmark/catalog/trading_geometry_study.yaml"] == (
        "exploratory_study_protocol"
    )
    assert artifacts["benchmark/outputs/kdd_trading_geometry/manifest.json"] == (
        "exploratory_study_manifest"
    )
    assert artifacts["benchmark/outputs/kdd_trading_geometry/findings.json"] == (
        "exploratory_study_findings"
    )
    assert artifacts["benchmark/outputs/kdd_trading_geometry/raw_runs.jsonl"] == (
        "exploratory_study_results"
    )


def test_frozen_core_manifest_binds_outcome_semantic_and_qualification_evidence() -> None:
    payload = json.loads(
        (
            REPOSITORY_ROOT
            / "benchmark"
            / "reproduction"
            / "kdd2027_core_manifest.json"
        ).read_text(encoding="utf-8")
    )
    artifacts = {item["path"]: item["role"] for item in payload["artifacts"]}

    expected = {
        "benchmark/outputs/kdd_heldout_confirmatory/reference_outcome_audit.json": "reference_outcome_audit",
        "benchmark/outputs/kdd_heldout_replication_v2/reference_outcome_audit.json": "replication_reference_outcome_audit",
        "benchmark/outputs/kdd_market_semantics/market_semantic_alignment.json": "market_semantic_alignment",
        "benchmark/outputs/kdd_market_semantics/evidence_layers.csv": "market_semantic_layer_table",
        "benchmark/outputs/kdd_qualification_analysis/summary.json": "qualification_analysis_summary",
        "benchmark/outputs/kdd_qualification_analysis/method_failure_decomposition.csv": "qualification_failure_table",
        "benchmark/outputs/kdd_qualification_analysis/minimum_relaxation_frontier.csv": "qualification_relaxation_frontier",
    }
    for path, role in expected.items():
        assert artifacts[path] == role


def test_frozen_core_manifest_binds_aggregate_type_envelope_evidence() -> None:
    """Keep the grouped-type sensitivity evidence behind claim F11 runnable."""

    payload = json.loads(
        (
            REPOSITORY_ROOT
            / "benchmark"
            / "reproduction"
            / "kdd2027_core_manifest.json"
        ).read_text(encoding="utf-8")
    )
    artifacts = {item["path"]: item["role"] for item in payload["artifacts"]}

    expected = {
        "benchmark/scripts/run_aggregate_type_envelope.py": "aggregate_type_envelope_runner",
        "benchmark/catalog/aggregate_type_envelope.yaml": "aggregate_type_envelope_protocol",
        "benchmark/docs/aggregate_type_envelope_study.md": "aggregate_type_envelope_documentation",
        "benchmark/outputs/kdd_aggregate_type_envelope/raw_runs.jsonl": "aggregate_type_envelope_results",
        "benchmark/outputs/kdd_aggregate_type_envelope/profile_method_summary.csv": "aggregate_type_envelope_profile_table",
        "benchmark/outputs/kdd_aggregate_type_envelope/method_robustness_summary.csv": "aggregate_type_envelope_method_table",
        "benchmark/outputs/kdd_aggregate_type_envelope/headline_regret_summary.csv": "aggregate_type_envelope_regret_table",
        "benchmark/outputs/kdd_aggregate_type_envelope/rank_reversals.csv": "aggregate_type_envelope_reversals",
        "benchmark/outputs/kdd_aggregate_type_envelope/all_method_rank_reversals.csv": "aggregate_type_envelope_all_reversals",
        "benchmark/outputs/kdd_aggregate_type_envelope/point_selection_transfer.csv": "aggregate_type_envelope_transfer_table",
        "benchmark/outputs/kdd_aggregate_type_envelope/selection_view_profile.csv": "aggregate_type_envelope_selection_profile",
        "benchmark/outputs/kdd_aggregate_type_envelope/selection_view_summary.csv": "aggregate_type_envelope_selection_summary",
        "benchmark/outputs/kdd_aggregate_type_envelope/joint_admissibility.csv": "aggregate_type_envelope_joint_admissibility",
        "benchmark/outputs/kdd_aggregate_type_envelope/admissibility_relaxation_frontier.csv": "aggregate_type_envelope_admissibility_frontier",
        "benchmark/outputs/kdd_aggregate_type_envelope/findings.json": "aggregate_type_envelope_findings",
        "benchmark/outputs/kdd_aggregate_type_envelope/report.md": "aggregate_type_envelope_report",
        "benchmark/outputs/kdd_aggregate_type_envelope/manifest.json": "aggregate_type_envelope_manifest",
    }
    for path, role in expected.items():
        assert artifacts[path] == role


def test_frozen_core_manifest_binds_external_sbba_specialization_evidence() -> None:
    payload = json.loads(
        (
            REPOSITORY_ROOT
            / "benchmark"
            / "reproduction"
            / "kdd2027_core_manifest.json"
        ).read_text(encoding="utf-8")
    )
    artifacts = {item["path"]: item["role"] for item in payload["artifacts"]}

    assert artifacts[
        "benchmark/scripts/run_external_sbba_validation.py"
    ] == "external_implementation_validation_runner"
    assert artifacts[
        "benchmark/external/erelsgl_auctions/trade_reduction_protocol.py"
    ] == "external_implementation_source"
    assert artifacts[
        "benchmark/external/erelsgl_auctions/sbba_fixtures.json"
    ] == "external_implementation_fixtures"
    assert artifacts[
        "benchmark/evidence/external_erelsgl_sbba_v1.json"
    ] == "external_implementation_validation_record"
    assert artifacts[
        "benchmark/evidence/external_erelsgl_sbba_results_v1.json"
    ] == "external_implementation_validation_results"


def test_frozen_core_manifest_binds_external_exact_shapley_evidence() -> None:
    payload = json.loads(
        (
            REPOSITORY_ROOT
            / "benchmark"
            / "reproduction"
            / "kdd2027_core_manifest.json"
        ).read_text(encoding="utf-8")
    )
    artifacts = {item["path"]: item["role"] for item in payload["artifacts"]}

    assert artifacts[
        "benchmark/scripts/run_external_shapley_validation.py"
    ] == "external_implementation_validation_runner"
    assert artifacts[
        "benchmark/external/svarm_official/ApproxMethods/GroundTruth/ExhaustiveSearch.py"
    ] == "external_implementation_source"
    assert artifacts[
        "benchmark/external/svarm_official/exact_shapley_fixtures.json"
    ] == "external_implementation_fixtures"
    assert artifacts[
        "benchmark/evidence/external_svarm_exact_shapley_v1.json"
    ] == "external_implementation_validation_record"
    assert artifacts[
        "benchmark/evidence/external_svarm_exact_shapley_results_v1.json"
    ] == "external_implementation_validation_results"


def test_frozen_core_manifest_is_a_python_only_release() -> None:
    payload = json.loads(
        (
            REPOSITORY_ROOT
            / "benchmark"
            / "reproduction"
            / "kdd2027_core_manifest.json"
        ).read_text(encoding="utf-8")
    )
    artifacts = {item["path"]: item["role"] for item in payload["artifacts"]}

    assert "benchmark/reproduction/Dockerfile" not in artifacts
    assert "benchmark/.dockerignore" not in artifacts


def test_frozen_core_manifest_binds_separate_v2_replication_evidence() -> None:
    payload = json.loads(
        (
            REPOSITORY_ROOT
            / "benchmark"
            / "reproduction"
            / "kdd2027_core_manifest.json"
        ).read_text(encoding="utf-8")
    )
    artifacts = {item["path"]: item["role"] for item in payload["artifacts"]}

    expected = {
        "benchmark/configs/kdd_heldout_replication_v2.yaml": "replication_protocol_config",
        "benchmark/evidence/kdd_heldout_replication_protocol_v1.json": "replication_protocol",
        "benchmark/evidence/kdd_heldout_replication_v2.json": "replication_evidence",
        "benchmark/scripts/build_kdd_replication_report.py": "replication_report_builder",
        "benchmark/outputs/kdd_heldout_replication_v2/confirmatory_contrasts.json": "replication_contrasts",
        "benchmark/outputs/kdd_heldout_replication_v2/replication_comparisons.json": "replication_comparisons",
        "benchmark/outputs/kdd_heldout_replication_v2/replication_block_effects.csv": "replication_block_effects",
        "benchmark/outputs/kdd_heldout_replication_v2/replication_summary.json": "replication_summary",
        "benchmark/outputs/kdd_heldout_replication_v2/replication_report.md": "replication_report",
        "benchmark/outputs/kdd_heldout_replication_v2/replication_manifest.json": "replication_manifest",
    }
    for path, role in expected.items():
        assert artifacts[path] == role
    assert payload["replication_scientific_results"]["path"] == (
        "benchmark/outputs/kdd_heldout_replication_v2/raw_results.jsonl"
    )
    assert payload["replication_scientific_results"]["row_count"] == 140


def test_frozen_core_manifest_binds_direct_listing_support_without_raw_csv() -> None:
    payload = json.loads(
        (
            REPOSITORY_ROOT
            / "benchmark"
            / "reproduction"
            / "kdd2027_core_manifest.json"
        ).read_text(encoding="utf-8")
    )
    artifacts = {item["path"]: item["role"] for item in payload["artifacts"]}

    expected = {
        "benchmark/catalog/dadada_market_calibration.yaml": "direct_market_calibration_protocol",
        "benchmark/scripts/build_dadada_market_calibration.py": "direct_market_calibration_builder",
        "benchmark/scripts/run_direct_market_transfer.py": "direct_market_transfer_runner",
        "benchmark/data/market_calibration/dadada_source_receipt.json": "external_source_receipt",
        "benchmark/data/market_calibration/dadada_price_profiles.json": "processed_direct_market_support",
        "benchmark/outputs/kdd_direct_market_transfer/raw_runs.jsonl": "direct_market_transfer_results",
        "benchmark/outputs/kdd_direct_market_transfer/cohort_method_summary.csv": "direct_market_transfer_table",
        "benchmark/outputs/kdd_direct_market_transfer/method_summary.csv": "direct_market_transfer_table",
        "benchmark/outputs/kdd_direct_market_transfer/transfer_contrasts.csv": "direct_market_transfer_table",
        "benchmark/outputs/kdd_direct_market_transfer/findings.json": "direct_market_transfer_findings",
        "benchmark/outputs/kdd_direct_market_transfer/report.md": "direct_market_transfer_report",
        "benchmark/outputs/kdd_direct_market_transfer/manifest.json": "direct_market_transfer_manifest",
    }
    for path, role in expected.items():
        assert artifacts[path] == role
    assert all(not path.endswith("final_data.csv") for path in artifacts)
    assert "dadada-final_data.csv" not in json.dumps(payload)


def test_frozen_core_manifest_binds_triple_eagle_exploratory_extension() -> None:
    payload = json.loads(
        (
            REPOSITORY_ROOT
            / "benchmark"
            / "reproduction"
            / "kdd2027_core_manifest.json"
        ).read_text(encoding="utf-8")
    )
    artifacts = {item["path"]: item["role"] for item in payload["artifacts"]}

    expected = {
        "benchmark/catalog/qualification.yaml": "result_qualification_policy",
        "benchmark/configs/kdd_triple_eagle_extension.yaml": "exploratory_study_protocol",
        "benchmark/configs/kdd_triple_eagle_baseline_completion.yaml": "exploratory_study_protocol",
        "benchmark/docs/reference_fidelity_triple_eagle.md": "mechanism_fidelity_audit",
        "benchmark/docs/procurement_external_implementation_search.md": "external_code_search_audit",
        "benchmark/scripts/run_triple_eagle_extension.py": "exploratory_study_runner",
        "benchmark/outputs/kdd_triple_eagle_extension/raw_results.jsonl": "exploratory_study_results",
        "benchmark/outputs/full/raw_results.jsonl": "exploratory_study_baseline_results",
        "benchmark/outputs/kdd_triple_eagle_baseline_completion/raw_results.jsonl": "exploratory_study_baseline_completion",
        "benchmark/outputs/kdd_triple_eagle_extension/analysis/manifest.json": "exploratory_study_manifest",
        "benchmark/outputs/kdd_triple_eagle_extension/analysis/report.md": "exploratory_study_report",
        "benchmark/outputs/kdd_triple_eagle_extension/analysis/randomization_audit.csv": "exploratory_study_table",
        "benchmark/outputs/kdd_triple_eagle_extension/analysis/variant_comparison.csv": "exploratory_study_table",
        "benchmark/outputs/kdd_triple_eagle_extension/analysis/theorem_claim_audit.csv": "exploratory_study_table",
    }
    for path, role in expected.items():
        assert artifacts[path] == role


def test_frozen_core_manifest_binds_bfm_vm_post_freeze_extension() -> None:
    """Prevent the new paper/source discrepancy evidence from being omitted."""

    payload = json.loads(
        (
            REPOSITORY_ROOT
            / "benchmark"
            / "reproduction"
            / "kdd2027_core_manifest.json"
        ).read_text(encoding="utf-8")
    )
    artifacts = {item["path"]: item["role"] for item in payload["artifacts"]}
    expected = {
        "benchmark/configs/kdd_bfm_vm_extension.yaml": "exploratory_study_protocol",
        "benchmark/docs/reference_fidelity_bfm_vm.md": "mechanism_fidelity_audit",
        "benchmark/evidence/bfm_vm_source_audit_v1.json": "external_source_audit",
        "benchmark/scripts/audit_bfm_vm_source.py": "external_source_audit_runner",
        "benchmark/scripts/run_bfm_vm_extension.py": "exploratory_study_runner",
        "benchmark/outputs/kdd_bfm_vm_extension/raw_results.jsonl": "exploratory_study_results",
        "benchmark/outputs/kdd_bfm_vm_extension/analysis/manifest.json": "exploratory_study_manifest",
        "benchmark/outputs/kdd_bfm_vm_extension/analysis/report.md": "exploratory_study_report",
        "benchmark/outputs/kdd_bfm_vm_extension/analysis/method_setting_summary.csv": "exploratory_study_table",
        "benchmark/outputs/kdd_bfm_vm_extension/analysis/bfm_vm_paired_oracle_ratio.csv": "exploratory_study_table",
        "benchmark/outputs/kdd_bfm_vm_extension/analysis/bfm_vm_constraint_audit.csv": "exploratory_study_table",
    }
    for path, role in expected.items():
        assert artifacts[path] == role


def test_frozen_core_manifest_binds_external_submission_template() -> None:
    """Catch a release that documents submissions but omits its runnable template."""

    payload = json.loads(
        (
            REPOSITORY_ROOT
            / "benchmark"
            / "reproduction"
            / "kdd2027_core_manifest.json"
        ).read_text(encoding="utf-8")
    )
    artifacts = {item["path"]: item["role"] for item in payload["artifacts"]}

    assert artifacts["benchmark/submission_template/submission.yaml"] == (
        "external_submission_template_metadata"
    )
    assert artifacts["benchmark/submission_template/results.jsonl"] == (
        "external_submission_template_results"
    )
    assert artifacts["benchmark/catalog/benchmark_release.yaml"] == (
        "benchmark_release_contract"
    )


def test_frozen_core_manifest_binds_open_case_admission_template() -> None:
    """Catch a release that exposes case admission without its audited example."""

    payload = json.loads(
        (
            REPOSITORY_ROOT
            / "benchmark"
            / "reproduction"
            / "kdd2027_core_manifest.json"
        ).read_text(encoding="utf-8")
    )
    artifacts = {item["path"]: item["role"] for item in payload["artifacts"]}
    expected = {
        "benchmark/case_submission_template/case_submission.yaml": (
            "open_case_admission_template_metadata"
        ),
        "benchmark/case_submission_template/source_snapshot.json": (
            "open_case_admission_template_source"
        ),
        "benchmark/case_submission_template/transform_case.py": (
            "open_case_admission_template_transform"
        ),
    }

    for path, role in expected.items():
        assert artifacts[path] == role


def test_frozen_core_manifest_binds_decision_impact_artifacts() -> None:
    """Catch release candidates that omit the evidence behind paper claim F9."""

    payload = json.loads(
        (
            REPOSITORY_ROOT
            / "benchmark"
            / "reproduction"
            / "kdd2027_core_manifest.json"
        ).read_text(encoding="utf-8")
    )
    artifacts = {item["path"]: item["role"] for item in payload["artifacts"]}

    expected = {
        "benchmark/scripts/build_decision_impact.py": "decision_impact_runner",
        "benchmark/outputs/kdd_decision_impact/decision_details.csv": "decision_impact_detail",
        "benchmark/outputs/kdd_decision_impact/layer_summary.csv": "decision_impact_table",
        "benchmark/outputs/kdd_decision_impact/summary.json": "decision_impact_summary",
        "benchmark/outputs/kdd_decision_impact/report.md": "decision_impact_report",
        "benchmark/outputs/kdd_decision_impact/manifest.json": "decision_impact_manifest",
    }
    for path, role in expected.items():
        assert artifacts[path] == role


def test_frozen_core_manifest_binds_mechanism_risk_card_artifacts() -> None:
    """Prevent ethics evidence from disappearing from a public candidate."""

    payload = json.loads(
        (
            REPOSITORY_ROOT
            / "benchmark"
            / "reproduction"
            / "kdd2027_core_manifest.json"
        ).read_text(encoding="utf-8")
    )
    artifacts = {item["path"]: item["role"] for item in payload["artifacts"]}

    expected = {
        "benchmark/catalog/mechanism_risk_cards.yaml": "mechanism_risk_catalog",
        "benchmark/scripts/build_mechanism_risk_cards.py": "mechanism_risk_runner",
        "benchmark/outputs/kdd_mechanism_risks/mechanism_risk_cards.csv": "mechanism_risk_table",
        "benchmark/outputs/kdd_mechanism_risks/dimension_audit.csv": "mechanism_risk_dimension_audit",
        "benchmark/outputs/kdd_mechanism_risks/summary.json": "mechanism_risk_summary",
        "benchmark/outputs/kdd_mechanism_risks/report.md": "mechanism_risk_report",
        "benchmark/outputs/kdd_mechanism_risks/manifest.json": "mechanism_risk_manifest",
    }
    for path, role in expected.items():
        assert artifacts[path] == role


def test_runtime_pythonpath_includes_benchmark_and_datavalor_source() -> None:
    module = _load_reproduce_script()

    pythonpath = module._runtime_pythonpath(REPOSITORY_ROOT, "existing-path")

    assert pythonpath.split(os.pathsep) == [
        str(REPOSITORY_ROOT / "benchmark" / "src"),
        str(REPOSITORY_ROOT / "src"),
        "existing-path",
    ]


def test_runtime_version_contract_rejects_python_39() -> None:
    module = _load_reproduce_script()

    assert module._runtime_version_error((3, 9, 18)) == (
        "unsupported_python:requires>=3.10:observed=3.9.18"
    )
    assert module._runtime_version_error((3, 10, 0)) is None


def test_run_pipeline_stops_at_first_failed_stage() -> None:
    module = _load_reproduce_script()
    observed: list[str] = []

    def fake_run(command, **kwargs):
        del kwargs
        observed.append(Path(command[1]).name)
        return SimpleNamespace(returncode=7 if len(observed) == 2 else 0)

    failure = module._run_pipeline(REPOSITORY_ROOT, {"PYTHONPATH": "x"}, runner=fake_run)

    assert failure == "heldout_replication_v2_runner_exit_code:7"
    assert observed == ["run_kdd_heldout_confirmation.py", "run_kdd_heldout_confirmation.py"]
