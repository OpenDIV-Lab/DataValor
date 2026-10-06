from __future__ import annotations

import hashlib
import json
from pathlib import Path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_record(tmp_path: Path) -> tuple[Path, Path, Path]:
    source = tmp_path / "external.py"
    source.write_text("# official external implementation\n", encoding="utf-8")
    license_file = tmp_path / "LICENSE.txt"
    license_file.write_text("MIT License\n", encoding="utf-8")
    fixtures = tmp_path / "fixtures.json"
    fixtures.write_text(json.dumps({"cases": ["c1", "c2", "c3"]}), encoding="utf-8")
    runner = tmp_path / "runner.py"
    runner.write_text("# deterministic comparison runner\n", encoding="utf-8")
    result = tmp_path / "result.json"
    result.write_text(
        json.dumps({
            "schema_version": "1.0",
            "result_kind": "external_implementation_comparison",
            "validation_id": "fixture-validation",
            "method_id": "knn_shapley",
            "external_commit": "5c2856b95237a07ee4565638060e043f1e410822",
            "executed_source_sha256": _sha256(source),
            "source_execution": "unchanged_upstream_file_with_minimal_api_import_shim",
            "execution_environment": {
                "python": "3.13.5",
                "numpy": "2.3.5",
                "scikit_learn": "1.6.1",
                "torch": "2.9.0+cu128",
                "tqdm": "4.67.1",
            },
            "tolerance": 1e-12,
            "all_close": True,
            "maximum_absolute_error": 0.0,
            "comparisons": [
                {
                    "case_id": case_id,
                    "local_scores": [0.5, -0.25],
                    "external_scores": [0.5, -0.25],
                    "maximum_absolute_error": 0.0,
                }
                for case_id in ("c1", "c2", "c3")
            ],
        }, sort_keys=True),
        encoding="utf-8",
    )
    artifacts = [
        ("external_source", source),
        ("external_license", license_file),
        ("comparison_fixtures", fixtures),
        ("comparison_results", result),
        ("validation_runner", runner),
    ]
    record = tmp_path / "record.json"
    record.write_text(
        json.dumps({
            "schema_version": "1.0",
            "record_kind": "external_implementation_validation",
            "validation_id": "fixture-validation",
            "method_id": "knn_shapley",
            "track": "valuation",
            "claim_boundary": "algorithm_core_with_declared_preprocessing_alignment",
            "external_implementation": {
                "name": "OpenDataVal KNNShapley",
                "origin": "official_upstream",
                "repository_url": "https://github.com/opendataval/opendataval",
                "commit_sha": "5c2856b95237a07ee4565638060e043f1e410822",
                "source_url": "https://github.com/opendataval/opendataval/blob/5c2856b95237a07ee4565638060e043f1e410822/opendataval/dataval/knnshap/knnshap.py",
                "source_sha256": _sha256(source),
                "archive_sha256": "e13ff293c86c51796445d0de3bb74b3511ab8cc994eb9496b01c2582e2689dd0",
                "license_id": "MIT",
            },
            "artifacts": [
                {
                    "role": role,
                    "path": path.name,
                    "sha256": _sha256(path),
                    "bytes": path.stat().st_size,
                }
                for role, path in artifacts
            ],
        }, sort_keys=True),
        encoding="utf-8",
    )
    return record, source, result


def test_external_validation_accepts_bound_official_output_agreement(
    tmp_path: Path,
) -> None:
    from datamechbench.external_validation import (
        audit_external_implementation_records,
    )

    record, _, _ = _write_record(tmp_path)

    audit = audit_external_implementation_records(
        (record.name,),
        tmp_path,
        expected_method_ids={"knn_shapley"},
        minimum_records=1,
        minimum_fixtures=3,
    )

    assert audit == {
        "passed": True,
        "status": "pass",
        "record_count": 1,
        "distinct_record_count": 1,
        "valid_record_count": 1,
        "validated_method_ids": ["knn_shapley"],
        "distinct_method_count": 1,
        "tracks": ["valuation"],
        "track_count": 1,
        "official_upstream_count": 1,
        "unique_external_source_count": 1,
        "unique_external_repository_count": 1,
        "fixture_count": 3,
        "maximum_absolute_error": 0.0,
        "errors": [],
    }


def test_external_validation_rejects_duplicate_record_path(tmp_path: Path) -> None:
    from datamechbench.external_validation import (
        audit_external_implementation_records,
    )

    record, _, _ = _write_record(tmp_path)

    audit = audit_external_implementation_records(
        (record.name, record.name),
        tmp_path,
        expected_method_ids={"knn_shapley"},
        minimum_records=2,
        minimum_fixtures=3,
        minimum_methods=1,
        minimum_sources=1,
        minimum_repositories=1,
        minimum_tracks=1,
    )

    assert audit["passed"] is False
    assert audit["distinct_record_count"] == 1
    assert any(error.startswith("duplicate_record_path:") for error in audit["errors"])


