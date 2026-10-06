from __future__ import annotations

import hashlib
from pathlib import Path

import yaml
from datamechbench.case_submission import validate_case_submission


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _package(tmp_path: Path, **updates) -> Path:
    package = tmp_path / "case-submission"
    package.mkdir()
    source = package / "source_snapshot.json"
    source.write_text('{"normalized_listing_asks":[0.5,1.0,2.0]}\n', encoding="utf-8")
    transform = package / "transform_case.py"
    transform.write_text("def build_case(payload):\n    return payload\n", encoding="utf-8")
    payload = {
        "schema_version": "1.0",
        "submission_kind": "open_case_admission",
        "contributor": "Example Contributor",
        "case_pack_id": "dadada-listing-example-v1",
        "example_only": True,
        "track": "procurement",
        "cohort": "open_development",
        "setting_id": "P-ADDITIVE",
        "source": {
            "source_uri": "https://github.com/ZJU-DIVER/DaDaDa",
            "source_version": "ead4f7f88f22933fcdc3a8bf2f239294a6cb6c3c",
            "license_id": "Apache-2.0",
            "license_url": "https://github.com/ZJU-DIVER/DaDaDa/blob/ead4f7f88f22933fcdc3a8bf2f239294a6cb6c3c/LICENSE",
            "redistributable": True,
            "input_path": source.name,
            "input_sha256": _sha256(source),
        },
        "privacy": {
            "classification": "no_personal_data",
            "review": "Anonymous aggregate listing-price support only.",
        },
        "independence": {
            "unit": "market_source",
            "unit_ids": ["dadada-example-source"],
        },
        "realism": {
            "data": "Observed public listing asks, reduced to anonymous support.",
            "utility": "Controlled additive procurement utility.",
            "participant_type": "Listing asks are stress proxies, not private costs.",
            "institutional": "Public data-product marketplace listings without transactions.",
        },
        "economic_observable": {
            "semantic": "listing_ask",
            "observed_measure": "public listing ask",
            "benchmark_role": "procurement cost-support stress",
            "claims_supported": ["listing_ask"],
            "claims_forbidden": [
                "transaction_price",
                "reservation_value",
                "buyer_value",
            ],
        },
        "transformation": {
            "code_path": transform.name,
            "code_sha256": _sha256(transform),
            "deterministic": True,
            "description": "Map an anonymous normalized ask profile to one case.",
        },
        "cases": [
            {
                "case_id": "OPEN-dadada-ask-1",
                "source_unit_id": "dadada-example-source",
            }
        ],
    }
    payload.update(updates)
    (package / "case_submission.yaml").write_text(
        yaml.safe_dump(payload, sort_keys=False), encoding="utf-8"
    )
    return package


def test_valid_example_case_pack_is_structurally_valid_but_not_review_evidence(
    tmp_path: Path,
) -> None:
    package = _package(tmp_path)

    result = validate_case_submission(package)

    assert result.valid
    assert result.review_eligible is False
    assert result.evidence_scope == "open_development_only"
    assert result.track == "procurement"
    assert result.setting_id == "P-ADDITIVE"
    assert result.case_count == 1
    assert result.independence_unit_count == 1
    assert result.errors == ()
    assert len(result.package_digest) == 64


def test_case_pack_rejects_heldout_claim_and_canonical_case_collision(
    tmp_path: Path,
) -> None:
    package = _package(
        tmp_path,
        cohort="heldout",
        cases=[
            {
                "case_id": "PADD-independent-b30",
                "source_unit_id": "dadada-example-source",
            }
        ],
    )

    errors = validate_case_submission(package).errors

    assert "cohort must be open_development" in errors
    assert "case_id collides with a canonical benchmark case: PADD-independent-b30" in errors


def test_case_pack_fails_closed_on_unsafe_or_unbound_artifacts_and_rights(
    tmp_path: Path,
) -> None:
    package = _package(tmp_path)
    payload_path = package / "case_submission.yaml"
    payload = yaml.safe_load(payload_path.read_text(encoding="utf-8"))
    payload["source"]["input_path"] = "../outside.json"
    payload["source"]["source_uri"] = "https:"
    payload["source"]["redistributable"] = False
    payload["source"]["license_url"] = ""
    payload["transformation"]["code_sha256"] = "0" * 64
    payload["privacy"]["classification"] = "unknown"
    payload_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    errors = validate_case_submission(package).errors

    assert "source.input_path must stay inside the case package" in errors
    assert "source.source_uri must use http or https" in errors
    assert "source.redistributable must be true" in errors
    assert "source.license_url must use http or https" in errors
    assert "transformation.code_sha256 mismatch" in errors
    assert "privacy.classification must be no_personal_data or deidentified" in errors


def test_case_pack_reuses_economic_claim_boundary_rules(tmp_path: Path) -> None:
    package = _package(tmp_path)
    payload_path = package / "case_submission.yaml"
    payload = yaml.safe_load(payload_path.read_text(encoding="utf-8"))
    payload["economic_observable"]["claims_supported"] = ["transaction_price"]
    payload["economic_observable"]["claims_forbidden"] = ["buyer_value"]
    payload_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    errors = validate_case_submission(package).errors

    assert any(
        "unsupported_economic_claim:listing_ask:transaction_price" in error
        for error in errors
    )
    assert any(
        "missing_forbidden_economic_claim:listing_ask:reservation_value" in error
        for error in errors
    )


def test_distributed_case_submission_template_satisfies_current_contract() -> None:
    repository = Path(__file__).resolve().parents[2]

    result = validate_case_submission(
        repository / "benchmark" / "case_submission_template"
    )

    assert result.valid is True
    assert result.review_eligible is False
    assert result.evidence_scope == "open_development_only"
    assert result.track == "procurement"
    assert result.setting_id == "P-ADDITIVE"
    assert result.case_count == 1
