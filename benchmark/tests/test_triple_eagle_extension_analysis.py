from __future__ import annotations

import csv
import json
import math

import pytest
from datamechbench.triple_eagle_analysis import (
    BASELINE_METHODS,
    TRIPLE_EAGLE_METHODS,
    build_triple_eagle_extension_artifacts,
    verify_triple_eagle_extension_artifacts,
)


def _csv(path):
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_extension_analysis_keeps_variants_separate_and_hash_binds_sources(tmp_path) -> None:
    manifest = build_triple_eagle_extension_artifacts(
        "benchmark/outputs/kdd_triple_eagle_extension/raw_results.jsonl",
        "benchmark/outputs/full/raw_results.jsonl",
        tmp_path,
        supplemental_results=(
            "benchmark/outputs/kdd_triple_eagle_baseline_completion/raw_results.jsonl"
        ),
    )

    assert manifest["extension_run_count"] == 408
    assert manifest["extension_status_counts"] == {"completed": 408}
    assert manifest["extension_source"]["sha256"]
    assert manifest["baseline_source"]["sha256"]
    assert manifest["supplemental_source"]["sha256"]
    assert manifest["supplemental_source"]["accepted_row_count"] == 102
    assert manifest["comparison_case_count"] == 34
    assert set(manifest["comparison_methods"]) == set(BASELINE_METHODS) | set(
        TRIPLE_EAGLE_METHODS
    )

    summary = _csv(tmp_path / "method_setting_summary.csv")
    assert {row["method_id"] for row in summary} == set(BASELINE_METHODS) | set(
        TRIPLE_EAGLE_METHODS
    )
    assert any(
        row["method_id"] == "triple_eagle_randomized"
        and row["setting"] == "P-SUBMODULAR"
        for row in summary
    )
    assert any(
        row["method_id"] == "triple_eagle_deterministic"
        and row["setting"] == "P-SUBMODULAR"
        for row in summary
    )
    ml_deterministic = next(
        row
        for row in summary
        if row["method_id"] == "triple_eagle_deterministic"
        and row["setting"] == "P-ML-ACQUISITION"
    )
    assert float(ml_deterministic["mean_normalized_oracle_gain_ratio"]) < float(
        ml_deterministic["mean_oracle_ratio"]
    )

    branches = _csv(tmp_path / "branch_summary.csv")
    assert sum(int(row["run_count"]) for row in branches) == 374
    assert {row["branch"] for row in branches} >= {
        "best_effort",
        "best_singleton",
        "lsd_suffix",
        "two_phase_suffix",
    }

    paired = _csv(tmp_path / "paired_oracle_ratio.csv")
    assert len(paired) == 2 * len(BASELINE_METHODS) * 4
    assert all(int(row["paired_case_count"]) > 0 for row in paired)
    numerical_tie = next(
        row
        for row in paired
        if row["method_id"] == "triple_eagle_deterministic"
        and row["comparison_method_id"] == "cgl_randomized"
        and row["setting"] == "P-SUBMODULAR"
    )
    assert float(numerical_tie["mean_oracle_ratio_difference"]) == 0.0
    assert float(numerical_tie["case_bootstrap_ci_low"]) == 0.0
    assert float(numerical_tie["case_bootstrap_ci_high"]) == 0.0
    assert float(numerical_tie["tie_fraction"]) == 1.0

    claims = _csv(tmp_path / "theorem_claim_audit.csv")
    assert len(claims) == 10
    assert {row["method_id"] for row in claims} == set(TRIPLE_EAGLE_METHODS)
    assert all(row["setting"] == "P-SUBMODULAR" for row in claims)
    randomized_claims = [
        row for row in claims if row["method_id"] == "triple_eagle_randomized"
    ]
    assert all(
        row["expectation_evaluation"] == "exact_two_branch_weighting"
        for row in randomized_claims
    )
    assert any(
        abs(float(row["oracle_ratio"]) - float(row["seed_panel_oracle_ratio"]))
        > 1e-6
        for row in randomized_claims
    )

    randomization = _csv(tmp_path / "randomization_audit.csv")
    assert len(randomization) == 34
    low_supply = [row for row in randomization if row["randomized_branch"] == "True"]
    paper_probability = (math.sqrt(13.0) + 1.0) / (math.sqrt(13.0) + 5.0)
    assert low_supply
    assert all(
        float(row["paper_singleton_probability"]) == pytest.approx(paper_probability)
        for row in low_supply
    )
    assert {float(row["seed_panel_singleton_rate"]) for row in low_supply} == {0.4}
    assert max(float(row["absolute_seed_panel_bias"]) for row in low_supply) > 0.0

    variants = _csv(tmp_path / "variant_comparison.csv")
    assert len(variants) == 4
    assert {row["setting"] for row in variants} == {
        "P-ADDITIVE",
        "P-SUBMODULAR",
        "P-ML-ACQUISITION",
        "P-MARKET-CONCENTRATION",
    }

    on_disk = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert on_disk == manifest
    assert verify_triple_eagle_extension_artifacts(tmp_path / "manifest.json") == {
        "valid": True,
        "errors": [],
        "extension_run_count": 408,
        "comparison_case_count": 34,
    }

    report = tmp_path / "report.md"
    report.write_text(report.read_text(encoding="utf-8") + "tampered\n", encoding="utf-8")
    checked = verify_triple_eagle_extension_artifacts(tmp_path / "manifest.json")
    assert checked["valid"] is False
    assert "output_hash_mismatch:report.md" in checked["errors"]