def test_external_validation_requires_distinct_evidence_dimensions(
    tmp_path: Path,
) -> None:
    from datamechbench.external_validation import (
        audit_external_implementation_records,
    )

    record, _, _ = _write_record(tmp_path)

    audit = audit_external_implementation_records(
        (record.name,),
        tmp_path,
        expected_method_ids={"knn_shapley"},
        minimum_records=1,
        minimum_fixtures=3,
        minimum_methods=2,
        minimum_sources=2,
        minimum_repositories=2,
        minimum_tracks=2,
    )

    assert audit["passed"] is False
    assert audit["distinct_method_count"] == 1
    assert audit["track_count"] == 1
    assert {
        "insufficient_methods:1<2",
        "insufficient_external_sources:1<2",
        "insufficient_external_repositories:1<2",
        "insufficient_tracks:1<2",
    } <= set(audit["errors"])


def test_external_validation_rejects_duplicate_validation_id(
    tmp_path: Path,
) -> None:
    from datamechbench.external_validation import (
        audit_external_implementation_records,
    )

    record, _, _ = _write_record(tmp_path)
    copied_record = tmp_path / "record-copy.json"
    copied_record.write_bytes(record.read_bytes())

    audit = audit_external_implementation_records(
        (record.name, copied_record.name),
        tmp_path,
        expected_method_ids={"knn_shapley"},
        minimum_records=2,
        minimum_fixtures=3,
    )

    assert audit["passed"] is False
    assert "duplicate_validation_id:fixture-validation" in audit["errors"]


def test_external_validation_rejects_tampered_upstream_source(tmp_path: Path) -> None:
    from datamechbench.external_validation import (
        audit_external_implementation_records,
    )

    record, source, _ = _write_record(tmp_path)
    source.write_text("# tampered implementation\n", encoding="utf-8")

    audit = audit_external_implementation_records(
        (record.name,),
        tmp_path,
        expected_method_ids={"knn_shapley"},
        minimum_records=1,
        minimum_fixtures=3,
    )

    assert audit["status"] == "fail"
    assert "sha256_mismatch:fixture-validation:external_source" in audit["errors"]


def test_external_validation_recomputes_score_disagreement(tmp_path: Path) -> None:
    from datamechbench.external_validation import (
        audit_external_implementation_records,
    )

    record, _, result = _write_record(tmp_path)
    result_payload = json.loads(result.read_text(encoding="utf-8"))
    result_payload["comparisons"][0]["external_scores"][0] = 0.75
    result.write_text(json.dumps(result_payload, sort_keys=True), encoding="utf-8")
    record_payload = json.loads(record.read_text(encoding="utf-8"))
    binding = next(
        item
        for item in record_payload["artifacts"]
        if item["role"] == "comparison_results"
    )
    binding["sha256"] = _sha256(result)
    binding["bytes"] = result.stat().st_size
    record.write_text(json.dumps(record_payload, sort_keys=True), encoding="utf-8")

    audit = audit_external_implementation_records(
        (record.name,),
        tmp_path,
        expected_method_ids={"knn_shapley"},
        minimum_records=1,
        minimum_fixtures=3,
    )

    assert audit["status"] == "fail"
    assert "score_disagreement:fixture-validation:c1" in audit["errors"]


def test_external_validation_rejects_source_identity_drift(tmp_path: Path) -> None:
    from datamechbench.external_validation import (
        audit_external_implementation_records,
    )

    record, _, _ = _write_record(tmp_path)
    payload = json.loads(record.read_text(encoding="utf-8"))
    payload["external_implementation"]["source_sha256"] = "0" * 64
    payload["external_implementation"]["source_url"] = payload[
        "external_implementation"
    ]["source_url"].replace("5c2856b95237a07ee4565638060e043f1e410822", "1" * 40)
    record.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")

    audit = audit_external_implementation_records(
        (record.name,),
        tmp_path,
        expected_method_ids={"knn_shapley"},
        minimum_records=1,
        minimum_fixtures=3,
    )

    assert audit["status"] == "fail"
    assert "external_source_hash_mismatch:fixture-validation" in audit["errors"]
    assert "source_url_commit_mismatch:fixture-validation" in audit["errors"]


def test_external_validation_requires_execution_environment(tmp_path: Path) -> None:
    from datamechbench.external_validation import (
        audit_external_implementation_records,
    )

    record, _, result = _write_record(tmp_path)
    result_payload = json.loads(result.read_text(encoding="utf-8"))
    del result_payload["execution_environment"]
    result.write_text(json.dumps(result_payload, sort_keys=True), encoding="utf-8")
    record_payload = json.loads(record.read_text(encoding="utf-8"))
    binding = next(
        item
        for item in record_payload["artifacts"]
        if item["role"] == "comparison_results"
    )
    binding["sha256"] = _sha256(result)
    binding["bytes"] = result.stat().st_size
    record.write_text(json.dumps(record_payload, sort_keys=True), encoding="utf-8")

    audit = audit_external_implementation_records(
        (record.name,),
        tmp_path,
        expected_method_ids={"knn_shapley"},
        minimum_records=1,
        minimum_fixtures=3,
    )

    assert audit["status"] == "fail"
    assert "missing_execution_environment:fixture-validation" in audit["errors"]


