from __future__ import annotations

import csv
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPOSITORY_ROOT / "benchmark/src/datamechbench/decision_impact.py"
SCRIPT_PATH = REPOSITORY_ROOT / "benchmark/scripts/build_decision_impact.py"


def _module():
    # The first RED run fails here until the production feature exists.
    assert MODULE_PATH.is_file(), "decision-impact builder is not implemented"
    spec = importlib.util.spec_from_file_location("decision_impact_under_test", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_csv(path: Path, columns: tuple[str, ...], rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _fixture(tmp_path: Path) -> dict[str, Path]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    contrasts = tmp_path / "contrasts.csv"
    _write_csv(
        contrasts,
        ("track", "contrast_id", "effect", "decision"),
        [
            {
                "track": "valuation",
                "contrast_id": "V-POSITIVE-BOUNDARY",
                "effect": 0.2,
                "decision": "boundary",
            },
            {
                "track": "valuation",
                "contrast_id": "V-POSITIVE-CONFIRMED",
                "effect": 0.1,
                "decision": "confirmed",
            },
            {
                "track": "procurement",
                "contrast_id": "P-NEGATIVE-BOUNDARY",
                "effect": -0.1,
                "decision": "boundary",
            },
        ],
    )
    profiles = tmp_path / "profiles.csv"
    _write_csv(
        profiles,
        (
            "track",
            "method_id",
            "completed_runs",
            "primary_mean",
            "guardrail_1_coverage",
            "guardrail_1_max",
            "guardrail_2_coverage",
            "guardrail_2_max",
        ),
        [
            {
                "track": "procurement",
                "method_id": "complete",
                "completed_runs": 4,
                "primary_mean": 0.9,
                "guardrail_1_coverage": "4/4",
                "guardrail_1_max": 0,
                "guardrail_2_coverage": "4/4",
                "guardrail_2_max": 0,
            },
            {
                "track": "procurement",
                "method_id": "missing-payment",
                "completed_runs": 4,
                "primary_mean": 0.95,
                "guardrail_1_coverage": "3/4",
                "guardrail_1_max": 0,
                "guardrail_2_coverage": "4/4",
                "guardrail_2_max": 0,
            },
            {
                "track": "valuation",
                "method_id": "out-of-scope",
                "completed_runs": 4,
                "primary_mean": 0.8,
                "guardrail_1_coverage": "4/4",
                "guardrail_1_max": 0,
                "guardrail_2_coverage": "4/4",
                "guardrail_2_max": 0,
            },
        ],
    )
    incentives = tmp_path / "incentives.csv"
    _write_csv(
        incentives,
        (
            "track",
            "method_id",
            "profitable_deviation_count",
            "conclusion",
            "report_domain_complete",
            "random_support_complete",
        ),
        [
            {
                "track": "procurement",
                "method_id": "finite-clear",
                "profitable_deviation_count": 0,
                "conclusion": "no_counterexample_complete_finite_domain",
                "report_domain_complete": "true",
                "random_support_complete": "true",
            },
            {
                "track": "procurement",
                "method_id": "panel-clear",
                "profitable_deviation_count": 0,
                "conclusion": "no_counterexample_complete_reports_seed_panel",
                "report_domain_complete": "true",
                "random_support_complete": "false",
            },
            {
                "track": "trading",
                "method_id": "witnessed",
                "profitable_deviation_count": 2,
                "conclusion": "counterexample_within_audited_domain",
                "report_domain_complete": "true",
                "random_support_complete": "false",
            },
        ],
    )
    return {
        "confirmatory_contrasts": contrasts,
        "constraint_profiles": profiles,
        "finite_incentives": incentives,
    }


def test_builder_separates_three_decision_layers_without_composite(tmp_path: Path) -> None:
    """Catch combining unlike evidence units or hiding optimistic promotions."""

    module = _module()
    output = tmp_path / "output"

    manifest = module.build_decision_impact(
        _fixture(tmp_path), output, repository_root=tmp_path
    )
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    layers = {item["layer_id"]: item for item in summary["layers"]}

    assert summary["no_cross_layer_composite"] is True
    assert summary["claim_scope"] == "diagnostic_counterfactual_decision_impact"
    assert "aggregate_score" not in summary
    assert layers["confirmatory_claims"] == {
        "layer_id": "confirmatory_claims",
        "unit": "registered_contrast",
        "denominator": 3,
        "incomplete_screen_admitted": 2,
        "full_protocol_admitted": 1,
        "optimistic_promotions_prevented": 1,
        "affected_ids": ["V-POSITIVE-BOUNDARY"],
    }
    assert layers["constraint_admissibility"] == {
        "layer_id": "constraint_admissibility",
        "unit": "procurement_or_trading_headline_method",
        "denominator": 2,
        "incomplete_screen_admitted": 2,
        "full_protocol_admitted": 1,
        "optimistic_promotions_prevented": 1,
        "affected_ids": ["missing-payment"],
    }
    assert layers["finite_incentive_claims"]["zero_witness_methods"] == 2
    assert layers["finite_incentive_claims"]["source_theorem_claims_established"] == 0
    assert layers["finite_incentive_claims"]["counterexample_methods"] == 1
    assert layers["finite_incentive_claims"]["fixed_seed_panel_methods"] == 2
    assert manifest["row_counts"] == {"decision_details.csv": 8, "layer_summary.csv": 3}


def test_repeated_builds_are_byte_identical_and_tamper_is_detected(tmp_path: Path) -> None:
    """Catch nondeterministic output or a verifier that trusts stale hashes."""

    module = _module()
    inputs = _fixture(tmp_path)
    first = tmp_path / "first"
    second = tmp_path / "second"

    manifest_a = module.build_decision_impact(
        inputs, first, repository_root=tmp_path
    )
    manifest_b = module.build_decision_impact(
        inputs, second, repository_root=tmp_path
    )

    assert manifest_a == manifest_b
    for name in manifest_a["outputs"]:
        assert (first / name).read_bytes() == (second / name).read_bytes()
    assert module.verify_decision_impact_manifest(first / "manifest.json") == {
        "valid": True,
        "errors": [],
        "manifest": str(first / "manifest.json"),
    }
    (first / "summary.json").write_text("{}\n", encoding="utf-8")
    checked = module.verify_decision_impact_manifest(first / "manifest.json")
    assert checked["valid"] is False
    assert "output_sha256_mismatch:summary.json" in checked["errors"]


def test_builder_rejects_malformed_guardrail_coverage(tmp_path: Path) -> None:
    """Catch silently treating malformed or zero-denominator coverage as complete."""

    module = _module()
    inputs = _fixture(tmp_path)
    profiles = inputs["constraint_profiles"]
    text = profiles.read_text(encoding="utf-8").replace("3/4", "3/0")
    profiles.write_text(text, encoding="utf-8")

    with pytest.raises(ValueError, match="invalid guardrail coverage.*3/0"):
        module.build_decision_impact(
            inputs, tmp_path / "output", repository_root=tmp_path
        )


def test_default_frozen_evidence_has_expected_decision_impacts(tmp_path: Path) -> None:
    """Catch drift that weakens the paper's decision-impact finding."""

    module = _module()
    manifest = module.build_decision_impact(module.DEFAULT_INPUTS, tmp_path)
    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    layers = {item["layer_id"]: item for item in summary["layers"]}

    assert layers["confirmatory_claims"]["denominator"] == 6
    assert layers["confirmatory_claims"]["incomplete_screen_admitted"] == 3
    assert layers["confirmatory_claims"]["full_protocol_admitted"] == 1
    assert layers["confirmatory_claims"]["optimistic_promotions_prevented"] == 2
    assert layers["constraint_admissibility"]["denominator"] == 11
    assert layers["constraint_admissibility"]["full_protocol_admitted"] == 10
    assert layers["constraint_admissibility"]["affected_ids"] == ["jt_random_eom"]
    assert layers["finite_incentive_claims"]["denominator"] == 11
    assert layers["finite_incentive_claims"]["zero_witness_methods"] == 9
    assert layers["finite_incentive_claims"]["counterexample_methods"] == 2
    assert manifest["row_counts"] == {"decision_details.csv": 28, "layer_summary.csv": 3}


def test_manifest_is_portable_across_repository_roots(tmp_path: Path) -> None:
    """Catch absolute host paths leaking into an otherwise deterministic manifest."""

    module = _module()
    root_a = tmp_path / "checkout-a"
    inputs_a = _fixture(root_a)
    root_b = tmp_path / "checkout-b"
    shutil.copytree(root_a, root_b)
    inputs_b = {name: root_b / path.relative_to(root_a) for name, path in inputs_a.items()}

    manifest_a = module.build_decision_impact(
        inputs_a, tmp_path / "out-a", repository_root=root_a
    )
    manifest_b = module.build_decision_impact(
        inputs_b, tmp_path / "out-b", repository_root=root_b
    )

    assert manifest_a == manifest_b
    assert (tmp_path / "out-a/manifest.json").read_bytes() == (
        tmp_path / "out-b/manifest.json"
    ).read_bytes()
    assert all(
        not Path(binding["path"]).is_absolute()
        for binding in manifest_a["inputs"].values()
    )


def test_cli_builds_and_verifies_explicit_evidence_bundle(tmp_path: Path) -> None:
    """Catch a release entrypoint that cannot rebuild the artifact from explicit inputs."""

    assert SCRIPT_PATH.is_file(), "decision-impact CLI is not implemented"
    inputs = _fixture(tmp_path)
    output = tmp_path / "output"
    environment = {"PYTHONPATH": str(REPOSITORY_ROOT / "benchmark/src")}
    build = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--build",
            "--confirmatory-contrasts",
            str(inputs["confirmatory_contrasts"]),
            "--constraint-profiles",
            str(inputs["constraint_profiles"]),
            "--finite-incentives",
            str(inputs["finite_incentives"]),
            "--output-dir",
            str(output),
            "--repository-root",
            str(tmp_path),
        ],
        cwd=REPOSITORY_ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    verify = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--verify",
            "--output-dir",
            str(output),
        ],
        cwd=REPOSITORY_ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )

    assert build.returncode == 0, build.stderr
    assert json.loads(build.stdout)["row_counts"] == {
        "decision_details.csv": 8,
        "layer_summary.csv": 3,
    }
    assert verify.returncode == 0, verify.stderr
    assert json.loads(verify.stdout)["valid"] is True
