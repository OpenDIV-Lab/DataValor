"""Fail-closed admission gates for high-value external benchmark assets."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping

import yaml

REAL_TYPE_REQUIREMENTS = (
    "institution_semantics",
    "roles_and_rights",
    "price_semantics",
    "reproducible_access",
    "reuse_rights",
    "privacy_safe",
    "independent_units",
    "transformation_audit",
)
CODE_REQUIREMENTS = (
    "source_identity_verified",
    "redistribution_authorized",
    "structural_checks_passed",
    "executable_output_parity",
)
OUTPUT_NAMES = ("audit.json", "report.md")


def _mapping(raw: Any, label: str) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise ValueError(f"{label} must be a mapping")
    return {str(key): value for key, value in raw.items()}


def _read_yaml(path: Path) -> dict[str, Any]:
    return _mapping(yaml.safe_load(path.read_text(encoding="utf-8")) or {}, "catalog")


def _read_json(path: Path) -> dict[str, Any]:
    return _mapping(json.loads(path.read_text(encoding="utf-8")), "source audit")


def audit_external_assets(
    candidate_catalog: str | Path,
    procurement_source_audit: str | Path,
) -> dict[str, Any]:
    """Evaluate real-type and independent-code assets without partial promotion."""

    catalog = _read_yaml(Path(candidate_catalog))
    if catalog.get("schema_version") != "1.0":
        raise ValueError("unsupported source candidate catalog")
    declared = tuple(str(value) for value in catalog.get("eligibility_criteria", ()))
    if declared != REAL_TYPE_REQUIREMENTS:
        raise ValueError("source eligibility criteria do not match the admission contract")
    candidates = catalog.get("candidates")
    if not isinstance(candidates, list):
        raise ValueError("source candidates must be a list")
    matches = [
        _mapping(item, "Wu candidate")
        for item in candidates
        if isinstance(item, Mapping)
        and item.get("candidate_id") == "wu-secondary-monetization"
    ]
    if len(matches) != 1:
        raise ValueError("expected exactly one Wu reservation-type candidate")
    candidate = matches[0]
    criteria = _mapping(candidate.get("criteria"), "Wu criteria")
    if set(criteria) != set(REAL_TYPE_REQUIREMENTS):
        raise ValueError("Wu candidate criteria do not match the admission contract")
    statuses: dict[str, str] = {}
    for requirement in REAL_TYPE_REQUIREMENTS:
        record = _mapping(criteria[requirement], f"Wu criterion {requirement}")
        status = str(record.get("status", ""))
        if status not in {"met", "not_met", "unknown"}:
            raise ValueError(f"invalid Wu criterion status: {requirement}:{status}")
        statuses[requirement] = status
    real_requirements = {
        requirement: statuses[requirement] == "met"
        for requirement in REAL_TYPE_REQUIREMENTS
    }
    real_failed = [
        requirement for requirement in REAL_TYPE_REQUIREMENTS
        if not real_requirements[requirement]
    ]
    consequential = (
        candidate.get("source_kind")
        == "incentive_compatible_reservation_price_experiment"
        and all(
            statuses[key] == "met"
            for key in ("institution_semantics", "roles_and_rights", "price_semantics")
        )
    )

    source = _read_json(Path(procurement_source_audit))
    if source.get("schema_version") != "1.0" or source.get("method_id") != "bfm_vm":
        raise ValueError("unsupported procurement source audit")
    identity = _mapping(source.get("source_identity"), "source identity")
    license_audit = _mapping(source.get("license_audit"), "source licence")
    checks = _mapping(source.get("paper_code_checks"), "paper/code checks")
    code_requirements = {
        "source_identity_verified": identity.get("identity_verified") is True,
        "redistribution_authorized": license_audit.get("redistribution_authorized") is True,
        "structural_checks_passed": bool(checks) and all(value is True for value in checks.values()),
        "executable_output_parity": source.get("executable_output_parity") is True,
    }
    code_failed = [
        requirement for requirement in CODE_REQUIREMENTS
        if not code_requirements[requirement]
    ]

    assets = {
        "real_reservation_types": {
            "candidate_id": "wu-secondary-monetization",
            "source_url": str(candidate.get("source_url", "")),
            "semantic_strength": (
                "consequential_incentive_compatible"
                if consequential
                else "reservation_semantics_not_established"
            ),
            "criterion_status": statuses,
            "requirements": real_requirements,
            "failed_requirements": real_failed,
            "eligible": not real_failed,
            "promotion_scope": (
                "participant-level reservation-type calibration"
                if not real_failed
                else "candidate ledger only"
            ),
        },
        "independent_procurement_implementation": {
            "method_id": "bfm_vm",
            "repository_url": str(identity.get("repository_url", "")),
            "commit": str(identity.get("commit", "")),
            **code_requirements,
            "requirements": code_requirements,
            "failed_requirements": code_failed,
            "eligible": not code_failed,
            "promotion_scope": (
                "executable independent output parity"
                if not code_failed
                else "identity/static source audit only"
            ),
        },
    }
    return {
        "schema_version": "1.0",
        "audit_kind": "external_asset_admission",
        "assets": assets,
        "eligible_asset_count": sum(asset["eligible"] for asset in assets.values()),
        "claim_boundary": (
            "Semantic strength never overrides access, licence, privacy, transform, "
            "or executable-parity requirements. Failed assets remain visible candidates."
        ),
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_external_asset_audit(
    output_dir: str | Path,
    *,
    candidate_catalog: str | Path,
    procurement_source_audit: str | Path,
) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    catalog = Path(candidate_catalog).resolve()
    source = Path(procurement_source_audit).resolve()
    audit = audit_external_assets(catalog, source)
    (output / "audit.json").write_text(
        json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    lines = [
        "# External asset admission audit",
        "",
        "Admission is conjunctive: strong semantics cannot override missing rights, privacy review, or parity.",
        "",
        "| Asset | Eligible | Failed requirements | Current evidence scope |",
        "|---|---|---|---|",
    ]
    for name, asset in audit["assets"].items():
        failed = ", ".join(asset["failed_requirements"]) or "none"
        lines.append(
            f"| {name} | {str(asset['eligible']).lower()} | {failed} | {asset['promotion_scope']} |"
        )
    (output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    manifest = {
        "schema_version": "1.0",
        "manifest_kind": "external_asset_admission",
        "inputs": [
            {"path": os.path.relpath(catalog, output), "sha256": _sha256(catalog)},
            {"path": os.path.relpath(source, output), "sha256": _sha256(source)},
        ],
        "outputs": [
            {"path": name, "sha256": _sha256(output / name)} for name in OUTPUT_NAMES
        ],
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return audit


def verify_external_asset_audit(manifest_path: str | Path) -> dict[str, Any]:
    path = Path(manifest_path)
    errors: list[str] = []
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"valid": False, "errors": [f"invalid_manifest:{type(exc).__name__}"]}
    if manifest.get("schema_version") != "1.0":
        errors.append("invalid_schema_version")
    if manifest.get("manifest_kind") != "external_asset_admission":
        errors.append("invalid_manifest_kind")
    for section, expected in (("inputs", None), ("outputs", set(OUTPUT_NAMES))):
        records = manifest.get(section)
        if not isinstance(records, list):
            errors.append(f"{section}_not_list")
            continue
        seen: set[str] = set()
        for record in records:
            if not isinstance(record, Mapping):
                errors.append(f"invalid_{section}_record")
                continue
            name = str(record.get("path", ""))
            target = (path.parent / name).resolve()
            if name in seen:
                errors.append(f"duplicate_{section}:{name}")
            seen.add(name)
            if not target.is_file():
                errors.append(f"missing_{section}:{name}")
            elif _sha256(target) != record.get("sha256"):
                errors.append(f"hash_mismatch:{name}")
        if expected is not None and seen != expected:
            errors.append("output_set_mismatch")
    audit_path = path.parent / "audit.json"
    audit: dict[str, Any] = {}
    if audit_path.is_file():
        try:
            audit = _mapping(json.loads(audit_path.read_text(encoding="utf-8")), "audit")
        except (OSError, json.JSONDecodeError, ValueError):
            errors.append("invalid_audit")
    assets = audit.get("assets")
    if not isinstance(assets, Mapping):
        errors.append("missing_assets")
        assets = {}
    expected_assets = {
        "real_reservation_types": REAL_TYPE_REQUIREMENTS,
        "independent_procurement_implementation": CODE_REQUIREMENTS,
    }
    for name, requirements in expected_assets.items():
        asset = assets.get(name)
        if not isinstance(asset, Mapping):
            errors.append(f"missing_asset:{name}")
            continue
        decisions = asset.get("requirements")
        if not isinstance(decisions, Mapping) or set(decisions) != set(requirements):
            errors.append(f"invalid_requirements:{name}")
            continue
        failed = [key for key in requirements if decisions.get(key) is not True]
        if asset.get("failed_requirements") != failed:
            errors.append(f"failed_requirement_mismatch:{name}")
        expected_eligible = not failed
        if asset.get("eligible") is not expected_eligible:
            errors.append(
                "real_type_eligibility_mismatch"
                if name == "real_reservation_types"
                else "procurement_code_eligibility_mismatch"
            )
    eligible_count = sum(
        isinstance(asset, Mapping) and asset.get("eligible") is True
        for asset in assets.values()
    )
    if audit.get("eligible_asset_count") != eligible_count:
        errors.append("eligible_asset_count_mismatch")
    return {"valid": not errors, "errors": errors, "eligible_asset_count": eligible_count}


__all__ = [
    "CODE_REQUIREMENTS",
    "REAL_TYPE_REQUIREMENTS",
    "audit_external_assets",
    "build_external_asset_audit",
    "verify_external_asset_audit",
]