def test_external_validation_accepts_hash_bound_dependency_sources_and_minimal_runtime(
    tmp_path: Path,
) -> None:
    """Trading validators must bind every executed upstream module without ML deps."""

    from datamechbench.external_validation import (
        audit_external_implementation_records,
    )

    record, source, result = _write_record(tmp_path)
    dependency = tmp_path / "dependency.py"
    dependency.write_text("# upstream dependency\n", encoding="utf-8")
    result_payload = json.loads(result.read_text(encoding="utf-8"))
    result_payload["execution_environment"] = {"python": "3.13.5"}
    result_payload["executed_source_files"] = {
        "external_source": _sha256(source),
        "external_dependency_trade": _sha256(dependency),
    }
    result.write_text(json.dumps(result_payload, sort_keys=True), encoding="utf-8")
    record_payload = json.loads(record.read_text(encoding="utf-8"))
    record_payload["artifacts"].append({
        "role": "external_dependency_trade",
        "path": dependency.name,
        "sha256": _sha256(dependency),
        "bytes": dependency.stat().st_size,
    })
    binding = next(
        item
        for item in record_payload["artifacts"]
        if item["role"] == "comparison_results"
    )
    binding["sha256"] = _sha256(result)
    binding["bytes"] = result.stat().st_size
    record.write_text(json.dumps(record_payload, sort_keys=True), encoding="utf-8")

    audit = audit_external_implementation_records(
        (record.name,),
        tmp_path,
        expected_method_ids={"knn_shapley"},
        minimum_records=1,
        minimum_fixtures=3,
    )

    assert audit["passed"] is True


def test_external_validation_rejects_jointly_wrong_outputs_against_fixture_oracle(
    tmp_path: Path,
) -> None:
    """Agreement between two implementations cannot override a hand-derived oracle."""

    from datamechbench.external_validation import (
        audit_external_implementation_records,
    )

    record, _, result = _write_record(tmp_path)
    result_payload = json.loads(result.read_text(encoding="utf-8"))
    comparison = result_payload["comparisons"][0]
    comparison["expected_scores"] = [0.75, -0.25]
    result.write_text(json.dumps(result_payload, sort_keys=True), encoding="utf-8")
    record_payload = json.loads(record.read_text(encoding="utf-8"))
    binding = next(
        item
        for item in record_payload["artifacts"]
        if item["role"] == "comparison_results"
    )
    binding["sha256"] = _sha256(result)
    binding["bytes"] = result.stat().st_size
    record.write_text(json.dumps(record_payload, sort_keys=True), encoding="utf-8")

    audit = audit_external_implementation_records(
        (record.name,),
        tmp_path,
        expected_method_ids={"knn_shapley"},
        minimum_records=1,
        minimum_fixtures=3,
    )

    assert audit["status"] == "fail"
    assert "fixture_oracle_disagreement:fixture-validation:c1" in audit["errors"]


def test_external_validation_rejects_tampered_declared_boundary_difference(
    tmp_path: Path,
) -> None:
    """A hash-consistent record cannot relabel a known discrepancy as matched."""

    from datamechbench.external_validation import (
        audit_external_implementation_records,
    )

    record, _, result = _write_record(tmp_path)
    result_payload = json.loads(result.read_text(encoding="utf-8"))
    result_payload["boundary_fixture_count"] = 1
    result_payload["boundary_comparisons"] = [{
        "case_id": "strict-vs-nonstrict-tie",
        "status": "expected_semantic_boundary",
        "matches_declared_difference": False,
        "local_scores": [3.0, 17.0],
        "external_scores": [2.0, 13.0],
        "expected_local_scores": [3.0, 17.0],
        "expected_external_scores": [2.0, 13.0],
        "maximum_absolute_difference": 4.0,
    }]
    result.write_text(json.dumps(result_payload, sort_keys=True), encoding="utf-8")
    record_payload = json.loads(record.read_text(encoding="utf-8"))
    binding = next(
        item
        for item in record_payload["artifacts"]
        if item["role"] == "comparison_results"
    )
    binding["sha256"] = _sha256(result)
    binding["bytes"] = result.stat().st_size
    record.write_text(json.dumps(record_payload, sort_keys=True), encoding="utf-8")

    audit = audit_external_implementation_records(
        (record.name,),
        tmp_path,
        expected_method_ids={"knn_shapley"},
        minimum_records=1,
        minimum_fixtures=3,
    )

    assert audit["status"] == "fail"
    assert "boundary_not_matched:fixture-validation:strict-vs-nonstrict-tie" in (
        audit["errors"]
    )
