from __future__ import annotations

import json
from pathlib import Path

import yaml
from datamechbench.submission import evaluate_submission, validate_submission

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _metadata(**updates) -> dict:
    value = {
        "submitter": "Benchmark Tester",
        "method_id": "external_method",
        "family_id": "external_family",
        "track": "valuation",
        "source_url": "https://example.org/method",
        "implementation_version": "abc123",
        "implementation_license": "Apache-2.0",
        "division": "open",
        "benchmark_version": "0.3.0",
        "result_schema_version": "1.2",
        "submission_schema_version": "1.1",
        "environment": {"python": "3.11"},
        "supported_settings": ["V-AXIOM"],
        "seeds": [0],
    }
    value.update(updates)
    return value


def _row(**updates) -> dict:
    value = {
        "run_id": "external-1",
        "track": "valuation",
        "method_id": "external_method",
        "case_id": "VAX-additive",
        "seed": 0,
        "status": "completed",
        "metrics": {"score_mae": 0.1},
        "outcome": {
            "scores": {"a": 1.0, "b": 2.0, "c": 3.0, "d": 4.0},
            "utility_calls": None,
            "diagnostics": {},
        },
        "runtime_seconds": 0.1,
        "error": None,
        "metadata": {
            "method_family": "external_family",
            "benchmark_setting": "V-AXIOM",
        },
        "schema_version": "1.2",
    }
    value.update(updates)
    return value


def _package(path: Path, metadata: dict, lines: list[str]) -> Path:
    path.mkdir()
    (path / "submission.yaml").write_text(yaml.safe_dump(metadata), encoding="utf-8")
    (path / "results.jsonl").write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return path


def _v_axiom_rows(*, seeds: tuple[int, ...] = (0,)) -> list[dict]:
    case_ids = (
        "VAX-additive",
        "VAX-dummy",
        "VAX-symmetric",
        "VAX-complementary",
        "VAX-harmful",
    )
    return [
        _row(
            run_id=f"external-{case_id}-{seed}",
            case_id=case_id,
            seed=seed,
        )
        for case_id in case_ids
        for seed in seeds
    ]


def test_valid_external_submission_is_accepted(tmp_path: Path) -> None:
    package = _package(
        tmp_path / "valid",
        _metadata(),
        [json.dumps(row) for row in _v_axiom_rows()],
    )

    validation = validate_submission(package)

    assert validation.valid
    assert validation.errors == ()
    assert validation.division == "open"
    assert validation.row_count == 5
    assert validation.settings == ("V-AXIOM",)
    assert len(validation.coverage) == 1
    assert validation.coverage[0].setting == "V-AXIOM"
    assert validation.coverage[0].expected_case_count == 5
    assert validation.coverage[0].expected_row_count == 5
    assert validation.coverage[0].observed_row_count == 5
    assert validation.coverage[0].missing_case_seed_pairs == ()
    assert len(validation.package_digest) == 64


def test_trusted_evaluator_ignores_tampered_submitted_metrics(tmp_path: Path) -> None:
    rows = _v_axiom_rows()
    rows[0]["metrics"] = {"score_mae": -999999.0}
    package = _package(
        tmp_path / "tampered",
        _metadata(),
        [json.dumps(row) for row in rows],
    )

    evaluation = evaluate_submission(package)

    assert evaluation["authoritative_metrics"] == "evaluator_recomputed"
    first = next(row for row in evaluation["results"] if row["case_id"] == "VAX-additive")
    assert first["metrics"]["score_mae"]["value"] == 0.0
    assert first["metrics"]["score_mae"]["value"] != rows[0]["metrics"]["score_mae"]


def test_completed_submission_requires_raw_outcome(tmp_path: Path) -> None:
    rows = _v_axiom_rows()
    del rows[0]["outcome"]
    package = _package(
        tmp_path / "missing-outcome",
        _metadata(),
        [json.dumps(row) for row in rows],
    )

    errors = validate_submission(package).errors

    assert "row 1: completed result requires a raw outcome" in errors


def test_declared_setting_requires_complete_case_seed_grid(tmp_path: Path) -> None:
    rows = _v_axiom_rows(seeds=(0, 1))[:-1]
    package = _package(
        tmp_path / "incomplete",
        _metadata(seeds=[0, 1]),
        [json.dumps(row) for row in rows],
    )

    validation = validate_submission(package)

    assert not validation.valid
    assert validation.coverage[0].expected_row_count == 10
    assert validation.coverage[0].observed_row_count == 9
    assert validation.coverage[0].missing_case_seed_pairs == (("VAX-harmful", 1),)
    assert "missing declared case/seed result: VAX-harmful/1" in validation.errors


