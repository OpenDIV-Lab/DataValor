from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
from datamechbench.bfm_vm_analysis import (
    BFM_VM_COMPARISON_METHODS,
    build_bfm_vm_extension_artifacts,
    paired_bfm_effect_rows,
    verify_bfm_vm_extension_artifacts,
)

ROOT = Path(__file__).resolve().parents[2]


def _row(
    method_id: str,
    case_id: str,
    seed: int,
    value: float,
    *,
    setting: str = "P-TEST",
) -> dict:
    return {
        "method_id": method_id,
        "case_id": case_id,
        "seed": seed,
        "status": "completed",
        "metrics": {
            "oracle_ratio": {"applicable": True, "value": value},
        },
        "metadata": {"benchmark_setting": setting},
    }


def test_paired_effects_macro_average_random_seeds_before_cases() -> None:
    """Catches random mechanisms receiving extra weight from repeated seeds."""

    rows = [
        _row("bfm_vm", "c1", 0, 0.8),
        _row("bfm_vm", "c2", 0, 0.2),
        _row("baseline", "c1", 0, 0.4),
        _row("baseline", "c1", 1, 0.6),
        _row("baseline", "c2", 0, 0.4),
        _row("baseline", "c2", 1, 0.6),
    ]

    result = paired_bfm_effect_rows(
        rows,
        comparison_methods=("baseline",),
        settings=("P-TEST",),
    )

    assert len(result) == 1
    assert result[0]["paired_case_count"] == 2
    assert result[0]["mean_oracle_ratio_difference"] == pytest.approx(0.0)
    assert result[0]["win_fraction"] == 0.5
    assert result[0]["loss_fraction"] == 0.5
    assert result[0]["tie_fraction"] == 0.0


def test_paired_effects_reject_incomplete_common_case_surface() -> None:
    """Catches comparisons that silently drop a case missing from one method."""

    rows = [
        _row("bfm_vm", "c1", 0, 0.8),
        _row("bfm_vm", "c2", 0, 0.2),
        _row("baseline", "c1", 0, 0.4),
    ]

    with pytest.raises(ValueError, match="case alignment failed"):
        paired_bfm_effect_rows(
            rows,
            comparison_methods=("baseline",),
            settings=("P-TEST",),
        )


def test_paired_effects_treat_machine_precision_differences_as_ties() -> None:
    """Catches spurious decisive intervals produced by floating-point noise."""

    rows = [
        _row("bfm_vm", "c1", 0, 0.8),
        _row("bfm_vm", "c2", 0, 0.6),
        _row("baseline", "c1", 0, 0.8 + 5e-16),
        _row("baseline", "c2", 0, 0.6 - 5e-16),
    ]

    result = paired_bfm_effect_rows(
        rows,
        comparison_methods=("baseline",),
        settings=("P-TEST",),
    )[0]

    assert result["mean_oracle_ratio_difference"] == 0.0
    assert result["case_bootstrap_ci_low"] == 0.0
    assert result["case_bootstrap_ci_high"] == 0.0
    assert result["tie_fraction"] == 1.0


def test_bfm_vm_analysis_builds_and_verifies_complete_comparison(
    tmp_path: Path,
) -> None:
    """Catches missing methods, settings, lineage, or output hash bindings."""

    manifest = build_bfm_vm_extension_artifacts(
        ROOT / "benchmark/outputs/kdd_bfm_vm_extension/raw_results.jsonl",
        ROOT / "benchmark/outputs/full/raw_results.jsonl",
        ROOT / "benchmark/outputs/kdd_triple_eagle_extension/raw_results.jsonl",
        ROOT / "benchmark/outputs/kdd_triple_eagle_baseline_completion/raw_results.jsonl",
        ROOT / "benchmark/evidence/bfm_vm_source_audit_v1.json",
        tmp_path,
        repository_root=ROOT,
    )

    assert manifest["comparison_case_count"] == 34
    assert manifest["comparison_methods"] == ["bfm_vm", *BFM_VM_COMPARISON_METHODS]
    assert manifest["paper_code_alignment"] == "source_audited_not_paper_parity"
    with (tmp_path / "bfm_vm_paired_oracle_ratio.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        paired = list(csv.DictReader(handle))
    assert len(paired) == 4 * len(BFM_VM_COMPARISON_METHODS)

    checked = verify_bfm_vm_extension_artifacts(
        tmp_path / "manifest.json", repository_root=ROOT
    )

    assert checked == {
        "valid": True,
        "errors": [],
        "comparison_case_count": 34,
        "comparison_method_count": 10,
    }

    tampered = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    (tmp_path / "report.md").write_text("tampered\n", encoding="utf-8")
    assert tampered["outputs"]["report.md"]["sha256"]
    assert not verify_bfm_vm_extension_artifacts(
        tmp_path / "manifest.json", repository_root=ROOT
    )["valid"]
