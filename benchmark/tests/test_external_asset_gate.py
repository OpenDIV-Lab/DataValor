from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml
from datamechbench.external_asset_gate import (
    audit_external_assets,
    build_external_asset_audit,
    verify_external_asset_audit,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _catalog(tmp_path: Path, *, overrides: dict[str, str] | None = None) -> Path:
    statuses = {
        "institution_semantics": "met",
        "roles_and_rights": "met",
        "price_semantics": "met",
        "reproducible_access": "met",
        "reuse_rights": "met",
        "privacy_safe": "met",
        "independent_units": "met",
        "transformation_audit": "met",
        **(overrides or {}),
    }
    payload = {
        "schema_version": "1.0",
        "eligibility_criteria": list(statuses),
        "candidates": [
            {
                "candidate_id": "wu-secondary-monetization",
                "source_url": "https://doi.org/10.1287/mnsc.2022.03423",
                "source_kind": "incentive_compatible_reservation_price_experiment",
                "criteria": {
                    key: {"status": status, "evidence": "fixture", "limitation": "fixture"}
                    for key, status in statuses.items()
                },
            }
        ],
    }
    path = tmp_path / "candidates.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


def _source_audit(tmp_path: Path, *, parity: bool = False) -> Path:
    payload = {
        "schema_version": "1.0",
        "audit_kind": "external_author_source_static_audit",
        "method_id": "bfm_vm",
        "source_identity": {
            "repository_url": "https://github.com/xue74193-dot/BFM-SWM",
            "commit": "82f97be91f4404a9f943c5ebf3d60a272a76a13d",
            "identity_verified": True,
        },
        "license_audit": {"redistribution_authorized": True},
        "paper_code_checks": {"check-a": True},
        "executable_output_parity": parity,
    }
    path = tmp_path / "source.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_real_type_gate_is_conjunctive_even_with_consequential_semantics(
    tmp_path: Path,
) -> None:
    """Catches monetary semantics being used to bypass licence/privacy failures."""

    audit = audit_external_assets(
        _catalog(
            tmp_path,
            overrides={"reuse_rights": "not_met", "privacy_safe": "unknown"},
        ),
        _source_audit(tmp_path, parity=True),
    )

    real_type = audit["assets"]["real_reservation_types"]
    assert real_type["eligible"] is False
    assert real_type["failed_requirements"] == ["reuse_rights", "privacy_safe"]
    assert real_type["semantic_strength"] == "consequential_incentive_compatible"


def test_real_type_gate_promotes_only_when_every_requirement_is_met(
    tmp_path: Path,
) -> None:
    """Catches a gate that can never admit a fully documented future cohort."""

    audit = audit_external_assets(
        _catalog(tmp_path),
        _source_audit(tmp_path, parity=True),
    )

    assert audit["assets"]["real_reservation_types"]["eligible"] is True


def test_procurement_code_gate_distinguishes_static_audit_from_output_parity(
    tmp_path: Path,
) -> None:
    """Catches source identity being mislabeled as executable agreement."""

    audit = audit_external_assets(
        _catalog(tmp_path),
        _source_audit(tmp_path, parity=False),
    )

    code = audit["assets"]["independent_procurement_implementation"]
    assert code["source_identity_verified"] is True
    assert code["structural_checks_passed"] is True
    assert code["executable_output_parity"] is False
    assert code["eligible"] is False
    assert code["failed_requirements"] == ["executable_output_parity"]


def test_external_asset_verifier_rejects_hash_consistent_false_promotion(
    tmp_path: Path,
) -> None:
    """Catches a verifier that authenticates a fabricated eligibility decision."""

    output = tmp_path / "audit"
    build_external_asset_audit(
        output,
        candidate_catalog=REPOSITORY_ROOT / "benchmark/catalog/direct_market_source_candidates.yaml",
        procurement_source_audit=REPOSITORY_ROOT / "benchmark/evidence/bfm_vm_source_audit_v1.json",
    )
    report_path = output / "audit.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["assets"]["real_reservation_types"]["eligible"] = True
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    manifest_path = output / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for record in manifest["outputs"]:
        if record["path"] == "audit.json":
            record["sha256"] = hashlib.sha256(report_path.read_bytes()).hexdigest()
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    verification = verify_external_asset_audit(manifest_path)

    assert verification["valid"] is False
    assert "real_type_eligibility_mismatch" in verification["errors"]