def test_submission_rejects_invalid_division_license_and_seed_declaration(
    tmp_path: Path,
) -> None:
    rows = _v_axiom_rows()
    rows[0]["seed"] = 0.5
    package = _package(
        tmp_path / "bad-policy",
        _metadata(
            division="closed",
            implementation_license="",
            seeds=[0, 0],
        ),
        [json.dumps(row) for row in rows],
    )

    errors = validate_submission(package).errors

    assert "division must be reference or open" in errors
    assert "missing required metadata: implementation_license" in errors
    assert "seeds must contain unique integers" in errors
    assert any("seed must be an integer" in error for error in errors)


def test_division_identity_rules_prevent_reference_and_open_id_confusion(
    tmp_path: Path,
) -> None:
    reference_rows = _v_axiom_rows()
    for row in reference_rows:
        row["method_id"] = "unknown_reference"
        row["metadata"]["method_family"] = "unknown_family"
    reference = _package(
        tmp_path / "unknown-reference",
        _metadata(
            division="reference",
            method_id="unknown_reference",
            family_id="unknown_family",
        ),
        [json.dumps(row) for row in reference_rows],
    )
    open_rows = _v_axiom_rows()
    for row in open_rows:
        row["method_id"] = "random"
        row["metadata"]["method_family"] = "random"
    open_collision = _package(
        tmp_path / "open-collision",
        _metadata(method_id="random", family_id="random"),
        [json.dumps(row) for row in open_rows],
    )

    reference_errors = validate_submission(reference).errors
    open_errors = validate_submission(open_collision).errors

    assert "reference division requires a registered method_id" in reference_errors
    assert "open division method_id collides with a registered method" in open_errors


def test_noncompleted_rows_require_reason_and_empty_metrics(tmp_path: Path) -> None:
    rows = _v_axiom_rows()
    rows[0].update(status="skipped", error=None)
    rows[1].update(status="failed", error="crashed", metrics={"score_mae": 0.1})
    package = _package(
        tmp_path / "bad-status",
        _metadata(),
        [json.dumps(row) for row in rows],
    )

    errors = "\n".join(validate_submission(package).errors)

    assert "skipped result requires a non-empty error/reason" in errors
    assert "failed result requires empty metrics" in errors


def test_malformed_error_field_is_reported_without_crashing(tmp_path: Path) -> None:
    rows = _v_axiom_rows()
    rows[0]["error"] = {"message": "not a string"}
    package = _package(
        tmp_path / "malformed-error",
        _metadata(),
        [json.dumps(row) for row in rows],
    )

    validation = validate_submission(package)

    assert not validation.valid
    assert "row 1: completed result requires an empty error" in validation.errors


def test_distributed_submission_template_satisfies_current_contract() -> None:
    validation = validate_submission(
        REPOSITORY_ROOT / "benchmark" / "submission_template"
    )

    assert validation.valid, validation.errors
    assert validation.division == "open"
    assert validation.coverage[0].missing_case_seed_pairs == ()


def test_invalid_submission_collects_independent_errors(tmp_path: Path) -> None:
    unknown = _row(
        case_id="UNKNOWN",
        method_id="wrong_method",
        schema_version="9.9",
        metadata={"method_family": "wrong_family", "benchmark_setting": "UNKNOWN-SETTING"},
    )
    duplicate = _row()
    package = _package(
        tmp_path / "invalid",
        _metadata(source_url="", benchmark_version="9.9"),
        [json.dumps(unknown), json.dumps(duplicate), json.dumps(duplicate), json.dumps(_row()).replace("0.1", "NaN", 1)],
    )

    validation = validate_submission(package)
    errors = "\n".join(validation.errors)

    assert not validation.valid
    for phrase in (
        "source_url",
        "benchmark version",
        "unknown case",
        "unknown setting",
        "method mismatch",
        "family mismatch",
        "schema version",
        "duplicate",
        "non-standard numeric constant",
    ):
        assert phrase in errors


def test_empty_submission_is_rejected(tmp_path: Path) -> None:
    package = _package(tmp_path / "empty", _metadata(), [])

    validation = validate_submission(package)

    assert not validation.valid
    assert any("zero valid results" in error for error in validation.errors)


def test_submission_rejects_missing_result_contract_fields_and_bad_metadata_types(tmp_path: Path) -> None:
    row = _row()
    del row["run_id"]
    package = _package(
        tmp_path / "bad-contract",
        _metadata(environment="python", supported_settings="V-AXIOM"),
        [json.dumps(row)],
    )

    errors = "\n".join(validate_submission(package).errors)

    assert "environment must be a mapping" in errors
    assert "supported_settings must be a list" in errors
    assert "missing result field: run_id" in errors
