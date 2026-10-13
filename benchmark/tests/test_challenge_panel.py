from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path

import pytest
import yaml
from datamechbench.challenge_panel import (
    HEADLINE_METHODS,
    build_challenge_panel,
    load_challenge_protocol,
    make_challenge_cases,
    verify_challenge_panel,
)
from datamechbench.report import load_jsonl_results

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PROTOCOL = REPOSITORY_ROOT / "benchmark" / "catalog" / "diagnostic_challenge_panel.yaml"


def test_challenge_cases_pin_theory_vectors_before_execution() -> None:
    """Catches post-hoc case substitution or accidental vector drift."""

    protocol = load_challenge_protocol(PROTOCOL)
    cases = make_challenge_cases(protocol)

    assert tuple(case.case_id for case in cases["procurement"]) == (
        "PCH-diffuse",
        "PCH-singleton-boundary",
        "PCH-threshold-boundary",
        "PCH-density-tie",
    )
    assert tuple(cases["procurement"][1].public.seller_values.values()) == (
        6.0,
        2.0,
        2.0,
        2.0,
    )
    assert tuple(cases["procurement"][2].public.reported_costs.values()) == (
        Decimal("2.9"),
        Decimal("1.1"),
        Decimal("1.0"),
        Decimal("0.9"),
    )
    assert tuple(case.case_id for case in cases["trading"]) == (
        "TCH-one-efficient-trade",
        "TCH-candidate-feasible",
        "TCH-candidate-infeasible",
        "TCH-marginal-tie",
        "TCH-side-asymmetry",
    )
    assert tuple(cases["trading"][4].public.bids.values()) == (
        Decimal("1"),
        Decimal("0.9"),
        Decimal("0.8"),
        Decimal("0.3"),
        Decimal("0.2"),
    )
    assert all(
        case.metadata["cohort"] == "diagnostic_challenge"
        and case.metadata["independent_block"] == case.case_id
        and case.metadata["theory_clause"]
        for track_cases in cases.values()
        for case in track_cases
    )


def test_challenge_protocol_rejects_embedded_observed_winner(tmp_path: Path) -> None:
    """Catches a protocol amended after inspecting mechanism outcomes."""

    payload = yaml.safe_load(PROTOCOL.read_text(encoding="utf-8"))
    payload["cases"]["procurement"][0]["observed_winner"] = "method-a"
    path = tmp_path / "leaked.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    with pytest.raises(ValueError, match="outcome-contaminated"):
        load_challenge_protocol(path)


def test_challenge_build_covers_every_headline_method_and_case(tmp_path: Path) -> None:
    """Catches a nominal panel that silently omits hard methods or cells."""

    output = tmp_path / "panel"
    summary = build_challenge_panel(
        output,
        repository_root=REPOSITORY_ROOT,
        protocol_path=PROTOCOL,
    )
    rows = load_jsonl_results(output / "raw_results.jsonl")

    assert summary["valid"] is True
    assert summary["case_counts"] == {"procurement": 4, "trading": 5}
    assert summary["headline_method_counts"] == {"procurement": 6, "trading": 5}
    assert summary["pair_counts"] == {"procurement": 15, "trading": 10}
    assert summary["strongest_cases"] == {
        "procurement": "PCH-threshold-boundary",
        "trading": "TCH-candidate-feasible",
    }
    assert len(summary["case_resolution"]) == 9
    for track, methods in HEADLINE_METHODS.items():
        case_ids = {row.case_id for row in rows if row.track == track}
        for method in methods:
            assert {
                row.case_id
                for row in rows
                if row.track == track and row.method_id == method
            } == case_ids
    assert all(
        row.metadata["cohort"] == "diagnostic_challenge"
        for row in rows
    )
    assert verify_challenge_panel(output / "manifest.json")["valid"] is True


def test_challenge_verifier_rejects_hash_consistent_cohort_tampering(
    tmp_path: Path,
) -> None:
    """Catches a verifier that authenticates bytes but not panel separation."""

    output = tmp_path / "panel"
    build_challenge_panel(
        output,
        repository_root=REPOSITORY_ROOT,
        protocol_path=PROTOCOL,
    )
    results = output / "raw_results.jsonl"
    lines = results.read_text(encoding="utf-8").splitlines()
    first = json.loads(lines[0])
    first["metadata"]["cohort"] = "heldout"
    lines[0] = json.dumps(first, sort_keys=True, separators=(",", ":"))
    results.write_text("\n".join(lines) + "\n", encoding="utf-8")
    manifest_path = output / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for record in manifest["outputs"]:
        if record["path"] == "raw_results.jsonl":
            record["sha256"] = hashlib.sha256(results.read_bytes()).hexdigest()
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    verification = verify_challenge_panel(manifest_path)

    assert verification["valid"] is False
    assert any(error.startswith("invalid_cohort:") for error in verification["errors"])


def test_challenge_verifier_recomputes_separation_summary(tmp_path: Path) -> None:
    """Catches hash-consistent exaggeration of diagnostic pair separation."""

    output = tmp_path / "panel"
    build_challenge_panel(
        output,
        repository_root=REPOSITORY_ROOT,
        protocol_path=PROTOCOL,
    )
    summary_path = output / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["separable_pair_counts"]["procurement"] = 15
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    manifest_path = output / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for record in manifest["outputs"]:
        if record["path"] == "summary.json":
            record["sha256"] = hashlib.sha256(summary_path.read_bytes()).hexdigest()
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    verification = verify_challenge_panel(manifest_path)

    assert verification["valid"] is False
    assert "summary_separation_mismatch" in verification["errors"]
